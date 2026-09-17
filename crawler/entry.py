# coding:utf-8
"""
统一的模式分发：图形界面 / 命令行 / 自检 / 截图验收。

仓库根的三个入口都转发到这里，保证「打包后」和「源码直接跑」走的是同一条路：

    gui.py        开发态启动图形界面
    cli.py        开发态走命令行
    launcher.py   PyInstaller 的打包入口（exe 的四种用法都在这里分发）

为什么不把 gui.py / cli.py 直接当 PyInstaller 入口：PyInstaller 会把入口脚本
当作顶层 ``__main__`` 执行，脚本里的相对导入（``from .selftest import ...``）
会报 "attempted relative import with no known parent package"。所以打包入口
必须是一个包外的薄启动器，真正的东西都在 crawler 包内。

PyQt 会在 Qt 的虚函数（paintEvent / sizeHint 等）里捕获 Python 异常并直接
中止进程，看不到任何堆栈。所以这里装了 excepthook，把异常写进日志文件，
出问题时至少有个线索。
"""
import os
import sys
import traceback
from datetime import datetime


def _log_path():
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    d = os.path.join(base, 'TsinghuaBookCrawler')
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return os.path.join(os.getcwd(), 'error.log')
    return os.path.join(d, 'error.log')


def install_excepthook():
    def hook(exc_type, exc, tb):
        text = ''.join(traceback.format_exception(exc_type, exc, tb))
        sys.__stderr__.write(text) if sys.__stderr__ else None
        try:
            with open(_log_path(), 'a', encoding='utf-8') as f:
                f.write('\n=== %s ===\n%s' % (datetime.now().isoformat(), text))
        except OSError:
            pass
    sys.excepthook = hook


def _ensure_std_streams():
    """
    windowed 构建（console=False）下 sys.stdout / sys.stderr 是 None，
    任何 print() 都会炸。给它们塞一个空流，让命令行模式在 exe 上也能跑。
    """
    for name in ('stdout', 'stderr'):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))


def run_gui():
    from PyQt6.QtWidgets import QApplication
    from .gui.shell import APP_NAME, main
    QApplication.setApplicationName(APP_NAME)
    return main()


def run_cli(argv):
    """命令行模式。实现在 crawler/core/cli.py，打包后也能用。"""
    from .core import cli
    return cli.run(list(argv))


def run_selftest():
    from .selftest import run_selftest as _run
    return _run()


def main(argv=None):
    """
    按参数分发：

        (无参数) / --gui / --ui   -> 图形界面
        --selftest                -> 打包产物自检
        --screenshot <目录>        -> 渲染界面截图后退出（验收用）
        其它                      -> 命令行模式
    """
    install_excepthook()
    _ensure_std_streams()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == '--selftest':
        return run_selftest()
    if args and args[0] == '--screenshot':
        from .screenshot import render
        return render(args[1] if len(args) > 1 else os.getcwd())
    if args and args[0] not in ('--gui', '--ui'):
        return run_cli(args)
    return run_gui()
