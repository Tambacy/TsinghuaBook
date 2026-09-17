# coding:utf-8
"""
工作区外壳：统一的标题行 + 可滚动内容 + 响应式网格。

四个视图（队列/书库/设置/说明）都长在这个骨架上，保证它们的标题、
留白、滚动行为完全一致 —— 一致性比每页各自调更省事也更好看。
"""
from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtWidgets import (QGridLayout, QHBoxLayout, QScrollArea,
                             QSizePolicy, QVBoxLayout, QWidget)

from .. import theme as T
from .. import widgets as W


def scroll_qss():
    """滚动条默认隐形，鼠标移到滚动条上才显形（常驻滚动条会破坏留白）。"""
    return f"""
        QScrollArea {{ background: transparent; border: none; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
        QScrollBar:vertical {{
            background: transparent; width: 10px; margin: 2px 2px 2px 0;
        }}
        QScrollBar::handle:vertical {{
            background: transparent; border-radius: 4px; min-height: 30px;
        }}
        QScrollBar:vertical:hover QScrollBar::handle:vertical {{
            background: rgba(111,92,173,0.30);
        }}
        QScrollBar::handle:vertical:hover {{ background: rgba(111,92,173,0.58); }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0; background: transparent;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent;
        }}
        QScrollBar:horizontal {{ height: 0px; background: transparent; }}
        QScrollBar::handle:horizontal {{ background: transparent; }}
    """


class Workspace(QWidget):
    """
    一个视图的骨架。

    子类在 __init__ 里调 add_widget / box 往内容区加东西；
    header 右边的操作按钮用 add_action()。
    """

    def __init__(self, title, subtitle='', parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet('Workspace { background: %s; }' % T.BG)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- 标题行
        self.head = QWidget(self)
        self.head.setFixedHeight(T.WORKSPACE_HEAD_H)
        hbox = QHBoxLayout(self.head)
        hbox.setContentsMargins(T.PAD_PAGE[0], 12, T.PAD_PAGE[2], 6)
        hbox.setSpacing(12)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        self.title = W.Label(title, T.FS_FORM_TITLE - 4, 700, T.TEXT)
        text_col.addWidget(self.title)
        self.subtitle = W.Label(subtitle, T.FS_META, 400, T.TEXT_FAINT)
        text_col.addWidget(self.subtitle)
        hbox.addLayout(text_col)
        hbox.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(9)
        hbox.addLayout(self.actions)
        outer.addWidget(self.head)

        # ---- 可滚动内容
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(scroll_qss())
        self.body = QWidget()
        self.body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.body.setStyleSheet('QWidget { background: transparent; }')
        self.box = QVBoxLayout(self.body)
        self.box.setContentsMargins(T.PAD_PAGE[0], T.PAD_PAGE[1],
                                    T.PAD_PAGE[2], T.PAD_PAGE[3])
        self.box.setSpacing(T.GAP_PAGE)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)

    def add_widget(self, w):
        self.box.addWidget(w)
        return w

    def add_layout(self, lay):
        self.box.addLayout(lay)
        return lay

    def add_stretch(self):
        self.box.addStretch(1)

    def add_action(self, widget):
        self.actions.addWidget(widget)
        return widget

    def set_subtitle(self, text):
        self.subtitle.setText(text)

    def set_title(self, text):
        self.title.setText(text)


class BookGrid(QWidget):
    """
    响应式网格：按可用宽度决定列数，卡片等高。

    为什么手写几何而不用 QGridLayout：书库条目数量不定，窗口拖动时
    需要重新分列，QGridLayout 每次都要清空重建，闪得厉害；
    直接算位置反而更稳也更快。
    """

    def __init__(self, parent=None, min_w=None, gap=None):
        super().__init__(parent)
        self._items = []
        self._min_w = min_w or T.GRID_MIN_W
        self._gap = gap if gap is not None else T.GRID_GAP
        self._card_h = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def items(self):
        return list(self._items)

    def clear(self):
        for w in self._items:
            w.setParent(None)
            w.deleteLater()
        self._items = []
        self.updateGeometry()

    def set_items(self, widgets):
        self.clear()
        for w in widgets:
            w.setParent(self)
            w.show()
            self._items.append(w)
        self.relayout()

    def columns(self):
        gap = self._gap
        avail = max(1, self.width())
        cols = (avail + gap) // (self._min_w + gap)
        return max(1, int(cols))

    def relayout(self):
        cols = self.columns()
        gap = self._gap
        total_gap = gap * (cols - 1)
        card_w = max(120, (self.width() - total_gap) // cols)
        # 高度跟着宽度走：封面是 3:4，卡片越宽越高，所以这里不能写死
        card_h = int(card_w * 4 / 3) + getattr(
            self._items[0], 'TEXT_BLOCK_H', 92) if self._items else 0
        self._card_h = card_h
        for i, w in enumerate(self._items):
            r, c = divmod(i, cols)
            w.set_card_size(card_w, card_h)
            w.setGeometry(c * (card_w + gap), r * (card_h + gap), card_w, card_h)
        rows = (len(self._items) + cols - 1) // cols if self._items else 0
        self.setMinimumHeight(max(0, rows * (card_h + gap) - gap))

    def resizeEvent(self, _ev):
        self.relayout()

    def sizeHint(self):
        return QSize(self.width(), self.minimumHeight())
