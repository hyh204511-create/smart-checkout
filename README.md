# 基于端边云协同的智能视觉结算终端

> **2026 全国大学生嵌入式芯片与系统设计竞赛 — 应用赛道**  
> **瑞芯微（Rockchip）赛道 | 西南赛区**  
> **队伍：芯联云端智汇队**

---

## 📋 项目简介

本作品设计并实现了一套面向非标生鲜商品的 **端-边-云协同智能视觉结算终端**，针对农贸市场、社区生鲜店等小微零售场景中散装商品无条码、识别困难、结算效率低下的痛点，深度融合嵌入式实时控制、NPU 边缘 AI 推理、云端数据中台和微信小程序移动管理，构建了从商品自动识别、实时称重、智能计价、语音播报到移动端经营决策的全链路闭环。

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│  端侧 (STM32F407)          边侧 (RK3588)       云侧 (CloudBase) │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────┐  │
│  │ 称重采集滤波  │◄──►│ AI 视觉识别   │◄──►│ 设备集群管理    │  │
│  │ LCD 显示刷新  │    │ 收银业务核心  │    │ 商品订单存储    │  │
│  │ TTS 语音播报  │    │ 设备数据同步  │    │ 数据统计分析    │  │
│  │ 串口 DMA 通信 │    │ 外设统一管理  │    │ 微信小程序入口  │  │
│  └─────────────┘    └──────────────┘    └────────────────┘  │
│   FreeRTOS           Ubuntu + Django     腾讯云容器服务      │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 仓库结构

```
├── Core/                        # 下位机 STM32 源码
│   ├── Inc/                     # 头文件 (app.h, hx711.h, lcd.h, voice.h...)
│   ├── Src/                     # 源文件 (app.c, hx711.c, main.c, freertos.c...)
│   └── 基于端边云协同的智能视觉结算终端-下位机STM32源码说明.docx
│
├── Django/                      # 上位机 RK3588 源码
│   ├── checkout/                # Django 应用 (views.py, models.py, camera_manager.py...)
│   ├── smart_checkout/          # Django 配置 (settings.py, urls.py)
│   ├── device_agent.py          # 云端同步守护进程
│   ├── start_llm_api.py         # Qwen2.5 LLM 桥接服务
│   ├── templates/               # HTML 前端模板
│   ├── static/                  # 静态资源 (CSS, JS)
│   └── 基于端边云协同的智能视觉结算终端-上位机Django源码说明.docx
│
├── miniprogram/                 # 微信小程序源码
│   ├── pages/                   # 6 个页面 (dashboard, sales-report, product-manage...)
│   ├── utils/                   # API 封装 (api.js)
│   └── 基于端边云协同的智能视觉结算终端-微信小程序源码说明.docx
│
├── 基于端边云协同的智能视觉结算终端-上下位机连接及云端服务说明.docx
└── README.md
```

---

## 🔧 核心技术栈

| 层级 | 技术 |
|------|------|
| **端侧** | STM32F407ZGT6 · FreeRTOS · HX711 称重 · ILI9341 LCD · SYN6288 TTS |
| **边侧** | RK3588 (6TOPS NPU) · Ubuntu 22.04 · Django 4.2 · YOLO11 (RKNN) · Qwen2.5-1.5B (RKLLM) |
| **云侧** | Tencent CloudBase · Django REST Framework · JWT 认证 · SQLite WAL |
| **小程序** | 微信原生框架 · ECharts 图表 · REST API |

---

## 🚀 快速开始

### 下位机 (STM32)
1. 使用 Keil MDK 或 STM32CubeIDE 打开 `Core/` 目录
2. 编译烧录到 STM32F407ZGT6
3. UART1 (115200bps) 连接 RK3588

### 上位机 (RK3588)
```bash
cd Django/
pip install -r requirements.txt
python manage.py runserver 0.0.0.0:8000
# 启动 LLM 桥接
python start_llm_api.py
# 启动云端同步
python device_agent.py --device-name "1号机"
```

### 微信小程序
1. 微信开发者工具导入 `miniprogram/` 目录
2. 修改 `utils/api.js` 中的云端服务器地址
3. 编译预览

---

## 📊 性能指标

| 指标 | 数值 |
|------|------|
| 识别精度 (mAP@0.5) | ≥86% |
| 单帧推理 (NPU) | <30ms |
| 单帧推理 (CPU) | <300ms |
| 称重误差 | ±1g |
| 端到端延迟 | <300ms |
| CNN 模型大小 | 23MB (INT8) |

---

## 📄 许可证

本项目为 2026 嵌入式大赛参赛作品，遵循 MIT License 开源。

---

## 👥 队伍成员

**芯联云端智汇队** — 胡宇航、廖珂、蒲雄
