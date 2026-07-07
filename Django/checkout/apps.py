# -*- coding: utf-8 -*-
"""
Checkout 应用配置 — RK3588 智能结算终端
- SQLite WAL 性能优化
- Python GC 调优 (减少 GC pauses)
- 硬件驱动延迟初始化 (串口 + 摄像头)
"""
import os
import gc
import threading
import logging
import time

from django.apps import AppConfig
from django.db import connection

logger = logging.getLogger(__name__)


class CheckoutConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'checkout'

    # ✅ 全局单例槽位 — 供 views.py / camera_manager.py 共享访问
    driver = None          # SmartCheckoutProtocol 实例
    camera_manager = None  # CameraManager 实例

    def ready(self):
        """
        应用启动时执行：
        1. 配置 SQLite WAL 模式 + 性能优化
        2. 在后台线程中延迟初始化硬件驱动
        """
        # ---------- SQLite 性能优化 (利用 64GB RAM) ----------
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA busy_timeout=5000;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA cache_size=-65536;")  # 64MB 页面缓存
            cursor.execute("PRAGMA temp_store=MEMORY;")
            cursor.execute("PRAGMA mmap_size=268435456;")  # 256MB 内存映射 I/O
        logger.info("SQLite 性能优化: WAL + 64MB cache + 256MB mmap")

        # ---------- Python GC 调优 (减少 GC pauses) ----------
        # RK3588 64GB RAM 充足，用内存换延迟 — 提高阈值，减少触发频率
        gc.set_threshold(70000, 30, 30)  # (gen0=70k, gen1=30, gen2=30)
        # 启动后台 GC ticker: 每 30 秒触发一次可控 GC
        def _gc_ticker():
            while True:
                time.sleep(30)
                collected = gc.collect()
                if collected > 0:
                    logger.debug(f"  GC 回收 {collected} 个对象")

        threading.Thread(target=_gc_ticker, daemon=True, name="gc-ticker").start()
        logger.info("Python GC 调优: threshold=(70000,30,30) + 30s ticker")

        # ---------- 硬件驱动延迟初始化 ----------
        # 在后台线程中初始化，避免阻塞 Django 启动
        # 同时避免 import 循环: 驱动模块在运行时导入
        logger.info("CheckoutConfig.ready() 完成，硬件驱动将在后台线程中初始化")

        def startup():
            print(f"🚀 [系统启动] 正在初始化硬件驱动 (PID: {os.getpid()})...")

            from .serial_worker import SmartCheckoutProtocol

            try:
                CheckoutConfig.driver = SmartCheckoutProtocol(port='/dev/ttyS9')
                success = CheckoutConfig.driver.connect()
                if not success:
                    print("⚠️ 串口连接失败，请检查 /dev/ttyS9 是否存在")
                else:
                    print("✅ 串口驱动已就绪")
            except Exception as e:
                print(f"❌ 串口初始化异常: {e}")

            try:
                from .camera_manager import CameraManager
                CheckoutConfig.camera_manager = CameraManager()
                CheckoutConfig.camera_manager.start()
                print("✅ 摄像头管理器已就绪")
            except Exception as e:
                print(f"❌ 摄像头初始化异常: {e}")

            # 启动 WebSocket 视频推送服务器 (MPP 硬件编码)
            try:
                from .ws_video import start_ws_server, set_camera_manager
                # 注入 CameraManager 引用 (ws_video 模块使用)
                set_camera_manager(CheckoutConfig.camera_manager)
                start_ws_server(host="0.0.0.0", port=8765)
                print("✅ WebSocket 视频服务器已启动 (端口 8765)")
            except Exception as e:
                print(f"⚠️ WebSocket 视频服务器启动失败: {e}")

        threading.Thread(target=startup, daemon=True).start()
