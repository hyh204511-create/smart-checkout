"""
RK3588 智能结算终端 — 摄像头管理器 (ffmpeg MJPEG 直通版 v2.1)
支持罗技 C270i 等标准 USB UVC 摄像头
- ffmpeg MJPEG 直通: 零CPU编解码，直读JPEG → WebSocket (30fps)
- 降级: cv2.VideoCapture 管线 (当 ffmpeg 不可用时)
- 电子秤重量触发节能模式
- WebSocket JPEG 推送
- 手动参数持久化
"""
import cv2
import threading
import time
import subprocess
import numpy as np
import os
import gc
from django.apps import apps
from PIL import Image, ImageDraw, ImageFont

cv2.setNumThreads(3)


class MjpegFfmpegReader:
    """
    ffmpeg MJPEG 直通读取器
    使用 ffmpeg -c copy 从 V4L2 读取 MJPEG，直接输出原始 JPEG 流
    零 CPU 编解码开销，帧率可达摄像头物理上限 (C270i MJPG: 30fps@720p)
    """

    def __init__(self):
        self._proc = None
        self._buf = b''
        self._frame_count = 0
        self._t0 = 0.0
        self._lock = threading.Lock()

    def open(self, device, width=1280, height=720, fps=30):
        """启动 ffmpeg 子进程: V4L2 MJPEG → stdout pipe"""
        try:
            self._proc = subprocess.Popen(
                ['ffmpeg',
                 '-hide_banner', '-loglevel', 'error',
                 '-f', 'v4l2',
                 '-input_format', 'mjpeg',
                 '-video_size', f'{width}x{height}',
                 '-framerate', str(fps),
                 '-i', device,
                 '-c', 'copy',           # 零CPU拷贝！不编解码
                 '-f', 'image2pipe',     # 每帧一个完整 JPEG
                 '-vsync', 'drop',       # 丢帧保持帧率
                 '-'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            # 等首帧到达 (ffmpeg 需要约 0.5-1s 初始化)
            deadline = time.time() + 3.0
            while time.time() < deadline and len(self._buf) < 512:
                chunk = self._proc.stdout.read(65536)
                if chunk:
                    self._buf += chunk
                else:
                    time.sleep(0.05)
            if len(self._buf) < 512:
                print(f"  ffmpeg MJPEG: 首帧超时")
                self.close()
                return False

            self._t0 = time.time()
            soi = self._buf.find(b'\xff\xd8')
            if soi >= 0:
                eoi = self._buf.find(b'\xff\xd9', soi)
                if eoi >= 0:
                    first_mjpeg = self._buf[soi:eoi + 2]
                    sz_kb = len(first_mjpeg) / 1024.0
                    print(f"  ffmpeg MJPEG: {width}x{height} @ {fps}fps | "
                          f"直通零CPU | 首帧 ~{sz_kb:.0f}KB")
                self._buf = self._buf[soi:]  # 保留SOI及之后

            return True
        except FileNotFoundError:
            print(f"  ffmpeg MJPEG: ffmpeg 未安装")
            return False
        except Exception as e:
            print(f"  ffmpeg MJPEG: 启动失败 — {e}")
            return False

    def read_frame(self):
        """读取一帧完整 JPEG，返回 bytes 或 None"""
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                return None

            try:
                # 补充管道数据
                chunk = self._proc.stdout.read(65536)
                if chunk:
                    self._buf += chunk

                # 从缓冲区提取一帧完整 JPEG
                soi = self._buf.find(b'\xff\xd8')
                if soi < 0:
                    return None
                if soi > 0:
                    self._buf = self._buf[soi:]  # 丢弃 SOI 之前的垃圾

                eoi = self._buf.find(b'\xff\xd9', 2)
                if eoi < 0:
                    return None

                jpeg = self._buf[:eoi + 2]
                self._buf = self._buf[eoi + 2:]

                if len(jpeg) > 512:
                    self._frame_count += 1
                    return jpeg
                return None
            except Exception:
                return None

    def read_frame_nonblock(self):
        """非阻塞读取，没有帧立即返回 None"""
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                return None
            try:
                import select
                ready, _, _ = select.select([self._proc.stdout], [], [], 0.001)
                if not ready:
                    return None
                chunk = os.read(self._proc.stdout.fileno(), 65536)
                if chunk:
                    self._buf += chunk
            except Exception:
                pass

            soi = self._buf.find(b'\xff\xd8')
            if soi < 0:
                return None
            if soi > 0:
                self._buf = self._buf[soi:]

            eoi = self._buf.find(b'\xff\xd9', 2)
            if eoi < 0:
                return None

            jpeg = self._buf[:eoi + 2]
            self._buf = self._buf[eoi + 2:]

            if len(jpeg) > 512:
                self._frame_count += 1
                return jpeg
            return None

    @property
    def fps(self):
        elapsed = time.time() - self._t0
        return self._frame_count / max(elapsed, 0.001) if elapsed > 0.5 else 0.0

    def close(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        self._buf = b''


class CameraManager:
    def __init__(self):
        self.WEIGHT_THRESHOLD = 30.0
        self.IDLE_TIMEOUT = 10.0
        self.FRAME_W = 1280
        self.FRAME_H = 720
        self.JPEG_QUALITY = 88

        self.cap = None
        self.is_camera_on = False
        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.last_active_time = time.time()
        self._last_weight_time = 0.0     # 最后一次检测到重量 > 阈值的时间戳
        self._last_blank_push = 0.0      # 休眠时空白帧推送节流
        self.is_running = False

        self._usb_device = None
        self._is_mjpeg = False

        # ffmpeg MJPEG 直读器 (优先)
        self._mjpeg_reader = None

        # WebSocket JPEG
        self._latest_jpeg = None
        self._jpeg_lock = threading.Lock()

        # 推理帧槽位
        self._inference_jpeg = None
        self._inference_lock = threading.Lock()

        # 帧就绪事件: 摄像头产生新帧时触发, WebSocket 服务器等待此事件
        self._frame_ready = threading.Event()

        # 空白帧
        self.blank_frame = np.zeros((self.FRAME_H, self.FRAME_W, 3), dtype=np.uint8)
        self._blank_jpeg = None
        self._draw_blank()

    def _draw_blank(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        local_font = os.path.join(current_dir, "simhei.ttf")
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()
        if os.path.exists(local_font):
            try:
                font_large = ImageFont.truetype(local_font, 40)
                font_small = ImageFont.truetype(local_font, 30)
            except Exception:
                pass
        try:
            pil_img = Image.fromarray(cv2.cvtColor(self.blank_frame, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(pil_img)
            draw.text((230, 200), "节能模式", font=font_large, fill=(150, 150, 150))
            draw.text((180, 260), "放置物品启动检测", font=font_small, fill=(100, 100, 100))
            self.blank_frame = cv2.cvtColor(np.asarray(pil_img), cv2.COLOR_RGB2BGR)
        except Exception as e:
            print(f"绘图失败: {e}")
        ok, buf = cv2.imencode('.jpg', self.blank_frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            self._blank_jpeg = buf.tobytes()

    def get_driver(self):
        try:
            return apps.get_app_config('checkout').driver
        except Exception:
            return None

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        threading.Thread(target=self._monitor_loop, daemon=True, name="cam-monitor").start()
        threading.Thread(target=self._mjpeg_read_loop, daemon=True, name="mjpeg-reader").start()
        print("摄像头管理器已启动 (ffmpeg MJPEG直通 + OpenCV降级)")

    def get_frame(self):
        with self._inference_lock:
            jpeg = self._inference_jpeg
        if jpeg is not None and len(jpeg) > 512:
            arr = np.frombuffer(jpeg, dtype=np.uint8)
            bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if bgr is not None:
                return bgr
        with self.frame_lock:
            if self.is_camera_on and self.latest_frame is not None:
                return self.latest_frame
            return self.blank_frame

    def get_jpeg_frame(self):
        """返回最新 JPEG 帧 (摄像头休眠时返回空白帧)"""
        # 不再刷新 last_active_time — 休眠决策由重量驱动，不受消费者影响
        with self._jpeg_lock:
            if self._latest_jpeg is not None:
                return self._latest_jpeg
            return self._blank_jpeg

    def get_inference_jpeg(self):
        with self._inference_lock:
            return self._inference_jpeg

    def get_frame_event(self):
        """返回帧就绪事件 — WebSocket 服务器用 run_in_executor 等待它"""
        return self._frame_ready

    def get_sharpness(self):
        with self._jpeg_lock:
            jpeg = self._latest_jpeg
        if jpeg is None:
            return 0.0
        frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if frame is None:
            return 0.0
        return float(cv2.Laplacian(frame, cv2.CV_64F).var())

    # ================== 手动调参 ==================

    TUNABLE_PARAMS = {
        'exposure_absolute': {'label': '曝光', 'min': 1, 'max': 10000, 'step': 1, 'default': 250},
        'sharpness':         {'label': '锐度', 'min': 0, 'max': 255, 'step': 1, 'default': 128},
        'brightness':        {'label': '亮度', 'min': 0, 'max': 255, 'step': 1, 'default': 128},
        'contrast':          {'label': '对比度', 'min': 0, 'max': 255, 'step': 1, 'default': 48},
        'saturation':        {'label': '饱和度', 'min': 0, 'max': 255, 'step': 1, 'default': 48},
    }

    _saved_params = {}

    def _get_device(self):
        dev = self._usb_device
        if not dev:
            dev = self._find_usb_camera()
            if dev:
                self._usb_device = dev
        return dev

    def get_params(self):
        dev = self._get_device()
        if not dev:
            return {'success': False, 'error': '未检测到摄像头', 'params': {}}
        try:
            result = subprocess.run(['v4l2-ctl', '-d', dev, '-C'], capture_output=True, text=True, timeout=3)
            params = {}
            for key in self.TUNABLE_PARAMS:
                params[key] = {'value': self._saved_params.get(key, self.TUNABLE_PARAMS[key]['default'])}
            if result.returncode == 0:
                for key in self.TUNABLE_PARAMS:
                    for line in result.stdout.split('\n'):
                        if line.strip().startswith(key):
                            try:
                                val = int(line.split(':')[1].strip())
                                params[key]['value'] = val
                            except (ValueError, IndexError):
                                pass
            return {'success': True, 'params': params}
        except Exception as e:
            return {'success': False, 'error': str(e), 'params': {}}

    def set_param(self, name, value):
        if name not in self.TUNABLE_PARAMS:
            return {'success': False, 'error': f'未知参数: {name}'}
        dev = self._get_device()
        if not dev:
            return {'success': False, 'error': '摄像头未初始化'}
        self.last_active_time = time.time()
        try:
            clamped = max(self.TUNABLE_PARAMS[name]['min'],
                         min(self.TUNABLE_PARAMS[name]['max'], int(value)))
            subprocess.run(['v4l2-ctl', '-d', dev, '--set-ctrl=' + name + '=' + str(clamped)],
                         capture_output=True, timeout=3)
            if name == 'exposure_absolute':
                subprocess.run(['v4l2-ctl', '-d', dev, '--set-ctrl=exposure_auto=1'],
                             capture_output=True, timeout=2)
            self._saved_params[name] = clamped
            print(f"  {self.TUNABLE_PARAMS[name]['label']}: {clamped}", flush=True)
            return {'success': True, 'name': name, 'value': clamped}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _find_usb_camera(self):
        found = []
        try:
            result = subprocess.run(['v4l2-ctl', '--list-devices'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                current_name = ""
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if not line:
                        current_name = ""
                        continue
                    if any(kw in line.lower() for kw in
                           ['usb', 'uvc', 'c270', 'logitech', 'webcam', 'camera']):
                        current_name = line
                    elif line.startswith('/dev/video') and current_name:
                        dev = line.split('(')[0].strip()
                        if dev not in found:
                            found.append(dev)
                        current_name = ""
        except Exception:
            pass
        if not found:
            import glob
            for dev in sorted(glob.glob('/dev/video*')):
                name = os.path.basename(dev)
                if 'dec' in name or 'enc' in name:
                    continue
                try:
                    r = subprocess.run(['v4l2-ctl', '-d', dev, '--info'], capture_output=True, text=True, timeout=3)
                    if 'uvcvideo' in r.stdout:
                        found.append(dev)
                except Exception:
                    continue
        return found[0] if found else None

    def _apply_saved_params(self, dev):
        commands = ['white_balance_temperature_auto=1', 'backlight_compensation=1', 'exposure_auto=1']
        for name in self.TUNABLE_PARAMS:
            val = self._saved_params.get(name, self.TUNABLE_PARAMS[name]['default'])
            commands.append(f'{name}={val}')
        try:
            subprocess.run(['v4l2-ctl', '-d', dev] + ['--set-ctrl=' + c for c in commands],
                         capture_output=True, timeout=3)
        except Exception:
            pass

    def _open_camera(self):
        if self.is_camera_on:
            return
        self.last_active_time = time.time()
        self._last_weight_time = time.time()  # 记录唤醒时间
        print("🔆 正在唤醒摄像头...", flush=True)

        dev = self._find_usb_camera()
        if not dev:
            print("❌ 未检测到 USB 摄像头")
            return

        # 立即标记为"开"状态，阻止 _mjpeg_read_loop 持续推送空白帧
        self.is_camera_on = True

        # 优先 ffmpeg MJPEG 直通 (零 CPU)
        reader = MjpegFfmpegReader()
        if reader.open(dev, self.FRAME_W, self.FRAME_H, fps=30):
            self._apply_saved_params(dev)
            self._mjpeg_reader = reader
            self._usb_device = dev
            self._is_mjpeg = True
            print(f"✅ {self.FRAME_W}x{self.FRAME_H} @ 30fps ffmpeg直通 | {dev}", flush=True)
            return
        else:
            print("  ffmpeg 直通失败，降级到 OpenCV 管线...", flush=True)

        # 降级 OpenCV
        cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        if not cap.isOpened():
            print(f"❌ 无法打开 {dev}")
            self.is_camera_on = False  # 回退：摄像头未就绪
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.FRAME_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.FRAME_H)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
        ret, test_frame = cap.read()
        if ret and test_frame is not None and test_frame.shape[:2] == (self.FRAME_H, self.FRAME_W):
            self._is_mjpeg = True
            print(f"   {dev} MJPEG [OpenCV降级]", flush=True)
        else:
            cap.set(cv2.CAP_PROP_FOURCC, 0)
            ret, test_frame = cap.read()
            if ret and test_frame is not None:
                self._is_mjpeg = False
                print(f"   {dev} YUV [OpenCV降级]", flush=True)
            else:
                print(f"❌ {dev} 无法读取画面")
                cap.release()
                self.is_camera_on = False  # 回退：摄像头未就绪
                return

        self.cap = cap
        self._usb_device = dev
        # is_camera_on 已在上方设置为 True
        try:
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
        except Exception:
            pass
        self._apply_saved_params(dev)
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"   {actual_w}x{actual_h} | {dev}", flush=True)

    def _close_camera(self):
        if not self.is_camera_on:
            return
        print("💤 摄像头进入节能休眠", flush=True)

        if self._mjpeg_reader is not None:
            self._mjpeg_reader.close()
            self._mjpeg_reader = None

        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = None
        self._is_mjpeg = False
        # ↘ 关键：推空白帧到 WebSocket，让前端立即显示"节能模式"
        with self._jpeg_lock:
            self._latest_jpeg = self._blank_jpeg
        with self._inference_lock:
            self._inference_jpeg = self._blank_jpeg
        self._frame_ready.set()  # 唤醒 WebSocket 发送空白帧
        self._last_blank_push = time.time()
        self.is_camera_on = False

    # ================== ffmpeg 直读线程 ==================

    def _mjpeg_read_loop(self):
        """独立线程: 持续从 ffmpeg 管道读取 MJPEG，零 CPU

        - 摄像头开启: 实时读取并推送帧到 WebSocket
        - 摄像头休眠: 每 2 秒推送空白帧，让前端显示"节能模式"
        """
        gc_counter = 0
        frame_count = 0
        t0 = time.time()
        last_report_at = frame_count
        last_report_time = t0
        while self.is_running:
            try:
                if self.is_camera_on and self._mjpeg_reader is not None:
                    jpeg = self._mjpeg_reader.read_frame_nonblock()
                    if jpeg is not None and len(jpeg) > 512:
                        frame_count += 1
                        with self._jpeg_lock:
                            self._latest_jpeg = jpeg
                        with self._inference_lock:
                            self._inference_jpeg = jpeg
                        # 唤醒 WebSocket: 通知有新帧可用
                        self._frame_ready.set()

                        if frame_count % 90 == 1:
                            now = time.time()
                            # 瞬时帧率: 最近 90 帧的实际速率
                            delta_frames = frame_count - last_report_at
                            delta_time = now - last_report_time
                            inst_fps = delta_frames / max(delta_time, 0.001)
                            last_report_at = frame_count
                            last_report_time = now
                            sz_kb = len(jpeg) / 1024.0
                            print(f"  {frame_count} 帧 | ffmpeg直通 | ~{sz_kb:.0f}KB"
                                  f" | ~{inst_fps:.0f}fps (瞬时)", flush=True)
                    else:
                        # 无帧时极短等待，有帧时立即重试(连续读空管道缓冲)
                        time.sleep(0.0005)
                elif not self.is_camera_on:
                    # 摄像头休眠: 每 2s 推空白帧，让前端显示"节能模式"
                    now = time.time()
                    if now - self._last_blank_push > 2.0:
                        with self._jpeg_lock:
                            self._latest_jpeg = self._blank_jpeg
                        self._frame_ready.set()
                        self._last_blank_push = now
                    time.sleep(0.05)
                else:
                    # is_camera_on=True 但 _mjpeg_reader 尚未就绪 (唤醒过渡期)
                    time.sleep(0.05)

                gc_counter += 1
                if gc_counter >= 300:
                    gc.collect()
                    gc_counter = 0
            except Exception as e:
                print(f"ffmpeg 直读异常: {e}")
                time.sleep(0.1)

    # ================== 监控主循环 ==================

    def _monitor_loop(self):
        """重量感知节能 + OpenCV 降级采集

        休眠/唤醒策略 (v2.2):
        - 重量 > 30g → 唤醒摄像头，刷新 _last_weight_time
        - 重量 < 30g 持续 10s → 休眠摄像头
        - 启动时 _last_weight_time=0，摄像头默认休眠，有重量才唤醒
        """
        time.sleep(2)
        frame_count = 0
        last_w_print = 0.0

        while self.is_running:
            try:
                driver = self.get_driver()
                if driver:
                    try:
                        w = driver.get_weight()
                    except Exception:
                        w = 0.0

                    # 重量变化时打印
                    if abs(w - last_w_print) > 5:
                        print(f"⚖️ 重量: {w:.1f}g | 摄像头: {'开' if self.is_camera_on else '休眠'} | "
                              f"上次重量时间: {self._last_weight_time or '从未'}", flush=True)
                        last_w_print = w

                    if w > self.WEIGHT_THRESHOLD:
                        # 有重量：刷新时间戳，唤醒摄像头
                        self._last_weight_time = time.time()
                        self.last_active_time = time.time()
                        if not self.is_camera_on:
                            print(f"🔆 检测到重量 {w:.1f}g > {self.WEIGHT_THRESHOLD}g，唤醒摄像头", flush=True)
                            self._open_camera()
                    elif self.is_camera_on and self._last_weight_time > 0:
                        # 无重量：检查是否超过空闲超时
                        idle = time.time() - self._last_weight_time
                        if idle > self.IDLE_TIMEOUT:
                            print(f"💤 重量已消失 {idle:.0f}s，进入节能休眠", flush=True)
                            self._close_camera()
                else:
                    # 驱动未就绪，1s后重试
                    time.sleep(1)
                    continue

                # OpenCV 降级模式 (ffmpeg 直通模式跳过)
                if self.is_camera_on and self._mjpeg_reader is None and self.cap:
                    ret, frame = self.cap.read()
                    if ret and frame is not None:
                        frame_count += 1
                        with self.frame_lock:
                            self.latest_frame = frame
                        ret2, jpg = cv2.imencode('.jpg', frame,
                            [cv2.IMWRITE_JPEG_QUALITY, self.JPEG_QUALITY])
                        if ret2:
                            jpeg_bytes = jpg.tobytes()
                            with self._jpeg_lock:
                                self._latest_jpeg = jpeg_bytes
                            with self._inference_lock:
                                self._inference_jpeg = jpeg_bytes
                        if frame_count % 90 == 1:
                            sz_kb = len(jpeg_bytes) / 1024
                            print(f"  {frame_count} 帧 | {self.FRAME_W}x{self.FRAME_H}"
                                  f" | ~{sz_kb:.0f}KB [OpenCV]", flush=True)
                    else:
                        print("USB 摄像头读帧失败，尝试重新打开...")
                        self._close_camera()

                time.sleep(0.05)
            except Exception as e:
                print(f"监控循环异常: {e}")
                time.sleep(1)
