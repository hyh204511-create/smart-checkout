import os
import requests

# 配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 你的静态文件应该放在 app 下或者根目录 static 下，这里我们统一放在根目录 static
STATIC_ROOT = os.path.join(BASE_DIR, 'static')

FILES = {
    'js/jquery.min.js': 'https://cdn.bootcdn.net/ajax/libs/jquery/3.6.0/jquery.min.js',
    'js/sweetalert2.all.min.js': 'https://cdn.bootcdn.net/ajax/libs/limonte-sweetalert2/11.7.32/sweetalert2.all.min.js',
    'js/echarts.min.js': 'https://cdn.bootcdn.net/ajax/libs/echarts/5.4.3/echarts.min.js',
    'css/font-awesome.min.css': 'https://cdn.bootcdn.net/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css',
    # FontAwesome 字体文件 (必须)
    'fonts/fontawesome-webfont.woff2': 'https://cdn.bootcdn.net/ajax/libs/font-awesome/4.7.0/fonts/fontawesome-webfont.woff2?v=4.7.0'
}


def download_static():
    print(f"📂 正在检查静态目录: {STATIC_ROOT}")
    if not os.path.exists(STATIC_ROOT):
        os.makedirs(STATIC_ROOT)
        print("✅ 创建 static 根目录")

    for path, url in FILES.items():
        local_path = os.path.join(STATIC_ROOT, path.replace('/', os.sep))
        dir_name = os.path.dirname(local_path)

        if not os.path.exists(dir_name):
            os.makedirs(dir_name)

        print(f"⬇️ 正在下载: {path} ...")
        try:
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                with open(local_path, 'wb') as f:
                    f.write(res.content)
                print(f"   ✅ 保存成功")
            else:
                print(f"   ❌ 下载失败 (状态码 {res.status_code})")
        except Exception as e:
            print(f"   ❌ 下载异常: {e}")

    # 创建一个空的 css 文件防止报错
    custom_css = os.path.join(STATIC_ROOT, 'css', 'style.css')
    if not os.path.exists(custom_css):
        with open(custom_css, 'w') as f:
            f.write("/* Local CSS */")

    print("\n🎉 所有静态文件已就绪！请继续执行后续步骤。")


if __name__ == '__main__':
    download_static()