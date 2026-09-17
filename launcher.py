# coding:utf-8
"""
PyInstaller 打包入口（TsinghuaBookCrawler.spec 指向这个文件）。

它必须留在包外面：PyInstaller 会把入口脚本当作顶层 ``__main__`` 执行，
脚本里的相对导入会报 "attempted relative import with no known parent package"。
所以这里只做一件事 —— 把仓库根挂上 sys.path，然后交给 ``crawler.entry``。

exe 的用法（都由 crawler/entry.py 分发）：

    TsinghuaBookCrawler.exe                       -> 图形界面
    TsinghuaBookCrawler.exe --selftest            -> 打包产物自检
    TsinghuaBookCrawler.exe --screenshot <目录>    -> 渲染界面截图后退出（验收用）
    TsinghuaBookCrawler.exe <url> --token xxx     -> 命令行版本
"""
import os
import sys

# 冻结后 sys.path[0] 是 _MEIPASS，开发态是仓库根；两种情况下都能 import crawler
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from crawler.entry import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main() or 0)
