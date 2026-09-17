# coding:utf-8
"""
「有新版本」提示与在应用内更新。

状态机（同一套控件，按状态换文案和按钮，不新开窗口）：
    available    有新版本，展示更新说明，主按钮「下载并安装」
    downloading  下载中，展示进度，主按钮变「取消」
    ready        下完了，主按钮「立即安装并重启」
    failed       出错，展示原因，主按钮「重试」

下载跑在 QThread 里（worker.UpdateDownloadWorker），进度通过信号回到
GUI 线程 —— 这里绝不能自己开线程去碰控件，那是 2.0 修过的老问题。
"""
import os

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QPlainTextEdit, QSizePolicy,
                             QVBoxLayout, QWidget)

from ..core import updater
from ..core import worker as WK
from ..version import VERSION
from . import theme as T
from . import widgets as W
from .views.base import scroll_qss


def _human_size(n):
    if not n:
        return '未知大小'
    if n >= 1048576:
        return '%.1f MB' % (n / 1048576.0)
    if n >= 1024:
        return '%.0f KB' % (n / 1024.0)
    return '%d B' % n


def plain_notes(md):
    """
    更新说明是 markdown，这里只是给人看的，不做渲染 —— 去掉标记符号即可。
    刻意不引第三方 markdown 库：为了一个说明框不值得多一个依赖。
    """
    out = []
    for line in (md or '').splitlines():
        s = line.rstrip()
        stripped = s.strip()
        if not stripped:
            out.append('')
            continue
        if set(stripped) <= set('-=*_') and len(stripped) >= 3:
            continue                                   # 分隔线
        while stripped.startswith('#'):
            stripped = stripped[1:].strip()
        if stripped.startswith(('- ', '* ', '+ ')):
            stripped = '· ' + stripped[2:].strip()
        stripped = stripped.replace('**', '').replace('`', '')
        # [文字](链接) -> 文字（链接），说明里的链接对用户没什么用
        while '](' in stripped and '[' in stripped:
            a = stripped.rfind('[', 0, stripped.index(']('))
            b = stripped.index('](')
            c = stripped.find(')', b)
            if a < 0 or c < 0:
                break
            stripped = stripped[:a] + stripped[b + 2:c] + stripped[c + 1:]
        out.append(stripped)
    while out and not out[0]:
        out.pop(0)
    while out and not out[-1]:
        out.pop()
    return '\n'.join(out)


