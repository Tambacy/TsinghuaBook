# coding:utf-8
"""
自绘标题栏 + 无边框窗口的窗口级交互。

为什么要自己画标题栏：
  系统那套白底灰字的标题栏和这个应用的配色完全不是一个体系，摆在一起就是
  「一眼简陋」。改成自绘之后，标题栏用的是和页面同一套令牌（底色、分隔线、
  字重、悬停态），整个窗口才像一个产品。

窗口拖拽 / 缩放 / 贴边靠 **WM_NCHITTEST** 交给系统做（见 hit_test），
而不是自己在 mouseMove 里挪窗口。这一条很关键：
  - 自己在 move() 里挪，拖动时会掉帧、而且没有 Aero Snap（拖到屏幕边缘吸附）；
  - 返回 HTCAPTION 之后，拖动、双击最大化、贴边全部是系统原生行为，
    手感和资源管理器完全一致；
  - 返回 HTLEFT / HTRIGHT 等之后，边缘缩放也是原生的，不会出现
    「拖到一半窗口跳一下」。
Qt 层同样保留了一套纯 Qt 的拖动实现，作为 nativeEvent 不可用时的兜底
（比如非 Windows 平台或 offscreen 测试环境）。
"""
import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from . import theme as T

# Windows 命中码
HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17
WM_NCHITTEST = 0x0084

# 边缘缩放的判定宽度。太宽会吃掉页面里靠边的控件（比如表格右边缘的滚动条），
# 太窄又不好抓。5px 是各家自定义标题栏应用常用的折中值。
RESIZE_BORDER = 5

WIN_BTN_W = 46


class _Point(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]


class _Msg(ctypes.Structure):
    _fields_ = [('hWnd', wintypes.HWND),
                ('message', wintypes.UINT),
                ('wParam', wintypes.WPARAM),
                ('lParam', wintypes.LPARAM),
                ('time', wintypes.DWORD),
                ('pt', _Point)]


def nc_hit_test(window, event_type, message):
    """
    给顶层窗口的 nativeEvent 用：是 WM_NCHITTEST 就返回命中码，否则 None。

    解析 ctypes 结构这件事留在本模块里，shell.py 只负责转发。
    """
    if event_type != b'windows_generic_MSG':
        return None
    try:
        addr = int(message)
    except Exception:                                            # noqa: BLE001
        return None
    if not addr:
        # 空指针绝不能交给 from_address —— 那是在读地址 0，直接崩，
        # 而且 try/except 拦不住（不是 Python 异常）。
        return None
    try:
        msg = _Msg.from_address(addr)
    except Exception:                                            # noqa: BLE001
        return None
    if msg.message != WM_NCHITTEST:
        return None
    return hit_test(window, window.mapFromGlobal(QCursor.pos()))


def hit_test(window, pos):
    """
    给定窗口坐标，返回该交给系统的 WM_NCHITTEST 命中码；返回 None 表示让
    Qt 正常处理（普通客户区）。

    pos 用 Qt 的逻辑坐标。取坐标统一走 QCursor.pos()（也是逻辑坐标）——
    WM_NCHITTEST 的 lParam 是物理像素，在高 DPI 下直接换算容易错，
    而命中测试本来就是为了当前光标位置，用 QCursor 最稳。
    """
    if window.isMaximized() or window.isFullScreen():
        return None                       # 最大化时四周不留给缩放

    w, h = window.width(), window.height()
    x, y = pos.x(), pos.y()
    if x < 0 or y < 0 or x >= w or y >= h:
        return None

    left = x < RESIZE_BORDER
    right = x >= w - RESIZE_BORDER
    top = y < RESIZE_BORDER
    bottom = y >= h - RESIZE_BORDER

    if top and left:
        return HTTOPLEFT
    if top and right:
        return HTTOPRIGHT
    if bottom and left:
        return HTBOTTOMLEFT
    if bottom and right:
        return HTBOTTOMRIGHT
    if left:
        return HTLEFT
    if right:
        return HTRIGHT
    if top:
        return HTTOP
    if bottom:
        return HTBOTTOM

    bar = getattr(window, 'titlebar', None)
    if bar is not None and bar.is_draggable(window.mapToGlobal(pos)):
        return HTCAPTION
    return None


