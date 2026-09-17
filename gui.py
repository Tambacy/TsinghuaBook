# coding:utf-8
"""
图形界面入口（开发态用这个）。

    python gui.py

打包后就是 ``TsinghuaBookCrawler.exe`` 直接双击的效果。
真正的分发逻辑在 ``crawler/entry.py``；打包入口是仓库根的 ``launcher.py``。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler.entry import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main() or 0)
