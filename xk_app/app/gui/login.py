# coding:utf-8
"""
登录页：企业应用那种「先登录、再进主界面」的形态。

两种模式：
    统一身份认证 —— 应用内嵌一个浏览器，用户在窗口里输账号密码、完成 2FA，
                    程序盯着地址栏，一旦跳到 /index?token=xxx 就把 Token 截下来。
    直接填 Token —— 粘贴 Token（或整条带 token= 的地址），本地解析有效期。

为什么账号密码不能像老版本那样用表单 POST：
    1. 清华 ID 系统（id.tsinghua.edu.cn）已禁止非浏览器调用登录接口，
       直接 POST 会返回「该应用不允许调用登录接口」；
    2. 登录强制双因子认证（2FA），脚本无法独自完成。
    这不是实现选择，是平台限制，所以只能走内嵌浏览器的交互式登录。
    详见 README「登录方式说明」。

内嵌浏览器用持久化 profile：这样「信任此设备」能留下来，
下次 Token 失效时可以真的自动续期，而不是每次都重来一遍 2FA。
"""
import os
import shutil

from PyQt6.QtCore import (QEasingCurve, QCoreApplication, QPropertyAnimation,
                          QRectF, Qt, QUrl, pyqtProperty, pyqtSignal)
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QHBoxLayout, QPlainTextEdit, QSizePolicy,
                             QStackedWidget, QVBoxLayout, QWidget)

from ..core import store, tokeninfo
from . import theme as T
from . import widgets as W
from .backdrop import SkyBackdrop

