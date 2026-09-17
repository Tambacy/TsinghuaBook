# coding:utf-8
"""
离屏组件墙：把每一层控件都构造一遍并抓图。

作用是「任何一个自绘控件的 paintEvent 崩了，这里就会先崩」——
比起到界面里点半天才发现，这样定位快得多。
"""
import os
import sys
import traceback

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

# 配置目录隔离。这个脚本本身不碰 store，但控件层以后可能会。
from tests._isolate import isolate  # noqa: E402

_CFG = isolate()

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QVBoxLayout,  # noqa: E402
                             QWidget)

from xk_app.app.gui import theme as T  # noqa: E402
from xk_app.app.gui import widgets as W  # noqa: E402
from xk_app.app.gui.backdrop import SkyBackdrop, SkyPanel  # noqa: E402


def main():
    app = QApplication(sys.argv)
    out = os.path.join(_ROOT, '_smoke')
    os.makedirs(out, exist_ok=True)
    done = []

    # --- 侧边栏品牌区的天幕：四个变体各抓一张
    for v in T.SKY_VARIANTS:
        w = SkyBackdrop(v, animated=False)
        w.resize(T.SIDEBAR_W, T.SKY_PANEL_H)
        w.show()
        w.grab().save(os.path.join(out, 'sky_%s.png' % v))
        done.append('sky:%s' % v)
        w.hide()

    panel = SkyPanel('rose')
    panel.resize(T.SIDEBAR_W, T.SKY_PANEL_H + T.SKY_PANEL_FADE)
    panel.show()
    panel.grab().save(os.path.join(out, 'sky_panel.png'))
    done.append('sky_panel')

    # --- 组件墙
    wall = QWidget()
    wall.resize(1180, 860)
    wall.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    wall.setStyleSheet('QWidget { background: %s; }' % T.BG)
    root = QVBoxLayout(wall)
    root.setContentsMargins(34, 26, 34, 24)
    root.setSpacing(T.GAP_PAGE)

    # 粘贴卡
    paste = W.Card(padding=(20, 16, 20, 16), gap=10)
    paste.box.addWidget(W.card_title('添加书籍'))
    paste.box.addWidget(W.body('一次可以粘多条链接，一行一条。'))
    paste.box.addWidget(W.FieldRow('书籍链接', 'https://ereserves...',
                                   'bookDetail 页面链接'))
    row0 = QHBoxLayout()
    row0.setSpacing(10)
    row0.addWidget(W.PillButton('添加到队列', 'secondary'))
    row0.addWidget(W.PillButton('读剪贴板', 'ghost'))
    row0.addWidget(W.PillButton('开始下载', 'primary'))
    row0.addWidget(W.PillButton('停止', 'danger'))
    dis = W.PillButton('禁用', 'primary')
    dis.setEnabled(False)
    row0.addWidget(dis)
    row0.addStretch(1)
    paste.box.addLayout(row0)
    badges = QHBoxLayout()
    badges.setSpacing(8)
    for t, tone in (('有效', 'accent'), ('未校验', 'warn'),
                    ('失败', 'danger'), ('必填', 'info')):
        badges.addWidget(W.Badge(t, tone))
    badges.addStretch(1)
    paste.box.addLayout(badges)
    root.addWidget(paste)

    # 整批进度
    batch = W.BatchStrip()
    batch.set_text('正在下载（3 本排队中）', '第 214/386 页 · 大学俄语1（新版）')
    batch.set_progress(0.62, 1, 0, 3)
    root.addWidget(batch)

    # 队列行
    class _Job:
        order = 0
        url = 'https://ereserves.lib.tsinghua.edu.cn/bookDetail/c01e1db1'
        label = '大学俄语1（新版）'
        state = 'downloading'
        error = ''
        pages, chapters, done_pages, failed_pages = 386, 12, 214, 0
        active = True
        fraction = 0.55
        pdf_path = ''

    root.addWidget(W.JobRow(_Job()))

    class _Job2(_Job):
        order = 1
        state = 'failed'
        error = 'Token 不正确或已过期，请重新获取。'
        active = False
        fraction = 0.0

    class _Job3(_Job):
        order = 2
        state = 'done'
        active = False
        fraction = 1.0

    root.addWidget(W.JobRow(_Job2()))
    root.addWidget(W.JobRow(_Job3()))

    # 书库网格
    grid_holder = QWidget()
    gh = QHBoxLayout(grid_holder)
    gh.setContentsMargins(0, 0, 0, 0)
    gh.setSpacing(T.GRID_GAP)
    from xk_app.app.gui.views.base import BookGrid
    grid = BookGrid()
    grid.resize(1100, 420)
    grid.set_items([W.BookCard({'book_id': 'A', 'title': '大学俄语1（新版）',
                                'author': '史铁强', 'pages': 386, 'size': 48200000,
                                'pdf_path': '', 'cover': ''}),
                    W.BookCard({'book_id': 'B', 'title': '高等数学 上册',
                                'author': '同济大学数学系', 'pages': 428,
                                'size': 61400000, 'pdf_path': '', 'cover': ''}),
                    W.BookCard({'book_id': 'C', 'title': '数据结构（C 语言版）',
                                'author': '严蔚敏', 'pages': 335, 'size': 44800000,
                                'pdf_path': '', 'cover': ''})])
    gh.addWidget(grid)
    root.addWidget(grid_holder)

    # 复选框 / 空状态
    checks = QHBoxLayout()
    checks.setSpacing(20)
    c1 = W.CheckItem('保留临时图片')
    c1.setChecked(True)
    c2 = W.CheckItem('自动统一页面尺寸')
    checks.addWidget(c1)
    checks.addWidget(c2)
    checks.addStretch(1)
    root.addLayout(checks)
    root.addWidget(W.EmptyState('队列是空的', '把链接粘到上面就可以排队下载了。'))
    root.addStretch(1)

    wall.show()
    app.processEvents()
    wall.grab().save(os.path.join(out, 'widgets.png'))
    done.append('widgets')

    # --- 动效关掉后自绘控件仍必须能画出来
    T.motion.ENABLED = False
    batch2 = W.BatchStrip()
    batch2.set_text('已停止', '可点「重试失败」继续')
    batch2.set_progress(0.3, 0, 1, 1)
    batch2.resize(600, 58)
    batch2.show()
    app.processEvents()
    batch2.grab().save(os.path.join(out, 'batch_static.png'))
    done.append('batch_static')
    T.motion.ENABLED = True

    print('SMOKE OK:', ', '.join(done))
    print('screenshots ->', out)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main() or 0)
    except Exception:
        traceback.print_exc()
        sys.exit(1)