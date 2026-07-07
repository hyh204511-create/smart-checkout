import numpy as np
import cv2
import time
import logging
import os
# ?? ɾ����ȫ�ֵ� RKNNLite ���룬��ֹ���� Django ������

logger = logging.getLogger(__name__)

class RKNNDetectionService:
    def __init__(self, model_path=None):
        self.rknn = None
        
        # Parameter tuning
        # TH=0.55 高于 sigmoid(0)=0.5 噪声底线，避免 8400 个背景 anchor 全部通过
        self.CONF_THRESHOLD = 0.55
        self.IOU_THRESHOLD = 0.5
        self.TOP_K = 300  # NMS 前只保留 top-K，大幅加速

        self.class_names = {
            0: "apple", 1: "banana", 2: "orange", 3: "pear",
            4: "carrot", 5: "cherry", 6: "grape", 7: "watermelon",
            8: "honeydew", 9: "sunflower", 10: "peanut", 11: "pumpkin"
        }

        # Int8 模型 class 通道全部为 0（无法使用），默认使用 FP16
        if model_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(base_dir, 'yolo11_rk3588_fp16.rknn')
            
        self.model_path = model_path
        # ?? ���ĸĶ�������������ʱ����ģ�ͣ���ϵͳ��Դ���ø� Django

    def load_model(self, model_path):
        if not os.path.exists(model_path):
            logger.error(f"RKNN load failed: {model_path}")
            return False
        try:
            # ?? ���ĸĶ����ֲ��������ء� RKNNLite���ܿ� Django ����־������
            from rknnlite.api import RKNNLite
            self.rknn = RKNNLite()
            self.rknn.load_rknn(model_path)
            self.rknn.init_runtime(core_mask=RKNNLite.NPU_CORE_0)
            print(f"RKNN (NPU) model loaded successfully: {model_path}")
            return True
        except Exception as e:
            print(f"RKNN model load failed: {e}")
            return False

    def preprocess(self, image):
        """RKNN specific preprocess: keep NHWC, no need to divide by 255"""
        self.orig_height, self.orig_width = image.shape[:2]
        target_size = (640, 640)
        
        scale = min(target_size[0] / self.orig_width, target_size[1] / self.orig_height)
        new_w = int(self.orig_width * scale)
        new_h = int(self.orig_height * scale)
        
        resized = cv2.resize(image, (new_w, new_h))
        canvas = np.full((target_size[1], target_size[0], 3), 114, dtype=np.uint8)
        
        dx = (target_size[0] - new_w) // 2
        dy = (target_size[1] - new_h) // 2
        canvas[dy:dy+new_h, dx:dx+new_w] = resized
        
        self.pre_params = {'scale': scale, 'dx': dx, 'dy': dy}
        
        # BGR to RGB (keep NHWC format for RKNN)
        img_rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        img_input = np.expand_dims(img_rgb, axis=0) 
        return img_input

    def process_outputs(self, outputs):
        """解析 YOLO11 单tensor输出: (1, 4+num_classes, 8400) → 检测框列表
        RK3588 NPU 输出的模型是端到端格式，不需要 DFL/grid decode。
        全向量化处理 + top-K 预过滤。"""
        # 输出形状: (1, 16, 8400) → 转置为 (8400, 16)
        predictions = outputs[0].squeeze(0).transpose(1, 0)  # (8400, 16)

        # 类别 logits → sigmoid → probabilities
        cls_logits = predictions[:, 4:]      # (8400, 12)
        cls_prob = 1.0 / (1.0 + np.exp(-cls_logits))
        max_cls_prob = np.max(cls_prob, axis=1)
        max_cls_id = np.argmax(cls_prob, axis=1)

        # 置信度过滤
        valid_mask = max_cls_prob > self.CONF_THRESHOLD
        if not np.any(valid_mask):
            return [], [], []

        valid_indices = np.where(valid_mask)[0]
        valid_scores = max_cls_prob[valid_indices]
        valid_class_ids = max_cls_id[valid_indices]

        # top-K 预过滤：只保留最高分的 K 个框给 NMS（大幅加速）
        if len(valid_scores) > self.TOP_K:
            top_k_idx = np.argsort(valid_scores)[-self.TOP_K:]
            valid_indices = valid_indices[top_k_idx]
            valid_scores = valid_scores[top_k_idx]
            valid_class_ids = valid_class_ids[top_k_idx]

        # bbox (cx, cy, w, h) → (x, y, w, h) for NMSBoxes，全向量化
        bbox_coords = predictions[valid_indices, :4]
        cx, cy, bw, bh = bbox_coords[:, 0], bbox_coords[:, 1], bbox_coords[:, 2], bbox_coords[:, 3]
        x_arr = cx - bw / 2.0
        y_arr = cy - bh / 2.0

        boxes = np.stack([x_arr, y_arr, bw, bh], axis=1).astype(np.float32).tolist()
        scores = valid_scores.astype(np.float32).tolist()
        class_ids = valid_class_ids.astype(np.int32).tolist()

        return boxes, scores, class_ids

    def detect_products_optimized(self, image_data=None, image_path=None, image_obj=None):
        """Main detection interface: compatible with old onnx_service"""
        
        # ?? ���ĸĶ������������أ�ֻ�ڵ�һ�η���ͼƬʱ���Ż��� NPU ����ģ��
        if self.rknn is None:
            success = self.load_model(self.model_path)
            if not success:
                return {"success": False, "error": "RKNN model not loaded"}

        image = image_obj
        if image is None and image_path and os.path.exists(image_path):
            image = cv2.imread(image_path)
            
        if image is None:
            return {"success": False, "error": "Invalid image"}

        try:
            start = time.time()
            # 1. Preprocess
            input_tensor = self.preprocess(image)
            
            # 2. NPU Inference
            npu_start = time.time()
            outputs = self.rknn.inference(inputs=[input_tensor])
            
            # 3. CPU Decode + NMS
            boxes, scores, class_ids = self.process_outputs(outputs)
            
            products_raw = []
            if len(boxes) > 0:
                indices = cv2.dnn.NMSBoxes(boxes, scores, self.CONF_THRESHOLD, self.IOU_THRESHOLD)
                if len(indices) > 0:
                    for i in indices.flatten():
                        x, y, w, h = boxes[i]
                        scale = self.pre_params['scale']
                        dx = self.pre_params['dx']
                        dy = self.pre_params['dy']
                        
                        # Restore coordinates and prevent out of bounds
                        real_x1 = max(0, min((x - dx) / scale, self.orig_width))
                        real_y1 = max(0, min((y - dy) / scale, self.orig_height))
                        real_x2 = max(0, min((x + w - dx) / scale, self.orig_width))
                        real_y2 = max(0, min((y + h - dy) / scale, self.orig_height))
                        
                        products_raw.append({
                            "name": self.class_names.get(class_ids[i], "unknown"),
                            "confidence": scores[i],
                            "bbox": [real_x1, real_y1, real_x2, real_y2],
                            "class_id": class_ids[i]
                        })
            
            # 4. Assemble final format for frontend
            products = []
            class_stats = {}
            total_price = 0
            
            for idx, obj in enumerate(products_raw):
                name = obj['name']
                price = self._get_product_price(name)
                products.append({
                    "id": idx + 1,
                    "name": name,
                    "price": price,
                    "confidence": obj['confidence'],
                    "bbox": obj['bbox'],
                    "class_name": name,
                    "quantity": 1
                })
                class_stats[name] = class_stats.get(name, 0) + 1
                total_price += price

            return {
                "success": True,
                "products": products,
                "total_objects": len(products),
                "total_price": total_price,
                "processing_time": time.time() - start,
                "class_statistics": class_stats,
                "engine": "RKNN-FP16"
            }

        except Exception as e:
            logger.error(f"RKNN detection error: {e}")
            return {"success": False, "error": str(e)}

    def _get_product_price(self, name):
        """从数据库获取商品价格，失败时回退到默认价格表"""
        try:
            from django.db.models import Q
            from .models import Product
            product = Product.objects.filter(
                Q(name__icontains=name)
            ).order_by('-updated_at').first()
            if product:
                return float(product.price)
        except Exception:
            pass  # Django 未就绪时静默回退到硬编码表

        # 回退：默认价格表 (仅在 DB 不可用时使用)
        fallback = {
            "apple": 8.0, "banana": 6.0, "orange": 5.0, "pear": 7.0,
            "carrot": 3.0, "cherry": 25.0, "grape": 12.0, "watermelon": 15.0,
            "honeydew": 20.0, "sunflower": 15.0, "peanut": 8.0, "pumpkin": 12.0
        }
        return fallback.get(name, 10.0)

# Global singleton instance
rknn_detection_service = RKNNDetectionService()