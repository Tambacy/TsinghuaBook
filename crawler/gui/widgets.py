# coding:utf-8
"""
组件几何。这一层是全部视觉实现的一半（另一半是 backdrop.py）。

Qt 实现的硬约束（规范第十节）：
  * 样式表不支持 box-shadow        -> 用 QGraphicsEffect，一个控件只能有一个
  * 样式表不支持 transition        -> 用 QPropertyAnimation / QVariantAnimation
  * 样式表不支持 letter-spacing    -> 用 QFont.setLetterSpacing()
  * 渐变按钮用样式表效果次要        -> QLinearGradient + paintEvent 自绘
  * 半透明自绘控件默认会擦背景      -> WA_NoSystemBackground，但必须自己铺底
"""
import math
import os

from PyQt6.QtCore import (QEasingCurve, QObject, QPointF, QPropertyAnimation,
                          QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation,
                          pyqtProperty, pyqtSignal)
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient,
                         QPainter, QPainterPath, QPen, QPixmap)
from PyQt6.QtWidgets import (QCheckBox, QGraphicsDropShadowEffect, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)

from . import covers as C
from . import theme as T

_EASE = QEasingCurve.Type.OutCubic


def apply_shadow(widget, level, parent_for=None):
    """
    给控件挂一层分层柔投影。一个控件只能有一个 QGraphicsEffect ——
    父子都加会互相吃掉，所以只给最外层卡片挂。
    """
    blur, dx, dy, rgb, alpha = T.shadow_spec(level)
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(dx, dy)
    col = QColor(rgb[0], rgb[1], rgb[2])
    col.setAlpha(alpha)
    eff.setColor(col)
    widget.setGraphicsEffect(eff)
    return eff


def retarget_shadow(widget, level):
    blur, dx, dy, rgb, alpha = T.shadow_spec(level)
    eff = widget.graphicsEffect()
    if not isinstance(eff, QGraphicsDropShadowEffect):
        return apply_shadow(widget, level)
    eff.setBlurRadius(blur)
    eff.setOffset(dx, dy)
    col = QColor(rgb[0], rgb[1], rgb[2])
    col.setAlpha(alpha)
    eff.setColor(col)
    return eff


# ============================================================ 入场 / 悬停
class HoverLift(QObject):
    """
    悬停抬起：230ms，投影在 card 与 raised 之间切换 + 上移。
    过渡靠动画改 blur/alpha 和位置，不是切换图片。
    """

    def __init__(self, widget, base='card', hover='raised', lift=2):
        super().__init__(widget)
        self.w = widget
        self.base = base
        self.hover = hover
        self.lift = lift
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(T.motion.DUR_HOVER if T.motion.ENABLED else 0)
        self._anim.setEasingCurve(_EASE)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(0.0)
        self._anim.valueChanged.connect(self._on_value)
        self._y0 = None
        self._eff = None
        widget.installEventFilter(self)

    def _attach(self):
        if self._eff is None:
            from PyQt6.QtWidgets import QGraphicsDropShadowEffect
            self._eff = self.w.graphicsEffect()
            if not isinstance(self._eff, QGraphicsDropShadowEffect):
                self._eff = apply_shadow(self.w, self.base)

    def eventFilter(self, obj, ev):
        if obj is not self.w:
            return False
        if ev.type() == ev.Type.Enter:
            self._animate_to(1.0)
        elif ev.type() == ev.Type.Leave:
            self._animate_to(0.0)
        return False

    def _animate_to(self, v):
        self._attach()
        if not T.motion.ENABLED:
            self._on_value(v)
            return
        self._anim.stop()
        self._anim.setStartValue(self._anim.currentValue() if self._anim.currentValue() is not None else 0.0)
        self._anim.setEndValue(v)
        self._anim.start()

    def _on_value(self, v):
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        self._attach()
        b0, dx0, dy0, rgb0, a0 = T.shadow_spec(self.base)
        b1, dx1, dy1, rgb1, a1 = T.shadow_spec(self.hover)
        if isinstance(self._eff, QGraphicsDropShadowEffect):
            self._eff.setBlurRadius(b0 + (b1 - b0) * v)
            self._eff.setOffset(dx0 + (dx1 - dx0) * v, dy0 + (dy1 - dy0) * v)
            col = QColor(int(rgb0[0] + (rgb1[0] - rgb0[0]) * v),
                         int(rgb0[1] + (rgb1[1] - rgb0[1]) * v),
                         int(rgb0[2] + (rgb1[2] - rgb0[2]) * v))
            col.setAlpha(int(a0 + (a1 - a0) * v))
            self._eff.setColor(col)
        # 上移靠改边距实现，避免和布局管理器抢几何
        m = self.w.contentsMargins()
        if self._y0 is None:
            self._y0 = m.top()
            self._bottom0 = m.bottom()
        delta = -self.lift * v
        self.w.setContentsMargins(m.left(), int(self._y0 + delta), m.right(),
                                  int(self._bottom0 - delta))


class CardIn:
    """卡片入场：420ms，依次浮起。"""

    _seq = 0

    @staticmethod
    def run(widget, delay_ms=None):
        if not T.motion.ENABLED:
            widget.setWindowOpacity(1.0)
            return
        if delay_ms is None:
            delay_ms = CardIn._seq * 70
            CardIn._seq = (CardIn._seq + 1) % 8
        eff = apply_shadow(widget, 'card')
        anim = QPropertyAnimation(eff, b'blurRadius', widget)
        anim.setDuration(T.motion.DUR_CARD_IN)
        anim.setStartValue(0)
        anim.setEndValue(T.shadow_spec('card')[0])
        anim.setEasingCurve(_EASE)
        widget._card_in_anim = anim
        # 这里必须把 widget 当 context 传给 singleShot。
        # anim 的父对象就是 widget，卡片一旦被销毁（书库重建、切页、关窗口），
        # C++ 侧的 anim 也跟着没了；如果只写 singleShot(delay, anim.start)，
        # 延迟到点时会去调一个已经析构的对象，PyQt 直接 qFatal，表现成
        # 没有任何 Python 回溯的 0xC0000409 崩溃。传了 context 之后，
        # widget 一销毁这个定时器就自动作废。
        QTimer.singleShot(int(delay_ms), widget, anim.start)
        return anim


