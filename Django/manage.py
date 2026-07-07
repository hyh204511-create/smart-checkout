#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

#!/usr/bin/env python
import sys, os
print("=== Django 实际解释器 ===")
print("可执行文件:", sys.executable)
print("虚拟环境:", getattr(sys, 'base_prefix', sys.prefix))
print("PATH 前 3 项:", sys.path[:3])
def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smart_checkout.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
