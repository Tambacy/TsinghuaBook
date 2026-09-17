# coding:utf-8
"""
书库视图：已下载的书，按封面网格排。

这是「下载完之后」的界面，也是原来向导版本里最缺的一块 ——
下过的书散在磁盘目录里，想再打开一本得自己去翻文件夹。
这里给出封面、书名、作者、页数和体积，并且能直接打开 PDF 或定位到文件夹。
"""
import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit

from .. import theme as T
from .. import widgets as W
from .base import BookGrid, Workspace


class LibraryView(Workspace):
    open_pdf = pyqtSignal(object)
    open_folder = pyqtSignal(object)
    remove = pyqtSignal(object)
    refresh = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__('书库', '已经下载好的电子书。', parent)

        self.btn_folder = W.PillButton('打开下载目录', 'secondary', small=True)
        self.btn_refresh = W.PillButton('重新扫描', 'ghost', small=True)
        self.add_action(self.btn_folder)
        self.add_action(self.btn_refresh)

        # ---- 搜索
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText('按书名或作者筛选…')
        self.search.setFixedHeight(34)
        self.search.setFont(T.ui_font(T.FS_BODY))
        self.search.setStyleSheet(f"""
            QLineEdit {{
                background: {T.CARD};
                border: none;
                border-radius: {T.R_IN}px;
                padding: 0 12px;
                color: {T.TEXT};
            }}
            QLineEdit:focus {{ border: 1px solid {T.PRIMARY_SOFT}; }}
        """)
        bar.addWidget(self.search, 1)
        self.box.addLayout(bar)

        self.grid = BookGrid()
        self.box.addWidget(self.grid)

        self.empty = W.EmptyState(
            '书库还是空的',
            '下载完成的书会出现在这里，可以直接打开 PDF 或定位到文件夹。')
        self.box.addWidget(self.empty)
        self.add_stretch()

        self.btn_folder.clicked.connect(lambda: self.open_folder.emit(None))
        self.btn_refresh.clicked.connect(self.refresh.emit)
        self.search.textChanged.connect(lambda _t: self._apply_filter())
        self._records = []

    # -------------------------------------------------------------- 数据
    def set_records(self, records):
        self._records = list(records)
        self._apply_filter()

    def _apply_filter(self):
        needle = (self.search.text() or '').strip().lower()
        if needle:
            shown = [r for r in self._records
                     if needle in (r.get('title', '') or '').lower()
                     or needle in (r.get('author', '') or '').lower()
                     or needle in (r.get('book_id', '') or '').lower()]
        else:
            shown = list(self._records)

        cards = []
        for rec in shown:
            card = W.BookCard(rec)
            card.open_pdf.connect(self.open_pdf.emit)
            card.open_folder.connect(self.open_folder.emit)
            card.remove.connect(self.remove.emit)
            cards.append(card)
        self.grid.set_items(cards)

        total = len(self._records)
        missing = sum(1 for r in self._records
                      if not (r.get('pdf_path') and os.path.exists(r['pdf_path'])))
        parts = ['%d 本' % total]
        if needle:
            parts.append('筛选出 %d' % len(shown))
        if missing:
            parts.append('%d 本文件已丢失' % missing)
        size = sum(int(r.get('size') or 0) for r in self._records)
        if size:
            parts.append(_fmt_size(size))
        self.set_subtitle(' · '.join(parts) if parts else '已经下载好的电子书。')
        self.empty.setVisible(not cards)
        # 搜不到和没下过是两回事，提示要分开
        if not cards and needle:
            self.empty.set_title('没有匹配的书')
            self.empty.set_hint('换个关键词试试，或者清空搜索框。')
        else:
            self.empty.set_title('书库还是空的')
            self.empty.set_hint('下载完成的书会出现在这里，'
                                '可以直接打开 PDF 或定位到文件夹。')


def _fmt_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ''
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            if unit in ('B', 'KB'):
                return '%.0f %s' % (n, unit)
            return '%.1f %s' % (n, unit)
        n /= 1024.0
    return ''
