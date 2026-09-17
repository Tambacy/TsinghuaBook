# coding:utf-8
"""
化开区不透明度 + 接缝检查。

天幕底部那条「化开区」是叠在别的控件上的，一旦半透明，身后的东西就会透
出来。这个 bug 真的发生过：侧边栏下面压着已经隐藏的登录页品牌区，于是
侧边栏上浮出一行读不清的白字（截图里那行「电子教材 PDF 下载工具」）。

为什么不用抓屏验证：窗口的 z 序不稳定，抓到的可能是别的窗口（踩过）。
这里改成确定性的做法 —— 在侧边栏**正下方**放一块纯红，看它会不会透出来。
不依赖屏幕、不依赖 z 序、不依赖有没有登录页。

**坐标必须按 devicePixelRatio 换算**：QPixmap.grab() 返回的是物理像素图
（本机 dpr=1.5，220x860 的控件抓到的是 330x1290）。直接拿控件坐标去
pixelColor，采到的行会整体偏上 1/3 —— 这个坑先踩过一次，是假报错的来源。

退出码 0 = 全挡住且接缝平滑；1 = 有问题。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
from tests._isolate import isolate  # noqa: E402

isolate(webengine=True)

from PyQt6.QtCore import QRect, QRectF  # noqa: E402
from PyQt6.QtGui import QColor, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from crawler.gui import theme as T  # noqa: E402
from crawler.gui.backdrop import _FADE_ROW_BAND  # noqa: E402
from crawler.gui.sidebar import Sidebar  # noqa: E402

app = QApplication(sys.argv)
T.install_app_font(app)

RED = QColor('#FF0000')
SKY_H = T.SKY_PANEL_H
FADE_H = T.SKY_PANEL_FADE


class Backdrop(QWidget):
    """整块纯红，扮演「侧边栏身后的东西」。"""

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), RED)
        p.end()


def build(with_sidebar):
    host = QWidget()
    host.resize(T.SIDEBAR_W + 80, T.WIN_H)
    back = Backdrop(host)
    back.setGeometry(0, 0, host.width(), host.height())
    if with_sidebar:
        sb = Sidebar(host)
        sb.move(0, 0)
        sb.resize(T.SIDEBAR_W, T.WIN_H)
        sb.raise_()
    host.show()
    app.processEvents()
    return host


def count_red(img, dpr, x0, x1, y0, y1):
    """x/y 是控件坐标，内部按 dpr 换算成物理像素。"""
    n = tot = 0
    for wy in range(y0, y1):
        py = int((wy + 0.5) * dpr)
        if py >= img.height():
            continue
        for wx in range(x0, x1):
            px = int((wx + 0.5) * dpr)
            if px >= img.width():
                continue
            c = img.pixelColor(px, py)
            tot += 1
            if c.red() > 180 and c.green() < 90 and c.blue() < 90:
                n += 1
    return n, tot


ok = True

# --- 对照组：只有红底，确认红画得出来
host = build(False)
img = host.grab().toImage()
dpr = img.width() / float(T.SIDEBAR_W + 80)
ctrl, ctrl_tot = count_red(img, dpr, 20, T.SIDEBAR_W - 20, 60, 170)
host.hide()
print('dpr = %.2f' % dpr)
print('对照组（只有红底）      : 红像素 %5d / %5d' % (ctrl, ctrl_tot))
if ctrl_tot == 0 or ctrl < ctrl_tot * 0.99:
    print('  !! 对照组没数到红 —— 检查本身失效，先修检查')
    ok = False

# --- 实验组：红底 + 侧边栏
host = build(True)
img = host.grab().toImage()
print()
print('侧边栏：天幕内容 0..%d，化开区 %d..%d' % (SKY_H, SKY_H, SKY_H + FADE_H))
for label, y0, y1 in (('天幕区', 4, SKY_H - 4),
                      ('化开区', SKY_H + 2, SKY_H + FADE_H - 2),
                      ('导航区', SKY_H + FADE_H + 4, SKY_H + FADE_H + 80)):
    n, tot = count_red(img, dpr, 20, T.SIDEBAR_W - 20, y0, y1)
    bad = n > 0
    ok = ok and not bad
    print('  %-6s y %3d..%-3d  红像素 %5d / %5d   %s'
          % (label, y0, y1, n, tot, '!! 透出来了' if bad else 'OK 完全挡住'))

# --- 接缝：化开区必须从「天幕最后一行」平滑接出去，不能有硬边
mid = T.SIDEBAR_W // 2
prof = []
for wy in range(SKY_H - 3, SKY_H + FADE_H + 2):
    c = img.pixelColor(int((mid + 0.5) * dpr), int((wy + 0.5) * dpr))
    prof.append((c.red() + c.green() + c.blue()) / 3.0)
jumps = [abs(prof[i + 1] - prof[i]) for i in range(len(prof) - 1)]
mx = max(jumps) if jumps else 0.0
where = jumps.index(mx) + SKY_H - 3 if jumps else 0
print()
print('  化开区逐行亮度最大跳变 %.1f（在 y=%d；>60 视为硬边）' % (mx, where))
print('  起点 %.1f -> 终点 %.1f' % (prof[0], prof[-1]))
if mx > 60:
    ok = False

# --- 那道「细黑边」：化开区第一行不能比天幕最后一行暗
#
# 这一条是补上来的。上面那个「最大跳变 <= 60」量的是「有没有硬边」，
# 而用户报的是「紫色那块底边有一道很细的黑边」—— 它跳变只有 3 个灰阶，
# 远在 60 的阈值之下，所以整条检查一直是绿的，bug 却明明在。
#
# 成因：化开区顶端那一行本来是「把天幕最后一行拉伸铺满」。天幕收尾如果
# 正在压暗（程序化天幕的低空辉光中心在 h*1.02），最后一行就比倒数第二行
# 暗一点；那一点暗被拉伸放大成整条化开区的顶部，于是接缝处出现一条
# 1 像素的暗线。现在改成取最后几行的列均值，并显式判这一行。
print()
# 必须扫**整条宽度**：天幕的收尾深度左右不一致（程序化天幕的低空辉光中心
# 在中间，两侧先压暗），只量中间那一列会把两侧的暗线漏掉。
step_deltas = []
for x in range(2, T.SIDEBAR_W - 1):
    px = int((x + 0.5) * dpr)
    c_last = img.pixelColor(px, int((SKY_H - 1 + 0.5) * dpr))
    c_fade = img.pixelColor(px, int((SKY_H + 0.5) * dpr))
    l_last = (c_last.red() + c_last.green() + c_last.blue()) / 3.0
    l_fade = (c_fade.red() + c_fade.green() + c_fade.blue()) / 3.0
    step_deltas.append((l_fade - l_last, x, l_last, l_fade))

worst = min(step_deltas)
mid_d = dict((x, d) for d, x, _a, _b in step_deltas)[mid]
print('  接缝台阶（化开区第一行 - 天幕最后一行）：')
print('    中间列 x=%d  %+.1f' % (mid, mid_d))
print('    最差列 x=%d  %+.1f  （%.1f -> %.1f）'
      % (worst[1], worst[0], worst[2], worst[3]))
print('    逐列范围 %+.1f .. %+.1f'
      % (min(d for d, _x, _a, _b in step_deltas),
         max(d for d, _x, _a, _b in step_deltas)))
# 阈值 1.0 是**实测标定**出来的，不是拍的：
#   接缝本来就是平滑的，逐列只会有 ±0.5 的取整噪声；
#   退回旧写法（只取天幕最后一行）实测最差 -1.3 —— 会被抓；
#   现在取 3 行列均值实测最差 +1.3 —— 不会误报。
# 两个方向的余量都只有 0.3 左右，所以这是一条「紧」检查：以后谁把取行方式
# 改回单行、或者让天幕收尾更陡，它就会红。
SEAM_TOL = 1.0
if worst[0] < -SEAM_TOL:
    print('  !! 接缝处出现暗线：化开区顶端比天幕底部更暗（最差 %+.1f）——'
          % worst[0])
    print('     用户看到的就是「紫色那块底边有一道很细的黑边」。'
          '成因是化开区顶端取了天幕最后一行单行的颜色，')
    print('     而天幕收尾正在压暗，最后一行比上面暗一档，拉伸后被放大。')

# 天幕最后一行自己是不是比上面一行暗（同一成因的另一半）
self_dark = []
for x in range(2, T.SIDEBAR_W - 1):
    px = int((x + 0.5) * dpr)
    a = img.pixelColor(px, int((SKY_H - 2 + 0.5) * dpr))
    b = img.pixelColor(px, int((SKY_H - 1 + 0.5) * dpr))
    la = (a.red() + a.green() + a.blue()) / 3.0
    lb = (b.red() + b.green() + b.blue()) / 3.0
    self_dark.append(lb - la)
worst_self = min(self_dark)
print('  天幕最后一行相对上面一行：最差 %+.1f'
      '（只是成因说明，不单独判负 —— 见下）' % worst_self)
if worst_self < -SEAM_TOL:
    print('    天幕收尾在压暗。旧写法只取这一行，那点暗会被拉伸放大成接缝暗线；')
    print('    现在取最后 %d 行的列均值，这一行本身暗不暗就不再影响接缝。'
          % _FADE_ROW_BAND)

# 只有「接缝台阶」这一条判负。
# 为什么不把上面那条也当失败：天幕最后一行偏暗是**成因**，不是**症状**。
# 修复之后它照样偏暗（均值里也含它），但接缝已经不暗了 —— 拿成因判负会
# 误伤正确实现。症状（接缝台阶）才是用户看得见、也唯一该卡的东西。
if worst[0] < -SEAM_TOL:
    ok = False

# --- 化开区到底画了几笔、每笔盖住哪里
#
# 上面所有检查都只看**像素值**，而用户第二次报的那道黑边**像素值检查抓不到**：
# 它在 grab() 出来的图上根本不存在（离屏渲染是干净的），只在真实顶层窗口里
# 出现。于是「接缝台阶」一直是绿的，用户却还在报同一句话。
#
# 根因不在颜色，在**画法**：化开区原来分两笔画 ——
#   1) drawPixmap 把天幕最后 1 行拉伸铺满整条化开区（30 倍放大）
#   2) drawImage 把「最后 3 行的列均值」再盖一层
# 分数 dpr（1.25/1.5）下，第 1 笔的采样边界会算到源矩形之外，最底那一行
# 拿到一个明显更暗的采样结果；而第 2 笔盖的是「化开区整体」，最底那一行
# 恰好落在两笔之间的缝里，谁都没管。作者在 dpr=1.5 的真实窗口里复现到：
# 那一行亮度 148，上一行 248。
#
# 所以这里**改查画法**：把化开区里的每一笔绘制记下来，要求
#   (a) 没有任何一笔在拉伸单行（源高 < 2）—— 单行拉伸在分数缩放下不可靠；
#   (b) 化开区被完整覆盖（不能有哪一行落在两笔之间没人画）。
# 这一条是确定性的，不依赖屏幕、不依赖 z 序，也不受 grab() 是否干净影响。
print()
print('  化开区画法检查：')

import crawler.gui.backdrop as _bd  # noqa: E402

_real_painter = _bd.QPainter
_rec = []


class _SpyPainter(_real_painter):
    """
    替换 backdrop 模块里的 QPainter，记下每一笔 drawImage / drawPixmap 的
    目标矩形与源矩形高度。只对 SkyBackdrop 生效。
    """

    def __init__(self, target):
        super().__init__(target)
        if isinstance(target, _bd.SkyBackdrop):
            _rec.append(self)
            self.calls = []

    def drawImage(self, *a):
        if hasattr(self, 'calls'):
            self._note('image', a)
        return super().drawImage(*a)

    def drawPixmap(self, *a):
        if hasattr(self, 'calls'):
            self._note('pixmap', a)
        return super().drawPixmap(*a)

    def _note(self, kind, a):
        dst = src = None
        for x in a:
            if isinstance(x, (QRect, QRectF)):
                if dst is None:
                    dst = x
                else:
                    src = x
        self.calls.append((kind, dst, src))


_bd.QPainter = _SpyPainter
host3 = build(True)
host3.grab()
host3.hide()
_bd.QPainter = _real_painter

fade_calls = []
for sp in _rec:
    for kind, dst, src in sp.calls:
        if dst is None:
            continue
        if dst.top() <= SKY_H < dst.bottom() + 1:
            fade_calls.append((kind, dst, src))

single_row = [(k, d, s) for k, d, s in fade_calls
              if s is not None and s.height() < 2]
print('    化开区相关绘制 %d 笔' % len(fade_calls))
for k, d, s in fade_calls:
    sh = s.height() if s is not None else '-'
    print('      %-7s 目标 y=%d..%d  源高=%s'
          % (k, d.top(), d.bottom(), sh))
if single_row:
    ok = False
    print('    !! 有 %d 笔在拉伸单行（源高 < 2）。分数 dpr 下这种拉伸的采样'
          % len(single_row))
    print('       边界会算到源矩形之外，化开区最底一行会拿到更暗的采样结果 ——')
    print('       这就是「紫色那块底边有一道很细的黑边」。')
else:
    print('    OK 没有单行拉伸')

# 覆盖检查：化开区每一行都必须被至少一笔盖住
covered = [False] * FADE_H
for _k, d, _s in fade_calls:
    for wy in range(max(0, d.top() - SKY_H), min(FADE_H, d.bottom() + 1 - SKY_H)):
        covered[wy] = True
holes = [SKY_H + i for i, c in enumerate(covered) if not c]
if holes:
    ok = False
    print('    !! 化开区有 %d 行没被任何一笔盖住：y=%s' % (len(holes), holes[:8]))
    print('       这些行会露出下层内容，表现为接缝处的细线。')
else:
    print('    OK 化开区 %d 行全部被覆盖' % FADE_H)

print()
print('FADE CHECK %s' % ('OK' if ok else 'FAIL'))
sys.exit(0 if ok else 1)