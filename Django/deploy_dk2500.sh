#!/bin/bash
# ============================================================
# SmartCheckout DK-2500 一键部署脚本
# 在 DK-2500 Ubuntu 22.04 上以普通用户身份运行
# ============================================================
set -e

echo "🚀 SmartCheckout DK-2500 部署开始..."

# ---- 1. 系统依赖 ----
echo "📦 [1/5] 安装系统依赖..."
sudo apt update
sudo apt install -y python3-pip python3-venv fonts-wqy-zenhei v4l-utils

# ---- 2. Python 虚拟环境 ----
echo "🐍 [2/5] 创建 Python 虚拟环境..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip

# ---- 3. Python 包 ----
echo "📚 [3/5] 安装 Python 依赖..."
pip install -r requirements.txt

# ---- 4. Django 初始化 ----
echo "🗄️  [4/5] 初始化数据库..."
python manage.py makemigrations checkout 2>/dev/null || true
python manage.py migrate
python manage.py init_products 2>/dev/null || echo "⚠️  init_products 可能不存在，请手动添加商品"

# ---- 5. 检查关键文件 ----
echo "🔍 [5/5] 检查关键文件..."
if [ -f "best.onnx" ]; then
    echo "   ✅ best.onnx 模型文件已就位"
else
    echo "   ❌ 缺少 best.onnx！请将 ONNX 模型文件放到 $(pwd)/best.onnx"
fi

if [ -c "/dev/ttyS0" ]; then
    echo "   ✅ /dev/ttyS0 串口就绪"
else
    echo "   ⚠️  /dev/ttyS0 不存在，请确认 STM32 接线"
fi

ls /dev/video* 2>/dev/null && echo "   ✅ 摄像头已检测到" || echo "   ⚠️  未检测到摄像头，请插入 USB 摄像头"

echo ""
echo "✅ 部署完成！启动命令："
echo "   source venv/bin/activate"
echo "   python manage.py runserver 0.0.0.0:8000"
echo ""
echo "🔧 创建管理员: python manage.py createsuperuser"
