import logging
import threading
import time
import uuid
import json
from datetime import timedelta

import cv2
import numpy as np
from django.apps import apps
from django.contrib.auth import authenticate
from django.db import transaction, connection
from django.db.models import Sum
from django.http import StreamingHttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Product, Order, DetectionHistory, DetectionResult
from .serializers import ProductSerializer
from .rknn_service import rknn_detection_service
from .apps import CheckoutConfig

# ✅ 核心注入：Qwen 本地大模型服务
from .llm_service import local_ai, task_manager

logger = logging.getLogger(__name__)

# 线程安全锁 — 保护硬件驱动初始化
_driver_lock = threading.Lock()
_camera_lock = threading.Lock()

# ================== 推理缓存 (帧去重 + TTL) ==================
# 连续帧画面基本不变时，复用上次检测结果，避免重复推理
import hashlib

class InferenceCache:
    """推理结果缓存：画面指纹 + TTL 过期机制"""
    def __init__(self, ttl=0.3, max_age=3.0):
        self._last_hash = None
        self._last_result = None
        self._last_time = 0.0
        self.ttl = ttl           # 指纹相同时的复用窗口 (秒)
        self.max_age = max_age   # 绝对过期时间 (秒)，防止长期缓存

    def should_skip(self, jpeg_bytes, now=None):
        """画面没变 + 未过期 → 返回上次结果；否则返回 None"""
        if now is None:
            now = time.time()
        if self._last_result is None:
            return None
        # 绝对过期保护
        if now - self._last_time > self.max_age:
            self._last_result = None
            return None
        # 指纹对比 (采样头4KB + 尾1KB 做快速指纹)
        fingerprint = hashlib.md5(jpeg_bytes[:4096] + jpeg_bytes[-1024:]).digest()
        if fingerprint == self._last_hash and (now - self._last_time) < self.ttl:
            # 复用缓存，但重置时间戳以保持活跃
            cached = dict(self._last_result)
            cached['_cached'] = True
            return cached
        return None

    def update(self, jpeg_bytes, result, now=None):
        if now is None:
            now = time.time()
        self._last_hash = hashlib.md5(jpeg_bytes[:4096] + jpeg_bytes[-1024:]).digest()
        self._last_result = dict(result)
        self._last_time = now

    def clear(self):
        self._last_hash = None
        self._last_result = None
        self._last_time = 0.0

# 全局单例
_inference_cache = InferenceCache(ttl=0.3, max_age=3.0)


def init_driver():
    """惰性初始化串口驱动（真正线程安全）"""
    if CheckoutConfig.driver is None:
        with _driver_lock:
            if CheckoutConfig.driver is None:  # 双重检查
                try:
                    from .serial_worker import SmartCheckoutProtocol
                    CheckoutConfig.driver = SmartCheckoutProtocol(port='/dev/ttyS9')
                    if CheckoutConfig.driver.connect():
                        logger.info("串口驱动初始化成功 (惰性)")
                    else:
                        logger.error("串口连接失败")
                        CheckoutConfig.driver = False
                except Exception as e:
                    logger.error(f"串口驱动初始化失败: {e}")
                    CheckoutConfig.driver = False
    return CheckoutConfig.driver if CheckoutConfig.driver is not False else None


def get_driver():
    """安全获取驱动实例"""
    drv = CheckoutConfig.driver
    if drv is None:
        drv = init_driver()
    elif drv is False:
        return None
    return drv

# ================= 🛡️ 核心辅助函数：获取全局单例 =================
def get_camera_manager():
    """线程安全获取摄像头管理器单例"""
    cam = CheckoutConfig.camera_manager
    if cam is None:
        with _camera_lock:
            if CheckoutConfig.camera_manager is None:  # 双重检查
                try:
                    from .camera_manager import CameraManager
                    CheckoutConfig.camera_manager = CameraManager()
                    CheckoutConfig.camera_manager.start()  # 启动监控线程
                    logger.info("摄像头管理器初始化成功")
                except Exception as e:
                    logger.error(f"摄像头初始化失败: {e}")
                    CheckoutConfig.camera_manager = False
                    return None
    cam = CheckoutConfig.camera_manager
    if cam is False:
        return None
    return cam
def play_voice_async(text):
    drv = get_driver()
    if drv:
        threading.Thread(target=lambda: drv.play_voice(text), daemon=True).start()

# ================= 🎥 页面视图 (Page Views) =================

