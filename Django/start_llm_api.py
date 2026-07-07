# -*- coding: utf-8 -*-
"""
Qwen RKLLM API 桥接服务
启动 FastAPI 服务，接收 HTTP 请求 → 转发给 C++ RKLLM Runtime → Qwen2.5-1.5B NPU 推理

用法: python start_llm_api.py
监听: http://127.0.0.1:8080/v1/chat
"""

import subprocess
import uvicorn
import threading
import time
import logging
import re
import os
import fcntl
from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [Qwen-NPU-Bridge] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Qwen RKLLM Bridge", version="1.0.0")

# ==================== Qwen 引擎配置 ====================
# 模型: Qwen2.5-1.5B-Instruct (INT8 量化, RKLLM 格式)
# 硬件: RK3588 NPU (via rkllm_api_demo C++ Runtime)
CMD = [
    "/home/elf/rkllm-runtime/examples/rkllm_api_demo/deploy/build/llm_demo",
    "/home/elf/qwen2.5-1.5b-instruct-w8.rkllm",
    "2048",   # max_context_len
    "1024"    # max_new_tokens
]

# ==================== 全局状态管理 ====================
proc_lock = threading.Lock()
proc = None
last_success_time = time.time()
request_count = 0
MAX_REQUESTS = 20  # 每 20 次请求后重启引擎防止内存泄漏


def kill_engine():
    """强制杀掉旧引擎进程"""
    global proc
    if proc is not None:
        try:
            logger.warning("Force killing old C++ engine process...")
            proc.kill()
            proc.wait(timeout=2)
        except Exception as e:
            logger.error(f"Failed to kill engine: {e}")
        proc = None
    os.system("pkill -9 -f llm_demo")


def launch_engine():
    """启动 Qwen RKLLM C++ 引擎并等待就绪"""
    global proc, last_success_time, request_count
    kill_engine()
    logger.info("============== Starting Qwen NPU C++ Engine ==============")
    try:
        proc = subprocess.Popen(
            CMD,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0
        )
    except Exception as e:
        logger.critical(f"Engine failed to start: {e}")
        return

    request_count = 0
    start = time.time()
    fd = proc.stdout.fileno()
    old_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, old_flags | os.O_NONBLOCK)

    buffer = bytearray()
    while time.time() - start < 30:
        try:
            chunk = os.read(fd, 4096)
            if chunk:
                buffer.extend(chunk)
                if b"rkllm init success" in buffer:
                    logger.info("SUCCESS: Qwen NPU Engine initialized!")
                    break
        except (BlockingIOError, IOError):
            time.sleep(0.1)
    else:
        logger.error("TIMEOUT: Qwen engine init failed within 30s.")

    last_success_time = time.time()


def drain_stdout(fd):
    """清空标准输出缓冲区"""
    try:
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
    except (BlockingIOError, IOError):
        pass


def read_until_prompt(fd, timeout=45, marker="user:"):
    """
    从 C++ 引擎读取输出直到遇到提示符
    包含死锁检测和自动产出机制
    """
    start_time = time.time()
    buffer = bytearray()
    last_chunk_time = time.time()
    has_started = False

    logger.debug(f"Reading Qwen NPU output, max wait {timeout}s...")

    while time.time() - start_time < timeout:
        try:
            chunk = os.read(fd, 4096)
            if chunk == b'':
                logger.error("ERROR: C++ Engine stdout pipe closed.")
                break

            if chunk:
                buffer.extend(chunk)
                last_chunk_time = time.time()
                has_started = True
                text = buffer.decode('utf-8', errors='ignore')
                if text.strip().endswith(marker):
                    logger.info(f"SUCCESS: Caught marker '{marker}'. Time: {time.time() - start_time:.2f}s")
                    break
            else:
                idle_time = time.time() - last_chunk_time
                if not has_started and idle_time > 15.0:
                    logger.error("DEADLOCK DETECTED: 15s no output, assuming frozen!")
                    break
                if has_started and idle_time > 4.0:
                    text = buffer.decode('utf-8', errors='ignore')
                    logger.info(f"AUTO-YIELD: Engine idle for 4s, extracting {len(text)} chars!")
                    break

            time.sleep(0.1)

        except (BlockingIOError, IOError):
            idle_time = time.time() - last_chunk_time
            if not has_started and idle_time > 15.0:
                logger.error("DEADLOCK DETECTED: 15s no output, assuming frozen!")
                break
            if has_started and idle_time > 4.0:
                text = buffer.decode('utf-8', errors='ignore')
                logger.info(f"AUTO-YIELD: Engine idle for 4s, extracting {len(text)} chars!")
                break
            time.sleep(0.1)

    final_text = buffer.decode('utf-8', errors='ignore')
    logger.debug(f"RAW OUTPUT:\n{final_text}\n{'='*40}")
    return final_text


def health_check():
    """健康检查循环：检测引擎存活状态，必要时自动重启"""
    global proc, last_success_time
    while True:
        time.sleep(10)
        with proc_lock:
            if proc is None or proc.poll() is not None:
                logger.error("HEALTH CHECK: Qwen engine dead! Restarting...")
                launch_engine()
                continue
            if time.time() - last_success_time > 300:
                logger.warning("HEALTH CHECK: Engine idle for 5 mins, preventive restart...")
                launch_engine()


# ==================== API 端点 ====================

class ChatRequest(BaseModel):
    prompt: str


@app.post("/v1/chat")
async def chat(req: ChatRequest):
    """
    Qwen 对话接口
    接收 prompt → 转发 C++ 引擎 → 返回生成文本
    """
    global proc, request_count, last_success_time

    # 换行符替换为空格 (C++ getline 以换行分割)
    llm_prompt = req.prompt.replace('\n', ' ')
    logger.info(f"New chat request. Count: {request_count}/{MAX_REQUESTS}")

    with proc_lock:
        # 达到阈值或引擎死亡时重启
        if request_count >= MAX_REQUESTS or proc is None or proc.poll() is not None:
            launch_engine()

        if proc is None or proc.poll() is not None:
            return {"reply": "ERROR: Qwen NPU Engine failed to start."}

        fd = proc.stdout.fileno()
        drain_stdout(fd)

        # 写入 prompt 到 C++ 引擎 stdin
        try:
            logger.debug("Writing Prompt to C++ stdin...")
            proc.stdin.write((llm_prompt + "\n").encode('utf-8'))
            proc.stdin.flush()
        except BrokenPipeError:
            logger.error("BrokenPipeError! Qwen engine crashed during write. Restarting...")
            launch_engine()
            proc.stdin.write((llm_prompt + "\n").encode('utf-8'))
            proc.stdin.flush()
            fd = proc.stdout.fileno()

        raw_text = read_until_prompt(fd, timeout=45)
        clean_text = raw_text.replace("user:", "").replace("robot:", "").strip()

        last_success_time = time.time()
        request_count += 1
        return {"reply": clean_text}


# ==================== 启动入口 ====================

if __name__ == "__main__":
    # 启动健康检查线程
    threading.Thread(target=health_check, daemon=True).start()
    logger.info("Qwen API Bridge listening on http://127.0.0.1:8080")
    uvicorn.run(app, host="127.0.0.1", port=8080)