class _WinButton(QWidget):
    """标题栏右侧的三个按钮。自绘字形，跟系统那套完全脱钩。"""

    clicked = pyqtSignal()

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._hover = False
        self._press = False
        # 只有「用键盘 Tab 过来」才画焦点圈。鼠标点出来的焦点不画 ——
        # 等价于 CSS 的 :focus-visible，不然点一下按钮就留个圈。
        self._kb_focus = False
        self.setFixedSize(WIN_BTN_W, T.TITLEBAR_H)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        # 键盘也要能够到 —— 只靠鼠标的话，纯键盘用户关不掉窗口
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    # -------------------------------------------------- 交互
    def focusInEvent(self, ev):
        self._kb_focus = ev.reason() in (Qt.FocusReason.TabFocusReason,
                                         Qt.FocusReason.BacktabFocusReason,
                                         Qt.FocusReason.ShortcutFocusReason)
        self.update()
        super().focusInEvent(ev)

    def focusOutEvent(self, ev):
        self._kb_focus = False
        self.update()
        super().focusOutEvent(ev)

    def enterEvent(self, ev):
        self._hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        self._press = False
        self.update()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._press = True
            self.update()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self._press:
            self._press = False
            self.update()
            if self.rect().contains(ev.position().toPoint()):
                self.clicked.emit()
        super().mouseReleaseEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return,
                        Qt.Key.Key_Enter):
            self.clicked.emit()
            return
        super().keyPressEvent(ev)

    # -------------------------------------------------- 画
    def _is_close(self):
        return self.kind == 'close'

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self._hover:
            bg = QColor(T.DANGER) if self._is_close() else QColor(T.BG_SOFT)
            if self._press:
                bg = bg.darker(112)
            p.fillRect(self.rect(), bg)

        # 键盘焦点用一圈描边表示，绝不能用填充 —— 填充看起来就是鼠标悬停，
        # 窗口一打开就有一个按钮「亮着」，很怪。
        show_focus = (self._kb_focus and not self._hover
                      and self.window().isActiveWindow())

        if self._hover and self._is_close:
            pen_col = QColor('#FFFFFF')
        else:
            pen_col = QColor(T.TEXT if self._hover else T.TEXT_DIM)

        pen = QPen(pen_col)
        pen.setWidthF(1.3)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        s = 5.0                      # 字形半宽：整体 10x10，和系统一致

        if self.kind == 'min':
            p.drawLine(int(cx - s), int(cy + 0.5), int(cx + s), int(cy + 0.5))

        elif self.kind == 'max':
            if self.window().isMaximized():
                # 还原：两个错开的小方框
                p.drawRect(QRectF(cx - s, cy - s + 2, 2 * s - 2, 2 * s - 2))
                p.drawPolyline([
                    QPoint(int(cx - s + 2), int(cy - s + 2)),
                    QPoint(int(cx - s + 2), int(cy - s)),
                    QPoint(int(cx + s), int(cy - s)),
                    QPoint(int(cx + s), int(cy + s - 2)),
                ])
            else:
                p.drawRect(QRectF(cx - s, cy - s, 2 * s, 2 * s))

        elif self.kind == 'close':
            p.drawLine(int(cx - s), int(cy - s), int(cx + s), int(cy + s))
            p.drawLine(int(cx + s), int(cy - s), int(cx - s), int(cy + s))

        if show_focus:
            fp = QPen(QColor(T.PRIMARY), 1.2)
            p.setPen(fp)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(cx - 9, cy - 9, 18, 18), 4, 4)
        p.end()