def index(request):
    return render(request, 'index.html')

def login_page(request):
    return render(request, 'login.html')

def payment_page(request):
    return render(request, 'payment.html')

def dashboard(request):
    return render(request, 'admin.html')

def product_manager(request):
    return render(request, 'product_manager.html')

# ================= 🎥 视频流接口 =================

def gen_frames():
    while True:
        cam = get_camera_manager()
        if cam:
            frame = cam.get_frame()
            if frame is not None:
                try:
                    ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if ret:
                        frame_bytes = buffer.tobytes()
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                except Exception:
                    pass
        time.sleep(0.05)

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def video_feed(request):
    return StreamingHttpResponse(gen_frames(), content_type='multipart/x-mixed-replace; boundary=frame')

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def camera_snapshot(request):
    """返回单帧 JPEG（优先 MPP 硬件编码, 降级 CPU 软编码）"""
    from django.http import HttpResponse
    cam = get_camera_manager()
    if cam is None:
        return HttpResponse(status=503)

    # 优先 MPP 硬件编码 (零 CPU 开销)
    jpeg = cam.get_jpeg_frame()
    if jpeg and len(jpeg) > 512:
        return HttpResponse(jpeg, content_type='image/jpeg')

    # 降级: CPU 软编码
    frame = cam.get_frame()
    if frame is None:
        return HttpResponse(status=503)
    ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ret:
        return HttpResponse(status=500)
    return HttpResponse(buffer.tobytes(), content_type='image/jpeg')

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def camera_exposure(request):
    """实时调节摄像头曝光 — 委托给 camera_params"""
    return camera_params(request)

