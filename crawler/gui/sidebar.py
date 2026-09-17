# coding:utf-8
"""
侧边栏：品牌区（天幕）+ 导航 + 底部状态。

为什么是侧边栏而不是原设计稿的顶部导航胶囊 + 步骤导轨：
下载器是一个会被反复打开的工具，用户需要在「排队下载」「翻已下的书」「改设置」
之间来回切。顶部导航适合一次性线性流程，切来切去成本高；
侧边栏让当前位置一直可见，且把纵向空间全留给内容。
"""
from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
                             QWidget)

from . import icons
from . import theme as T
from . import widgets as W
from .backdrop import SkyPanel


class NavItem(QWidget):
    """一个导航项：图标 + 文字 + 选中态。整块可点。"""

    clicked = pyqtSignal(str)

    def __init__(self, key, label, icon, parent=None):
        super().__init__(parent)
        self.key = key
        self.label = label
        self.icon = icon
        self._active = False
        self._hover = False
        self.setFixedHeight(T.NAV_ITEM_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def sizeHint(self):
        return QSize(T.SIDEBAR_W, T.NAV_ITEM_H)

    def set_active(self, on):
        if self._active != on:
            self._active = on
            self.update()

    def enterEvent(self, _ev):
        self._hover = True
        self.update()

    def leaveEvent(self, _ev):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self.rect().contains(ev.position().toPoint()):
            self.clicked.emit(self.key)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect().adjusted(10, 0, -10, 0)

        if self._active:
            # 选中态用主色浅底 + 左侧一道主色指示条，而不是靠描边
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T.PRIMARY_LIGHT))
            p.drawRoundedRect(r, T.R_IN, T.R_IN)
            bar = QRect(r.left() + 1, r.center().y() - 9, 3, 18)
            p.setBrush(QColor(T.PRIMARY))
            p.drawRoundedRect(bar, 2, 2)
        elif self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T.BG_SOFT))
            p.drawRoundedRect(r, T.R_IN, T.R_IN)

        color = T.PRIMARY_DARK if self._active else T.TEXT_DIM
        ic = QRect(r.left() + 14, r.center().y() - 9, 19, 19)
        icons.paint_icon(p, self.icon, ic, color)

        p.setPen(QColor(color))
        f = T.ui_font(T.FS_SECTION, 600 if self._active else 400)
        p.setFont(f)
        p.drawText(QRect(ic.right() + 12, r.top(), r.width() - 58, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.label)
        p.end()


class Sidebar(QWidget):
    """
    左侧固定宽度的一条。顶部是天幕品牌区，中间导航，底部是 token 状态。
    """

    nav = pyqtSignal(str)
    logout_requested = pyqtSignal()
    update_clicked = pyqtSignal()

    def __init__(self, parent=None, variant='violet'):
        super().__init__(parent)
        self.setFixedWidth(T.SIDEBAR_W)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet('Sidebar { background: %s; }' % T.CARD_SOFT)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        # ---- 品牌区
        # fade_to 传侧边栏自己的底色：化开区是不透明的，落在页面底色上
        # 会在天幕和导航之间露出一条色差。
        self.sky = SkyPanel(variant, self, fade_to=T.CARD_SOFT)
        brand = QVBoxLayout(self.sky.slot)
        brand.setContentsMargins(20, 0, 16, 0)
        brand.setSpacing(1)
        brand.addStretch(1)
        self.app_name = QLabel('清华教参下载器')
        self.app_name.setFont(T.ui_font(T.FS_SECTION, 700, track=0.2))
        self.app_name.setStyleSheet('color: %s; background: transparent;' % T.ON_DARK)
        brand.addWidget(self.app_name)
        self.app_sub = QLabel('电子教材 PDF')
        self.app_sub.setFont(T.ui_font(T.FS_META, 400))
        self.app_sub.setStyleSheet('color: %s; background: transparent;' % T.ON_DARK_FAINT)
        brand.addWidget(self.app_sub)
        brand.addSpacing(20)
        box.addWidget(self.sky)

        # ---- 导航
        nav_wrap = QWidget(self)
        # 导航区顶上那一条要自己刷底色，见 _paint_seam 的说明。
        nav_wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        nav_wrap.setStyleSheet(
            'QWidget { background: %s; border-top: 3px solid %s; }'
            % (T.CARD_SOFT, T.CARD_SOFT))
        nav_box = QVBoxLayout(nav_wrap)
        nav_box.setContentsMargins(0, 14, 0, 0)
        nav_box.setSpacing(T.NAV_ITEM_GAP)
        self.items = {}
        for key, label, icon in (
                ('queue', '下载队列', 'queue'),
                ('library', '书库', 'library'),
                ('settings', '设置', 'settings'),
                ('help', '使用说明', 'help')):
            it = NavItem(key, label, icon, nav_wrap)
            it.clicked.connect(self.nav.emit)
            nav_box.addWidget(it)
            self.items[key] = it
        nav_box.addStretch(1)
        box.addWidget(nav_wrap, 1)

        # ---- 底部状态：token 有没有配、当前在不在跑
        # 更新提示平时是隐藏的，只有真发现新版本才显形 —— 常驻一条
        # 「已是最新」只会占地方。
        self.update_chip = W.SideChip(self)
        self.update_chip.setVisible(False)
        self.update_chip.clicked.connect(self.update_clicked.emit)
        self.status_chip = W.SideChip(self)
        self.btn_logout = W.PillButton('退出登录', 'ghost', self, small=True)
        self.btn_logout.clicked.connect(self.logout_requested.emit)
        foot = QWidget(self)
        foot_box = QVBoxLayout(foot)
        foot_box.setContentsMargins(12, 0, 12, 14)
        foot_box.setSpacing(8)
        foot_box.addWidget(self.update_chip)
        foot_box.addWidget(self.status_chip)
        foot_box.addWidget(self.btn_logout)
        box.addWidget(foot)

        self.set_active('queue')

    def set_active(self, key):
        for k, it in self.items.items():
            it.set_active(k == key)

    def set_variant(self, name, animate=True):
        self.sky.set_variant(name, animate)

    def set_token_state(self, ok, text=''):
        self.status_chip.set_state(ok, text)

    def show_update(self, version):
        """发现新版本：在侧边栏亮一条，点它就在应用内更新。"""
        self.update_chip.set_state(
            True, '点这里直接更新', title='有新版本 %s' % version, tone='info')
        self.update_chip.setToolTip('当前 %s，最新 %s' % (T.RELEASE_VERSION, version))
        self.update_chip.setVisible(True)

    def hide_update(self):
        self.update_chip.setVisible(False)
        self.update_chip.setToolTip('')

    def set_token_expiry(self, state, text='', account=None):
        """
        把 Token 的有效期也摆到侧边栏上。

        账号名放标题（有多账号时一眼能看出登的是谁），剩余时间放副标题，
        更长的说明走 tooltip —— 侧边栏那一格说不清那么多字。

        account 为 None 时标题退回状态文案，不会显示成空白。
        """
        self.status_chip.set_state(state in ('valid', 'unknown'), text,
                                   title=account)
        self.status_chip.setToolTip(text or '')
