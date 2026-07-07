import os
import requests
import time

# ================= 配置区域 =================
# 自动定位到当前脚本所在目录的 static/fonts 文件夹
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FONTS_DIR = os.path.join(BASE_DIR, 'static', 'fonts')

# 使用 360 前端公共库 (Baomitu)，国内速度极快且稳定，替代 BootCDN
MIRROR_BASE = "https://lib.baomitu.com/font-awesome/4.7.0/fonts/"

FILES = [
    'fontawesome-webfont.woff2',
    'fontawesome-webfont.woff',
    'fontawesome-webfont.ttf'
]

# 模拟浏览器头，防止被反爬拦截
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def fix_icons():
    print(f"📂 目标目录: {STATIC_FONTS_DIR}")

    # 1. 确保目录存在
    if not os.path.exists(STATIC_FONTS_DIR):
        try:
            os.makedirs(STATIC_FONTS_DIR)
            print(f"✅ 已创建目录: static/fonts")
        except Exception as e:
            print(f"❌ 无法创建目录: {e}")
            return

    print("🚀 开始通过国内高速镜像下载...")

    # 2. 循环下载
    success_count = 0
    for file_name in FILES:
        url = MIRROR_BASE + file_name
        save_path = os.path.join(STATIC_FONTS_DIR, file_name)

        print(f"\n⬇️ [{file_name}] 下载中...")

        try:
            # 设置 10秒超时
            res = requests.get(url, headers=HEADERS, timeout=10)

            if res.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(res.content)
                print(f"   ✅ 下载成功! ({len(res.content) / 1024:.2f} KB)")
                success_count += 1
            else:
                print(f"   ❌ 下载失败 (状态码: {res.status_code})")

        except requests.exceptions.Timeout:
            print("   ❌ 网络超时 (Timeout)")
        except requests.exceptions.ConnectionError:
            print("   ❌ 连接被拒绝 (Connection Error)")
        except Exception as e:
            print(f"   ❌ 未知错误: {e}")

        # 稍微停顿一下，防止请求过快
        time.sleep(0.5)

    print("\n" + "=" * 30)
    if success_count == 3:
        print("🎉 全部修复完成！")
        print("👉 请回到浏览器，按 【Ctrl + F5】 强制刷新页面，图标应该恢复了。")
    else:
        print(f"⚠️ 完成了 {success_count}/3 个文件。如果有失败的，请重新运行脚本。")


if __name__ == '__main__':
    fix_icons()