# QtWebEngine 有两条硬性要求，二选一，而且都必须在 QApplication 构造之前满足：
#   a) 先 import QtWebEngineWidgets，或
#   b) 先设 AA_ShareOpenGLContexts
# 我们想保持「不用 SSO 就不加载 Chromium」的惰性导入（启动更快、测试更轻），
# 所以走 b)。这个模块在 shell.py 里是模块级导入，一定早于 main() 里的
# QApplication()，在这里设属性是安全的。
# 不这么做的话，ensure_web() 里那次 import 会直接抛：
#   "QtWebEngineWidgets must be imported or Qt.AA_ShareOpenGLContexts
#    must be set before a QCoreApplication instance is created"
QCoreApplication.setAttribute(
    Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

PLATFORM_HOME = 'https://ereserves.lib.tsinghua.edu.cn/'

# 设了这个环境变量就完全不碰内嵌浏览器，退化成「只能用 Token 登录」。
# 两个用处：
#   1. 无头/CI 环境里 Chromium 起不来，或只是不想为它付启动成本；
#   2. 用户机器上 Chromium 出问题时的逃生口 —— 不至于因为浏览器起不来
#      就整个应用不能用。
NO_WEBENGINE_ENV = 'TSINGHUA_CRAWLER_NO_WEBENGINE'

BRAND_W_MIN = 380
BRAND_W_MAX = 560
BRAND_W_RATIO = 0.42
CARD_MAX_W = 520
CARD_MIN_W = 340
SIDE_PAD = 34


def _hug(widget):
    """
    让控件只占自己需要的高度。

    不这么做的话，QLabel 默认的纵向策略是 Preferred，会跟着布局一起被拉高：
    实测「粘贴 Token」这种一行文字被拉到 127px，卡片里就冒出一堆空档。
    多余的纵向空间应该集中到一处（面板底部的 stretch），而不是平摊给每一行。
    """
    widget.setSizePolicy(QSizePolicy.Policy.Preferred,
                         QSizePolicy.Policy.Maximum)
    return widget


def _profile_root():
    """内嵌浏览器所有 profile 代际的父目录。"""
    return os.path.join(store.data_dir(), 'webprofile')


def _profile_dir(settings):
    """
    当前这一代的 profile 目录。

    带代号是为了「退出登录」能真正退干净：只删 cookie 是异步的、而且清不掉
    localStorage 和缓存，下一代会用一个全新的空目录。
    """
    try:
        gen = int(settings.get('webprofile_gen') or 0)
    except (TypeError, ValueError):
        gen = 0
    return os.path.join(_profile_root(), 'g%d' % max(0, gen))


def _rmtree_quiet(path):
    """删目录，删不掉就算了 —— 文件可能正被 Chromium 占着。"""
    if not path or not os.path.isdir(path):
        return
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:                                                # noqa: BLE001
        pass


def _cleanup_old_profiles(settings, keep=2):
    """
    清掉旧的 profile 代际，免得退出登录几次就攒一堆 Chromium 数据目录。
    保留最近 keep 代（当前代 + 上一代），删更早的。

    顺带清掉旧的扁平布局：早期版本直接把 Chromium 文件放在 webprofile/ 下，
    现在改成 webprofile/gN/ 了。那些老文件不会再被读到，留着只是白占地方
    —— 而且里面正是「退出登录也退不掉」的那个旧会话，本来就该丢。
    """
    root = _profile_root()
    if not os.path.isdir(root):
        return
    try:
        cur = int(settings.get('webprofile_gen') or 0)
    except (TypeError, ValueError):
        cur = 0
    alive = {'g%d' % g for g in range(max(0, cur - keep + 1), cur + 1)}
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        if name in alive:
            continue
        if name.startswith('g') and name[1:].isdigit():
            _rmtree_quiet(os.path.join(root, name))
        else:
            # 扁平布局留下的文件，直接删
            path = os.path.join(root, name)
            try:
                if os.path.isdir(path):
                    _rmtree_quiet(path)
                else:
                    os.remove(path)
            except OSError:
                pass


def _is_platform_url(qurl):
    """只认教参/清华域名，避免别的站点带个 token= 就被当成凭证。"""
    try:
        host = (qurl.host() or '').lower()
    except AttributeError:
        return False
    return host.endswith('tsinghua.edu.cn')


# ====================================================================== 分段控件
class Segmented(QWidget):
    """两段式切换（企业应用登录页常见的那种）。自绘，带滑动指示器。"""

    changed = pyqtSignal(int)

    PAD = 4
    GAP = 4

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self._items = list(items)
        self._index = 0
        self._pos = 0.0                 # 指示器位置，单位是「第几段」
        self._hover = -1
        self.setFixedHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFont(T.ui_font(T.FS_BODY, 600))
        self._anim = QPropertyAnimation(self, b'pos', self)
        self._anim.setDuration(T.motion.DUR_HOVER if T.motion.ENABLED else 0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # -------------------------------------------------- 动画属性
    def get_pos(self):
        return self._pos

    def set_pos(self, v):
        self._pos = float(v)
        self.update()

    # 指示器位置。必须是类级属性，QPropertyAnimation 才能驱动它
    pos = pyqtProperty(float, get_pos, set_pos)

    # -------------------------------------------------- 状态
    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, i, animate=True):
        i = max(0, min(len(self._items) - 1, int(i)))
        if i == self._index:
            return
        self._index = i
        if animate and T.motion.ENABLED:
            self._anim.stop()
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(float(i))
            self._anim.start()
        else:
            self.set_pos(float(i))
        self.update()

    def _seg_rects(self):
        n = max(1, len(self._items))
        w = self.width() - self.PAD * 2 - self.GAP * (n - 1)
        each = w / n
        out = []
        for i in range(n):
            x = self.PAD + i * (each + self.GAP)
            out.append(QRectF(x, self.PAD, each, self.height() - self.PAD * 2))
        return out

    # -------------------------------------------------- 交互
    def _index_at(self, x):
        rects = self._seg_rects()
        for i, r in enumerate(rects):
            if x < r.right() + self.GAP / 2:
                return i
        return len(rects) - 1

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            i = self._index_at(int(ev.position().x()))
            if i != self._index:
                self.setCurrentIndex(i)
                self.changed.emit(i)
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        i = self._index_at(int(ev.position().x()))
        if i != self._hover:
            self._hover = i
            self.update()
        super().mouseMoveEvent(ev)

    def leaveEvent(self, ev):
        self._hover = -1
        self.update()
        super().leaveEvent(ev)

    # -------------------------------------------------- 绘制
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 轨道
        track = QPainterPath()
        track.addRoundedRect(QRectF(0, 0, self.width(), self.height()),
                             T.R_MD, T.R_MD)
        p.fillPath(track, T.qc(T.BG_SOFT))

        rects = self._seg_rects()
        if not rects:
            return

        # 指示器：在第 i 段和第 i+1 段之间插值
        lo = int(self._pos)
        hi = min(lo + 1, len(rects) - 1)
        frac = self._pos - lo
        a, b = rects[lo], rects[hi]
        ind = QRectF(a.x() + (b.x() - a.x()) * frac, a.y(),
                     a.width() + (b.width() - a.width()) * frac, a.height())

        pill = QPainterPath()
        pill.addRoundedRect(ind, T.R_MD - 2, T.R_MD - 2)
        p.fillPath(pill, T.qc(T.CARD))
        p.setPen(QPen(T.qc(T.BORDER_SOFT), 1))
        p.drawPath(pill)

        for i, (label, r) in enumerate(zip(self._items, rects)):
            active = i == self._index
            p.setFont(T.ui_font(T.FS_BODY, 600 if active else 400))
            col = T.TEXT if active else (
                T.TEXT_DIM if i == self._hover else T.TEXT_FAINT)
            p.setPen(T.qc(col))
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), label)
        p.end()


