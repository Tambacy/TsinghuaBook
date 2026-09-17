# coding:utf-8
"""
在真实显示上把四个视图渲染成 PNG，用来肉眼验收。

为什么要真实显示：offscreen 后端没有安装中文字体，渲染出来全是豆腐块，
看不出排版问题。这个脚本要求有桌面会话。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

from tests._isolate import isolate  # noqa: E402

_CFG = isolate()

OUT = os.path.join(_ROOT, '_smoke')


def main():
    os.makedirs(OUT, exist_ok=True)
    # 配置目录已由 tests/_isolate.py 顶到临时目录，这里不用再管

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from xk_app.app.core import store
    from xk_app.app.gui import theme as T
    from xk_app.app.gui.shell import MainWindow

    win = MainWindow()
    win.resize(T.WIN_W, T.WIN_H)
    win.show()

    # 造几条像样的数据，让截图能看出真实观感
    win.settings.update(token='eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.demo.token')
    win.settings_view.load(win.settings)
    win.settings_view.set_verify_result(True, '有效')

    urls = ['https://ereserves.lib.tsinghua.edu.cn/bookDetail/c01e1db11c4041a39db463e810bac8f94af518935a1ec46ef',
            'https://ereserves.lib.tsinghua.edu.cn/bookDetail/aaa111bbb222ccc333ddd444eee555fff666']
    win.queue_view.entry.setPlainText('\n'.join(urls))
    win._add_urls(urls)

    jobs = win.queue.snapshot()
    if len(jobs) > 0:
        j = jobs[0]
        j.title = '大学俄语1（新版）'
        j.book_id = '大学俄语1（新版）'
        j.pages, j.chapters, j.done_pages = 386, 12, 214
        j.state = 'downloading'
    if len(jobs) > 1:
        j2 = jobs[1]
        j2.title = '高等数学 上册'
        j2.book_id = '高等数学 上册'
        j2.pages, j2.chapters, j2.done_pages = 428, 9, 428
        j2.state = 'done'
        j2.pdf_path = os.path.join(OUT, 'fake.pdf')

    # 假的已下载记录（书库）
    import time
    recs = []
    for i, (bid, title, author, pages, size) in enumerate([
            ('大学俄语1（新版）', '大学俄语1（新版）', '史铁强', 386, 48200000),
            ('高等数学 上册', '高等数学 上册', '同济大学数学系', 428, 61400000),
            ('大学物理学', '大学物理学', '张三慧', 512, 73900000),
            ('线性代数', '线性代数', '居余马', 264, 31200000),
            ('数据结构', '数据结构（C 语言版）', '严蔚敏', 335, 44800000)]):
        rec = store.make_record(
            bid, os.path.join(OUT, 'missing_%d.pdf' % i), OUT,
            meta={'title': title, 'author': author}, pages=pages, size=size,
            chapters=12)
        rec['added_at'] = time.time() - i * 3600
        recs.append(rec)
    # 注意：要写进真正的 library（goto('library') 会从它重新读），
    # 直接调 set_records 会被下一次 goto 覆盖掉
    for r in recs:
        win.library.upsert(r)

    win.queue_view.set_jobs(win.queue.snapshot())
    win.queue_view.set_running(True)
    win.queue_view.set_counts(2, 1, 0, 1, 0.77)
    win.queue_view.set_batch_text('正在下载（1 本排队中）',
                                  '第 214/386 页 · 大学俄语1（新版）')

    order = ['queue', 'library', 'settings', 'help']

    def shoot():
        for i, key in enumerate(order):
            win.goto(key, animate=False)
            app.processEvents()
            win.grab().save(os.path.join(OUT, 'view_%d_%s.png' % (i + 1, key)))
        # 关掉动效再截一张，确认动效禁用时同样可用
        T.motion.ENABLED = False
        win.goto('queue', animate=False)
        app.processEvents()
        win.grab().save(os.path.join(OUT, 'view_motion_off.png'))
        print('真实渲染 OK -> %s' % OUT)
        app.quit()

    QTimer.singleShot(900, shoot)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main() or 0)
