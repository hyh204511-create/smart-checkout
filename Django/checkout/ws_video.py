#!/usr/bin/env python3
"""
RK3588 智能结算终端 — WebSocket 视频推送服务器 v2.3
独立端口 8765, 推送 MJPEG 帧 (事件驱动 + 短轮询混合)
协议: 二进制 WebSocket, 每帧一个完整 JPEG 消息
URL:  ws://<board-ip>:8765
"""

import asyncio
import time
import hashlib
import logging

logger = logging.getLogger(__name__)

# 全局引用, 由 Django 启动时注入
_camera_manager = None


def set_camera_manager(cm):
    """由 apps.py 在启动时调用, 注入 CameraManager 引用"""
    global _camera_manager
    _camera_manager = cm


async def ws_handler(websocket):
    """
    WebSocket 连接处理器 — v2.3 混合模式
    - 摄像头线程 set() threading.Event → asyncio 立即消费
    - 无帧时 8ms 短轮询（125Hz），CPU 可忽略
    - 哈希去重防止 V4L2 偶发重复帧
    """
    logger.info(f"📡 WebSocket 客户端已连接 (v2.3 混合模式)")
    frame_count = 0
    log_interval = 90
    frame_event = None
    last_hash = None
    t0 = time.time()

    if _camera_manager:
        try:
            frame_event = _camera_manager.get_frame_event()
        except Exception:
            pass

    try:
        while True:
            # 非阻塞检查: 摄像头线程是否通知了新帧
            if frame_event and frame_event.is_set():
                frame_event.clear()
                jpeg = _camera_manager.get_jpeg_frame()
                if jpeg and len(jpeg) > 512:
                    # 哈希去重: 跳过与上一帧完全相同的数据
                    h = hashlib.md5(jpeg[:4096]).digest()
                    if h != last_hash:
                        last_hash = h
                        await websocket.send(jpeg)
                        frame_count += 1
                        if frame_count % log_interval == 0:
                            elapsed = time.time() - t0
                            fps = frame_count / max(elapsed, 0.001)
                            sz_kb = len(jpeg) / 1024.0
                            logger.debug(f"📡 WS 已推送 {frame_count} 帧"
                                         f" (~{sz_kb:.0f}KB, ~{fps:.0f}fps)")
                        continue  # 跳过 sleep，立即检查是否有下一帧

            # 无新帧或无事件机制: 短让出 CPU，下轮再查
            await asyncio.sleep(0.008)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning(f"📡 WebSocket 异常: {e}")
    finally:
        elapsed = time.time() - t0
        fps = frame_count / max(elapsed, 0.001)
        logger.info(f"📡 WebSocket 客户端已断开"
                    f" (共 {frame_count} 帧, 平均 {fps:.1f}fps)")


async def _async_server(host, port):
    """异步主循环 (websockets 13+ API, 含端口冲突重试)"""
    import websockets
    import asyncio as aio

    for attempt in range(10):
        try:
            async with websockets.serve(
                ws_handler, host, port,
                max_size=2 * 1024 * 1024,
                ping_interval=30,
                ping_timeout=10,
            ):
                logger.info(f"🔌 WebSocket 视频服务器已启动: ws://{host}:{port}")
                print(f"🔌 WebSocket 视频服务器已启动: ws://{host}:{port}")
                await asyncio.Future()  # 永久运行
        except OSError as e:
            wait = 1 + attempt * 2
            logger.warning(f"⚠️ 端口 {port} 被占用，{wait}s 后重试 ({attempt+1}/10)...")
            await aio.sleep(wait)


def _run_server(host="0.0.0.0", port=8765):
    """在专用事件循环中运行 WebSocket 服务器 (阻塞)"""
    try:
        asyncio.run(_async_server(host, port))
    except Exception as e:
        logger.error(f"WebSocket 服务器异常: {e}")


def start_ws_server(host="0.0.0.0", port=8765):
    """同步入口 — 在新线程中启动 WebSocket 事件循环"""
    import threading

    t = threading.Thread(target=_run_server, args=(host, port), daemon=True, name="ws-video")
    t.start()
    return t