# ====================================================================== 左栏品牌
class BrandPanel(QWidget):
    """左栏：天幕 + 品牌与卖点。纯装饰，不承载功能。"""

    BULLETS = (
        ('批量排队', '一次粘多条链接，一本一本下完'),
        ('书库管理', '封面、书名、页数，随时找回来'),
        ('Token 续期', '失效自动重新获取，不用重来'),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        # 左栏单独出一张竖构图主视觉，而不是复用侧边栏那张方形底图：方形图
        # 铺到 537x860 上会被裁掉大半，构图散成一片几乎看不见内容的暗色。
        # 压暗也换成侧向的 —— 文字都在左边，右边留着让画露出来；均匀压到
        # 「字读得清」，画就糊没了。见 tools/make_hero.py。
        self.sky = SkyBackdrop('violet', self, sky_height=None,
                               art='login_hero', scrim=0.30, side_scrim=0.78)
        self.overlay = QWidget(self)
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        box = QVBoxLayout(self.overlay)
        # 右边留 150 而不是 40：文字列必须锁在左边那片压暗区里。留 40 的话
        # 一行字最长能铺到 0.93w，那边已经是没压暗的亮画，字就读不清了。
        # tools/check_backdrop_contrast.py 会按真实字形把这件事量出来。
        box.setContentsMargins(46, 54, 150, 40)
        box.setSpacing(0)

        mark = W.Label('清华教参下载器', T.FS_BRAND_TITLE, 700, T.ON_DARK,
                       parent=self.overlay)
        box.addWidget(mark)
        box.addSpacing(10)

        ver = W.Label('电子教材 PDF 下载工具', T.FS_BRAND_SUB, 400,
                      T.ON_DARK_MUTED, parent=self.overlay, wrap=True)
        box.addWidget(ver)
        box.addStretch(1)

        for head, desc in self.BULLETS:
            row = QWidget(self.overlay)
            row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(11)
            dot = W.Dot('#FFFFFF', 5, row)
            dot.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            rl.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            rl.addWidget(self._bullet(head, desc, row), 1)
            box.addWidget(row)
            box.addSpacing(16)

        box.addStretch(1)
        foot = W.Label('仅供个人学习研究使用 · 请遵守版权规定',
                       T.FS_META, 400, T.ON_DARK_FAINT, parent=self.overlay,
                       wrap=True)
        box.addWidget(foot)

    def _bullet(self, head, desc, parent):
        w = QWidget(parent)
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        h = W.Label(head, T.FS_SECTION, 600, T.ON_DARK, parent=w)
        # 说明文字允许折行 —— 否则这些文案会给左栏定一个很大的内容最小宽度，
        # 布局就再也压不下来了，窄窗口下会把右边的登录卡片挤出去
        d = W.Label(desc, T.FS_META, 400, T.ON_DARK_DIM, parent=w, wrap=True)
        v.addWidget(h)
        v.addWidget(d)
        return w

    def set_animated(self, on, animate=True):
        """
        开关天幕的呼吸动画。右边挂着内嵌浏览器时必须关掉 —— 理由见
        LoginScreen.set_mode 里那段注释（装饰和浏览器抢主线程）。
        """
        self.sky.set_animated(on and T.motion.ENABLED)

    def resizeEvent(self, _ev):
        self.sky.setGeometry(0, 0, self.width(), self.height())
        self.overlay.setGeometry(0, 0, self.width(), self.height())
        self.sky.lower()


# ====================================================================== Token 模式
class TokenPanel(QWidget):
    """直接粘贴 Token。本地解析有效期，失效时提醒更换。"""

    submit = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)

        box.addWidget(_hug(W.Label('粘贴 Token', T.FS_SECTION, 600, T.TEXT,
                                   parent=self)))

        self.edit = QPlainTextEdit(self)
        self.edit.setPlaceholderText(
            'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...\n'
            '也可以直接粘整条 index?token=xxx 的地址')
        self.edit.setFont(T.ui_font(T.FS_BODY, 400, mono=True))
        self.edit.setFixedHeight(96)
        self.edit.setTabChangesFocus(True)
        self.edit.setStyleSheet(
            'QPlainTextEdit { background: %s; border: 1px solid %s;'
            ' border-radius: %dpx; padding: 10px 12px; color: %s;'
            ' selection-background-color: %s; }'
            % (T.BG_SOFT, T.BORDER, T.R_IN, T.TEXT, T.PRIMARY_LIGHT))
        self.edit.textChanged.connect(self._on_text)
        box.addWidget(self.edit)

        self.status = W.Label('', T.FS_META, 400, T.TEXT_DIM, parent=self)
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(34)
        box.addWidget(_hug(self.status))
        # 多余高度留给状态行和按钮之间：上半部分是「输入」，下半部分是
        # 「动作」，卡片被撑高时这么分比在底部堆一大块空白自然
        box.addStretch(1)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.btn_paste = W.PillButton('从剪贴板粘贴', 'secondary', self)
        self.btn_paste.clicked.connect(self._paste)
        self.btn_go = W.PillButton('验证并登录', 'primary', self)
        self.btn_go.clicked.connect(self._submit)
        row.addWidget(self.btn_paste)
        row.addStretch(1)
        row.addWidget(self.btn_go)
        box.addLayout(row)

        hint = W.Label(
            '怎么拿到 Token：在浏览器打开教参平台并登录，按 F12 → Network，'
            '找到登录后第一条 index?token=xxx 的请求，等号后面的就是 Token。',
            T.FS_META, 400, T.TEXT_FAINT, parent=self)
        hint.setWordWrap(True)
        box.addWidget(_hug(hint))

    # -------------------------------------------------- 行为
    def _paste(self):
        from PyQt6.QtWidgets import QApplication
        text = QApplication.clipboard().text() or ''
        got = tokeninfo.extract_token(text)
        self.edit.setPlainText(got or text.strip())
        if got:
            self.status.setText('已从剪贴板识别到 Token。')
            self.status.setStyleSheet('color: %s;' % T.ACCENT)

    def _on_text(self):
        self._refresh_status()

    def _refresh_status(self, now=None):
        raw = self.edit.toPlainText().strip()
        if not raw:
            self.status.setText('')
            return
        tok = tokeninfo.extract_token(raw)
        if not tok:
            self.status.setText('这看起来不是 Token，检查一下是不是粘全了。')
            self.status.setStyleSheet('color: %s;' % T.DANGER)
            return
        info = tokeninfo.TokenInfo(tok)
        state = info.state(now)
        colour = {'expired': T.DANGER, 'soon': T.WARN,
                  'valid': T.ACCENT, 'unknown': T.TEXT_DIM}[state]
        if state == 'expired':
            self.status.setText('这个 Token 已经过期了，请重新获取一个。')
        else:
            self.status.setText(info.describe(now))
        self.status.setStyleSheet('color: %s;' % colour)

    def _submit(self):
        tok = tokeninfo.extract_token(self.edit.toPlainText())
        if not tok:
            self.status.setText('请先粘贴 Token。')
            self.status.setStyleSheet('color: %s;' % T.DANGER)
            return
        self.submit.emit(tok)

    def token(self):
        return tokeninfo.extract_token(self.edit.toPlainText())

    def set_token(self, tok):
        self.edit.setPlainText(tok or '')
        self._refresh_status()

    def refresh_expiry(self):
        self._refresh_status()


