# coding:utf-8
"""
图形界面入口。

命令行版本仍然可用：`python main.py <url> --token xxx`。
打包后的 exe 默认走图形界面，加参数时走命令行。

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


def run_gui():
    from PyQt6.QtWidgets import QApplication
    from .app.gui.shell import APP_NAME, main
    QApplication.setApplicationName(APP_NAME)
    return main()


def run_cli(argv):
    """命令行模式。实现在 xk_app/app/core/cli.py，打包后也能用。"""
    from .app.core import cli
    return cli.run(list(argv))


def _ensure_std_streams():
    """
    windowed 构建（console=False）下 sys.stdout / sys.stderr 是 None，
    任何 print() 都会炸。给它们塞一个空流，让命令行模式在 exe 上也能跑。
    """
    for name in ('stdout', 'stderr'):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))


def main():
    install_excepthook()
    _ensure_std_streams()
    args = sys.argv[1:]
    if args and args[0] == '--selftest':
        from .selftest import run_selftest
        return run_selftest()
    if args and args[0] not in ('--gui', '--ui'):
        return run_cli(args)
    return run_gui()


if __name__ == '__main__':
    sys.exit(main() or 0)