def shadow_margins(level):
    """
    自绘投影要在卡片本体外留多少像素：(左, 上, 右, 下)。

    QGraphicsDropShadowEffect 会自己往外画；换成自绘之后，这部分空间得由
    控件自己留出来，否则投影会被裁掉。
    """
    blur, dx, dy, _rgb, _alpha = T.shadow_spec(level)
    side = int(blur * 0.6) + 2
    return (side + max(0, -dx), side + max(0, -dy),
            side + max(0, dx), side + max(0, dy))


def render_shadow(level, radius, body_w, body_h, margins):
    """
    把柔投影预渲染成一张位图。

    做法是叠很多层圆角矩形，每层 alpha 很低，叠起来自然形成由内到外的衰减。
    那张图只需要一份，所以模糊只付一次代价。

    为什么非这么做不可：QGraphicsEffect 挂在 QWebEngineView 的祖先上时，
    Qt 会强制整棵子树走「离屏 pixmap + 模糊 + 合成」，浏览器每一帧都得过一遍。
    实测下来主线程 CPU 反而更低、但画面更新明显跟不上 —— 帧被丢掉了，
    用户感觉就是「滚动、点击都要反应很久」。自绘一次、缓存成位图以后，
    每帧只剩一次 blit，和浏览器渲染彻底解耦。
    """
    blur, dx, dy, rgb, alpha = T.shadow_spec(level)
    left, top, right, bottom = margins
    w = body_w + left + right
    h = body_h + top + bottom
    pm = QPixmap(max(1, w), max(1, h))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    steps = max(14, int(blur))
    base = QColor(rgb[0], rgb[1], rgb[2])
    # 让最内层叠出来的不透明度正好落在 alpha 上
    per = max(1, int(round(alpha / float(steps) * 1.1)))
    for i in range(steps):
        grow = blur * (1.0 - i / float(steps - 1))
        col = QColor(base)
        col.setAlpha(per)
        p.setBrush(col)
        p.drawRoundedRect(
            QRectF(left - grow + dx, top - grow + dy,
                   body_w + 2 * grow, body_h + 2 * grow),
            radius + grow, radius + grow)
    p.end()
    return pm


# ============================================================ 卡片
class Card(QWidget):
    """白底、R_CARD 圆角、card 投影。不描边 —— 靠投影和白底与页面底对比出来。"""

    def __init__(self, parent=None, padding=None, gap=None, radius=T.R_CARD,
                 bg=T.CARD, shadow='card', hover=False, painted_shadow=False):
        super().__init__(parent)
        self._radius = radius
        self._bg = bg
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        # painted_shadow=True：不用 QGraphicsEffect，自己画并缓存投影。
        # 含 QWebEngineView 的卡片必须走这条路，理由见 render_shadow。
        self._shadow_level = shadow if (shadow and painted_shadow) else None
        self._shadow_pm = None
        self._shadow_key = None
        self._margins = shadow_margins(self._shadow_level) \
            if self._shadow_level else (0, 0, 0, 0)
        pad = padding or T.PAD_CARD
        ml, mt, mr, mb = self._margins
        self.setContentsMargins(pad[0] + ml, pad[1] + mt,
                                pad[2] + mr, pad[3] + mb)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(gap if gap is not None else T.GAP_CARD)
        if shadow and not self._shadow_level:
            apply_shadow(self, shadow)
        self._hover = HoverLift(self, shadow, 'raised') if hover and shadow else None

    def shadow_margins(self):
        """投影在四周占掉的像素，调用方要把它算进宽度上限里。"""
        return self._margins

    def _body_rect(self):
        ml, mt, mr, mb = self._margins
        return QRectF(self.rect()).adjusted(ml, mt, -mr, -mb)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = self._body_rect()
        if self._shadow_level:
            key = (int(body.width()), int(body.height()))
            if self._shadow_pm is None or self._shadow_key != key:
                self._shadow_pm = render_shadow(
                    self._shadow_level, self._radius, key[0], key[1],
                    self._margins)
                self._shadow_key = key
            p.drawPixmap(0, 0, self._shadow_pm)
        r = body.adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._bg))
        p.drawRoundedRect(r, self._radius, self._radius)
        p.end()


class SoftBlock(QWidget):
    """卡片内的次级块：card_soft 底，无投影。"""

    def __init__(self, parent=None, padding=(16, 14, 16, 14), gap=8, radius=T.R_MD):
        super().__init__(parent)
        self._radius = radius
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(*padding)
        self.box.setSpacing(gap)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T.CARD_SOFT))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                          self._radius, self._radius)
        p.end()


# ============================================================ 文本
class Label(QLabel):
    def __init__(self, text='', px=T.FS_BODY, weight=400, color=T.TEXT,
                 mono=False, track=0.0, parent=None, wrap=False):
        super().__init__(text, parent)
        self.setFont(T.ui_font(px, weight, mono, track))
        self.setStyleSheet('color:%s;background:transparent;' % _css(color))
        if wrap:
            self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_color(self, color):
        """换文字颜色（状态从「检查中」变「失败」之类），不用重建控件。"""
        self.setStyleSheet('color:%s;background:transparent;' % _css(color))


def _css(color):
    """令牌 -> Qt 样式表颜色。支持 '#RRGGBB'、QColor、(r,g,b,a) 元组。"""
    if isinstance(color, str):
        return color
    if isinstance(color, QColor):
        return 'rgba(%d,%d,%d,%.3f)' % (color.red(), color.green(),
                                        color.blue(), color.alphaF())
    return 'rgba(%d,%d,%d,%.3f)' % (color[0], color[1], color[2],
                                    (color[3] / 255.0) if len(color) > 3 else 1.0)


def title(text, parent=None):
    return Label(text, T.FS_PAGE_TITLE, 700, T.TEXT, parent=parent)


def page_sub(text, parent=None):
    return Label(text, T.FS_PAGE_SUB, 400, T.TEXT_DIM, parent=parent)


def card_title(text, parent=None):
    return Label(text, T.FS_CARD_TITLE, 700, T.TEXT, parent=parent)