@api_view(['GET', 'POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def camera_params(request):
    """读取/设置摄像头参数 (曝光/锐度/亮度/对比度/饱和度)"""
    cam = get_camera_manager()
    if cam is None:
        return Response({'success': False, 'error': '摄像头未初始化'}, status=503)

    if request.method == 'GET':
        result = cam.get_params()
        # 附加当前清晰度
        result['sharpness'] = cam.get_sharpness()
        return Response(result)
    else:
        # POST: {"name": "exposure_absolute", "value": 300}
        name = request.data.get('name', '')
        value = request.data.get('value', None)
        if not name or value is None:
            return Response({'success': False, 'error': '缺少 name 或 value'}, status=400)
        return Response(cam.set_param(name, value))

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def camera_sharpness(request):
    """仅返回清晰度分数 (轻量级，供前端 1s 轮询)"""
    cam = get_camera_manager()
    if cam is None:
        return Response({'success': False, 'sharpness': 0.0}, status=503)
    return Response({'success': True, 'sharpness': cam.get_sharpness()})

# ================= 核心API：获取重量 & 去皮 =================

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def get_weight(request):
    drv = get_driver()
    if drv is None:
        return Response({'success': False, 'weight': 0.0, 'raw_gram': 0, 'error': 'Driver not loaded'})

    weight_g = drv.get_weight()
    if weight_g > 20000:
        weight_g = 0.0

    return Response({
        'success': True,
        'weight': round(weight_g / 500.0, 3),
        'unit': 'jin',
        'raw_gram': weight_g,
        'is_mock': False
    })

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def tare_scale(request):
    drv = get_driver()
    if drv:
        if hasattr(drv, 'tare'):
            drv.tare()
        else:
            logger.warning("驱动未实现 tare 方法")
        
        cam = get_camera_manager()
        if cam:
            cam.last_weight = 0.0
        return Response({'success': True, 'message': '去皮成功'})
    return Response({'success': False, 'error': '驱动未就绪'}, status=500)


# ================= 🤖 Qwen 本地大模型分析接口 =================

# views.py 中的相关函数替换

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@csrf_exempt
def request_ai_analysis(request):
    """
    提交分析任务，传递全部商品数据给 AI 引擎。
    """
    try:
        # 获取所有商品（限制数量以防过大）
        products = Product.objects.all()
        total_sales = Order.objects.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_orders = Order.objects.count()
        # 低库存商品（库存 < 10）
        low_stock_products = list(products.filter(stock__lt=10)[:10])
        # 构建全部商品列表，传递给 LLM
        product_list = []
        for p in products[:50]:  # 最多 50 个
            product_list.append({
                "name": p.name,
                "stock": p.stock,
                "price": float(p.price)
            })
        data_context = {
            "stats": {
                "total_sales": float(total_sales),
                "order_count": total_orders,
                "low_stock_count": len(low_stock_products)
            },
            "alerts": [
                {"name": p.name, "stock": p.stock, "price": float(p.price)}
                for p in low_stock_products
            ],
            "products": product_list   # 新增全部商品列表
        }
        task_id = local_ai.trigger_analysis_task(data_context)
        return JsonResponse({"success": True, "task_id": task_id})
    except Exception as e:
        logger.error(f"提交分析任务失败: {e}")
        return JsonResponse({"success": False, "error": str(e)})

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def poll_ai_status(request):
    """
    前端轮询任务状态
    """
    task_id = request.GET.get('task_id')
    if not task_id:
        return JsonResponse({"success": False, "error": "缺少 task_id"})

    task = local_ai.get_task_status(task_id)

    if task["status"] == "not_found":
        return JsonResponse({"success": False, "error": "任务不存在或已过期"})

    if task["status"] == "completed":
        result = task.get("result")
        # ✅ 防御：result 可能为 None
        if isinstance(result, dict):
            return JsonResponse({
                "success": True,
                "status": "completed",
                "overall_advice": result.get("overall_advice", "暂无建议"),
                "urgent_actions": result.get("urgent_actions", []),
                "recommendations": result.get("recommendations", [])
            })
        else:
            # 理论上不会到这里（有 fallback 兜底），但以防万一
            return JsonResponse({
                "success": True,
                "status": "completed",
                "overall_advice": "AI 引擎返回数据格式异常，请联系管理员",
                "urgent_actions": [],
                "recommendations": []
            })

    elif task["status"] == "failed":
        return JsonResponse({
            "success": False,
            "status": "failed",
            "error": "AI 分析失败，请稍后重试"
        })
    else:
        # processing
        return JsonResponse({"success": True, "status": "processing"})
@csrf_exempt
def detect_products_onnx(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '仅支持 POST 请求'})

    image = None
    jpeg_cache_bytes = None  # 用于推理缓存指纹
    cam = get_camera_manager()
    t_start = time.time()

    try:
        if 'image' in request.FILES:
            try:
                file_obj = request.FILES['image']
                nparr = np.frombuffer(file_obj.read(), np.uint8)
                decoded = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if decoded is not None:
                    image = decoded
                    jpeg_cache_bytes = nparr.tobytes()
            except Exception:
                pass

        if image is None and request.body:
            try:
                data = json.loads(request.body)
                base64_str = data.get('image')
                if base64_str:
                    # base64 → OpenCV image
                    import base64 as b64
                    img_data = b64.b64decode(base64_str)
                    image = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)
            except:
                pass

        if image is None:
            if cam:
                # 检查推理缓存（帧指纹不变 → 跳过推理）
                jpeg_cache_bytes = cam.get_inference_jpeg()
                if jpeg_cache_bytes and len(jpeg_cache_bytes) > 512:
                    cached = _inference_cache.should_skip(jpeg_cache_bytes)
                    if cached is not None:
                        cached['processing_time'] = time.time() - t_start
                        logger.debug(f"  ⚡ 推理命中缓存 ({cached['processing_time']*1000:.1f}ms)")
                        return JsonResponse(cached)

                # 休眠时强制唤醒
                if not cam.is_camera_on:
                    cam._open_camera()
                    for _ in range(100):
                        time.sleep(0.01)
                        frame = cam.get_frame()
                        if frame is not None and not (hasattr(cam, 'blank_frame') and frame is cam.blank_frame):
                            break
                image = cam.get_frame()
                if image is None or (hasattr(cam, 'blank_frame') and image is cam.blank_frame):
                    return JsonResponse({
                        "success": True,
                        "products": [],
                        "is_sleeping": True,
                        "message": "📷 摄像头不可用，请检查连接"
                    })
            else:
                 return JsonResponse({"success": False, "error": "摄像头管理器未初始化"}, status=500)

        if image is None:
            return JsonResponse({"success": False, "error": "未获取到有效图像数据"}, status=400)

        # ===== RKNN NPU 推理 =====
        result = None
        engine_used = 'RKNN-NPU'

        try:
            result = rknn_detection_service.detect_products_optimized(image_obj=image)
            if not result.get('success'):
                engine_used = 'FAIL'
                result = {"success": False, "error": "RKNN NPU 推理失败"}
        except Exception as npu_err:
            engine_used = 'FAIL'
            result = {"success": False, "error": f"RKNN NPU 推理失败: {str(npu_err)}"}

        result['engine'] = engine_used=

        # 更新推理缓存
        if result.get('success') and jpeg_cache_bytes and len(jpeg_cache_bytes) > 512:
            _inference_cache.update(jpeg_cache_bytes, result)

        NAME_MAPPING = {
            'apple': '苹果', 'banana': '香蕉', 'orange': '橘子', 'pear': '梨',
            'grape': '葡萄', 'watermelon': '西瓜', 'pineapple': '菠萝',
            'peanut': '花生', 'sunflower': '瓜子', 'sunflower_seeds': '瓜子','honeydew': '哈密瓜',
            'pumpkin': '南瓜子','pumpkin_seeds': '南瓜子', 'cantaloupe': '哈密瓜', 'eggplant': '茄子',
            'cherry': '樱桃', 'vegetable': '蔬菜', 'fruit': '水果', 'carrot': '胡萝卜',
            'seed': '种子', 'nut': '坚果', 'kiwi': '猕猴桃', 'lemon': '柠檬',
            'cucumber': '黄瓜', 'tomato': '西红柿', 'potato': '土豆'
        }

        if result.get('success') and result.get('products'):
            real_total_price = 0.0

            for p in result['products']:
                english_name = p['name'].lower()
                for k, v in NAME_MAPPING.items():
                    if k in english_name:
                        p['name'] = v
                        break

                product_obj = Product.objects.filter(name__icontains=p['name']).order_by('-updated_at').first()
                if product_obj:
                    db_price = float(product_obj.price)
                    p['price'] = db_price
                real_total_price += p.get('price', 0.0)

            result['total_price'] = real_total_price
            top_product = max(result['products'], key=lambda x: x['confidence'])

            drv = get_driver()
            if drv:
                threading.Thread(
                    target=drv.send_product_info,
                    args=(top_product['name'], top_product['price']),
                    daemon=True
                ).start()

        threading.Thread(target=save_detection_to_database, args=(result, engine_used), daemon=True).start()

        return JsonResponse(result)

    except Exception as e:
        return JsonResponse({"success": False, "error": f"识别服务错误: {str(e)}"}, status=500)

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def create_order(request):
    try:
        data = request.data
        total_price = float(data.get('total_price', 0))
        products_list = data.get('products_list', [])

        if total_price <= 0:
            return Response({'success': False, 'error': '金额无效'}, status=400)

        with transaction.atomic():
            order_id = timezone.now().strftime('%Y%m%d%H%M%S') + str(uuid.uuid4().int)[:4]
            order = Order.objects.create(
                order_id=order_id,
                total_amount=total_price,
                products=products_list,
                status='pending'
            )
            voice_text = f"[t5]共{total_price}元，请扫码支付"
            order_info = {"order_id": order.order_id, "voice_text": voice_text}

        play_voice_async(voice_text)
        return Response({"success": True, "message": "订单已生成", **order_info}, status=201)

    except Exception as e:
        return Response({'success': False, 'error': f"服务器错误: {str(e)}"}, status=500)

