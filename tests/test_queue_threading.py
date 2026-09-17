"""
两条回归测试，锁住「下载完就崩」这一类问题。

1) 下载线程绝不能碰控件。
   QueueManager 跑在普通 Python 线程上，而 Qt 控件只能在 GUI 线程碰。
   修复前 34 次 _queue_changed 里有 31 次跑在 download-queue 线程上。

2) 侧边栏状态块里的文字必须是 str。
   曾经把 bool 当成 title 传进去，绘制时 elidedText(True, ...) 抛 TypeError；
   PyQt 在绘制回调里遇到未捕获异常会直接 qFatal，进程以 0xC0000409 退出，
   连 Python 回溯都没有 —— 表现就是「下载完程序就崩，但书已经下好了」。
"""

import os
import sys
import threading
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _isolate import isolate                                          # noqa: E402

isolate()

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QEventLoop, QTimer                           # noqa: E402
from PyQt6.QtWidgets import QApplication                              # noqa: E402

from test_engine import build_fakes, patch                            # noqa: E402

FAILED = []


def check(ok, msg):
    print('  %s %s' % ('OK  ' if ok else 'FAIL', msg), flush=True)
    if not ok:
        FAILED.append(msg)


def pump(app, ms):
    """跑 ms 毫秒事件循环。guard 定时器显式停掉 —— 留一个待触发的
    singleShot 指向已经销毁的 QEventLoop，本身就会造成同样的 0xC0000409。"""
    loop = QEventLoop()
    guard = QTimer()
    guard.setSingleShot(True)
    guard.setInterval(ms)
    guard.timeout.connect(loop.quit)
    guard.start()
    loop.exec()
    guard.stop()
    app.processEvents()


def wait_for(app, pred, timeout_ms, what):
    end = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < end:
        if pred():
            return True
        pump(app, 30)
    raise AssertionError('timeout: %s' % what)


def main():
    app = QApplication(sys.argv)

    state = {}
    fg, fp, sg, sp = build_fakes(state)
    patch(fg, fp, sg, sp)

    from crawler.gui.shell import MainWindow
    from crawler.gui import theme as T

    tmp = tempfile.mkdtemp(prefix='xkc_thread_')
    win = MainWindow()
    win.resize(T.WIN_W, T.WIN_H)
    win.show()

    main_name = threading.current_thread().name
    seen = {'queue': [], 'library': []}

    real_qc = win._queue_changed
    real_lib = win._on_library_dirty

    def spy_qc():
        seen['queue'].append(threading.current_thread().name)
        return real_qc()

    def spy_lib():
        seen['library'].append(threading.current_thread().name)
        return real_lib()

    # 换掉的是 GUI 线程侧的落点：无论上游走信号还是直连，最终都到这里
    win._queue_changed = spy_qc
    win._queue_coalesce.timeout.disconnect()
    win._queue_coalesce.timeout.connect(spy_qc)
    win._on_library_dirty = spy_lib
    win._library_dirty.disconnect()
    win._library_dirty.connect(spy_lib)

    win.settings_view.token.edit.setText('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdefghij')
    win.settings_view.set_dir(os.path.join(tmp, 'downloads'))
    win._save_settings()
    win.goto('queue', animate=False)

    qv = win.queue_view
    qv.entry.setPlainText('https://x/bookDetail/VIEW1\n'
                          'https://x/bookDetail/BBB222\n'
                          'https://x/bookDetail/VIEW1')
    qv._emit_add()

    print('[A] 下载线程不碰控件', flush=True)
    check(len(win.queue.snapshot()) == 2, '重复链接去重后队列 = 2')

    win._start_queue()
    check(win.queue.running is True, '队列进入运行状态')

    wait_for(app, lambda: not win.queue.running, 60000, 'queue finished')
    pump(app, 400)

    bad_q = [n for n in seen['queue'] if n != main_name]
    bad_l = [n for n in seen['library'] if n != main_name]
    check(len(seen['queue']) > 0, '队列回调确实被调用过（%d 次）' % len(seen['queue']))
    check(not bad_q,
          '队列回调全部在 GUI 线程（越界 %d 次，来自 %s）'
          % (len(bad_q), sorted(set(bad_q))))
    check(not bad_l,
          '书库回调全部在 GUI 线程（越界 %d 次，来自 %s）'
          % (len(bad_l), sorted(set(bad_l))))

    print('[B] 侧边栏状态块的字必须是 str', flush=True)
    chip = win.sidebar.status_chip
    check(isinstance(chip._title, str),
          'status_chip._title 是 str（当前 %r，类型 %s）'
          % (chip._title, type(chip._title).__name__))
    check(isinstance(chip._sub, str),
          'status_chip._sub 是 str（当前 %r，类型 %s）'
          % (chip._sub, type(chip._sub).__name__))

    print('[C] 下载结果正确', flush=True)
    done, failed, left = win.queue.counts()
    check(done == 2, '两本都完成（当前 done=%d）' % done)
    check(failed == 0, '没有失败任务')
    check(abs(win.queue.progress() - 1.0) < 1e-6,
          '整批进度 = 100%%（当前 %.3f）' % win.queue.progress())

    print('[D] 触发一次重绘（原来就是在这里崩的）', flush=True)
    chip.update()
    win.repaint()
    pump(app, 200)
    check(True, '重绘后进程仍然活着')

    win.close()

    print('', flush=True)
    if FAILED:
        print('QUEUE THREADING FAIL (%d)' % len(FAILED), flush=True)
        for m in FAILED:
            print('   - %s' % m, flush=True)
        return 1
    print('QUEUE THREADING PASS', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())