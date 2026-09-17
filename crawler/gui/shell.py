# coding:utf-8
"""
主窗口：侧边栏 + 工作区。

与原设计稿最大的结构差别：去掉了「顶部天幕 + 居中导航胶囊 + 五步导轨」。
那套结构表达的是「你正处在一次性流程的第几步」，而下载器没有这个语义 ——
用户是在「排队 → 翻书库 → 改设置」之间来回切。所以导航改成常驻侧边栏，
天幕收进侧边栏顶部当品牌区，纵向空间基本全留给内容。
"""
import os
import subprocess
import sys
import time

from PyQt6.QtCore import QEvent, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QMessageBox,
                             QStackedWidget, QVBoxLayout, QWidget)

from ..core import store, tokeninfo
from ..core.queue import QueueManager
from ..core.worker import TaskRunner, CredCheckWorker
from . import theme as T
from . import widgets as W
from .login import LoginScreen
from .sidebar import Sidebar
from .titlebar import TitleBar
from .views.help_view import HelpView
from .views.library_view import LibraryView
from .views.queue_view import QueueView
from .views.settings_view import SettingsView

# 从 theme 取，保证标题栏 / 侧边栏 / 登录页 / 安装包用的是同一个名字
APP_NAME = T.APP_NAME

VIEW_ORDER = ['queue', 'library', 'settings', 'help']
VIEW_TITLES = {'queue': '下载队列', 'library': '书库',
               'settings': '设置', 'help': '使用说明'}

# nativeEvent 里兜住的异常。正常永远是空的；非空说明命中测试出问题了，
# 自检会把它报出来（静默吞掉异常是最难查的那类 bug）。
_NATIVE_ERRORS = []