@csrf_exempt
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def pay_order(request):
    order_id = request.data.get('order_id')
    if not order_id:
        return Response({'success': False, 'error': '缺少订单号'}, status=400)

    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(order_id=order_id)
            if order.status == 'paid':
                return Response({'success': True, 'message': '订单已支付'})

            order.status = 'paid'
            order.save()
            voice_text = f"支付成功，收款{order.total_amount}元"

        play_voice_async(voice_text)
        return Response({"success": True, "message": "支付成功"})

    except Order.DoesNotExist:
        return Response({'success': False, 'error': '订单不存在'}, status=404)
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=500)

# ================= 🔐 登录接口 =================

@csrf_exempt
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def api_user_login(request):
    username = request.data.get('username')
    password = request.data.get('password')
    user = authenticate(username=username, password=password)

    if user:
        return Response({"success": True, "message": "登录成功"})
    else:
        return Response({"success": False, "error": "用户名或密码错误"}, status=400)

@csrf_exempt
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def user_login(request):
    return api_user_login(request)

# ================= 🛠️ 辅助管理与健康检查接口 =================

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def hello_world(request):
    return Response({"message": "后端已启动", "timestamp": time.time()})

@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def send_tts(request):
    text = request.data.get('text', '')
    if not text:
        return Response({'success': False, 'error': '无内容'}, status=400)
    play_voice_async(text)
    return Response({'success': True, 'message': '指令已下发'})
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def send_voice_command(request):
    return send_tts(request)

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def rknn_health(request):
    is_loaded = hasattr(rknn_detection_service, 'rknn') and rknn_detection_service.rknn is not None
    return Response({"status": "healthy", "model_loaded": is_loaded})