# ====================================================================== SSO 模式
class _PlatformPage(object):
    """
    给 QWebEnginePage 用的两个覆写，延迟到真正 import 之后再生效。

    为什么要覆写而不是 connect：
      * certificateError 在 Qt6 里是**虚函数**，不是信号，connect 不上去
        （connect 会抛 AttributeError，被 try/except 吞掉，等于没处理）；
      * createWindow 同理，往实例上挂一个 Python 属性覆盖不了 C++ 虚函数。
    这两条以前是 Qt5 的信号/属性写法，Qt6 改了，必须换成子类覆写。

    教参平台的证书链在部分网络环境下 Chromium 不认，而原来的命令行实现
    是直接 verify=False 的；这里只对清华域名放行，别的一律拒绝。
    弹窗也一律收在当前视图里打开，免得 SSO 流程弹出一堆没人管的窗口。
    """

    @staticmethod
    def build():
        from PyQt6.QtWebEngineCore import QWebEnginePage

        class PlatformPage(QWebEnginePage):
            def certificateError(self, error):        # noqa: N802
                try:
                    if _is_platform_url(error.url()):
                        error.acceptCertificate()
                        return True
                except Exception:                                    # noqa: BLE001
                    pass
                return super().certificateError(error)

            def createWindow(self, wtype):            # noqa: N802
                return self

        return PlatformPage


