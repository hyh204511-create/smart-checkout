#!/usr/bin/env python3
"""
终端代理 — 连接云端服务器 (适配上位机-RK3588 项目)
=====================================================
独立于 Django 运行的后台进程，不影响现有收银功能。

功能:
    1. 首次启动自动注册设备到云端
    2. 每30秒上报心跳 (CPU/内存/磁盘/摄像头/串口状态)
    3. 异步上传本地订单到云端
    4. 定期从云端同步商品更新
    5. 支持 --mock 模式 (单机模拟多终端测试)
    6. 支持 --device-id 手动指定设备ID

用法:
    python device_agent.py --device-name "收银终端1号"       # 正常模式
    python device_agent.py --mock --device-id mock-001       # 模拟测试
    python device_agent.py --device-id dev-001 --device-name "1号机"  # 手动指定

与 systemd 集成:
    smart-checkout.service 中增加 ExecStartPost 或独立 .service 管理
"""
import argparse
import json
import logging
import os
import sys
import time
import threading
import queue
from datetime import datetime

import requests

# 抑制 HTTPS 自签名证书警告 (内网/开发环境)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== 路径配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(BASE_DIR, 'db.sqlite3')  # RK3588 上位机 SQLite 路径

# ==================== 云托管地址 ====================
CLOUD_SERVER_URL = os.environ.get(
    'CLOUD_SERVER_URL',
    'https://smart-checkout-265906-8-1439803189.sh.run.tcloudbase.com'
)

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('device_agent')

# ==================== 定时参数 ====================
HEARTBEAT_INTERVAL = 30       # 心跳间隔 (秒)
ORDER_CHECK_INTERVAL = 5      # 订单扫描间隔 (秒)
PRODUCT_SYNC_INTERVAL = 300   # 商品同步间隔 (秒, 5分钟)