class TitleBar(QWidget):
    """
    自绘标题栏：左边 logo + 应用名，右边最小化 / 最大化 / 关闭。

    高度固定，背景和页面同色，底部一条分隔线 —— 目的就是让它看起来是
    应用的一部分，而不是系统贴上来的一条。
    """

    def __init__(self, parent=None, subtitle=''):
        super().__init__(parent)
        self.setObjectName('appTitleBar')
        self.setFixedHeight(T.TITLEBAR_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        # 纯 Qt 拖动用的兜底状态
        self._drag_from = None

        box = QHBoxLayout(self)
        box.setContentsMargins(14, 0, 0, 0)
        box.setSpacing(10)

        from .widgets import Label
        self.icon = QWidget(self)
        self.icon.setFixedSize(18, 18)
        self._icon_pm = None
        box.addWidget(self.icon)

        self.title = Label(T.APP_NAME, 13, 600, T.TEXT, parent=self)
        box.addWidget(self.title)

        self.subtitle = Label(subtitle or '', 12, 400,
                              T.TEXT_FAINT, parent=self)
        # 没有副标题时不要留一个空的占位 Label：它占宽度、还会让标题左右
        # 间距看着不齐。直接藏掉。
        self.subtitle.setVisible(bool(subtitle))
        box.addWidget(self.subtitle)

        box.addStretch(1)

        self.btn_min = _WinButton('min', self)
        self.btn_max = _WinButton('max', self)
        self.btn_close = _WinButton('close', self)
        for b, name in ((self.btn_min, '最小化'), (self.btn_max, '最大化'),
                        (self.btn_close, '关闭')):
            b.setAccessibleName(name)
            b.setToolTip(name)
            box.addWidget(b)

        self.btn_min.clicked.connect(lambda: self.window().showMinimized())
        self.btn_max.clicked.connect(self._toggle_max)
        self.btn_close.clicked.connect(lambda: self.window().close())

        self._load_icon()

    # -------------------------------------------------- 图标
    def _load_icon(self):
        from ..gui.shell import resource_path
        import os
        for name in ('app.ico', 'logo32.png'):
            p = resource_path('assets', name)
            if os.path.exists(p):
                from PyQt6.QtGui import QIcon
                pm = QIcon(p).pixmap(18, 18)
                if not pm.isNull():
                    self._icon_pm = pm
                    break
        self.icon.paintEvent = self._paint_icon       # type: ignore[method-assign]

    def _paint_icon(self, _ev):
        if self._icon_pm is None:
            return
        p = QPainter(self.icon)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(0, 0, self._icon_pm)
        p.end()

    # -------------------------------------------------- 行为
    def _toggle_max(self):
        win = self.window()
        if win.isMaximized():
            win.showNormal()
        else:
            win.showMaximized()
        self.sync()

    def sync(self):
        """窗口状态变了以后刷新按钮字形（最大化 / 还原）。"""
        self.btn_max.update()
        tip = '还原' if self.window().isMaximized() else '最大化'
        self.btn_max.setToolTip(tip)
        self.btn_max.setAccessibleName(tip)

    # -------------------------------------------------- 命中测试
    def _button_rects(self):
        rects = []
        for b in (self.btn_min, self.btn_max, self.btn_close):
            tl = b.mapTo(self.window(), QPoint(0, 0))
            rects.append((tl.x(), tl.y(), b.width(), b.height()))
        return rects

    def is_draggable(self, global_pos):
        """
        global_pos 是不是落在「可以拖着走」的区域上。

        三个按钮以及标题栏上的其它可交互控件要排除掉，否则点按钮会变成拖窗口。
        """
        pos = self.mapFromGlobal(global_pos)
        if not self.rect().contains(pos):
            return False
        for (x, y, w, h) in self._button_rects():
            local = self.mapFrom(self.window(), QPoint(x, y))
            if local.x() <= pos.x() < local.x() + w and \
               local.y() <= pos.y() < local.y() + h:
                return False
        return True

    # -------------------------------------------------- 纯 Qt 兜底拖动
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            self._drag_from = (ev.globalPosition().toPoint(),
                               win.frameGeometry().topLeft())
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_from is None:
            return
        win = self.window()
        gp = ev.globalPosition().toPoint()
        start_gp, start_wp = self._drag_from
        if win.isMaximized():
            # 和系统一致：拖动最大化的窗口时先还原，并让光标落在标题栏上
            ratio = gp.x() / float(max(1, win.width()))
            win.showNormal()
            self.sync()
            new_x = int(gp.x() - win.width() * ratio)
            win.move(new_x, max(0, gp.y() - T.TITLEBAR_H // 2))
            self._drag_from = (gp, win.frameGeometry().topLeft())
            return
        win.move(start_wp.x() + gp.x() - start_gp.x(),
                 start_wp.y() + gp.y() - start_gp.y())

    def mouseReleaseEvent(self, ev):
        self._drag_from = None
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()
        super().mouseDoubleClickEvent(ev)

    # -------------------------------------------------- 画
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(T.BG))
        # 底部一条分隔线，把标题栏和内容分开；用令牌里的描边色，不抢戏
        p.setPen(QPen(QColor(T.BORDER), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()