def section(text, parent=None):
    return Label(text, T.FS_SECTION, 600, T.TEXT, parent=parent)


def meta(text, color=T.TEXT_DIM, parent=None):
    """元信息：12.5px / 600，字距 1.2px —— 让它读起来像标记而不是正文。"""
    return Label(text, T.FS_META, 600, color, track=T.TRACK_META, parent=parent)


def body(text, color=T.TEXT, weight=400, parent=None, wrap=True):
    return Label(text, T.FS_BODY, weight, color, parent=parent, wrap=wrap)


# ============================================================ 按钮
class PillButton(QPushButton):
    """
    胶囊按钮（导航、返回、下一步）。R_PILL 圆角，min-height >= 22px。
    """

    def __init__(self, text='', kind='primary', parent=None, small=False):
        super().__init__(text, parent)
        self.kind = kind
        self.small = small
        self._hover_v = 0.0
        self._pressed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(T.ui_font(T.FS_BODY if not small else T.FS_META, 600))
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hv = QVariantAnimation(self)
        self._hv.setDuration(T.motion.DUR_HOVER if T.motion.ENABLED else 0)
        self._hv.setEasingCurve(_EASE)
        self._hv.valueChanged.connect(self._on_hv)
        self.setMinimumHeight(34)      # 随后被 _apply_padding 按 kind 覆盖
        self._apply_padding()

    def _apply_padding(self):
        # small 用在标题行那一排操作上：那里高度有限，
        # 用标准尺寸会把标题行撑高，视觉上压过内容
        s = 0 if not self.small else 1
        if self.kind == 'primary':
            self.setMinimumHeight(44 - 12 * s)
            self.setContentsMargins(0, 0, 0, 0)
            self._pad = (11 - 4 * s, 28 - 8 * s)
            self._radius = T.R_MD
            if self.graphicsEffect() is None:
                apply_shadow(self, 'glow')
        elif self.kind == 'ghost':
            self.setMinimumHeight(30 - 2 * s)
            self._pad = (4, 14 - 4 * s)
            self._radius = 13
            self.setGraphicsEffect(None)
        else:
            self.setMinimumHeight(40 - 8 * s)
            self._pad = (11 - 4 * s, 22 - 6 * s)
            self._radius = T.R_MD
            self.setGraphicsEffect(None)

    def set_kind(self, kind):
        self.kind = kind
        self._apply_padding()
        self.update()

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        w = fm.horizontalAdvance(self.text()) + self._pad[1] * 2
        h = 44 if self.kind == 'primary' else (30 if self.kind == 'ghost' else 40)
        return QSize(max(w, 88 if self.kind != 'ghost' else 56), h)

    def minimumSizeHint(self):
        return self.sizeHint()

    def _on_hv(self, v):
        self._hover_v = v
        if self.kind == 'primary':
            retarget_shadow(self, 'glow' if v < 0.5 else 'glow_hi')
        self.update()

    def enterEvent(self, ev):
        super().enterEvent(ev)
        self._anim(1.0)

    def leaveEvent(self, ev):
        super().leaveEvent(ev)
        self._anim(0.0)

    def _anim(self, v):
        if not T.motion.ENABLED:
            self._on_hv(v)
            return
        self._hv.stop()
        self._hv.setStartValue(self._hover_v)
        self._hv.setEndValue(v)
        self._hv.start()

    def mousePressEvent(self, ev):
        self._pressed = True
        self.update()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(ev)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        v = self._hover_v
        enabled = self.isEnabled()
        k = self.kind

        if k == 'primary':
            # 主按钮：primary -> primary_2 竖渐变，悬停更亮，按下走 primary_dark
            top = _mix(T.PRIMARY, '#9C8BD8', v)
            bot = _mix(T.PRIMARY_2, '#A899DE', v)
            if self._pressed:
                top, bot = T.PRIMARY_DARK, T.PRIMARY
            if not enabled:
                top = bot = T.PRIMARY_MID
            g = QLinearGradient(0, 0, 0, self.height())
            g.setColorAt(0.0, QColor(top))
            g.setColorAt(1.0, QColor(bot))
            p.setBrush(QBrush(g))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, self._radius, self._radius)
            fg = '#FFFFFF'
        elif k == 'secondary':
            bg = _mix(T.PRIMARY_LIGHT, '#DCD5F2', v)
            p.setBrush(QColor(bg if enabled else T.BG_SOFT))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, self._radius, self._radius)
            fg = T.PRIMARY_DARK if enabled else T.TEXT_GHOST
        elif k == 'danger':
            p.setBrush(QColor(T.DANGER_LIGHT))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, self._radius, self._radius)
            fg = T.DANGER if enabled else T.TEXT_GHOST
        else:  # ghost（导航）
            if v > 0:
                p.setBrush(T.rgba('#FFFFFF', 0.12 * v))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(r, self._radius, self._radius)
            fg = 'rgba(255,255,255,%d)' % int(255 * (0.76 + 0.24 * v)) if enabled \
                else 'rgba(255,255,255,110)'

        if not enabled and k == 'primary':
            fg = 'rgba(255,255,255,190)'
        p.setPen(QPen(QColor(fg)))
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


