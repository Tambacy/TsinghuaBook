# coding:utf-8
"""
下载队列视图：粘链接、排队、看进度。

这是程序的主界面。相比原来的五步向导，这里把「要下什么」和「下到哪了」
放在同一屏：批量粘一批链接，点开始，然后就在下面看着逐本完成。
不用为了下第二本书再走一遍流程。
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget)

from .. import theme as T
from .. import widgets as W
from .base import Workspace


class QueueView(Workspace):
    add_requested = pyqtSignal(list)      # 新增一批链接
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    retry_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    open_folder = pyqtSignal(object)
    remove_job = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__('下载队列', '把书籍链接粘进来，一次可以放多条。', parent)

        # ---- 标题行按钮
        self.btn_retry = W.PillButton('重试失败', 'secondary', small=True)
        self.btn_clear = W.PillButton('清除已完成', 'ghost', small=True)
        self.btn_stop = W.PillButton('停止', 'danger', small=True)
        self.btn_start = W.PillButton('开始下载', 'primary', small=True)
        for b in (self.btn_retry, self.btn_clear, self.btn_stop, self.btn_start):
            self.add_action(b)
        self.btn_stop.setVisible(False)

        # ---- 粘贴区
        card = W.Card(padding=(20, 16, 20, 16), gap=10)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        head.addWidget(W.card_title('添加书籍'))
        head.addStretch(1)
        self.paste_hint = W.meta('每行一条，重复的会自动跳过', T.TEXT_FAINT)
        head.addWidget(self.paste_hint)
        card.box.addLayout(head)

        self.entry = QPlainTextEdit()
        self.entry.setPlaceholderText(
            'https://ereserves.lib.tsinghua.edu.cn/bookDetail/xxxxxxxx\n'
            '可以一次粘好几条，一行一条；带书名一起粘也没关系')
        self.entry.setFixedHeight(86)
        self.entry.setFont(T.ui_font(T.FS_BODY))
        self.entry.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {T.BG_SOFT};
                border: none;
                border-radius: {T.R_IN}px;
                padding: 10px 12px;
                color: {T.TEXT};
            }}
            QPlainTextEdit:focus {{
                background: {T.CARD};
                border: 1px solid {T.PRIMARY_SOFT};
            }}
        """)
        card.box.addWidget(self.entry)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.btn_add = W.PillButton('添加到队列', 'secondary')
        row.addWidget(self.btn_add)
        self.btn_paste = W.PillButton('读剪贴板', 'ghost')
        row.addWidget(self.btn_paste)
        row.addStretch(1)
        card.box.addLayout(row)
        self.box.addWidget(card)

        # ---- 整批进度（只在有任务时出现，不占常驻空间）
        self.batch = W.BatchStrip()
        self.batch.setVisible(False)
        self.box.addWidget(self.batch)

        # ---- 队列列表
        list_head = QHBoxLayout()
        list_head.setContentsMargins(0, 0, 0, 0)
        list_head.setSpacing(10)
        list_head.addWidget(W.card_title('队列'))
        list_head.addStretch(1)
        self.list_meta = W.meta('', T.TEXT_FAINT)
        list_head.addWidget(self.list_meta)
        self.box.addLayout(list_head)

        self.jobs_box = QVBoxLayout()
        self.jobs_box.setContentsMargins(0, 0, 0, 0)
        self.jobs_box.setSpacing(6)
        self.box.addLayout(self.jobs_box)

        self.empty = W.EmptyState(
            '队列是空的',
            '把教参书籍详情页的链接粘到上面的框里，就可以排队下载了。\n'
            '一次粘多条会依次下载，中途可以随时停。')
        self.box.addWidget(self.empty)
        self.add_stretch()

        # ---- 接线
        self.btn_add.clicked.connect(self._emit_add)
        self.btn_paste.clicked.connect(self._paste_from_clipboard)
        self.btn_start.clicked.connect(self.start_requested.emit)
        self.btn_stop.clicked.connect(self.stop_requested.emit)
        self.btn_retry.clicked.connect(self.retry_requested.emit)
        self.btn_clear.clicked.connect(self.clear_requested.emit)
        self._rows = {}

    # -------------------------------------------------------------- 交互
    def _emit_add(self):
        from ...core.queue import extract_urls
        urls = extract_urls(self.entry.toPlainText())
        if urls:
            self.add_requested.emit(urls)
            self.entry.clear()

    def _paste_from_clipboard(self):
        from PyQt6.QtWidgets import QApplication
        text = QApplication.clipboard().text() or ''
        if text.strip():
            self.entry.setPlainText(text.strip())
            self._emit_add()

    # -------------------------------------------------------------- 刷新
    def set_running(self, running, cancelled=False):
        self.btn_start.setVisible(not running)
        self.btn_stop.setVisible(running)
        self.btn_start.setEnabled(not running)
        self.batch.setVisible(running or cancelled)
        self.entry.setReadOnly(running)
        self.btn_add.setEnabled(not running)

    def set_jobs(self, jobs):
        """整表重建 —— 队列规模小（通常十几条），重建比差分更新更不容易出错。"""
        seen = set()
        for job in jobs:
            seen.add(id(job))
            row = self._rows.get(id(job))
            if row is None:
                row = W.JobRow(job)
                row.open_folder.connect(self.open_folder.emit)
                row.remove.connect(self.remove_job.emit)
                self._rows[id(job)] = row
                self.jobs_box.addWidget(row)
            row.set_job(job)
        for key in list(self._rows):
            if key not in seen:
                row = self._rows.pop(key)
                self.jobs_box.removeWidget(row)
                row.setParent(None)
                row.deleteLater()
        self.empty.setVisible(not jobs)

    def set_counts(self, total, done, failed, left, progress):
        self.list_meta.setText(
            '%d 本 · 完成 %d · 失败 %d' % (total, done, failed)
            if total else '')
        self.batch.set_progress(progress, done, failed, left)
        self.btn_retry.setEnabled(failed > 0)
        self.btn_clear.setEnabled(done + failed > 0)

    def set_batch_text(self, title, sub):
        self.batch.set_text(title, sub)