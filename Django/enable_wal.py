import sqlite3
import os

# 数据库文件路径 (通常在项目根目录)
db_path = 'db.sqlite3'


def enable_wal():
    if not os.path.exists(db_path):
        print(f"❌ 错误：找不到数据库文件 {db_path}")
        print("请确保你在项目根目录下运行此脚本，或者数据库文件尚未生成。")
        return

    try:
        # 连接数据库
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. 开启 Write-Ahead Logging (WAL) 模式
        # 这允许同时进行读写操作，大幅减少 "database is locked"
        cursor.execute("PRAGMA journal_mode=WAL;")
        mode_result = cursor.fetchone()

        # 2. 增加同步容忍度 (可选，进一步提升性能)
        cursor.execute("PRAGMA synchronous=NORMAL;")

        conn.close()

        print(f"✅ 数据库优化成功！")
        print(f"👉 当前模式 (journal_mode): {mode_result[0]}")
        print("🚀 现在数据库支持更高的并发写入了，重启 Django 服务后生效。")

    except Exception as e:
        print(f"❌ 数据库设置失败: {e}")


if __name__ == "__main__":
    enable_wal()