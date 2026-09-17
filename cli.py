# coding:utf-8
"""
命令行入口。

    python cli.py <书籍链接> --token eyJhb...
    python cli.py -h

真正的实现在 ``crawler/core/cli.py`` —— 收进包里是为了让打包后的 exe
也能直接用命令行（``TsinghuaBookCrawler.exe <url> --token xxx``），
而不是只有源码运行时才行。这里只做转发。

图形界面请用 ``python gui.py``。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler.core import cli  # noqa: E402

if __name__ == '__main__':
    sys.exit(cli.main() or 0)