def _mix(a, b, t):
    ca, cb = QColor(a), QColor(b)
    return QColor(int(ca.red() + (cb.red() - ca.red()) * t),
                  int(ca.green() + (cb.green() - ca.green()) * t),
                  int(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


# ============================================================ 输入框
class Field(QLineEdit):
    """
    输入框：底 card_soft，R_IN 圆角，border 描边，内边距 9/14，高度约 40。
    聚焦时描边换 primary，另加一圈极浅的 primary_tint 光晕。
    """

    def __init__(self, placeholder='', parent=None):
        super().__init__(parent)
        self.setFont(T.ui_font(T.FS_BODY, 400))
        self.setPlaceholderText(placeholder)
        self.setMinimumHeight(40)
        self.setFixedHeight(40)
        self.setStyleSheet(f"""
            QLineEdit {{
                background: {T.CARD_SOFT};
                border: 1px solid {T.BORDER};
                border-radius: {T.R_IN}px;
                padding: 9px 14px;
                color: {T.TEXT};
                selection-background-color: {T.PRIMARY_LIGHT};
                selection-color: {T.TEXT};
            }}
            QLineEdit:hover {{ border: 1px solid {T.BORDER_STRONG}; }}
            QLineEdit:focus {{
                border: 1px solid {T.PRIMARY};
                background: #FFFFFF;
            }}
            QLineEdit:disabled {{ color: {T.TEXT_FAINT}; background: {T.BG_SOFT}; }}
        """)
        self._glow = apply_shadow(self, 'glow')
        self._glow.setEnabled(False)
        self._glow.setBlurRadius(10)
        self.textChanged.connect(lambda _t: self._refresh_glow())
        self._refresh_glow()

    def _refresh_glow(self):
        # 聚焦光晕：只在有焦点时给一圈极浅的紫
        self._glow.setEnabled(self.hasFocus() and T.motion.ENABLED)

    def focusInEvent(self, ev):
        super().focusInEvent(ev)
        self._refresh_glow()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self._refresh_glow()


class FieldRow(QWidget):
    """标签 + 输入框 + 说明，纵向。compact=True 时收紧间距，用于内容较长的页。"""

    def __init__(self, label, placeholder='', hint='', mono=False, parent=None,
                 password=False, compact=False, show_label=True):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4 if compact else 6)
        # 卡片标题已经写明字段名时就不重复一个标签
        if show_label and label:
            box.addWidget(meta(label, T.TEXT_DIM))
        self.edit = Field(placeholder)
        if mono:
            self.edit.setFont(T.ui_font(T.FS_BODY, 400, mono=True))
        if password:
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        box.addWidget(self.edit)
        self.hint = body(hint, T.TEXT_FAINT, parent=self)
        self.hint.setVisible(bool(hint))
        box.addWidget(self.hint)


_BADGE = {
    'accent': (T.ACCENT_LIGHT, T.ACCENT),
    'warn': (T.WARN_LIGHT, T.WARN),
    'danger': (T.DANGER_LIGHT, T.DANGER),
    'info': (T.PRIMARY_LIGHT, T.PRIMARY_DARK),
}


class Badge(QLabel):
    """小圆角块（R_SM），浅底 + 深字。状态色只用在徽章和状态条，不参与构图。"""

    def __init__(self, text='', tone='info', parent=None):
        super().__init__(text, parent)
        self.setFont(T.ui_font(T.FS_META, 600, track=0.6))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(24)
        # 徽章要贴合内容，不能被布局拉成一条
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_tone(tone)

    def set_tone(self, tone):
        bg, fg = _BADGE.get(tone, _BADGE['info'])
        self.setStyleSheet(f"""
            QLabel {{
                background: {bg};
                color: {fg};
                border-radius: {T.R_SM}px;
                padding: 2px 9px;
            }}
        """)
        self.updateGeometry()

    def sizeHint(self):
        # 文字宽 + 左右 padding(9) 与描边留量
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self.text()) + 26, 24)

    def minimumSizeHint(self):
        return self.sizeHint()


# ============================================================ 统计块


class Dot(QWidget):
    """4px 小圆点。"""

    def __init__(self, color=T.PRIMARY, size=4, parent=None):
        super().__init__(parent)
        self._c = QColor(color)
        self.setFixedSize(size + 4, size + 4)

    def set_color(self, c):
        self._c = QColor(c)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._c)
        p.drawEllipse(QRectF(self.rect()).center(), 2.0, 2.0)
        p.end()


# ============================================================ 步骤导轨


def _elide(fm, text, width):
    # paintEvent 里抛异常在 PyQt 下等于 qFatal：进程直接 0xC0000409 退出，
    # 没有回溯、没有提示。所以绘制路径上不能相信任何外部传进来的类型。
    if not isinstance(text, str):
        text = '' if text is None else str(text)
    if width <= 0:
        return ''
    return fm.elidedText(text, Qt.TextElideMode.ElideRight, width)


# ============================================================ 大状态字