class ProgressBar(QWidget):
    """细进度条。沿用队列页批量条的观感：BG_DEEP 轨道 + PRIMARY 填充。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._fraction = 0.0
        self._busy = False

    def set_fraction(self, f, busy=False):
        self._fraction = max(0.0, min(1.0, float(f)))
        self._busy = bool(busy)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T.BG_DEEP))
        p.drawRoundedRect(r, 3, 3)
        if self._fraction <= 0 and not self._busy:
            p.end()
            return
        w = r.width() * self._fraction
        # 总长度未知时（服务器没给 Content-Length）至少画一小段，
        # 让用户看到「在动」，而不是一条空槽
        if self._busy and w < 24:
            w = 24
        p.setBrush(QColor(T.PRIMARY))
        p.drawRoundedRect(QRectF(r.left(), r.top(), max(w, 6.0), r.height()), 3, 3)
        p.end()


class UpdateDialog(QDialog):
    """
    有新版时弹这个。下载也在这里做，用户不用去仓库页面。
    """

    install_requested = pyqtSignal(str)      # 参数：本地安装包路径
    skip_requested = pyqtSignal(str)         # 参数：要跳过的版本号

    def __init__(self, release, parent=None):
        super().__init__(parent)
        self.release = release
        self._runner = None
        self._path = ''
        self._state = 'available'

        self.setWindowTitle('%s — 发现新版本' % T.APP_NAME)
        self.setModal(True)
        self.setMinimumWidth(600)
        self.setStyleSheet('QDialog { background: %s; }' % T.BG)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 20)
        outer.setSpacing(14)

        # ---------------- 标题 + 版本对照
        outer.addWidget(W.Label('有新版本 %s' % release.version,
                                T.FS_CARD_TITLE, 700, T.TEXT))
        vrow = QHBoxLayout()
        vrow.setContentsMargins(0, 0, 0, 0)
        vrow.setSpacing(8)
        vrow.addWidget(W.Badge('当前 %s' % VERSION, 'info'))
        vrow.addWidget(W.Badge('最新 %s' % release.version, 'accent'))
        vrow.addStretch(1)
        if release.asset_size:
            vrow.addWidget(W.meta(_human_size(release.asset_size), T.TEXT_FAINT))
        outer.addLayout(vrow)

        # ---------------- 更新说明
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setPlainText(plain_notes(release.notes) or '（这个版本没有写更新说明）')
        self.notes.setFont(T.ui_font(T.FS_BODY, 400))
        self.notes.setFixedHeight(210)
        self.notes.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Fixed)
        self.notes.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {T.CARD}; border: 1px solid {T.BORDER};
                border-radius: {T.R_IN}px; padding: 12px 14px; color: {T.TEXT};
            }}
            QPlainTextEdit:focus {{ border: 1px solid {T.PRIMARY_SOFT}; }}
            {scroll_qss()}
        """)
        outer.addWidget(self.notes)

        # ---------------- 进度（平时藏起来）
        self.progress = ProgressBar()
        self.progress.setVisible(False)
        outer.addWidget(self.progress)

        # ---------------- 状态行：文案说明当前在干什么，不靠颜色单独表意
        self.status = W.meta('', T.TEXT_DIM)
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        outer.addWidget(self.status)

        # ---------------- 按钮
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)
        self.btn_skip = W.PillButton('跳过此版本', 'ghost', small=True)
        self.btn_later = W.PillButton('稍后再说', 'secondary', small=True)
        self.btn_main = W.PillButton('下载并安装', 'primary')
        self.btn_main.setDefault(True)
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        row.addWidget(self.btn_later)
        row.addWidget(self.btn_main)
        outer.addLayout(row)

        self.btn_main.clicked.connect(self._on_main)
        self.btn_later.clicked.connect(self.reject)
        self.btn_skip.clicked.connect(self._on_skip)
        self._render()

    # ------------------------------------------------------------ 状态渲染
    def _render(self):
        s = self._state
        self.btn_main.setEnabled(True)
        self.btn_skip.setVisible(s in ('available', 'failed'))
        self.btn_later.setVisible(s != 'downloading')
        if s == 'available':
            self.btn_main.setText('下载并安装')
            self.progress.setVisible(False)
            self.status.setVisible(False)
        elif s == 'downloading':
            self.btn_main.setText('取消')
            self.progress.setVisible(True)
            self.status.setVisible(True)
        elif s == 'ready':
            self.btn_main.setText('立即安装并重启')
            self.progress.setVisible(True)
            self.progress.set_fraction(1.0)
            self.status.setVisible(True)
            self.status.setText('下载完成。点「立即安装并重启」会关闭本程序并开始安装，'
                                '装好后自动重新打开。')
        elif s == 'failed':
            self.btn_main.setText('重试')
            self.progress.setVisible(False)
            self.status.setVisible(True)

    def _set_state(self, state):
        self._state = state
        self._render()

    def _fail(self, msg):
        self._set_state('failed')
        self.status.setText('更新失败：%s' % msg)

    # ------------------------------------------------------------ 交互
    def _on_main(self):
        if self._state == 'downloading':
            self._cancel()
        elif self._state == 'ready':
            self.install_requested.emit(self._path)
            self.accept()
        else:
            self._start_download()

    def _on_skip(self):
        self.skip_requested.emit(self.release.version)
        self.reject()

    def _cancel(self):
        if self._runner is not None:
            self._runner.stop()
            # 停完必须把引用放掉：留着的话下次点「下载并安装」会以为
            # 线程还在跑，按钮就再也不响应了。
            self._finish_runner()
        self._set_state('available')
        self.status.setVisible(False)

    def _start_download(self):
        if not self.release.asset_url:
            self._fail('这个版本没有提供安装包')
            return
        self._set_state('downloading')
        self.progress.set_fraction(0.0, busy=True)
        self.status.setText('正在下载 %s …' % (
            self.release.asset_name or '安装包'))

        w = WK.UpdateDownloadWorker(self.release)
        w.push_progress.connect(self._on_progress)
        w.finished_ok.connect(self._on_done)
        w.failed.connect(self._on_failed)
        self._runner = WK.TaskRunner(w, self)
        self._runner.start()

    def _on_progress(self, done, total):
        if total > 0:
            self.progress.set_fraction(float(done) / float(total))
            self.status.setText('正在下载 %s / %s' % (_human_size(done),
                                                     _human_size(total)))
        else:
            self.progress.set_fraction(0.0, busy=True)
            self.status.setText('正在下载 %s' % _human_size(done))

    def _on_done(self, path):
        self._path = path
        self._finish_runner()
        self._set_state('ready')

    def _on_failed(self, msg, _detail=''):
        self._finish_runner()
        # 用户自己点取消不算失败，安静回到初始状态
        if '取消' in msg:
            self._set_state('available')
            self.status.setVisible(False)
            return
        self._fail(msg)

    def _finish_runner(self):
        if self._runner is not None:
            self._runner.finish()
            self._runner = None

    # ------------------------------------------------------------ 收尾
    def closeEvent(self, ev):
        self._cancel()
        super().closeEvent(ev)

    def reject(self):
        # 关窗口 / 按 Esc 时如果还在下载，先把线程停掉
        if self._state == 'downloading':
            self._cancel()
        super().reject()


def open_installer(path, on_error=None):
    """
    跑安装包并让程序退出。返回 True 表示命令已发出去。

    单独包一层是为了 shell 那边不用 import updater 的细节。
    """
    try:
        updater.launch(path, exe=updater.current_exe())
        return True
    except updater.UpdateError as e:
        if on_error:
            on_error(str(e))
        return False
    except Exception as e:                                        # noqa: BLE001
        if on_error:
            on_error(str(e))
        return False


def installed_path_exists():
    return bool(os.path.exists(updater.dest_dir()))
