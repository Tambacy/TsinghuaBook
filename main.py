# coding:utf-8
"""
命令行入口（保留原有用法：``python main.py <url> --token xxx``）。

真正的实现在 xk_app/app/core/cli.py —— 收进包里是为了让打包后的 exe
也能直接用命令行，而不是只有源码运行时才行。这里只做转发。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from xk_app.app.core import cli  # noqa: E402

if __name__ == '__main__':
    sys.exit(cli.main() or 0)