class DeviceAgent:
    """RK3588 终端代理 — 连接云托管"""

    def __init__(self, device_id=None, device_name=None, mock_mode=False):
        self.mock_mode = mock_mode
        self.device_id = device_id
        self.device_name = device_name or os.environ.get('DEVICE_NAME', 'RK3588-收银终端')
        self.device_token = None
        self.product_version = 0
        self.running = False
        self._driver = None  # 串口驱动引用 (惰性加载)

        os.makedirs(DATA_DIR, exist_ok=True)

    # ==================== 设备ID & Token ====================

    def _load_or_generate_device_id(self):
        """加载或生成设备ID"""
        id_file = os.path.join(DATA_DIR, 'device_id.txt')
        if self.device_id:
            return
        if os.path.exists(id_file):
            with open(id_file, 'r') as f:
                self.device_id = f.read().strip()
                if self.device_id:
                    logger.info(f"加载已有设备ID: {self.device_id}")
                    return
        self.device_id = 'DEV-' + str(int(time.time()))[-6:] + '-' + os.uname().nodename[:4] if hasattr(os, 'uname') else 'DEV-' + str(int(time.time()))[-6:]
        with open(id_file, 'w') as f:
            f.write(self.device_id)
        logger.info(f"生成新设备ID: {self.device_id}")

    def _token_file(self):
        return os.path.join(DATA_DIR, f'device_token_{self.device_id}.txt')

    def _load_or_register(self):
        """加载本地 token 或向云端注册"""
        token_file = self._token_file()
        if os.path.exists(token_file):
            with open(token_file, 'r') as f:
                self.device_token = f.read().strip()
                if self.device_token:
                    logger.info(f"已加载本地 token ({self.device_id})")
                    return True

        logger.info(f"首次启动 ({self.device_id})，向云端注册...")
        try:
            resp = requests.post(
                f'{CLOUD_SERVER_URL}/api/device/register/',
                json={
                    'device_id': self.device_id,
                    'device_name': self.device_name,
                    'agent_version': '2.0.0-rk3588',
                },
                timeout=15,
                verify=False,
            )
            data = resp.json()
            if data.get('success'):
                self.device_token = data['device_token']
                if data.get('device_id'):
                    self.device_id = data['device_id']
                with open(token_file, 'w') as f:
                    f.write(self.device_token)
                logger.info(f"注册成功! device_id={self.device_id}")
                return True
            else:
                logger.error(f"注册失败: {data.get('error')}")
                return False
        except Exception as e:
            logger.error(f"注册请求失败: {e}")
            return False

    # ==================== API 调用 ====================

    def _api_post(self, path, data=None):
        try:
            resp = requests.post(
                f'{CLOUD_SERVER_URL}{path}',
                json=data or {},
                headers={'Authorization': f'Bearer {self.device_token}',
                         'Content-Type': 'application/json'},
                timeout=15, verify=False,
            )
            if resp.status_code == 401:
                logger.error("Token 无效，重新注册...")
                token_file = self._token_file()
                if os.path.exists(token_file):
                    os.remove(token_file)
                self.device_token = None
                if self._load_or_register():
                    return self._api_post(path, data)
            data_resp = resp.json()
            # 云端可能返回 200 但 body 中是未授权错误
            if data_resp and data_resp.get('error') == '未授权':
                logger.error("Token 已过期，重新注册...")
                token_file = self._token_file()
                if os.path.exists(token_file):
                    os.remove(token_file)
                self.device_token = None
                if self._load_or_register():
                    return self._api_post(path, data)
            return data_resp
        except Exception as e:
            logger.error(f"API请求失败 [{path}]: {e}")
            return None

    def _api_get(self, path, params=None):
        try:
            resp = requests.get(
                f'{CLOUD_SERVER_URL}{path}',
                params=params or {},
                headers={'Authorization': f'Bearer {self.device_token}'},
                timeout=15, verify=False,
            )
            if resp.status_code == 401:
                logger.error("Token 无效，重新注册...")
                token_file = self._token_file()
                if os.path.exists(token_file):
                    os.remove(token_file)
                self.device_token = None
                if self._load_or_register():
                    return self._api_get(path, params)
            data_resp = resp.json()
            if data_resp and data_resp.get('error') == '未授权':
                logger.error("Token 已过期，重新注册...")
                token_file = self._token_file()
                if os.path.exists(token_file):
                    os.remove(token_file)
                self.device_token = None
                if self._load_or_register():
                    return self._api_get(path, params)
            return data_resp
        except Exception as e:
            logger.error(f"API请求失败 [{path}]: {e}")
            return None

    # ==================== 系统状态采集 ====================

    def _get_driver(self):
        """惰性获取串口驱动引用 (仅检查设备文件, 不打开串口避免与 Django 冲突)"""
        if self._driver is not None:
            return self._driver
        self._driver = False
        try:
            import glob
            ports = glob.glob('/dev/ttyS*') + glob.glob('/dev/ttyUSB*')
            if ports:
                self._driver = True  # 有串口设备即可, 不实际打开
        except Exception:
            pass
        return self._driver if self._driver is not False else None

    def _collect_system_status(self):
        """采集系统状态 (兼容 RK3588)"""
        if self.mock_mode:
            import random
            return {
                'cpu_temp': round(random.uniform(40, 65), 1),
                'cpu_usage': round(random.uniform(10, 80), 1),
                'memory_usage': round(random.uniform(30, 70), 1),
                'disk_free': random.randint(5000000000, 15000000000),
                'camera_ok': True,
                'scale_ok': True,
                'model_ok': True,
            }

        status = {
            'cpu_temp': None,
            'cpu_usage': None,
            'memory_usage': None,
            'disk_free': None,
            'camera_ok': False,
            'scale_ok': False,
            'model_ok': False,
        }

        # CPU / 内存 / 磁盘
        try:
            import psutil
            status['cpu_usage'] = psutil.cpu_percent(interval=0.3)
            status['memory_usage'] = psutil.virtual_memory().percent
            status['disk_free'] = psutil.disk_usage('/').free
            try:
                temps = psutil.sensors_temperatures()
                for entries in temps.values():
                    if entries:
                        status['cpu_temp'] = entries[0].current
                        break
            except Exception:
                pass
        except ImportError:
            pass

        # 串口/称重 — 只检查设备文件是否存在 (不打开, 避免与 Django 抢串口)
        drv = self._get_driver()
        if drv:
            status['scale_ok'] = True

        # 摄像头 — 只检查设备文件是否存在 (不打开 V4L2, 避免与 ffmpeg 抢占)
        try:
            import glob
            video_devs = glob.glob('/dev/video*')
            # 排除 ISP 辅助节点：只检查可读写的真实摄像头
            for dev in sorted(video_devs):
                if dev.startswith('/dev/video-dec') or dev.startswith('/dev/video-enc'):
                    continue
                if os.access(dev, os.R_OK | os.W_OK):
                    status['camera_ok'] = True
                    break
        except Exception:
            pass

        # AI 模型文件存在即认为就绪
        rknn_path = os.path.join(BASE_DIR, 'yolo11_rk3588_int8.rknn')
        onnx_path = os.path.join(BASE_DIR, 'best.onnx')
        status['model_ok'] = os.path.exists(rknn_path) or os.path.exists(onnx_path)

        return status

    # ==================== 心跳 ====================

    def _heartbeat_loop(self):
        while self.running:
            try:
                status = self._collect_system_status()
                result = self._api_post('/api/device/heartbeat/', status)
                if result and result.get('success'):
                    if result.get('need_sync'):
                        self._sync_products()
                    logger.info(f"心跳正常 (v={result.get('product_version')})")
                else:
                    logger.warning("心跳上报失败")
            except Exception as e:
                logger.error(f"心跳异常: {e}")
            time.sleep(HEARTBEAT_INTERVAL)

    # ==================== 订单上传 ====================

    def _get_synced_set(self):
        """读取已同步的订单 ID 集合 (文件追踪, 不修改 DB 模型)"""
        sync_file = os.path.join(DATA_DIR, 'synced_orders.txt')
        if not os.path.exists(sync_file):
            return set()
        with open(sync_file, 'r') as f:
            return set(line.strip() for line in f if line.strip())

    def _mark_order_synced(self, order_id):
        """标记订单已同步 (追加到文件)"""
        sync_file = os.path.join(DATA_DIR, 'synced_orders.txt')
        with open(sync_file, 'a') as f:
            f.write(order_id + '\n')
        # 超过 10000 行自动裁剪
        if os.path.getsize(sync_file) > 500000:
            with open(sync_file, 'r') as f:
                lines = f.readlines()
            with open(sync_file, 'w') as f:
                f.writelines(lines[-5000:])

    def _get_pending_orders(self):
        """扫描本地 SQLite 中待同步的订单 (排除已同步的)"""
        if self.mock_mode:
            return self._generate_mock_orders()

        if not os.path.exists(DB_PATH):
            return []

        synced = self._get_synced_set()

        try:
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            # RK3588 上位机 Order 模型: 无 synced 字段, status='paid' 即为已支付
            cursor = conn.execute(
                "SELECT * FROM checkout_order WHERE status='paid' ORDER BY created_time"
            )
            orders = []
            for row in cursor.fetchall():
                oid = row['order_id']
                if oid in synced:
                    continue
                products = row['products']
                if isinstance(products, str):
                    try:
                        products = json.loads(products)
                    except Exception:
                        products = []
                orders.append({
                    'order_id': oid,
                    'total_amount': float(row['total_amount']),
                    'products': products,
                    'created_time': row['created_time'],
                    'paid_time': row['created_time'],  # 模型无 paid_time, 用 created_time
                })
            conn.close()
            return orders
        except Exception as e:
            logger.error(f"读取本地订单失败: {e}")
            return []

    def _generate_mock_orders(self):
        """模拟模式: 随机生成订单"""
        import random
        if random.random() > 0.3:
            return []
        fruits = ['apple', 'banana', 'orange', 'grape', 'watermelon', 'cherry']
        product = random.choice(fruits)
        qty = round(random.uniform(0.3, 2.0), 1)
        price = round(random.uniform(3, 15) * qty, 1)
        return [{
            'order_id': f'MOCK-{int(time.time())}-{random.randint(100, 999)}',
            'total_amount': price,
            'products': [{'name': product, 'quantity': qty, 'price': price}],
            'created_time': datetime.now().isoformat(),
            'paid_time': datetime.now().isoformat(),
        }]

    def _upload_order(self, order):
        result = self._api_post('/api/order/upload/', {
            'order_id': order['order_id'],
            'total_amount': str(order['total_amount']),
            'products': order['products'],
            'created_time': order['created_time'],
            'paid_time': order.get('paid_time'),
        })
        return result and result.get('success')

    def _order_sync_loop(self):
        while self.running:
            try:
                orders = self._get_pending_orders()
                for order in orders:
                    if self._upload_order(order):
                        if not self.mock_mode:
                            self._mark_order_synced(order['order_id'])
                        logger.info(f"订单已上传: {order['order_id']} ¥{order['total_amount']}")
                    else:
                        logger.warning(f"订单上传失败: {order['order_id']}")
            except Exception as e:
                logger.error(f"订单同步异常: {e}")
            time.sleep(ORDER_CHECK_INTERVAL)

    # ==================== 商品同步 ====================

    def _sync_products(self):
        """从云端同步商品到本地 SQLite"""
        result = self._api_get('/api/product/sync/', {'current_version': self.product_version})
        if not result or not result.get('success'):
            return False
        if not result.get('need_update'):
            return True

        products = result.get('products', [])
        if not products:
            return True

        try:
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            # 注意: 不删除本地自建商品（id >= 9000 是本地手动添加的）
            conn.execute("DELETE FROM checkout_product WHERE id < 9000")
            for p in products:
                pid = p['id']
                # 跳过云端同步下来的本地商品占位符
                conn.execute(
                    """INSERT INTO checkout_product
                       (id, name, price, stock, cost_price, barcode, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (pid, p['name'], p['price'], p.get('stock', 0),
                     p.get('cost_price', 0), p.get('barcode', ''),
                     p.get('created_at', datetime.now().isoformat()),
                     p.get('updated_at', datetime.now().isoformat()))
                )
            conn.commit()
            conn.close()
            self.product_version = result.get('version', 0)
            logger.info(f"商品同步完成: {len(products)} 个 (v{self.product_version})")
            return True
        except Exception as e:
            logger.error(f"商品同步写入失败: {e}")
            return False

    def _product_sync_loop(self):
        while self.running:
            time.sleep(PRODUCT_SYNC_INTERVAL)
            if self.running:
                self._sync_products()

    # ==================== 主循环 ====================

    def start(self):
        self.running = True
        self._load_or_generate_device_id()
        logger.info(f"RK3588 设备代理启动: device_id={self.device_id}")

        if not self._load_or_register():
            logger.error("设备注册失败，退出")
            return

        self._sync_products()

        threads = [
            threading.Thread(target=self._heartbeat_loop, daemon=True, name='heartbeat'),
            threading.Thread(target=self._order_sync_loop, daemon=True, name='order-sync'),
            threading.Thread(target=self._product_sync_loop, daemon=True, name='product-sync'),
        ]
        for t in threads:
            t.start()

        logger.info(f"[OK] 终端代理运行中 (云端: {CLOUD_SERVER_URL})")

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.running = False
        logger.info("终端代理已停止")


# ==================== 入口 ====================

def main():
    parser = argparse.ArgumentParser(description='RK3588 智能收银终端代理')
    parser.add_argument('--device-id', type=str, default=None, help='设备ID')
    parser.add_argument('--device-name', type=str, default=None, help='设备名称')
    parser.add_argument('--cloud-url', type=str, default=None, help='云端地址')
    parser.add_argument('--mock', action='store_true', help='模拟模式')
    args = parser.parse_args()

    global CLOUD_SERVER_URL
    if args.cloud_url:
        CLOUD_SERVER_URL = args.cloud_url

    if args.mock:
        logger.info("=" * 40)
        logger.info("模拟模式 - 用于 PC 单机测试多终端")
        logger.info(f"设备ID: {args.device_id or '自动生成'}")
        logger.info(f"云端: {CLOUD_SERVER_URL}")
        logger.info("=" * 40)

    agent = DeviceAgent(
        device_id=args.device_id,
        device_name=args.device_name,
        mock_mode=args.mock,
    )
    agent.start()


if __name__ == '__main__':
    main()