class SsoPanel(QWidget):
    """
    统一身份认证：内嵌浏览器。

    浏览器是按需创建的 —— 只用 Token 模式的用户不该为一个 Chromium 付启动成本，
    测试环境里也不该被它拖慢。
    """

    captured = pyqtSignal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._view = None
        self._profile = None
        self._loaded_once = False
        self._loading = False
        self._captured = False
        self._last_token = ''
        # 退出登录后、新会话的第一个页面加载完之前，忽略截到的 Token。
        # 否则旧会话残留的那次跳转会把刚清掉的 Token 又抓回来，用户看到
        # 的就是「点了退出登录，结果还是登录状态」。
        self._suppress_capture = False

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(_hug(W.Label('清华统一身份认证', T.FS_SECTION, 600, T.TEXT,
                                    parent=self)))
        head.addStretch(1)
        self.btn_reload = W.PillButton('重新加载', 'ghost', self, small=True)
        self.btn_reload.clicked.connect(lambda: self._navigate(force=True))
        head.addWidget(self.btn_reload)
        box.addLayout(head)

        self.host = QWidget(self)
        # 同样用 #id 选择器：'QWidget { }' 会把描边和圆角也刷到里面的
        # 浏览器视图和占位文案上
        self.host.setObjectName('ssoHost')
        self.host.setStyleSheet(
            '#ssoHost { background: %s; border: 1px solid %s;'
            ' border-radius: %dpx; }' % (T.BG_SOFT, T.BORDER, T.R_IN))
        self.host.setMinimumHeight(360)
        self.host.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Expanding)
        hv = QVBoxLayout(self.host)
        hv.setContentsMargins(1, 1, 1, 1)
        hv.setSpacing(0)
        self._host_box = hv

        self.placeholder = W.Label(
            '正在准备登录窗口…', T.FS_BODY, 400, T.TEXT_DIM, parent=self.host)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        hv.addWidget(self.placeholder)
        box.addWidget(self.host, 1)

        self.status = W.Label('', T.FS_META, 400, T.TEXT_DIM, parent=self)
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(34)
        box.addWidget(_hug(self.status))

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(10)
        self.btn_browser = W.PillButton('用系统浏览器打开', 'ghost', self)
        self.btn_browser.clicked.connect(self._open_system_browser)
        foot.addWidget(self.btn_browser)
        foot.addStretch(1)
        self.btn_enter = W.PillButton('我已登录，继续', 'primary', self)
        self.btn_enter.clicked.connect(self._manual_check)
        foot.addWidget(self.btn_enter)
        box.addLayout(foot)

        self.set_status('登录窗口准备中…')

    # -------------------------------------------------- 状态文案
    def set_status(self, text, tone='dim'):
        colour = {'dim': T.TEXT_DIM, 'ok': T.ACCENT,
                  'warn': T.WARN, 'err': T.DANGER}[tone]
        self.status.setText(text)
        self.status.setStyleSheet('color: %s;' % colour)

    # -------------------------------------------------- 创建浏览器
    def ensure_web(self):
        """按需创建 QWebEngineView。返回是否可用。"""
        if self._view is not None:
            return True
        if os.environ.get(NO_WEBENGINE_ENV):
            self.placeholder.setText(
                '内嵌浏览器已按环境变量 %s 关闭。\n'
                '请改用「直接填 Token」登录。' % NO_WEBENGINE_ENV)
            self.set_status('内嵌浏览器已关闭，请改用 Token 登录。', 'warn')
            self.btn_enter.setEnabled(False)
            self.btn_reload.setEnabled(False)
            return False
        try:
            from PyQt6.QtWebEngineCore import (QWebEngineProfile,
                                               QWebEngineSettings)
            from PyQt6.QtWebEngineWidgets import QWebEngineView
        except ImportError as e:                                     # noqa: BLE001
            self.placeholder.setText(
                '这台机器上没有可用的内嵌浏览器组件，\n'
                '请改用「直接填 Token」登录。\n\n(%s)' % e)
            self.set_status('内嵌浏览器不可用，请改用 Token 登录。', 'err')
            self.btn_enter.setEnabled(False)
            return False

        # 持久化 profile：让「信任此设备」留到下次，Token 失效时才能真正自动续期。
        #
        # 目录名带一个「代」号：正常启动一直用同一代，所以登录态跨启动保留；
        # 用户主动退出登录时把代号 +1，下次就用一个全新的空目录 —— 见
        # reset_session 里为什么必须这么做。
        prof_dir = _profile_dir(self.settings)
        try:
            os.makedirs(prof_dir, exist_ok=True)
        except OSError:
            pass
        prof = QWebEngineProfile('thu-sso', self)
        try:
            prof.setPersistentStoragePath(prof_dir)
            prof.setCachePath(os.path.join(prof_dir, 'cache'))
            prof.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        except Exception:                                            # noqa: BLE001
            pass
        self._profile = prof

        view = QWebEngineView(self.host)
        # 用子类覆写证书处理和弹窗，见 _PlatformPage 的说明
        try:
            page = _PlatformPage.build()(prof, view)
            view.setPage(page)
        except Exception:                                            # noqa: BLE001
            pass
        try:
            view.page().setBackgroundColor(QColor(T.BG_SOFT))
        except Exception:                                            # noqa: BLE001
            pass

        view.urlChanged.connect(self._on_url)
        view.loadStarted.connect(self._on_load_started)
        view.loadFinished.connect(self._on_load_finished)

        settings = view.settings()
        for attr in ('JavascriptEnabled', 'LocalStorageEnabled',
                     'PluginsEnabled', 'JavascriptCanOpenWindows'):
            try:
                settings.setAttribute(
                    getattr(QWebEngineSettings.WebAttribute, attr), True)
            except Exception:                                        # noqa: BLE001
                pass

        self._host_box.addWidget(view)
        self.placeholder.hide()
        self._view = view
        return True

    def _on_load_started(self):
        self._loading = True
        self.set_status('正在载入…')

    def _on_load_finished(self, ok):
        self._loading = False
        # 新会话的第一个页面落地了，从这一刻起截 Token 才作数
        self._suppress_capture = False
        if not ok:
            self.set_status('页面加载失败，检查一下网络，或点「重新加载」。', 'err')
        elif self._captured:
            pass          # 已经拿到 Token 了，别用「请完成登录」把它盖掉
        else:
            self.set_status('请在窗口中完成登录（含双因子认证）。')

    # -------------------------------------------------- 截 Token
    def _on_url(self, qurl):
        if self._suppress_capture:
            # 刚退出登录，旧会话残留的跳转不该把 Token 又抓回来
            return
        if not _is_platform_url(qurl):
            return
        text = qurl.toString()
        if 'token=' not in text:
            return
        tok = tokeninfo.extract_token(text)
        if not tok:
            return
        # 一次导航会触发多次 urlChanged（请求地址 + 落地地址 + 重定向），
        # 不去重的话同一个 Token 会被反复上报，登录成功会被报好几遍
        if tok == self._last_token:
            return
        self._last_token = tok
        self._captured = True
        self.set_status('已获取 Token，正在登录…', 'ok')
        self.captured.emit(tok)

    def _manual_check(self):
        """用户说「我登好了」——主动从当前地址栏再找一次 Token。"""
        if self._view is None:
            return
        url = self._view.url().toString()
        tok = tokeninfo.extract_token(url)
        if tok and 'token=' in url:
            self.captured.emit(tok)
        else:
            self.set_status(
                '地址栏里还没有 Token。请确认已经登录成功、'
                '页面停在教参平台首页。', 'warn')
            self._navigate(force=True)

    # -------------------------------------------------- 导航
    def _navigate(self, force=False):
        if not self.ensure_web():
            return
        if self._loaded_once and not force:
            return
        self._loaded_once = True
        self._view.setUrl(QUrl(PLATFORM_HOME))

    def start(self, force=False):
        """进入 SSO 模式时调用。"""
        self._navigate(force=force)

    def _open_system_browser(self):
        import webbrowser
        try:
            webbrowser.open(PLATFORM_HOME)
            self.set_status(
                '已在系统浏览器打开教参平台。登录后把地址栏里 '
                'index?token=xxx 整条复制回来，切到「直接填 Token」粘贴即可。',
                'dim')
        except Exception as e:                                       # noqa: BLE001
            self.set_status('打不开系统浏览器：%s' % e, 'err')

    def reset_session(self):
        """
        退出登录：把内嵌浏览器的登录态彻底清掉。

        为什么不能只调 deleteAllCookies()：
          - 它是异步的，紧接着就导航的话，页面很可能还是带着旧会话加载出来，
            用户看到的就是「点了退出登录，结果还是已登录的界面」；
          - 平台的登录态不一定只在 cookie 里，localStorage / 缓存里都可能有。

        所以这里直接换一代 profile 目录：新的那代是空的，登录态必然是清的。
        旧的目录尽力删掉（文件可能还被 Chromium 占着，删不掉也无所谓，
        下次启动会再清一遍）。
        """
        self._suppress_capture = True
        self._captured = False
        self._last_token = ''

        # 尽力清一下当前 profile，让文件句柄早点松开，好删目录
        if self._profile is not None:
            try:
                self._profile.cookieStore().deleteAllCookies()
                self._profile.clearHttpCache()
            except Exception:                                        # noqa: BLE001
                pass

        # 拆掉浏览器和 profile —— 下次 ensure_web() 会用新目录重建
        old = _profile_dir(self.settings)
        if self._view is not None:
            try:
                self._host_box.removeWidget(self._view)
                self._view.setPage(None)
                self._view.setParent(None)
                self._view.deleteLater()
            except Exception:                                        # noqa: BLE001
                pass
            self._view = None
        if self._profile is not None:
            try:
                self._profile.deleteLater()
            except Exception:                                        # noqa: BLE001
                pass
            self._profile = None

        # 换代：下一代会是一个全新的空目录
        try:
            gen = int(self.settings.get('webprofile_gen') or 0) + 1
            self.settings.update(webprofile_gen=gen)
            self.settings.save()
        except Exception:                                            # noqa: BLE001
            pass

        _rmtree_quiet(old)
        _rmtree_quiet(_profile_dir(self.settings))

        self._loaded_once = False
        self._host_box.addWidget(self.placeholder)
        self.placeholder.setText('已退出登录，正在准备登录窗口…')
        self.placeholder.show()
        self.btn_enter.setEnabled(True)
        self.btn_reload.setEnabled(True)
        self.set_status('已退出登录。请在窗口中重新登录。')
        if self._view is not None:
            self._view.setUrl(QUrl('about:blank'))
        self._loaded_once = False
        # 也得把去重状态清掉，否则退出后重新登录，同一个 Token 会被
        # 当成「上报过了」而不再上报
        self._captured = False
        self._last_token = ''