@api_view(['GET'])
def product_list(request):
    if Product.objects.count() == 0:
        samples = [
            {"name": "苹果", "price": 8, "barcode": "1001", "stock": 50},
            {"name": "香蕉", "price": 6, "barcode": "1002", "stock": 100}
        ]
        for p in samples:
            Product.objects.get_or_create(name=p["name"], defaults=p)

    products = Product.objects.all().order_by('-updated_at')
    return Response({"success": True, "products": ProductSerializer(products, many=True).data})

@api_view(['PUT', 'DELETE'])
@authentication_classes([])
@permission_classes([AllowAny])
def product_detail(request, pk):
    try:
        product = Product.objects.get(pk=pk)
    except Product.DoesNotExist:
        return Response({'success': False, 'error': '商品不存在'}, status=404)

    if request.method == 'PUT':
        serializer = ProductSerializer(product, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({'success': True, 'data': serializer.data})
        return Response({'success': False, 'error': serializer.errors}, status=400)
    elif request.method == 'DELETE':
        product.delete()
        return Response({'success': True}, status=204)

@csrf_exempt
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def upload_fruit(request):
    try:
        data = request.data.copy()
        name = data.get('name')
        if not name:
            return Response({"success": False, "error": "无商品名称"}, status=400)

        if not data.get('barcode'):
            auto_code = str(int(time.time() * 1000))[-13:]
            data['barcode'] = auto_code

        try:
            product = Product.objects.get(name=name)
            serializer = ProductSerializer(product, data=data, partial=True)
        except Product.DoesNotExist:
            serializer = ProductSerializer(data=data)

        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "product": serializer.data}, status=200)
        else:
            error_msg = str(serializer.errors)
            for key, val in serializer.errors.items():
                error_msg = f"{key}: {val[0]}"
                break
            return Response({"success": False, "error": error_msg, "details": serializer.errors}, status=400)
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)

@api_view(['GET'])
def sales_data(request):
    try:
        qs = (DetectionResult.objects.filter(detection_history__detection_time__date=timezone.now().date())
              .values('product_name').annotate(quantity_sold=Sum('quantity'), sellingPrice=Sum('price')))
        return Response({"success": True, "data": list(qs)})
    except Exception:
        return Response({"success": True, "data": []})

@api_view(['GET'])
def dashboard_data(request):
    try:
        today = timezone.now().date()
        line_dates, line_values = [], []
        for i in range(6, -1, -1):
            target = today - timedelta(days=i)
            line_dates.append(target.strftime('%m-%d'))
            val = Order.objects.filter(created_time__date=target, status='paid').aggregate(t=Sum('total_amount'))['t']
            line_values.append(float(val or 0))

        pie_data = []
        for item in DetectionResult.objects.values('product_name').annotate(v=Sum('price')).order_by('-v'):
            pie_data.append({"name": item['product_name'], "value": float(item['v'] or 0)})

        return Response({"success": True, "line_chart": {"dates": line_dates, "values": line_values}, "pie_chart": pie_data})
    except Exception as e:
        return Response({"success": False, "error": str(e)}, status=500)

# ================= 💾 异步数据库保存函数 =================

def save_detection_to_database(result, engine_type):
    try:
        with transaction.atomic():
            hist = DetectionHistory.objects.create(
                detection_time=timezone.now(),
                engine_type=engine_type,
                status='success' if result['success'] else 'failed',
                total_objects=result.get('total_objects', 0),
                total_price=result.get('total_price', 0),
                error_message=result.get('error', '')
            )
            if result['success']:
                for p in result['products']:
                    DetectionResult.objects.create(
                        detection_history=hist,
                        product_name=p['name'],
                        confidence=p['confidence'],
                        bbox_x1=p['bbox'][0], bbox_y1=p['bbox'][1], bbox_x2=p['bbox'][2], bbox_y2=p['bbox'][3],
                        price=p['price'],
                        quantity=p.get('quantity', 1)
                    )
        return hist.id
    except Exception as e:
        logger.error(f"保存识别记录失败: {e}")
        return None
    finally:
        # ✅ 释放当前野生线程的数据库连接，避免 SQLite 被锁死
        connection.close()