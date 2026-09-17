# coding:utf-8
"""
设置视图：token、保存位置、下载参数。

为什么这些从「流程的某一步」搬到独立页面：
token 是一个会话凭证，抓一次能用很久；保存目录和清晰度更是设一次就不动了。
它们在原向导里被当成每本书都要确认的输入，等于每次下载都逼用户重看一遍。
"""
import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QGridLayout, QHBoxLayout, QLineEdit,
                             QVBoxLayout, QWidget)

from .. import theme as T
from .. import widgets as W
from .base import Workspace


class TokenField(QWidget):
    """token 输入：默认遮住，可以点眼睛看明文（token 很长，看不清容易粘错）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QToolButton
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText('粘贴 /index?token= 等号后面那一长串')
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setFont(T.ui_font(T.FS_BODY, 400, mono=True))
        self.edit.setFixedHeight(38)
        self.edit.setStyleSheet(f"""
            QLineEdit {{
                background: {T.CARD};
                border: 1px solid {T.BORDER};
                border-radius: {T.R_IN}px;
                padding: 0 12px;
                color: {T.TEXT};
            }}
            QLineEdit:focus {{ border: 1px solid {T.PRIMARY_SOFT}; }}
        """)
        box.addWidget(self.edit, 1)
        self.btn_eye = QToolButton()
        self.btn_eye.setText('显示')
        self.btn_eye.setCheckable(True)
        self.btn_eye.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_eye.setFixedHeight(38)
        self.btn_eye.setStyleSheet(f"""
            QToolButton {{
                background: {T.BG_SOFT}; border: none;
                border-radius: {T.R_IN}px; padding: 0 14px;
                color: {T.TEXT_DIM};
            }}
            QToolButton:checked {{ background: {T.PRIMARY_LIGHT}; color: {T.PRIMARY_DARK}; }}
        """)
        self.btn_eye.toggled.connect(self._toggle)
        box.addWidget(self.btn_eye)

    def _toggle(self, on):
        self.edit.setEchoMode(QLineEdit.EchoMode.Normal if on
                              else QLineEdit.EchoMode.Password)
        self.btn_eye.setText('隐藏' if on else '显示')


class SettingsView(Workspace):
    save_requested = pyqtSignal()
    verify_requested = pyqtSignal(str)
    pick_dir = pyqtSignal()
    open_dir = pyqtSignal()
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__('设置', '这些设置会记住，下次打开不用再填。', parent)

        self.status = W.Badge('未校验', 'warn')
        self.add_action(self.status)
        self.btn_verify = W.PillButton('校验 token', 'secondary', small=True)
        self.add_action(self.btn_verify)

        # ---------------- token
        card = W.Card(padding=(22, 18, 22, 18), gap=9)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        head.addWidget(W.card_title('登录凭证 token'))
        head.addStretch(1)
        head.addWidget(W.Badge('必填', 'warn'))
        card.box.addLayout(head)
        card.box.addWidget(W.body(
            '清华教参要求双因子认证，程序不再收学号密码。'
            '在浏览器里按 F12 打开开发者工具、切到 Network，然后登录教参平台，'
            '找到一条 index?token=eyJh... 的请求，等号后面那串就是 token。',
            T.TEXT_DIM))
        self.token = TokenField()
        card.box.addWidget(self.token)
        self.token_hint = W.meta('token 会随会话过期，失效时重新抓一次即可。',
                                 T.TEXT_FAINT)
        card.box.addWidget(self.token_hint)
        self.box.addWidget(card)

        # ---------------- 保存位置
        card2 = W.Card(padding=(22, 18, 22, 18), gap=9)
        card2.box.addWidget(W.card_title('保存位置'))
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText('留空则用程序目录下的 downloads')
        self.dir_edit.setFont(T.ui_font(T.FS_BODY, 400, mono=True))
        self.dir_edit.setFixedHeight(38)
        self.dir_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {T.CARD}; border: 1px solid {T.BORDER};
                border-radius: {T.R_IN}px; padding: 0 12px; color: {T.TEXT};
            }}
            QLineEdit:focus {{ border: 1px solid {T.PRIMARY_SOFT}; }}
        """)
        card2.box.addWidget(self.dir_edit)
        drow = QHBoxLayout()
        drow.setContentsMargins(0, 0, 0, 0)
        drow.setSpacing(9)
        self.btn_pick = W.PillButton('选择目录', 'secondary', small=True)
        self.btn_open = W.PillButton('打开目录', 'ghost', small=True)
        drow.addWidget(self.btn_pick)
        drow.addWidget(self.btn_open)
        drow.addStretch(1)
        card2.box.addLayout(drow)
        card2.box.addWidget(W.meta(
            '每本书会放在 <保存位置>/<书号>/ 下面，PDF 与临时图片都在里面。',
            T.TEXT_FAINT))
        self.box.addWidget(card2)

        # ---------------- 下载参数
        card3 = W.Card(padding=(22, 18, 22, 18), gap=12)
        card3.box.addWidget(W.card_title('下载参数'))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        self.row_workers = W.FieldRow(
            '进程数', '4', '范围 1~16，默认 4。网络不稳时可调到 2。', compact=True)
        self.row_workers.edit.setInputMask('99')
        grid.addWidget(self.row_workers, 0, 0)
        self.row_quality = W.FieldRow(
            'PDF 质量', '10', '范围 3~10，默认 10（最高）。调小可减小体积。',
            compact=True)
        self.row_quality.edit.setInputMask('99')
        grid.addWidget(self.row_quality, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        card3.box.addLayout(grid)

        self.chk_keep = W.CheckItem('保留临时图片（方便中途失败后重跑）')
        self.chk_resize = W.CheckItem('自动统一页面尺寸（部分书籍每页尺寸不一致）')
        for chk in (self.chk_keep, self.chk_resize):
            card3.box.addWidget(chk)
        self.box.addWidget(card3)

        # ---------------- 保存
        frow = QHBoxLayout()
        frow.setContentsMargins(0, 0, 0, 0)
        frow.setSpacing(10)
        self.btn_save = W.PillButton('保存设置', 'primary')
        frow.addWidget(self.btn_save)
        self.saved_hint = W.meta('', T.ACCENT)
        frow.addWidget(self.saved_hint)
        frow.addStretch(1)
        self.box.addLayout(frow)
        self.add_stretch()

        # 接线：改任何一项都算「有未保存的改动」
        self.btn_save.clicked.connect(self.save_requested.emit)
        self.btn_pick.clicked.connect(self.pick_dir.emit)
        self.btn_open.clicked.connect(self.open_dir.emit)
        self.btn_verify.clicked.connect(
            lambda: self.verify_requested.emit(self.token.edit.text().strip()))
        for w in (self.token.edit, self.dir_edit, self.row_workers.edit,
                  self.row_quality.edit):
            w.textChanged.connect(self._touch)
        self.chk_keep.toggled.connect(self._touch)
        self.chk_resize.toggled.connect(self._touch)

    def _touch(self, *_a):
        self.saved_hint.setText('')
        self.changed.emit()

    # -------------------------------------------------------------- 数据
    def load(self, settings):
        self.token.edit.setText(settings.get('token', '') or '')
        self.dir_edit.setText(settings.get('save_dir', '') or '')
        self.row_workers.edit.setText(str(settings.get('workers', 4)))
        self.row_quality.edit.setText(str(settings.get('quality', 10)))
        self.chk_keep.setChecked(bool(settings.get('keep_images', True)))
        self.chk_resize.setChecked(bool(settings.get('auto_resize', False)))
        self.saved_hint.setText('')

    def values(self):
        def _int(edit, lo, hi, fallback):
            try:
                n = int(edit.text().strip() or fallback)
            except ValueError:
                n = fallback
            return max(lo, min(hi, n))

        return {
            'token': self.token.edit.text().strip(),
            'save_dir': self.dir_edit.text().strip(),
            'workers': _int(self.row_workers.edit, 1, 16, 4),
            'quality': _int(self.row_quality.edit, 3, 10, 10),
            'keep_images': bool(self.chk_keep.isChecked()),
            'auto_resize': bool(self.chk_resize.isChecked()),
        }

    def set_dir(self, path):
        self.dir_edit.setText(path)

    def set_verify_result(self, ok, text=''):
        if ok:
            self.status.setText(text or '有效')
            self.status.set_tone('accent')
            self.token_hint.setText('token 可用。')
        else:
            self.status.setText(text or '校验失败')
            self.status.set_tone('danger')
            self.token_hint.setText(text or '校验失败，请重新获取 token。')

    def clear_verify(self):
        self.status.setText('未校验')
        self.status.set_tone('warn')

    def mark_saved(self):
        self.saved_hint.setText('已保存')