def app_base_dir():
    """
    程序「自己的目录」：打包后是 exe 所在目录，开发态是仓库根。

    开发态要从 crawler/gui/shell.py 往上数三层才到仓库根（gui → crawler → 仓库根）。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def resource_path(*parts):
    """
    取打包进来的资源（assets/ 下的图标、底图、封面）。

    冻结态：资源在 sys._MEIPASS 下（spec 里 datas 把 crawler/assets 映射成 assets）。
    开发态：从本文件往上两层到仓库根，再拼 parts —— 即 crawler/gui/shell.py
    → crawler/ → 仓库根，所以是 crawler/assets/...。
    """
    base = getattr(sys, '_MEIPASS', None)
    if base:
        return os.path.join(base, *parts)
    here = os.path.abspath(__file__)
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(repo_root, 'crawler', *parts)


def _open_path(path):
    """在资源管理器里定位到文件，或打开目录。失败返回 False。"""
    if not path or not os.path.exists(path):
        return False
    try:
        if os.path.isdir(path):
            os.startfile(path)                                   # noqa: S606
        else:
            subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
        return True
    except Exception:                                            # noqa: BLE001
        try:
            os.startfile(os.path.dirname(path))                  # noqa: S606
            return True
        except Exception:                                        # noqa: BLE001
            return False


def _open_file(path):
    if not path or not os.path.exists(path):
        return False
    try:
        os.startfile(path)                                       # noqa: S606
        return True
    except Exception:                                            # noqa: BLE001
        return False


class MainWindow(QWidget):
    # 下载跑在一个普通 Python 线程上（QueueManager._run），而 Qt 控件只能
    # 在 GUI 线程碰 —— QPixmap 更是明确不线程安全。以前 QueueManager 的回调
    # 直接指向下面的界面方法，于是 set_jobs / set_counts / _refresh_library
    # 全都在下载线程里执行，界面卡死再崩。这里统一改成信号：下载线程只负责
    # emit，Qt 自己排队投递到 GUI 线程再执行。
    # _queue_dirty 是高频的（每下一页一次），所以接一个合并定时器，免得一次
    # 下载往事件队列里灌几千个事件。
    _queue_dirty = pyqtSignal()
    _library_dirty = pyqtSignal()
    _log_line = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(T.WIN_W, T.WIN_H)
        self.setMinimumSize(980, 660)

        # 无边框 + 自绘标题栏。系统的白底标题栏和这套配色放一起太违和。
        # 去掉系统边框之后，拖动 / 缩放 / 贴边由 nativeEvent 里的
        # WM_NCHITTEST 交回给系统处理（见 titlebar.hit_test），
        # 所以手感和资源管理器一致，不是「自己搬窗口」那种廉价实现。
        self.setWindowFlags(Qt.WindowType.Window
                            | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        # 系统是否真的把四角剪圆了（Win11 才行）。决定描边画圆角还是直角。
        self._rounded = False

        icon = resource_path('assets', 'app.ico')
        if os.path.exists(icon):
            from PyQt6.QtGui import QIcon
            self.setWindowIcon(QIcon(icon))

        # ---- 数据
        self.settings = store.Settings()
        self.library = store.Library()
        self.queue = QueueManager(
            self.settings, self.library,
            on_change=self._emit_queue_dirty,
            on_log=self._emit_log,
            on_library_changed=self._emit_library_dirty)
        # 必须显式写 QueuedConnection：默认的 AutoConnection 在「发送者与接收者
        # 同属一个线程」时会退化成直连，那就又回到跨线程碰控件的老路了。
        self._queue_dirty.connect(self._on_queue_dirty,
                                  Qt.ConnectionType.QueuedConnection)
        self._library_dirty.connect(self._on_library_dirty,
                                    Qt.ConnectionType.QueuedConnection)
        self._log_line.connect(self._log, Qt.ConnectionType.QueuedConnection)
        # 高频信号合并：60ms 内的多次变化只刷一次界面
        self._queue_coalesce = QTimer(self)
        self._queue_coalesce.setSingleShot(True)
        self._queue_coalesce.setInterval(60)
        self._queue_coalesce.timeout.connect(self._queue_changed)
        self._runner = None
        self._verify_runner = None
        self._view = 'queue'
        self._expiry_handled = False
        # 「登录回来后自动接上刚才失败的书」用：见 _maybe_resume
        self._resume_pending = False
        self._resume_count = 0
        # 侧边栏那行「还剩多久」要自己走字，不能只在切页面时才更新
        self._token_timer = QTimer(self)
        self._token_timer.setInterval(30 * 1000)
        self._token_timer.timeout.connect(self._sync_token_chip)

        self._build()
        self._wire()

        self.settings_view.load(self.settings)
        self._sync_sidebar()
        self._refresh_library(import_existing=True)
        self._queue_changed()

        # 首次启动直接落在队列页；如果书库里有书但队列空着，说明是老用户，
        # 那也不改，避免「上次看哪这次还看哪」这种猜测
        self.goto('queue', animate=False)

    # ================================================================ 构建
    def _build(self):
        # 最外层是一个两页的堆栈：0 = 登录页，1 = 主界面。
        # 登录成功后整页换掉，而不是把登录做成一个对话框 —— 企业应用
        # 都是这个形态，而且这样 Token 失效时可以原样退回去重登。
        #
        # 四周留 1px 给窗口描边（paintEvent 里画）。没有这条线，浅色桌面上
        # 窗口边界会糊掉，看起来就是个没做完的东西。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        self.titlebar = TitleBar(self)
        outer.addWidget(self.titlebar)

        self.root_stack = QStackedWidget(self)
        outer.addWidget(self.root_stack, 1)

        self.login = LoginScreen(self.settings, self.root_stack)
        self.root_stack.addWidget(self.login)

        shell = QWidget(self.root_stack)
        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar(shell)
        root.addWidget(self.sidebar)

        right = QWidget(shell)
        right.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        right.setStyleSheet('QWidget { background: %s; }' % T.BG)
        right_box = QHBoxLayout(right)
        right_box.setContentsMargins(0, 0, 0, 0)
        right_box.setSpacing(0)

        self.stack = QStackedWidget(right)
        self.queue_view = QueueView()
        self.library_view = LibraryView()
        self.settings_view = SettingsView()
        self.help_view = HelpView()
        self.views = {
            'queue': self.queue_view,
            'library': self.library_view,
            'settings': self.settings_view,
            'help': self.help_view,
        }
        for key in VIEW_ORDER:
            self.stack.addWidget(self.views[key])
        right_box.addWidget(self.stack)
        root.addWidget(right, 1)
        self.root_stack.addWidget(shell)
        # 默认停在主界面，而不是登录页。决定权交给 start()：真实启动路径会
        # 调它，没登录就切到登录页；直接构造 MainWindow 的测试和工具则照旧
        # 看到主界面，不会莫名其妙被登录页挡住。
        self.root_stack.setCurrentIndex(1)

    def _wire(self):
        self.sidebar.nav.connect(self.goto)
        self.sidebar.status_chip.clicked.connect(lambda: self.goto('settings'))
        self.sidebar.logout_requested.connect(self._logout)
        self.login.logged_in.connect(self._on_logged_in)
        self.login.mode_changed.connect(self._on_login_mode_changed)

        qv = self.queue_view
        qv.add_requested.connect(self._add_urls)
        qv.start_requested.connect(self._start_queue)
        qv.stop_requested.connect(self._stop_queue)
        qv.retry_requested.connect(self._retry_failed)
        qv.clear_requested.connect(self._clear_finished)
        qv.open_folder.connect(self._open_job_folder)
        qv.remove_job.connect(self._remove_job)

        lv = self.library_view
        lv.open_pdf.connect(lambda rec: self._toast_open(_open_file(rec.get('pdf_path')),
                                                         '打不开这个 PDF，文件可能已被移动。'))
        lv.open_folder.connect(self._open_library_folder)
        lv.remove.connect(self._remove_record)
        lv.refresh.connect(lambda: self._refresh_library(import_existing=True))

        sv = self.settings_view
        sv.save_requested.connect(self._save_settings)
        sv.verify_requested.connect(self._verify_token)
        sv.pick_dir.connect(self._pick_dir)
        sv.open_dir.connect(self._open_save_dir)
        sv.changed.connect(lambda: sv.clear_verify())

    # ================================================================ 窗口外壳
    def _apply_round_corners(self):
        """
        Win11 原生圆角。用 DWM 让系统把窗口四角剪圆，而不是开
        WA_TranslucentBackground 自己画 —— 半透明顶层窗口叠 QtWebEngine
        会拖慢合成（前面刚为这个查过一次性能），而 DWM 这条是免费的。
        Win10 上这个属性不存在，静默忽略即可。
        """
        if sys.platform != 'win32':
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2
            pref = ctypes.c_int(2)
            res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
            # 只有系统真的把四角剪圆了，我们才把描边也画成圆角。
            # 否则（Win10 上这个属性不存在）窗口本身是方的，里面却画一条
            # 圆角线，四角会露出底色方块 —— 比不圆角还难看。
            self._rounded = (res == 0)
            # 深色标题栏属性关掉，免得系统按深色主题去改我们的边框
            dark = ctypes.c_int(0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
        except Exception:                                        # noqa: BLE001
            self._rounded = False
        self.update()

    def nativeEvent(self, event_type, message):
        """
        接管 WM_NCHITTEST：把窗口拖拽 / 八方向缩放交回给系统。

        这是自绘标题栏能做「像原生一样」的关键一步。如果自己在 mouseMove
        里 move() 窗口，会丢 Aero Snap（拖到屏幕边缘吸附）、拖动掉帧、
        最大化时拖动的手感也不对。返回 HTCAPTION / HTLEFT 这些命中码之后，
        拖动、双击最大化、贴边、边缘缩放全部是系统行为。

        **这里有两个坑，都踩过了：**

        1. nativeEvent 是从 Windows 消息循环里回调进来的，PyQt 对虚函数里
           逃出去的异常的处理是直接 abort —— 表现是进程静默消失、退出码
           0xC000041D，连栈都看不到。所以异常要自己兜住。
        2. **绝对不能调 `super().nativeEvent(...)`。** 实测在这一版
           PyQt6 + Qt6 上，那个基类实现本身就会让进程 abort（同样是
           0xC000041D，而且 try/except BaseException 也拦不住，因为根本不是
           Python 异常）。不处理的消息直接返回 `(False, 0)` 就是官方语义里的
           「我没处理，交给 Qt」，效果和基类默认实现一致。
        """
        from .titlebar import nc_hit_test
        try:
            code = nc_hit_test(self, event_type, message)
        except Exception as exc:                                 # noqa: BLE001
            if len(_NATIVE_ERRORS) < 8:
                _NATIVE_ERRORS.append('%s: %s' % (type(exc).__name__, exc))
            code = None
        if code is not None:
            return True, code
        return False, 0

    def paintEvent(self, _ev):
        """
        画窗口最外圈的 1px 描边。

        没有这条线时，浅色窗口贴在浅色桌面上是没有边界的，「哪里有窗口」
        全靠猜 —— 用户说的「突兀的白边」就是这个问题的另一面。
        失焦时描边变淡，和系统窗口行为一致。
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(T.BG))       # 兜底，别露出系统白底

        col = QColor(T.WINDOW_BORDER if self.isActiveWindow()
                     else T.WINDOW_BORDER_IDLE)
        pen = QPen(col, 1)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        r = T.WINDOW_RADIUS if (self._rounded
                                and not self.isMaximized()) else 0
        # 0.5 偏移让 1px 的线落在像素中心，不然会被抗锯齿糊成 2px 灰线
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if r:
            p.drawRoundedRect(rect, r, r)
        else:
            p.drawRect(rect)
        p.end()

    def changeEvent(self, ev):
        """窗口状态 / 激活状态变了要重画描边，并同步标题栏的最大化按钮字形。"""
        et = ev.type()
        if et in (QEvent.Type.WindowStateChange,
                  QEvent.Type.ActivationChange):
            bar = getattr(self, 'titlebar', None)
            if bar is not None:
                bar.sync()
            self.update()
        super().changeEvent(ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._apply_round_corners()

    # ================================================================ 导航
    def goto(self, key, animate=True):
        """
        切页。

        animate 参数留着只是为了不改调用方签名：页面切换现在是硬切，
        不再放「粒子渐变揭示」。那个特效是装饰性的 —— 它不提示任何状态，
        只是在每次翻页时糊一层会动的雾。用户明确说看着不舒服，删掉。
        （数据入场、悬停抬起这类「说明发生了什么」的动效不受影响。）
        """
        if key not in self.views:
            return
        self._view = key
        self.stack.setCurrentWidget(self.views[key])
        self.sidebar.set_active(key)
        if key == 'library':
            self._refresh_library(import_existing=False)

    # ================================================================ 登录
    def start(self):
        """
        决定开机落在哪一页：Token 还有效就直接进主界面，否则回登录页。

        不无条件要求登录 —— 那对老用户是纯打扰。也不无条件放行 ——
        Token 过期了还让人进主界面，等下载报错才说，那是更差的体验。
        """
        # 从这里开始才让侧边栏自己走字（构造期间不启动，免得测试被打断）
        self._token_timer.start()
        token = (self.settings.token or '').strip()
        info = tokeninfo.TokenInfo(token)
        state = info.state() if token else 'expired'
        if token and state in ('valid', 'soon'):
            self._enter_shell(source=self.settings.get('login_mode') or 'token',
                              fresh=False)
            return
        # 模式以设置为准，而不是以 LoginScreen 构造时读到的那份为准 ——
        # 构造在前、改设置在后（测试里就这么用），不重新同步会停在错的模式上
        self.login.set_mode(self.settings.get('login_mode') or 'sso',
                            animate=False, start=False)
        self._show_login()
        if token:
            # 预填旧 Token，方便用户对着换
            self.login.token.set_token(token)

    def _show_login(self):
        self.root_stack.setCurrentWidget(self.login)
        # SSO 面板第一次显示时才去加载认证页；_loaded_once 保证只加载一次
        if self.login.mode() == 'sso':
            self.login.sso.start()

    def _enter_shell(self, source, fresh=True):
        self.root_stack.setCurrentIndex(1)
        self._sync_sidebar()
        if fresh:
            self.goto('queue', animate=False)
            self._log('登录成功，Token 已保存。', 'ok')

    def _on_logged_in(self, token, source):
        token = (token or '').strip()
        if not token:
            return
        self.settings.update(token=token, last_login_at=int(time.time()),
                             login_mode=source)
        self.settings.save()
        # 换了新 Token，允许以后再触发一次失效处理
        self._expiry_handled = False
        self.settings_view.load(self.settings)
        self._enter_shell(source=source, fresh=True)
        self._log('已通过%s获取 Token。' % ('统一身份认证' if source == 'sso'
                                            else '手动填写'), 'ok')
        # 登录页上可能已经排了队，回来后刷新一下
        self.queue_view.set_jobs(self.queue.snapshot())
        self._queue_changed()
        self._maybe_resume()

    def _maybe_resume(self):
        """
        这次登录如果是「Token 失效」逼出来的，登回来就把刚才失败的书接上。

        不接的话用户看到的是：下到第 5 本，Token 到期，剩下 6 本全报错，
        还得自己点一下「重试失败」。而清华教参的 Token 只活 63 分钟，
        一次批量下载跨过一整个有效期是常事，这一下点击会变得很烦人。

        计数上限：万一新拿到的 Token 也立刻被拒（账号被停用之类），
        不能没完没了地自动重试 —— 两次之后交回用户手动处理。
        """
        if not self._resume_pending:
            return
        self._resume_pending = False
        if self._resume_count >= 2:
            self._log('Token 又失效了，已停止自动重试，请检查账号状态。', 'err')
            return
        self._resume_count += 1
        # 让这一次 login 信号先走完再动队列，避免在信号处理里重入
        QTimer.singleShot(0, self._retry_failed)

    def _on_login_mode_changed(self, mode):
        self.settings.set('login_mode', mode)
        self.settings.save()

    def _logout(self):
        """
        退出登录：清 Token、清内嵌浏览器会话，回到登录页。

        不管当前记的是哪种登录模式都要清浏览器会话 —— 用户可能先用统一身份
        认证登录、之后才把模式改成 Token，这时候浏览器里还留着旧的登录态。
        """
        self.login.sso.reset_session()
        self.settings.update(token='', last_login_at=0)
        self.settings.save()
        self.settings_view.load(self.settings)
        self._sync_sidebar()
        self.login.token.set_token('')
        self._show_login()
        self.login.set_mode(self.settings.get('login_mode') or 'sso')

    # ---------------------------------------------------------------- 失效处理
    def _watch_for_expiry(self, jobs):
        """
        发现 Token 失效就处理一次，别反复弹窗。

        守卫不能省：_queue_changed 在下载过程中会被高频调用，而失败任务会
        一直留在快照里，没有守卫的话每一帧都会触发一次「去重新登录」。

        两条发现途径：
          1. 任务自己报错（engine 会抛「Token 不正确或已过期」）—— 准；
          2. 本地解出 JWT 的 exp 已经过去，且正在下载 —— 早。
        """
        if self._expiry_handled:
            return
        token = (self.settings.token or '').strip()
        if not token:
            return

        msg = ' '.join(str(getattr(j, 'error', '') or '') for j in jobs)
        reported = 'Token 不正确或已过期' in msg
        info = tokeninfo.TokenInfo(token)
        local = bool(info.has_expiry and info.is_expired() and self.queue.running)
        if not (reported or local):
            return

        self._expiry_handled = True
        QTimer.singleShot(0, self._token_expired)

    def _token_expired(self):
        """
        下载过程中发现 Token 失效时走这里。

        统一身份认证模式：不用打扰用户，回登录页让内嵌浏览器自己去续
        （profile 里的会话还在的话，页面会直接跳回 /index?token=xxx，
        用户什么都不用点）。
        手动 Token 模式：没法自动续，明确告诉用户去换一个。
        """
        mode = self.settings.get('login_mode') or 'token'
        if mode == 'sso' and self.settings.get('auto_refresh', True):
            self._log('Token 已失效，正在通过统一身份认证自动重新获取…', 'warn')
            # 登回来之后把刚才失败的书自动接上（见 _maybe_resume）
            self._resume_pending = True
            self._show_login()
            self.login.set_mode('sso')
            self.login.sso.start(force=True)
            self.login.sso.set_status(
                'Token 已失效，正在尝试自动重新获取；'
                '如果弹出的窗口要求登录，请完成认证。', 'warn')
        else:
            self._log('Token 已失效，请更换 Token。', 'err')
            self.settings.update(token='')
            self.settings.save()
            self._sync_sidebar()
            self._show_login()
            self.login.set_mode('token')
            self.login.token.set_token('')
            QMessageBox.warning(
                self, APP_NAME,
                'Token 已失效，需要更换。\n\n'
                '请在浏览器里重新登录教参平台，把新的 Token '
                '（或整条 index?token=xxx 的地址）粘回登录页。')

    # ================================================================ 设置
    def _save_settings(self):
        vals = self.settings_view.values()
        self.settings.update(**vals)
        ok = self.settings.save()
        if ok:
            self.settings_view.mark_saved()
        else:
            QMessageBox.warning(self, APP_NAME, '设置保存失败，请检查磁盘权限。')
        self._sync_sidebar()

    def _pick_dir(self):
        start = self.settings_view.values().get('save_dir') or app_base_dir()
        chosen = QFileDialog.getExistingDirectory(self, '选择保存位置', start)
        if chosen:
            self.settings_view.set_dir(chosen)
            self._save_settings()

    def _open_save_dir(self):
        d = self.settings.resolve_save_dir(app_base_dir())
        os.makedirs(d, exist_ok=True)
        if not _open_path(d):
            QMessageBox.information(self, APP_NAME, '目录：%s' % d)

    def _verify_token(self, token):
        token = (token or '').strip()
        if not token:
            self.settings_view.set_verify_result(False, '请先填写 token')
            return
        # 校验需要一个链接；没有就只检查格式，不为校验而要求用户先有链接
        self.settings_view.status.setText('校验中…')
        self.settings_view.status.set_tone('info')
        # 存下来，让校验和下载用的是同一份值
        self.settings.update(token=token)
        self.settings.save()
        self._sync_sidebar()
        jobs = self.queue.snapshot()
        url = jobs[0].url if jobs else ''
        if not url:
            self.settings_view.set_verify_result(
                True, '已保存')
            self.settings_view.token_hint.setText(
                'token 已保存。加入书籍链接后会在下载时校验。')
            return

        worker = CredCheckWorker(url, token)
        runner = TaskRunner(worker)
        self._verify_runner = runner
        worker.done.connect(self._on_verify_done)
        worker.failed.connect(self._on_verify_failed)
        runner.finished.connect(lambda: setattr(self, '_verify_runner', None))
        runner.start()

    def _on_verify_done(self, info):
        meta = info.get('meta') or {}
        title = meta.get('title') or info.get('book_real_id', '')
        self.settings_view.set_verify_result(True, '有效')
        self.settings_view.token_hint.setText(
            'token 可用。第一本：《%s》，共 %d 章 %d 页。'
            % (title, info.get('chapters', 0), info.get('pages', 0)))

    def _on_verify_failed(self, msg):
        self.settings_view.set_verify_result(False, '校验失败')
        self.settings_view.token_hint.setText(str(msg))

    # ================================================================ 队列
    def _add_urls(self, urls):
        n = self.queue.add(urls)
        if n == 0:
            self._log('这些链接已经在队列里了，没有重复添加。', 'warn')
        else:
            self.queue_view.set_jobs(self.queue.snapshot())
            self._queue_changed()
            self._log('已加入 %d 条链接。' % n)
        self.queue_view.set_jobs(self.queue.snapshot())
        self._queue_changed()

    def _start_queue(self):
        # 先落盘当前设置，避免界面改了没保存就去下载
        self.settings.update(**self.settings_view.values())
        self.settings.save()
        self._sync_sidebar()
        if not (self.settings.token or '').strip():
            QMessageBox.information(
                self, APP_NAME,
                '还没有登录。\n\n请先获取 Token 再开始下载。')
            self._show_login()
            return
        if not self.queue.snapshot():
            return
        if self.queue.start():
            self.queue_view.set_running(True)
            self._log('开始下载，共 %d 本。' % len(self.queue.snapshot()))

    def _stop_queue(self):
        self.queue.cancel()
        self._log('已请求停止，正在收尾…', 'warn')

    def _retry_failed(self):
        n = self.queue.reset_failed()
        if n:
            self._log('%d 本失败/停止的任务已重新排队。' % n)
            self._start_queue()

    def _clear_finished(self):
        self.queue.clear_finished()
        self.queue_view.set_jobs(self.queue.snapshot())
        self._queue_changed()

    def _remove_job(self, job):
        if job.active:
            return
        self.queue.remove(job)
        self.queue_view.set_jobs(self.queue.snapshot())
        self._queue_changed()

    def _open_job_folder(self, job):
        target = job.pdf_path or job.url
        if job.pdf_path and os.path.exists(job.pdf_path):
            _open_path(job.pdf_path)
        else:
            QMessageBox.information(self, APP_NAME, '还没有生成文件。')

    # ================================================================ 书库
    def _refresh_library(self, import_existing=False):
        if import_existing:
            root = self.settings.resolve_save_dir(app_base_dir())
            try:
                self.library.import_existing(root)
                # 用户改过文件夹名的话，记录里的绝对路径已经失效，而
                # import_existing 只补新记录、不修老记录，书库就会一直显示
                # 「文件已丢失」且刷新无效。这里按 <book_id>.pdf 重新认领一遍。
                self.library.relocate_missing(root)
            except Exception:                                    # noqa: BLE001
                pass
        self.library_view.set_records(self.library.all())

    def _library_changed(self):
        self._on_library_dirty()

    # ---- 下载线程 -> GUI 线程的跳板
    # 这四个方法只负责 emit，本身不碰任何控件，所以可以在下载线程里安全调用。
    def _emit_queue_dirty(self):
        self._queue_dirty.emit()

    def _emit_library_dirty(self):
        self._library_dirty.emit()

    def _emit_log(self, msg, tone=''):
        self._log_line.emit(msg, tone)

    def _on_queue_dirty(self):
        # 已经在 GUI 线程了。合并成一次刷新，避免每个页面都重建一遍列表。
        if not self._queue_coalesce.isActive():
            self._queue_coalesce.start()

    def _on_library_dirty(self):
        self._refresh_library(import_existing=False)

    def _open_library_folder(self, rec):
        if rec:
            if not _open_path(rec.get('pdf_path')):
                QMessageBox.information(self, APP_NAME, '文件已丢失或被移动。')
            return
        d = self.settings.resolve_save_dir(app_base_dir())
        os.makedirs(d, exist_ok=True)
        _open_path(d)

    def _remove_record(self, rec):
        self.library.remove(rec.get('book_id'))
        self._refresh_library(import_existing=False)

    # ================================================================ 状态
    def _queue_changed(self):
        jobs = self.queue.snapshot()
        qv = self.queue_view
        qv.set_jobs(jobs)
        done, failed, left = self.queue.counts()
        qv.set_counts(len(jobs), done, failed, left, self.queue.progress())

        # Token 失效是唯一需要打断流程的失败：本地解析出过期、或者任务报了
        # 「Token 不正确或已过期」，都转给 _handle_expiry 去处理
        if jobs:
            self._watch_for_expiry(jobs)

        running = self.queue.running
        qv.set_running(running)
        if running:
            active = next((j for j in jobs if j.active), None)
            if active is not None:
                if active.pages:
                    sub = '第 %d/%d 页 · %s' % (
                        active.done_pages, active.pages,
                        active.title or active.book_id or '')
                else:
                    sub = active.title or active.book_id or '正在解析…'
                qv.set_batch_text('正在下载（%d 本排队中）' % max(0, left), sub)
                self._set_sidebar_status('下载中', '正在处理：%s' % (active.book_id or '…'))
            else:
                qv.set_batch_text('准备中…', '')
        else:
            # 跑完了：停掉定时刷新，并把最后一批状态补齐
            self._refresh_library(import_existing=False)
            if done or failed:
                # 以前这里把「token 是否有效」当成 title 传了进来，而
                # _set_sidebar_status 的第一个参数是标题文字 —— 于是
                # status_chip._title 变成了一个 bool，绘制时
                # elidedText(True, ...) 抛 TypeError。PyQt 在绘制回调里碰到
                # 未捕获异常会直接 qFatal，进程以 0xC0000409 退出且没有 Python
                # 回溯 —— 这就是「下载完就崩、但书其实已经下好了」的真正原因。
                self._set_sidebar_status(
                    '下载完成',
                    '完成 %d · 失败 %d' % (done, failed))
            else:
                self._sync_sidebar()

    def _sync_sidebar(self):
        """
        侧边栏底部的登录状态。

        以前只有一个布尔值（有 / 没有）。既然现在能解出有效期和账号名，
        就一起说清楚：登的是谁、还剩多久。
        """
        self._sync_token_chip()

    def _sync_token_chip(self):
        """
        只刷底部那一块。定时器每 30 秒叫一次。

        为什么需要定时刷：Token 只活 63 分钟，而这块显示的是「还剩 X 分钟」。
        只在切页面/开下载时更新的话，程序静置半小时后那行字就是错的，
        从「有效」跳到「快过期」也不会自己发生 —— 得等下载报错才发现。
        """
        token = (self.settings.token or '').strip()
        if not token:
            self.sidebar.set_token_state(False)
            self.sidebar.status_chip.setToolTip('还没登录')
            return
        info = tokeninfo.TokenInfo(token)
        state = info.state()
        # 副标题给剩余时间，标题给账号名；两边各说一件事，不重复
        self.sidebar.set_token_expiry(state, info.left_text(),
                                      account=info.account_label())
        tip = info.describe()
        who = info.account_tooltip()
        if who:
            tip = '当前账号：%s\n%s' % (who, tip)
        self.sidebar.status_chip.setToolTip(tip)

    def _set_sidebar_status(self, title, sub=''):
        self.sidebar.status_chip._title = title
        self.sidebar.status_chip._sub = sub
        self.sidebar.status_chip.update()

    def _log(self, msg, tone=''):
        # 日志目前只在需要时打；后续加日志面板时接到这里
        try:
            print(msg)
        except Exception:                                        # noqa: BLE001
            pass

    def _toast_open(self, ok, fail_msg):
        if not ok:
            QMessageBox.information(self, APP_NAME, fail_msg)

    # ================================================================ 退出
    def closeEvent(self, ev):
        if self.queue.running:
            r = QMessageBox.question(
                self, APP_NAME, '还有下载任务在跑，确定要退出吗？\n'
                                '已下好的图片会保留，下次可以接着下。',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                ev.ignore()
                return
            self.queue.cancel()
            self.queue.wait(2.0)
        self.settings.update(**self.settings_view.values())
        self.settings.save()
        ev.accept()


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)

    from . import theme as T
    T.install_app_font(app)

    win = MainWindow()
    win.show()
    # 开机落哪一页要等窗口显示之后再定：登录页的 SSO 面板靠 showEvent
    # 才去加载内嵌浏览器，提前调用会白等
    QTimer.singleShot(0, win.start)
    return app.exec()