class SideChip(QWidget):
    """
    侧边栏底部的状态块：一个圆点 + 一行说明。

    比 Badge 更适合这里：侧边栏窄，需要能放两行（标题 + 副标题），
    而且要随状态变色。自绘是因为要圆角和内边距同时成立。
    """

    clicked = pyqtSignal()

    # 三种语义。以前只有「绿=好 / 黄=要注意」，更新提示是中性信息，
    # 套绿色会被读成「成功了」，所以补一个品牌紫的 info。
    _TONES = {
        'ok':   (T.ACCENT_LIGHT, T.ACCENT),
        'warn': (T.WARN_LIGHT, T.WARN),
        'info': (T.PRIMARY_LIGHT, T.PRIMARY),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ok = False
        self._tone = 'warn'
        self._title = '未设置 token'
        self._sub = '下载前需要先抓一个'
        self.setFixedHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_state(self, ok, sub='', title=None, tone=None):
        """
        title 给了就用它（比如显示当前账号名），没给就按 ok 出默认文案。

        默认文案两边几乎一样（"token 有效" / "可以开始下载"），是因为以前
        这里只有「有没有 token」一个信息。现在有效期能算出来了，
        调用方会把剩余时间放进 sub，两行才各说一件事。

        tone 不传就按 ok 推：有效=绿、无效=黄。更新提示会显式传 'info'。
        """
        self._ok = bool(ok)
        self._tone = tone or ('ok' if ok else 'warn')
        self._title = title or ('token 有效' if ok else '未设置 token')
        self._sub = sub or ('可以开始下载' if ok else '点这里去设置')
        self.update()

    def sizeHint(self):
        return QSize(T.SIDEBAR_W - 24, 46)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg, dot = self._TONES.get(self._tone, self._TONES['warn'])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(r, T.R_IN, T.R_IN)

        p.setBrush(QColor(dot))
        p.drawEllipse(QPointF(r.left() + 15, r.center().y()), 3.6, 3.6)

        w = int(r.width() - 34)
        p.setPen(QColor(T.TEXT))
        f_title = T.ui_font(T.FS_META, 600)
        p.setFont(f_title)
        # 账号名是用户数据，长度不可控 —— 必须省略号截断，否则会画到圆角外面
        p.drawText(QRectF(r.left() + 26, r.top() + 8, w, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   _elide(QFontMetrics(f_title), self._title, w))
        p.setPen(QColor(T.TEXT_DIM))
        f_sub = T.ui_font(T.FS_META - 1, 400)
        p.setFont(f_sub)
        p.drawText(QRectF(r.left() + 26, r.top() + 23, w, 15),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   _elide(QFontMetrics(f_sub), self._sub, w))
        p.end()


# ==================================================================== 队列
# 任务状态 -> (中文, 语义色)
JOB_STATE_VIEW = {
    'pending':     ('排队中', T.TEXT_DIM),
    'resolving':   ('解析中', T.PRIMARY),
    'downloading': ('下载中', T.PRIMARY),
    'converting':  ('生成 PDF', T.PRIMARY),
    'done':        ('已完成', T.ACCENT),
    'failed':      ('失败', T.DANGER),
    'skipped':     ('已存在', T.TEXT_FAINT),
    'cancelled':   ('已停止', T.WARN),
}


def _draw_mini_cover(p, rect, title):
    """
    队列行左边的小封面。

    和书库共用同一套底图、同一个分配规则（covers.pick），所以同一本书在队列
    和书库里长得一样。两处对得上，才像同一个应用的两面；各画各的纯色小方块
    就只是两个装饰。

    这里不画标题字：30x40 上排不下任何可读的中文，硬塞只会变成一团墨点。
    真正的辨识信息是右边那行标题。
    """
    name = C.pick(title)
    art = C.pixmap(name)
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), 4, 4)
    p.save()
    p.setClipPath(path)
    if not art.isNull():
        tw, th = int(rect.width()), int(rect.height())
        scaled = art.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
        src = QRect(max(0, (scaled.width() - tw) // 2),
                    max(0, (scaled.height() - th) // 2), tw, th)
        p.drawPixmap(rect.toRect(), scaled, src)
        # 压一道暗：小图上不压的话，浅色底图在白色行里会「发飘」
        p.fillRect(rect, T.rgba('#000000', 0.18))
    else:
        p.fillRect(rect, QColor(T.PRIMARY_LIGHT))
        p.fillRect(QRectF(rect.left(), rect.top(), 4, rect.height()),
                   QColor(T.PRIMARY_MID))
    p.restore()
    p.setPen(QPen(T.qc(T.HAIRLINE), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)


class JobRow(QWidget):
    """
    队列里的一行。

    刻意不做成「课程卡片」那种左侧 4px 状态色条：那需要每行一个大色块，
    而队列里同时有十几行时满屏色条会很吵。这里把状态收进右侧的小字 +
    一条细进度条，颜色只用在真正需要被注意到的那一处。
    """

    open_folder = pyqtSignal(object)
    remove = pyqtSignal(object)

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = job
        self._hover = False
        self.setFixedHeight(64)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet('JobRow { background: transparent; }')
        self._sync_cursor()

    def _sync_cursor(self):
        # 只有完成的行整行可点（打开文件夹）；排队中的行只有悬停图标可点，
        # 整行给手型是在骗人
        self.setCursor(Qt.CursorShape.PointingHandCursor
                       if self.job.state in ('done', 'skipped')
                       else Qt.CursorShape.ArrowCursor)

    def set_job(self, job):
        self.job = job
        self._sync_cursor()
        self.update()

    def enterEvent(self, _ev):
        self._hover = True
        self.update()

    def leaveEvent(self, _ev):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, ev):
        """
        悬停时出现的那两个图标是自绘的、不是真按钮，所以这里必须自己做命中
        测试。

        以前只处理了「打开文件夹」，垃圾桶画出来了却没有任何命中判断 ——
        点上去完全没反应（用户报的 bug）。两个图标各自跟随可用状态：
        删除只对没在跑的行有效，打开文件夹只对已完成的行有效，点空了不做事。
        """
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if self._hover:
            pos = ev.position().toPoint()
            ro, rm = self._buttons()
            # 两个矩形不重叠；删除是破坏性操作，命中判断上先给它
            if rm.contains(pos):
                if not self.job.active:
                    self.remove.emit(self.job)
                return
            if ro.contains(pos):
                if self.job.state in ('done', 'skipped'):
                    self.open_folder.emit(self.job)
                return
        # 点行内其他地方：完成的行整行都是「打开文件夹」，其余不做事
        if self.job.state in ('done', 'skipped'):
            self.open_folder.emit(self.job)

    def _buttons(self):
        """悬停时显示的两个小按钮命中区。"""
        r = self.rect()
        size = 26
        top = r.center().y() - size // 2
        rm = QRect(r.right() - 16 - size, top, size, size)
        ro = QRect(rm.left() - 6 - size, top, size, size)
        return ro, rm

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0, 1.5, 0, -1.5)
        job = self.job

        p.setPen(Qt.PenStyle.NoPen)
        if job.active:
            p.setBrush(QColor(T.PRIMARY_TINT))
        elif self._hover:
            p.setBrush(QColor(T.BG_SOFT))
        else:
            p.setBrush(QColor(T.CARD))
        p.drawRoundedRect(r, T.R_IN, T.R_IN)

        # 序号
        num_x = r.left() + 12
        p.setPen(QColor(T.TEXT_GHOST))
        p.setFont(T.ui_font(T.FS_META, 600, mono=True))
        p.drawText(QRectF(num_x, r.top(), 22, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   '%02d' % (job.order + 1))

        # 小封面：和书库同一套图、同一个分配规则，同一本书两处长得一样
        thumb = QRectF(num_x + 28, r.center().y() - 20, 30, 40)
        _draw_mini_cover(p, thumb, getattr(job, 'label', '') or '')

        text_left = thumb.right() + 12
        right_pad = 16 if not self._hover else 16 + 26 + 6 + 26 + 6
        avail = r.width() - (text_left - r.left()) - right_pad - 96

        # 标题
        fm = QFontMetrics(T.ui_font(T.FS_BODY, 600))
        title = _elide(fm, job.label, max(60, int(avail)))
        p.setPen(QColor(T.TEXT if not job.active else T.PRIMARY_DEEP))
        p.setFont(T.ui_font(T.FS_BODY, 600))
        p.drawText(QRectF(text_left, r.top() + 12, avail, 18),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   title)

        # 副行：页数 / 失败 / 错误
        label, tone = JOB_STATE_VIEW.get(job.state, (job.state, T.TEXT_DIM))
        if job.state == 'failed' and job.error:
            sub = _elide(QFontMetrics(T.ui_font(T.FS_META, 400)), job.error,
                         max(60, int(avail)))
        elif job.pages:
            sub = '%d 页 · %d 章 · 失败 %d' % (job.pages, job.chapters,
                                              job.failed_pages)
            sub = sub.replace(' · 失败 0', '')
        else:
            sub = _elide(QFontMetrics(T.ui_font(T.FS_META, 400)), job.url,
                         max(60, int(avail)))
        p.setPen(QColor(T.DANGER if job.state == 'failed' else T.TEXT_FAINT))
        p.setFont(T.ui_font(T.FS_META, 400))
        p.drawText(QRectF(text_left, r.top() + 32, avail, 16),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, sub)

        # 状态文字
        p.setPen(QColor(tone))
        p.setFont(T.ui_font(T.FS_META, 600))
        p.drawText(QRectF(r.right() - 16 - 90, r.top(), 90, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   label)

        # 进度条（细，只在有进度时画）
        if job.active or 0 < job.fraction < 1:
            bar = QRectF(text_left, r.bottom() - 12, max(40, avail), 3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T.BG_DEEP))
            p.drawRoundedRect(bar, 1.5, 1.5)
            f = max(0.0, min(1.0, job.fraction))
            if f > 0:
                p.setBrush(QColor(T.PRIMARY))
                p.drawRoundedRect(QRectF(bar.left(), bar.top(),
                                         bar.width() * f, bar.height()), 1.5, 1.5)

        # 悬停按钮
        if self._hover:
            from . import icons
            ro, rm = self._buttons()
            can_open = job.state in ('done', 'skipped')
            for rect, name, enabled in ((ro, 'folder', can_open),
                                        (rm, 'trash', not job.active)):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(T.BG_DEEP if enabled else T.BG_SOFT))
                p.drawRoundedRect(QRectF(rect), T.R_SM, T.R_SM)
                col = T.TEXT_DIM if enabled else T.TEXT_GHOST
                icons.paint_icon(p, name,
                                 QRectF(rect).adjusted(6, 6, -6, -6), col)
        p.end()


class BookCard(QWidget):
    """书库网格里的一张卡片：封面 + 书名 + 作者 + 元信息 + 悬停操作。"""

    open_pdf = pyqtSignal(object)
    open_folder = pyqtSignal(object)
    remove = pyqtSignal(object)

    def __init__(self, rec, parent=None):
        super().__init__(parent)
        self.rec = rec
        self._hover = False
        self._w = T.GRID_MIN_W
        self._h = int(T.GRID_MIN_W * 4 / 3) + self.TEXT_BLOCK_H
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_record(self, rec):
        self.rec = rec
        self.update()

    def enterEvent(self, _ev):
        self._hover = True
        self.update()

    def leaveEvent(self, _ev):
        self._hover = False
        self.update()

    def _hit_rects(self):
        r = self.rect()
        size = 28
        y = r.top() + 8
        rm = QRect(r.right() - 10 - size, y, size, size)
        rf = QRect(rm.left() - 6 - size, y, size, size)
        ro = QRect(rf.left() - 6 - size, y, size, size)
        return ro, rf, rm

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        pos = ev.position().toPoint()
        ro, rf, rm = self._hit_rects()
        if self._hover and rm.contains(pos):
            self.remove.emit(self.rec)
        elif self._hover and rf.contains(pos):
            self.open_folder.emit(self.rec)
        else:
            # 整张卡片都是「打开这本书」，不用非得点中那个小图标
            self.open_pdf.emit(self.rec)

    # ---- 尺寸由 BookGrid 统一决定，保证同排卡片一样高
    TEXT_BLOCK_H = 92

    def set_card_size(self, w, h):
        self._w, self._h = int(w), int(h)
        self.update()

    def sizeHint(self):
        return QSize(self._w, self._h)

    def cover_rect(self):
        """封面铺满卡片宽度、3:4 比例，顶部随圆角裁切。"""
        r = QRectF(self.rect())
        h = min(r.width() * 4.0 / 3.0, r.height() - self.TEXT_BLOCK_H)
        return QRectF(r.left(), r.top(), r.width(), max(40.0, h))

    def paintEvent(self, _ev):
        from . import icons
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T.CARD))
        p.drawRoundedRect(r, T.R_CARD, T.R_CARD)

        rec = self.rec
        # 封面直接在 paintEvent 里画，不给每张卡片建子控件 ——
        # 书库可能有几百本，子控件数量会明显拖慢滚动
        cr = self.cover_rect()
        self._paint_cover(p, cr, rec)

        pad = 13
        text_left = r.left() + pad
        text_w = r.width() - pad * 2

        # 书名固定占两行，这样同一排卡片的高度和文字基线都对齐
        fm = QFontMetrics(T.ui_font(T.FS_BODY, 600))
        lines = _wrap_two(fm, rec.get('title') or rec.get('book_id') or '',
                          int(text_w))
        y = cr.bottom() + 10
        p.setPen(QColor(T.TEXT))
        p.setFont(T.ui_font(T.FS_BODY, 600))
        for ln in lines[:2]:
            p.drawText(QRectF(text_left, y, text_w, 18),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, ln)
            y += 17

        # 作者 / 出版年
        sub = ' · '.join([x for x in ((rec.get('author') or '').strip(),
                                      (rec.get('year') or '').strip()) if x])
        if not sub:
            sub = (rec.get('publisher') or '').strip()
        if sub:
            p.setPen(QColor(T.TEXT_FAINT))
            p.setFont(T.ui_font(T.FS_META, 400))
            p.drawText(QRectF(text_left, y + 1, text_w, 16),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       _elide(QFontMetrics(T.ui_font(T.FS_META, 400)), sub, int(text_w)))
            y += 17

        # 页数 / 体积 + 丢失标记
        meta_txt = []
        if rec.get('pages'):
            meta_txt.append('%d 页' % rec['pages'])
        if rec.get('size'):
            meta_txt.append(_fmt_size(rec['size']))
        line = ' · '.join(meta_txt)
        missing = not _rec_exists(rec)
        p.setPen(QColor(T.DANGER if missing else T.TEXT_DIM))
        p.setFont(T.ui_font(T.FS_META, 600 if missing else 400))
        p.drawText(QRectF(text_left, y + 2, text_w - 4, 16),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   '文件已丢失' if missing else line)

        # 悬停操作按钮
        if self._hover:
            ro, rf, rm = self._hit_rects()
            for rect, name, col in ((ro, 'folder', T.TEXT_DIM),
                                    (rf, 'retry', T.TEXT_DIM),
                                    (rm, 'trash', T.DANGER)):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(T.BG_SOFT))
                p.drawRoundedRect(QRectF(rect), T.R_SM, T.R_SM)
                icons.paint_icon(p, name, QRectF(rect).adjusted(7, 7, -7, -7), col)
        p.end()

    def _paint_cover(self, p, cr, rec):
        """封面只圆上面两个角，下面和文字区连成一体。"""
        path = QPainterPath()
        rad = T.R_CARD
        path.moveTo(cr.left(), cr.bottom())
        path.lineTo(cr.left(), cr.top() + rad)
        path.quadTo(cr.left(), cr.top(), cr.left() + rad, cr.top())
        path.lineTo(cr.right() - rad, cr.top())
        path.quadTo(cr.right(), cr.top(), cr.right(), cr.top() + rad)
        path.lineTo(cr.right(), cr.bottom())
        path.closeSubpath()
        p.save()
        p.setClipPath(path)
        from PyQt6.QtGui import QPixmap
        cover = rec.get('cover') or ''
        pm = QPixmap(cover) if cover and os.path.exists(cover) else QPixmap()
        if not pm.isNull():
            # 居中裁剪填满封面区，避免把封面拉变形
            tw, th = int(cr.width()), int(cr.height())
            scaled = pm.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
            src = QRect(max(0, (scaled.width() - tw) // 2),
                        max(0, (scaled.height() - th) // 2), tw, th)
            p.drawPixmap(cr.toRect(), scaled, src)
        else:
            title = rec.get('title') or rec.get('book_id') or '书'
            author = (rec.get('author') or '').strip()
            # 先试生成的艺术底图。8 张一套，按书名稳定分配 —— 同一本书
            # 永远是同一张。底图明暗差得很多，标题用深色还是白色由 covers
            # 按图算，写死的话深底图上就是一团黑。
            name = C.pick(title)
            art = C.pixmap(name)
            if not art.isNull():
                tw, th = int(cr.width()), int(cr.height())
                scaled = art.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                    Qt.TransformationMode.SmoothTransformation)
                src = QRect(max(0, (scaled.width() - tw) // 2),
                            max(0, (scaled.height() - th) // 2), tw, th)
                p.drawPixmap(cr.toRect(), scaled, src)
                ink = C.ink(name, art)
                sc = C.scrim(name, art)
                # 上下各压一道很淡的渐变：艺术底图本身留了白，但留多留少
                # 是模型说了算，压一道才能保证标题和作者一定读得出来。
                gtop = QLinearGradient(0, cr.top(), 0, cr.top() + cr.height() * 0.62)
                gtop.setColorAt(0.0, T.rgba(sc, 0.46))
                gtop.setColorAt(1.0, T.rgba(sc, 0.0))
                p.fillRect(QRectF(cr.left(), cr.top(), cr.width(),
                                  cr.height() * 0.62), QBrush(gtop))
                gbot = QLinearGradient(0, cr.bottom() - cr.height() * 0.30, 0, cr.bottom())
                gbot.setColorAt(0.0, T.rgba(sc, 0.0))
                gbot.setColorAt(1.0, T.rgba(sc, 0.42))
                p.fillRect(QRectF(cr.left(), cr.bottom() - cr.height() * 0.30,
                                  cr.width(), cr.height() * 0.30), QBrush(gbot))
                # 书脊：底图再好看，少了这一道就不像书，像一张海报
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(T.rgba(ink, 0.30))
                p.drawRect(QRectF(cr.left(), cr.top(), 7, cr.height()))
            else:
                bg = (T.PRIMARY_LIGHT, T.BG_SOFT, T.PRIMARY_TINT, T.ACCENT_LIGHT)[
                    sum(ord(c) for c in title) % 4]
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(bg))
                p.drawRect(cr)
                # 左侧一道书脊，让占位块看起来像本书
                p.setBrush(QColor(T.PRIMARY_MID))
                p.drawRect(QRectF(cr.left(), cr.top(), 7, cr.height()))
                ink = T.PRIMARY_DEEP

            # 按「封面」而不是「图标」来排：标题块偏上，作者贴底。
            # 单个大字放在正中央会显得像个图标，而不是一本书。
            left = cr.left() + max(14.0, cr.width() * 0.16)
            avail = cr.width() - (left - cr.left()) - max(12.0, cr.width() * 0.10)

            tpx = max(13, min(25, int(cr.width() * 0.115)))
            fm = QFontMetrics(T.ui_font(tpx, 700))
            ty = cr.top() + cr.height() * 0.20
            p.setPen(QColor(ink))
            p.setFont(T.ui_font(tpx, 700))
            for ln in _wrap_n(fm, title, int(avail), 3):
                p.drawText(QRectF(left, ty, avail, tpx + 6),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           ln)
                ty += tpx + 5

            if author:
                apx = max(11, tpx - 7)
                afm = QFontMetrics(T.ui_font(apx, 400))
                p.setPen(T.rgba(ink, 0.74))
                p.setFont(T.ui_font(apx, 400))
                p.drawText(QRectF(left, cr.bottom() - 22 - apx, avail, apx + 6),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           _elide(afm, author, int(avail)))
        p.restore()
        # 底边一道极淡的分隔，让封面和文字区分开而不需要画线框
        p.setPen(QPen(T.qc(T.HAIRLINE), 1))
        p.drawLine(QPointF(cr.left(), cr.bottom()), QPointF(cr.right(), cr.bottom()))


def _rec_exists(rec):
    p = rec.get('pdf_path') or ''
    return bool(p) and os.path.exists(p)


def _fmt_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ''
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return ('%.0f %s' % (n, unit)) if unit in ('B', 'KB') else ('%.1f %s' % (n, unit))
        n /= 1024.0
    return ''


def _wrap_two(fm, text, width):
    """把文本折成最多两行，第二行超出部分省略。"""
    lines = _wrap_n(fm, text, width, 2)
    return lines if lines else ['']


def _wrap_n(fm, text, width, max_lines):
    """
    按像素宽度折行，最多 max_lines 行，最后一行超出部分省略。

    中文没有空格，不能按词折，只能逐字累加 —— 对中英混排也够用。
    """
    text = (text or '').strip()
    if not text:
        return []
    lines = []
    rest = text
    while rest and len(lines) < max_lines:
        if fm.horizontalAdvance(rest) <= width:
            lines.append(rest)
            rest = ''
            break
        cut = ''
        for ch in rest:
            if fm.horizontalAdvance(cut + ch) > width:
                break
            cut += ch
        if not cut:                       # 一个字符都放不下，别死循环
            cut = rest[:1]
        lines.append(cut)
        rest = rest[len(cut):]
    if rest and lines:
        lines[-1] = _elide(fm, lines[-1] + rest, width)
    return lines


class CheckItem(QCheckBox):
    """
    自绘复选框。

    为什么不用样式表：Qt 样式表里把 indicator 的 background 设成主色之后
    并不会画出对勾（那需要 image: url(...) 一张勾的图）。结果就是「勾上了
    但看不出来」，用户没法确认状态。这里连对勾一起画。
    """

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setFont(T.ui_font(T.FS_BODY))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMinimumHeight(30)

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self.text()) + 38, 30)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        box = QRectF(r.left(), r.center().y() - 9, 18, 18)

        on = self.isChecked()
        hover = self.underMouse()

        p.setPen(Qt.PenStyle.NoPen)
        if on:
            p.setBrush(QColor(T.PRIMARY))
            p.drawRoundedRect(box, 5, 5)
            # 对勾：两段线，比用字体画稳
            pen = QPen(QColor('#FFFFFF'))
            pen.setWidthF(2.1)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            path = QPainterPath(QPointF(box.left() + 4.4, box.center().y() + 0.4))
            path.lineTo(QPointF(box.left() + 7.6, box.center().y() + 3.6))
            path.lineTo(QPointF(box.right() - 4.0, box.center().y() - 3.8))
            p.drawPath(path)
        else:
            p.setBrush(QColor(T.CARD))
            p.drawRoundedRect(box, 5, 5)
            pen = QPen(QColor(T.PRIMARY_SOFT if hover else T.BORDER_STRONG))
            pen.setWidthF(1.5)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(0.75, 0.75, -0.75, -0.75), 5, 5)

        p.setPen(QColor(T.TEXT if self.isEnabled() else T.TEXT_GHOST))
        p.setFont(self.font())
        p.drawText(QRectF(box.right() + 9, r.top(), r.width() - box.width() - 12,
                          r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.text())
        p.end()


class BatchStrip(QWidget):
    """
    整批进度条。只在队列运行时出现 —— 常驻会白占一块空间，
    而队列空闲时「总体进度」没有意义。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fraction = 0.0
        self._anim = None
        self.setFixedHeight(58)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet('BatchStrip { background: transparent; }')
        self._title = '正在下载'
        self._sub = ''

    def set_text(self, title, sub=''):
        self._title = title or ''
        self._sub = sub or ''
        self.update()

    def set_progress(self, fraction, done=0, failed=0, left=0):
        target = max(0.0, min(1.0, float(fraction)))
        if abs(target - self._fraction) < 0.002 or not T.motion.ENABLED:
            self._fraction = target
            self.update()
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(float(self._fraction))
        anim.setEndValue(target)
        anim.setDuration(T.motion.DUR_DATA_IN)
        anim.setEasingCurve(_EASE)

        def on_val(v):
            self._fraction = float(v)
            self.update()

        anim.valueChanged.connect(on_val)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._anim = anim
        self._done, self._failed, self._left = done, failed, left
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T.PRIMARY_TINT))
        p.drawRoundedRect(r, T.R_IN, T.R_IN)

        p.setPen(QColor(T.PRIMARY_DEEP))
        p.setFont(T.ui_font(T.FS_BODY, 600))
        p.drawText(QRectF(r.left() + 16, r.top() + 9, r.width() - 130, 18),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._title)
        if self._sub:
            p.setPen(QColor(T.TEXT_DIM))
            p.setFont(T.ui_font(T.FS_META, 400))
            p.drawText(QRectF(r.left() + 16, r.top() + 28, r.width() - 130, 16),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       self._sub)

        p.setPen(QColor(T.PRIMARY_DARK))
        p.setFont(T.ui_font(T.FS_SECTION, 700, mono=True))
        p.drawText(QRectF(r.right() - 96, r.top(), 80, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   '%d%%' % round(self._fraction * 100))

        bar = QRectF(r.left() + 16, r.bottom() - 10, r.width() - 32, 4)
        p.setBrush(QColor(T.BG_DEEP))
        p.drawRoundedRect(bar, 2, 2)
        if self._fraction > 0:
            p.setBrush(QColor(T.PRIMARY))
            p.drawRoundedRect(QRectF(bar.left(), bar.top(),
                                     bar.width() * self._fraction, bar.height()),
                              2, 2)
        p.end()


class EmptyState(QWidget):
    """空状态：一句话说明 + 一句怎么办。不用插画，留白本身就是设计。"""

    def __init__(self, title, hint='', parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 34, 0, 0)
        box.setSpacing(7)
        box.addStretch(1)
        self._title = Label(title, T.FS_CARD_TITLE, 700, T.TEXT_GHOST)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self._title)
        self._hint = Label(hint, T.FS_BODY, 400, T.TEXT_FAINT)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setVisible(bool(hint))
        box.addWidget(self._hint)
        box.addStretch(1)

    def set_title(self, text):
        self._title.setText(text)

    def set_hint(self, text):
        self._hint.setText(text)
        self._hint.setVisible(bool(text))