# ====================================================================== 登录页
class LoginScreen(QWidget):
    """
    整个登录页。登录成功后发 logged_in(token, source)。
    source 是 'sso' 或 'token'，主界面据此决定 Token 失效率后怎么处理。
    """

    logged_in = pyqtSignal(str, str)
    mode_changed = pyqtSignal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        # 退出登录会攒下旧的 Chromium profile 目录，启动时清一清
        _cleanup_old_profiles(settings)
        self.setAutoFillBackground(True)
        self.setStyleSheet('LoginScreen { background: %s; }' % T.BG)
        self._mode = settings.get('login_mode') or 'sso'
        self._shown = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.brand = BrandPanel(self)
        # 用拉伸比而不是 setFixedWidth：给子控件设固定宽度会把它算进父窗口的
        # 最小宽度里，窗口就再也缩不回去了（实测 resize(980) 会被顶到 1083）。
        self.brand.setMinimumWidth(BRAND_W_MIN)
        self.brand.setMaximumWidth(BRAND_W_MAX)
        root.addWidget(self.brand, 42)

        right = QWidget(self)
        right.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 必须用 #id 选择器，不能用 'QWidget { ... }'：后者会连子孙控件一起
        # 刷成这个底色，卡片内部就被染成页面灰，白底卡片直接废掉
        right.setObjectName('loginBg')
        right.setStyleSheet('#loginBg { background: %s; }' % T.BG)
        rbox = QHBoxLayout(right)
        rbox.setContentsMargins(SIDE_PAD, 32, SIDE_PAD, 32)
        rbox.setSpacing(0)
        # 卡片要给拉伸权重，否则它只拿 sizeHint —— 窗口最大化的时候卡片反而
        # 缩在最小宽度，里面那个内嵌浏览器只剩 280 逻辑像素宽，整站被挤成
        # 手机版。给它权重以后它会一直长到 CARD_MAX_W，多出来的给两边。
        rbox.addStretch(1)
        rbox.addWidget(self._build_form(right), 8)
        rbox.addStretch(1)
        root.addWidget(right, 58)

        self.set_mode(self._mode, animate=False, start=False)

    # -------------------------------------------------- 表单
    def _build_form(self, parent):
        # 登录卡片是全窗口的视觉中心，用更强的一档投影。
        #
        # painted_shadow=True 是必须的：这张卡片里装着 QWebEngineView，
        # 挂 QGraphicsEffect 会让浏览器每一帧都被迫走离屏重绘（见
        # widgets.render_shadow 的说明）。自绘的投影会往本体外多占一圈，
        # 所以下面把宽度上限加上投影边距，保证「看得见的卡片」还是原来那么宽。
        card = W.Card(parent, padding=(30, 28, 30, 26), gap=0,
                      radius=T.R_CARD, shadow='raised', painted_shadow=True)
        ml, _mt, mr, _mb = card.shadow_margins()
        card.setMinimumWidth(CARD_MIN_W + ml + mr)
        card.setMaximumWidth(CARD_MAX_W + ml + mr)
        self.card = card

        v = card.box

        head = W.Label('登录', T.FS_FORM_TITLE, 700, T.TEXT, parent=card)
        v.addWidget(_hug(head))
        v.addSpacing(6)
        sub = W.Label('使用清华统一身份认证，或直接粘贴 Token',
                      T.FS_PAGE_SUB, 400, T.TEXT_DIM, parent=card)
        v.addWidget(_hug(sub))
        v.addSpacing(20)

        self.tabs = Segmented(['统一身份认证', '直接填 Token'], card)
        self.tabs.changed.connect(lambda i: self._on_tab(i))
        v.addWidget(_hug(self.tabs))
        v.addSpacing(20)

        self.stack = QStackedWidget(card)
        self.sso = SsoPanel(self.settings, self.stack)
        self.token = TokenPanel(self.stack)
        self.stack.addWidget(self.sso)
        self.stack.addWidget(self.token)
        v.addWidget(self.stack)

        self.sso.captured.connect(lambda t: self._finish(t, 'sso'))
        self.token.submit.connect(lambda t: self._finish(t, 'token'))
        return card

    # -------------------------------------------------- 模式
    def _on_tab(self, i):
        self.set_mode('sso' if i == 0 else 'token', animate=True)
        self.mode_changed.emit(self._mode)

    def _update_sky_animation(self):
        """
        天幕动画只在「登录页真的可见 且 右边没挂浏览器」时才跑。

        为什么必须停下来 —— 实测数据：这块天幕高频重绘整块品牌面板，加上 Qt
        为它做的整窗重合成，会吃掉主线程 50%~74% 的 CPU（天幕自绘只占 21%，
        其余全是重合成开销）。浏览器渲染进程的消息和鼠标输入事件排在同一条
        主线程后面，被动画挤到只剩三成时间 —— 用户感觉就是「点一下输入框
        要等 3 秒」。装饰不该和用户正在打字的浏览器抢 CPU。

        另外两种情况也必须停：
          - 登录页已经切走（Token 还有效时直接进主界面），不可见的动画纯属
            白烧 CPU，而且用户根本看不到；
          - 关掉后画面依然是完整的静态天幕 —— 底色、星点、弧线都来自缓存位图，
            极光带也会以当前相位画一次，不是半成品。
        """
        visible = self.isVisible()
        want = visible and self._mode != 'sso'
        self.brand.set_animated(want)

    def set_mode(self, name, animate=True, start=True):
        name = 'token' if name == 'token' else 'sso'
        self._mode = name
        i = 0 if name == 'sso' else 1
        self.tabs.setCurrentIndex(i, animate=animate)
        self.stack.setCurrentIndex(i)
        # 内嵌浏览器在跑的时候把左侧天幕动画停掉。理由见 _update_sky_animation
        self._update_sky_animation()
        if name == 'sso':
            # start=False 用在构造阶段：那时候窗口还没显示，没必要先把
            # Chromium 拉起来（也免得测试环境里白等它初始化）
            if start:
                self.sso.start()
        else:
            self.token.refresh_expiry()

    def showEvent(self, ev):
        """第一次显示时才真正去加载统一身份认证页。"""
        super().showEvent(ev)
        self._update_sky_animation()
        if not self._shown:
            self._shown = True
            if self._mode == 'sso':
                self.sso.start()

    def hideEvent(self, ev):
        # 切到主界面后登录页不可见了，天幕动画没有继续跑的理由
        super().hideEvent(ev)
        self._update_sky_animation()

    def mode(self):
        return self._mode

    # -------------------------------------------------- 登录
    def prefill(self, token):
        self.token.set_token(token or '')

    def _finish(self, token, source):
        token = (token or '').strip()
        if not token:
            return
        self.logged_in.emit(token, source)

    def reset_busy(self):
        self.sso.set_status('请在窗口中完成登录（含双因子认证）。')


def main():                                                          # pragma: no cover
    """单独预览登录页：python -m xk_app.app.gui.login"""
    import sys
    from PyQt6.QtWidgets import QApplication
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    T.install_app_font(app)
    scr = LoginScreen(store.Settings())
    scr.resize(1180, 760)
    scr.show()
    return app.exec()


if __name__ == '__main__':                                           # pragma: no cover
    raise SystemExit(main())
