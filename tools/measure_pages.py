# coding:utf-8
"""
量一下每个视图内容的真实高度，确认是否需要滚动。

滚一点不是问题（书库、说明本来就会长），但如果设置页和队列页在
1280x820 下也溢出，说明留白或分块该收一收了。
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

from tests._isolate import isolate  # noqa: E402

_CFG = isolate()

from PyQt6.QtWidgets import QApplication  # noqa: E402

from crawler.gui import theme as T  # noqa: E402


def main():
    app = QApplication(sys.argv)
    from crawler.core import store
    from crawler.gui.shell import MainWindow

    win = MainWindow()
    win.resize(T.WIN_W, T.WIN_H)
    win.show()
    app.processEvents()

    # 给队列和书库放点数据，量的才是「用起来的样子」
    win.settings_view.token.edit.setText(
        'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdefghij')
    urls = ['https://x/bookDetail/VIEW1', 'https://x/bookDetail/AAA111']
    win.queue_view.entry.setPlainText('\n'.join(urls))
    win._add_urls(urls)
    jobs = win.queue.snapshot()
    for j in jobs:
        j.title, j.pages, j.chapters, j.done_pages = '大学俄语1（新版）', 386, 12, 214
    win.queue_view.set_jobs(jobs)
    win.queue_view.set_running(True)
    win.queue_view.set_counts(len(jobs), 1, 0, 1, 0.62)
    win.queue_view.set_batch_text('正在下载', '第 214/386 页')
    win.library_view.set_records([
        store.make_record('B%d' % i, 'x.pdf', '.', meta={'title': '书 %d' % i},
                          pages=300, size=1000, chapters=5)
        for i in range(8)])
    app.processEvents()

    print('window %dx%d   sidebar=%d   sky=%d (%.1f%% of height)'
          % (win.width(), win.height(), win.sidebar.width(),
             win.sidebar.sky.height(),
             100.0 * win.sidebar.sky.height() / win.height()), flush=True)

    ok = True
    for key in ('queue', 'library', 'settings', 'help'):
        win.goto(key, animate=False)
        app.processEvents()
        view = win.views[key]
        vp = view.scroll.viewport()
        need = view.body.sizeHint().height()
        overflow = need - vp.height()
        flag = 'OVERFLOW' if overflow > 0 else 'fits'
        print('  %-9s viewport=%4d  content=%4d  %s %+d'
              % (key, vp.height(), need, flag, -overflow), flush=True)
        # 队列页和设置页应当一屏放得下；书库和说明长一点是正常的
        if key in ('queue', 'settings') and overflow > 0:
            ok = False

    print('MEASURE %s' % ('OK' if ok else 'FAIL'), flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main() or 0)
