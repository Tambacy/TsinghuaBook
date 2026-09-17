# coding:utf-8
"""
整窗冒烟：逐视图抓图，并检查骨架几何。

只做「能不能画出来 / 尺寸对不对」，不碰网络。用 offscreen 平台跑，
所以中文字形是豆腐块 —— 这里看的是布局，观感请用 tests/render_real.py。
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

# 配置目录隔离：MainWindow 一构造就会读写设置与书库。
from tests._isolate import isolate  # noqa: E402

_CFG = isolate()


def main():
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    return _run(app)


def _run(app):
    from xk_app.app.core import store
    from xk_app.app.gui import theme as T
    from xk_app.app.gui.shell import MainWindow

    out = os.path.join(_ROOT, '_smoke')
    os.makedirs(out, exist_ok=True)

    win = MainWindow()
    win.resize(T.WIN_W, T.WIN_H)
    win.show()
    app.processEvents()

    # 填一些假数据，让每个视图看起来是「用起来的样子」
    win.settings.update(token='eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig')
    win.settings_view.load(win.settings)
    win.settings_view.set_verify_result(True, '有效')

    win.queue_view.entry.setPlainText(
        'https://ereserves.lib.tsinghua.edu.cn/bookDetail/'
        'c01e1db11c4041a39db463e810bac8f94af518935a1ec46ef')
    win._add_urls(['https://ereserves.lib.tsinghua.edu.cn/bookDetail/'
                   'c01e1db11c4041a39db463e810bac8f94af518935a1ec46ef'])
    jobs = win.queue.snapshot()
    for i, j in enumerate(jobs):
        j.title = ['大学俄语1（新版）', '高等数学 上册'][i % 2]
        j.pages, j.chapters, j.done_pages = 386, 12, 214
        j.state = 'downloading' if i == 0 else 'done'
    win.queue_view.set_jobs(jobs)
    win.queue_view.set_running(True)
    win.queue_view.set_counts(len(jobs), 1, 1, 0, 0.62)
    win.queue_view.set_batch_text('正在下载', '第 214/386 页')

    for i, (bid, title) in enumerate([('大学俄语1（新版）', '大学俄语1（新版）'),
                                      ('高等数学 上册', '高等数学 上册')]):
        win.library.upsert(store.make_record(
            bid, os.path.join(out, 'gone_%d.pdf' % i), out,
            meta={'title': title, 'author': '史铁强'}, pages=386, size=48200000,
            chapters=12))
    app.processEvents()

    for i, key in enumerate(['queue', 'library', 'settings', 'help']):
        win.goto(key, animate=False)
        app.processEvents()
        path = os.path.join(out, 'win_%d_%s.png' % (i + 1, key))
        win.grab().save(path)
        print('saved', path, flush=True)

    # ---- 几何检查
    ok = True

    def check(cond, label, extra=''):
        nonlocal ok
        if not cond:
            ok = False
        print('%-4s %s %s' % ('OK' if cond else 'FAIL', label, extra), flush=True)

    check(win.sidebar.width() == T.SIDEBAR_W, 'sidebar width',
          '= %d (expect %d)' % (win.sidebar.width(), T.SIDEBAR_W))
    sky_h = win.sidebar.sky.height()
    ratio = sky_h / float(win.height())
    check(ratio <= 0.20, 'sky band <= 20%% of window',
          '= %.3f (%d px)' % (ratio, sky_h))
    check(win.stack.count() == 4, 'four views mounted', '= %d' % win.stack.count())

    qv = win.queue_view
    # 量尺寸前先把队列页切回当前页：非当前页会被 QStackedWidget 隐藏，
    # 隐藏控件的布局不再重算，geometry 可能是 0，量出来是假的
    win.goto('queue', animate=False)
    app.processEvents()
    # 用 isVisibleTo 而不是 isVisible：此刻栈上停的是别的视图，
    # 队列页整体不可见，isVisible 会一律返回 False
    check(qv.batch.isVisibleTo(qv), 'batch strip visible while running')
    check(not qv.btn_start.isVisibleTo(qv) and qv.btn_stop.isVisibleTo(qv),
          'start/stop swap while running')
    check(qv.entry.isReadOnly(), 'paste box locked while running')

    # 队列行必须和列表同宽，否则进度条会短一截
    check(len(qv._rows) == len(jobs), 'one row per job', '= %d' % len(qv._rows))
    for row in qv._rows.values():
        check(row.width() == qv.jobs_box.geometry().width(),
              'job row spans the list',
              '= %d vs %d' % (row.width(), qv.jobs_box.geometry().width()))
        break

    # 书库网格：列数 × 卡宽 不能超出可用宽度
    grid = win.library_view.grid
    cards = grid.items()
    check(len(cards) == 2, 'library cards rendered', '= %d' % len(cards))
    if cards:
        cols = grid.columns()
        right_edge = max(c.geometry().right() for c in cards)
        check(right_edge <= grid.width() + 1, 'grid fits its width',
              'cols=%d right=%d w=%d' % (cols, right_edge, grid.width()))
        check(all(c.geometry().height() > 0 for c in cards), 'cards have height')
        check(cards[0].cover_rect().width() == cards[0].width(),
              'cover fills card width')

    # 动效关掉后必须仍完整可用
    T.motion.ENABLED = False
    win2 = MainWindow()
    win2.resize(T.WIN_W, T.WIN_H)
    win2.show()
    for key in ('queue', 'library', 'settings', 'help'):
        win2.goto(key, animate=False)
        app.processEvents()
    win2.queue_view.set_running(True)
    app.processEvents()
    win2.grab().save(os.path.join(out, 'win_motion_off.png'))
    # 切页时不再有揭示层（原来这里断言 win2.reveal 不可见）。
    # 现在反过来卡住「别再长回来」：谁要是把粒子揭示加回去，这条会红。
    check(not hasattr(win2, 'reveal'),
          'no page-transition reveal layer on the window any more')
    # 硬切之后每一页都得真的换过去
    for key in ('queue', 'library', 'settings', 'help'):
        win2.goto(key)
        app.processEvents()
        check(win2.stack.currentWidget() is win2.views[key],
              'goto(%s) switches immediately' % key)
    print('static motion-off render ok', flush=True)

    # 窄窗口也要能排下来
    win3 = MainWindow()
    win3.resize(980, 660)
    win3.show()
    win3.goto('library', animate=False)
    app.processEvents()
    check(win3.library_view.grid.columns() >= 1, 'narrow window keeps a column',
          '= %d' % win3.library_view.grid.columns())
    win3.resize(1600, 900)
    app.processEvents()
    wide = win3.library_view.grid.columns()
    win3.resize(980, 660)
    app.processEvents()
    narrow = win3.library_view.grid.columns()
    check(wide >= narrow, 'grid columns grow with width',
          '%d -> %d' % (narrow, wide))

    print('WINDOW SMOKE %s' % ('OK' if ok else 'FAIL'), flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main() or 0)