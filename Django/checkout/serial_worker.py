import serial
import time
import threading
import struct
import logging

logger = logging.getLogger(__name__)

# ================= 协议常量定义 =================
# STM32 固件帧格式 (8字节):
#   AA 55 01 02 H L SUM FF
#   - AA 55: 帧头
#   - 01: 重量数据类型
#   - 02: 数据长度 (H+L = 2字节)
#   - H/L: int16 重量 (克), Big-Endian, STM32 已校准去皮
#   - SUM: (AA+55+01+02+H+L) & 0xFF
#   - FF: 帧尾
FRAME_HEAD_1 = 0xAA
FRAME_HEAD_2 = 0x55
FRAME_TAIL = 0xFF

TYPE_WEIGHT = 0x01  # 接收：重量数据
TYPE_INFO   = 0x02  # 发送：语音/商品信息/去皮指令


class SmartCheckoutProtocol:
    """
    智能称重系统 - 协议驱动类
    对应 STM32 固件 app.c Send_Weight_To_Pi() 的 8 字节帧格式。
    STM32 已做校准去皮 + 中值滤波 + EMA + 迟滞状态机，
    Python 端只做透传，不重复滤波。
    """

    def __init__(self, port='/dev/ttyS9', baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.running = False
        self.write_lock = threading.Lock()

        # 最新重量 (克)，STM32 已校准
        self.latest_weight_g = 0.0

    def connect(self):
        """连接串口并启动接收线程"""
        if self.ser and self.ser.is_open:
            return True

        try:
            self.ser = serial.Serial(
                self.port,
                self.baudrate,
                timeout=0.05,
                write_timeout=0.5
            )
            self.running = True

            self.rx_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.rx_thread.start()

            print(f"✅ [协议驱动] 串口 {self.port} 已连接 (8字节帧格式)")
            return True
        except Exception as e:
            print(f"❌ [协议驱动] 连接失败: {e}")
            return False

    def close(self):
        self.running = False
        if self.ser:
            self.ser.close()

    def get_weight(self):
        """获取当前重量 (克) — STM32 已校准，直接透传"""
        return self.latest_weight_g

    # ================= 发送指令 =================

    def _send_info_frame(self, data_bytes):
        """发送 TYPE_INFO 帧到 STM32"""
        if not self.ser or not self.ser.is_open:
            return False
        try:
            length = len(data_bytes)
            if length > 30:
                data_bytes = data_bytes[:30]
                length = 30

            checksum = (FRAME_HEAD_1 + FRAME_HEAD_2 + TYPE_INFO + length)
            for b in data_bytes:
                checksum += b
            checksum &= 0xFF

            packet = (
                struct.pack('BBBB', FRAME_HEAD_1, FRAME_HEAD_2, TYPE_INFO, length) +
                data_bytes +
                struct.pack('BB', checksum, FRAME_TAIL)
            )
            with self.write_lock:
                self.ser.write(packet)
            return True
        except Exception as e:
            print(f"❌ 发送帧异常: {e}")
            return False

    def play_voice(self, text):
        """发送语音播报指令 (TYPE_INFO 帧，STM32 解析后调用 Voice_Speak)"""
        if not self.ser or not self.ser.is_open:
            return False
        try:
            text_bytes = text.encode('gbk', errors='ignore')
            return self._send_info_frame(text_bytes)
        except Exception as e:
            print(f"❌ 发送语音异常: {e}")
            return False

    def tare(self):
        """去皮：发送 CMD_TARE 指令，STM32 收到后执行 HX711_Init_Tare()"""
        return self.play_voice("CMD_TARE")

    def send_product_info(self, name, price):
        """发送商品信息给 STM32 显示 (格式: name:price)"""
        content = f"{name}:{price}"
        return self.play_voice(content)

    # ================= 接收：重量帧解析 =================

    def _receive_loop(self):
        """
        接收线程 — 解析 STM32 发来的 8 字节重量帧。

        STM32 帧格式 (app.c Send_Weight_To_Pi):
          [0]AA [1]55 [2]01 [3]02 [4]H [5]L [6]SUM [7]FF

        H/L: int16 Big-Endian, 重量(克), STM32 已校准去皮
        SUM: (AA+55+01+02+H+L) & 0xFF
        """
        buffer = b''
        FRAME_LEN = 8  # AA 55 01 02 H L SUM FF

        while self.running:
            try:
                if self.ser.in_waiting:
                    buffer += self.ser.read(self.ser.in_waiting)

                while len(buffer) >= FRAME_LEN:
                    # 1. 帧头检查
                    if buffer[0] != FRAME_HEAD_1 or buffer[1] != FRAME_HEAD_2:
                        buffer = buffer[1:]
                        continue

                    # 2. 帧尾检查
                    if buffer[7] != FRAME_TAIL:
                        buffer = buffer[1:]
                        continue

                    # 3. 类型检查
                    if buffer[2] != TYPE_WEIGHT:
                        buffer = buffer[1:]
                        continue

                    # 4. 校验和: AA+55+01+02+H+L
                    calc_sum = (FRAME_HEAD_1 + FRAME_HEAD_2 + TYPE_WEIGHT +
                                buffer[3] + buffer[4] + buffer[5]) & 0xFF
                    recv_sum = buffer[6]

                    if calc_sum != recv_sum:
                        # 校验失败，跳过 1 字节继续搜索
                        hex_str = buffer[0:FRAME_LEN].hex().upper()
                        print(f"⚠️ 校验失败: Calc 0x{calc_sum:02X} != Recv 0x{recv_sum:02X} | 帧:{hex_str}")
                        buffer = buffer[1:]
                        continue

                    # ✅ 校验成功 — 解析重量
                    # H 在 buffer[4], L 在 buffer[5], Big-Endian int16
                    w = (buffer[4] << 8) | buffer[5]
                    if w > 32767:
                        w -= 65536

                    # STM32 发送的单位就是克，直接使用
                    self.latest_weight_g = float(w)

                    # 调试打印 (每 20 帧打印一次，减少刷屏)
                    hex_str = buffer[0:FRAME_LEN].hex().upper()
                    print(f"🔍 [RX] 帧:{hex_str} | 重量:{self.latest_weight_g:.1f}g")

                    buffer = buffer[FRAME_LEN:]

                time.sleep(0.005)

            except Exception as e:
                print(f"❌ 接收循环错误: {e}")
                time.sleep(1)
