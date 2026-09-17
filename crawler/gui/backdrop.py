# coding:utf-8
"""
程序化的夜空天幕。不依赖任何外部图片 —— 把图放到
assets/backdrop.jpg|png|webp 即自动覆盖。

四层叠成，全部用 QPainter 现画：
  1. 竖向渐变底  sky_top -> sky_mid -> sky_bottom
  2. 极光带      三段椭圆，按不同透明度叠加、缓慢漂移
  3. 星点        随机分布，半径 1~2px，透明度随机
  4. 同心弧纹    sky_glow 的细弧线，极低透明度

静态层（底渐变 + 星点）预算成 QPixmap，只有极光带和弧纹逐帧变，
这样 60fps 的重绘开销压在后台缓冲交换上，而不是 paintEvent 里。
"""
import math
import os
import random
import sys

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap, QRadialGradient)
from PyQt6.QtWidgets import QWidget

from . import theme as T

import sys

_ASSET_DIRS = []
if getattr(sys, '_MEIPASS', None):
    # PyInstaller 把只读资源解到这里
    _ASSET_DIRS.append(os.path.join(sys._MEIPASS, 'assets'))
# 开发态：本文件在 crawler/gui/ 下，往上两层到仓库根，再进 crawler/assets
_ASSET_DIRS.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'crawler', 'assets'))
_BACKDROP_EXTS = ('.jpg', '.jpeg', '.png', '.webp')


# 天幕自己的刷新间隔，刻意定得比常规动画慢（33ms / 30fps）。
#
# 极光带的正弦漂移周期是 2π/0.11 ≈ 57 秒，66fps 对它是纯粹的浪费：每一帧都要
# 重画 4 个铺满整块面板的抗锯齿径向渐变，而 Qt 还要为这个窗口做整窗重合成。
# 实测登录页那块大天幕在 66fps 下吃掉主线程 50%~74% 的 CPU（天幕自绘只占 21%，
# 其余是重合成），30fps 下肉眼分辨不出差别，代价直接减半。
SKY_TICK_MS = 33

# 化开区顶端那一行取天幕最后几行的列均值。见 paintEvent 里「四」那段：
# 只取最后一行的话，天幕收尾正在压暗，那一行会比上面暗一档，拉伸之后
# 就是用户看到的那道细黑边。3 行是「够抹平单行偏差」和「不糊掉逐列
# 明暗」之间的折中。
_FADE_ROW_BAND = 3

# 化开区末尾留出的纯底色尾巴行数。见 paintEvent 里「八」那段：化开区底边
# 正好是 SkyPanel 的下边界，分数 dpr 下这条边界会落在两个物理像素之间，
# 那个跨边界的物理像素会采到化开区身后天幕的暗部，留下一行紫灰色接缝。
# 尾巴留 2 行，边界上下两侧就都是纯底色，取整怎么取都不会有杂色。
_FADE_TAIL = 2


def _find_asset(stem):
    """在 assets/ 下按 stem 找一个图片文件，返回路径或 None。"""
    for d in _ASSET_DIRS:
        for ext in _BACKDROP_EXTS:
            p = os.path.join(d, stem + ext)
            if os.path.exists(p):
                return p
    return None


def _find_backdrop():
    return _find_asset('backdrop')


def _mix_color(a, b, t):
    """在两个颜色令牌之间插值 —— 用于天幕变体切换时的平滑过渡。"""
    ca, cb = QColor(a), QColor(b)
    return QColor(int(ca.red() + (cb.red() - ca.red()) * t),
                  int(ca.green() + (cb.green() - ca.green()) * t),
                  int(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


class SkyBackdrop(QWidget):
    """一屏天幕。可作为一个铺满的底层控件，也可以被嵌进更大的容器。"""

    def __init__(self, variant='violet', parent=None, animated=True,
                 sky_height=None, fade_to=None, art=None, scrim=None,
                 side_scrim=0.0):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        # sky_height 不为 None 时，控件上半部画天幕、下半部化开进页面底色。
        self._sky_height = sky_height
        # 化开区最后落到哪个底色上。默认是页面底色；侧边栏会传自己的底色
        # 进来 —— 化开区必须是**不透明**的，落在别的颜色上就会露出一条
        # 色差。理由见 paintEvent 里那段注释。
        self._fade_to = fade_to or T.BG
        # 底图可以换成别的（登录页左栏用自己那张竖构图），压暗程度也可以调。
        self._art_stem = art
        self._scrim = T.BACKDROP_SCRIM if scrim is None else scrim
        # 左轻右重的一道侧向压暗：左栏的文字都在左边，右边留着让画露出来。
        # 均匀压暗要么糊掉画、要么压不住字，侧向压暗两个都要得到。
        self._side_scrim = side_scrim
        self._variant = variant if variant in T.VARIANTS else 'violet'
        self._params = dict(T.VARIANTS[self._variant])
        self._target = dict(self._params)
        self._phase = 0.0
        self._blend = 1.0            # 变体切换的插值进度
        self._from = dict(self._params)
        self._animated = animated
        self._stars = []
        self._static = None
        self._static_key = None
        # 天幕最后一行的平均色。化开区要接着这一行往下走 ——
        # 见 paintEvent 里那段注释。
        self._bottom_color = QColor(T.SKY_BOTTOM)
        self._image = None
        self._img_path = _find_asset(art) if art else _find_backdrop()
        if self._img_path:
            self._image = QImage(self._img_path)
        # 有底图时整块天幕是静态的：底图自己就带着光，再往上叠程序化的
        # 星点、弧纹和逐帧漂移的极光带，只会和画面打架，还白烧一份重合成
        # 的 CPU。见 README「底图与天幕」。
        self._has_art = self._image is not None and not self._image.isNull()

        self._timer = None
        if animated and T.motion.ENABLED and not self._has_art:
            self._timer = QTimer(self)
            self._timer.setTimerType(Qt.TimerType.PreciseTimer)
            self._timer.setInterval(SKY_TICK_MS)
            self._timer.timeout.connect(self._tick)
            self._timer.start()

    # ------------------------------------------------------------ 对外接口
    def set_variant(self, name, animate=True):
        if name not in T.VARIANTS:
            return
        self._from = dict(self._params)
        self._target = dict(T.VARIANTS[name])
        self._variant = name
        if not animate or not self._animated or not T.motion.ENABLED:
            self._params = dict(self._target)
            self._blend = 1.0
            self._static_key = None
        else:
            self._blend = 0.0
        self.update()

    def set_animated(self, on):
        """动画关掉时界面必须是完整可用的静态版本。"""
        self._animated = bool(on)
        if self._timer is not None:
            self._timer.start() if on else self._timer.stop()
        self.update()

    # ------------------------------------------------------------ 内部
    def _tick(self):
        # 相位推进量必须和定时器间隔一致，否则改了刷新率会连带把漂移速度也改掉
        self._phase += SKY_TICK_MS / 1000.0
        if self._blend < 1.0:
            self._blend = min(1.0, self._blend + SKY_TICK_MS / 700.0)
        self.update()

    def _lerp_params(self):
        t = self._blend
        a, b = self._from, self._target
        out = {}
        for k in ('alphas',):
            out[k] = tuple(a[k][i] + (b[k][i] - a[k][i]) * t for i in range(3))
        for k in ('stars', 'top_shift', 'glow_a'):
            if k in a and k in b:
                out[k] = a[k] + (b[k] - a[k]) * t
        for k in ('c1', 'c2', 'c3', 'glow'):
            if k in a and k in b:
                out[k] = _mix_color(a[k], b[k], t)
        out['ys_band'] = a['ys_band']
        return out

    def _sky_h(self, h):
        return min(h, self._sky_height) if self._sky_height else h

    def _ensure_static(self, w, h):
        key = (w, h, self._variant if self._blend >= 1.0 else 'blend',
               round(self._params.get('stars', 1.0), 3))
        if self._static is not None and self._static_key == key:
            return
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_base(p, w, h)
        if not self._has_art:
            # 星点和弧纹是程序化天幕的一部分；底图已经是一张成品画面，
            # 再撒一层假星星只会显得脏。
            self._stars = self._make_stars(w, self._sky_h(h))
            self._paint_stars(p, w, h)
            self._paint_arcs(p, w, h)
        p.end()
        self._static = pm
        self._static_key = key
        self._bottom_color = self._sample_bottom(pm)

    def _sample_bottom(self, pm):
        """
        取天幕最后一行的平均色，作为化开区的起点色。

        为什么不直接用 T.SKY_BOTTOM：有底图时天幕末尾是照片（还压了一层
        暗色），和 SKY_BOTTOM 差得很明显 —— 差一点就是一道肉眼可见的硬边。
        取平均而不是取中间那一个像素：程序化天幕会撒星点，正好采到一颗星
        的话，整个化开区就会变成一条亮带。
        """
        sh = self._sky_h(pm.height())
        if sh < 1 or pm.width() < 1:
            return QColor(T.SKY_BOTTOM)
        img = pm.toImage().convertToFormat(QImage.Format.Format_RGB32)
        y = sh - 1
        rs = gs = bs = n = 0
        for x in range(0, img.width(), max(1, img.width() // 24)):
            c = img.pixelColor(x, y)
            rs += c.red()
            gs += c.green()
            bs += c.blue()
            n += 1
        if not n:
            return QColor(T.SKY_BOTTOM)
        return QColor(rs // n, gs // n, bs // n)

    def _make_stars(self, w, h):
        rng = random.Random(20241107)
        mult = self._params.get('stars', 1.0)
        n = int(w * h / 5200.0 * mult)
        stars = []
        for _ in range(max(24, n)):
            stars.append((rng.uniform(0, w), rng.uniform(0, h),
                          rng.uniform(0.9, 2.0), rng.uniform(0.15, 0.78)))
        return stars

    def _paint_base(self, p, w, h):
        sh = self._sky_h(h)
        if self._has_art:
            self._paint_photo(p, w, sh)
            return
        g = QLinearGradient(0, 0, 0, sh)
        g.setColorAt(0.0, T.qc(T.SKY_TOP))
        g.setColorAt(0.52, T.qc(T.SKY_MID))
        g.setColorAt(1.0, T.qc(T.SKY_BOTTOM))
        p.fillRect(0, 0, w, sh, QBrush(g))

    def _paint_photo(self, p, w, sh):
        """铺底图，再按文字所在的高度分三层压暗。

        底图是「艺术」，压暗是「工程」：画面里最亮的那一带不能刚好落在
        某行白字底下，否则那行字就是读不出来的。三个系数在 theme 里，
        tools/check_backdrop_contrast.py 会按真实控件几何量对比度。
        """
        img = self._image.scaled(w, sh,
                                 Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
        sx = max(0, (img.width() - w) // 2)
        sy = max(0, (img.height() - sh) // 2)
        p.drawImage(QRect(0, 0, w, sh), img, QRect(sx, sy, w, sh))

        p.fillRect(0, 0, w, sh, T.rgba(T.PRIMARY_DEEP, self._scrim))

        top_h = max(1.0, sh * T.BACKDROP_SCRIM_TOP_H)
        g = QLinearGradient(0, 0, 0, top_h)
        g.setColorAt(0.0, T.rgba(T.PRIMARY_DEEP, T.BACKDROP_SCRIM_TOP))
        g.setColorAt(1.0, T.rgba(T.PRIMARY_DEEP, 0.0))
        p.fillRect(QRectF(0, 0, w, top_h), QBrush(g))

        bot_y = sh * T.BACKDROP_SCRIM_BOTTOM_Y
        g2 = QLinearGradient(0, bot_y, 0, sh)
        g2.setColorAt(0.0, T.rgba(T.PRIMARY_DEEP, 0.0))
        g2.setColorAt(1.0, T.rgba(T.PRIMARY_DEEP, T.BACKDROP_SCRIM_BOTTOM))
        p.fillRect(QRectF(0, bot_y, w, sh - bot_y), QBrush(g2))

        if self._side_scrim > 0:
            # 侧向压暗：登录页左栏的文字全在左边，右边留着让主视觉露出来。
            # 均匀压暗到「字读得清」的程度，画就没了；只压左边，两个都要得到。
            gw = max(1.0, w * 0.88)
            gs = QLinearGradient(0, 0, gw, 0)
            gs.setColorAt(0.0, T.rgba(T.PRIMARY_DEEP, self._side_scrim))
            # 中段保持在 0.72 而不是 0.46：左栏的文字列一直到 0.72w 都可能有字
            # （标题那一行最长），掉太快的话右半截文字就落在亮画上了。
            gs.setColorAt(0.75, T.rgba(T.PRIMARY_DEEP, self._side_scrim * 0.72))
            gs.setColorAt(1.0, T.rgba(T.PRIMARY_DEEP, 0.0))
            p.fillRect(QRectF(0, 0, gw, sh), QBrush(gs))

    def _paint_stars(self, p, w, h):
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, r, a in self._stars:
            p.setBrush(T.rgba('#FFFFFF', a * 0.85))
            p.drawEllipse(QPointF(x, y), r, r)

    def _paint_arcs(self, p, w, h):
        """同心弧纹：sky_glow 的细弧线，极低透明度。"""
        pen = QPen(T.rgba(T.SKY_GLOW, 0.05))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = w * 0.5, h * 1.35
        for i in range(6):
            r = h * (1.05 + i * 0.30)
            p.drawEllipse(QPointF(cx, cy), r * 1.6, r)

    def _paint_aurora(self, p, w, h, prm):
        p.setPen(Qt.PenStyle.NoPen)
        # 关掉抗锯齿：这几条极光带在边缘处 alpha 已经渐到 0，边界本来就看
        # 不见，给一条全透明的边缘做抗锯齿是纯浪费。实测这是每帧最贵的一步。
        # 渐变的内部平滑由 QRadialGradient 自己保证，不受影响。
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        h = self._sky_h(h)
        bands = prm['ys_band']
        colors = (prm['c1'], prm['c2'], prm['c3'])
        alphas = prm['alphas']
        shift = prm.get('top_shift', 0.0) * h
        for i, (cy, rx, ry, rot) in enumerate(bands):
            drift = math.sin(self._phase * (0.18 + i * 0.07) + i * 2.1) * h * 0.055
            cx = w * (0.5 + 0.16 * math.sin(self._phase * 0.11 + i * 1.7))
            rect = QRectF(cx - w * rx * 0.5, cy * h + shift + drift - h * ry * 0.5,
                          w * rx, h * ry * 2.2)
            grad = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 0.5)
            col = QColor(colors[i])
            a = alphas[i]
            grad.setColorAt(0.0, T.rgba(col.name(), a))
            grad.setColorAt(0.55, T.rgba(col.name(), a * 0.38))
            grad.setColorAt(1.0, T.rgba(col.name(), 0.0))
            p.save()
            p.translate(rect.center())
            p.rotate(rot)
            p.translate(-rect.center())
            p.setBrush(QBrush(grad))
            p.drawEllipse(rect)
            p.restore()

        # 低空辉光
        ga = prm.get('glow_a', 0.2)
        if ga:
            g2 = QRadialGradient(QPointF(w * 0.5, h * 1.02), w * 0.55)
            g2.setColorAt(0.0, T.rgba(prm['glow'], ga))
            g2.setColorAt(1.0, T.rgba(prm['glow'], 0.0))
            p.setBrush(QBrush(g2))
            p.drawEllipse(QRectF(w * 0.5 - w * 0.55, h * 1.02 - h * 0.7,
                                 w * 1.1, h * 1.4))

    def paintEvent(self, _ev):
        w, h = max(1, self.width()), max(1, self.height())
        self._ensure_static(w, h)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawPixmap(0, 0, self._static)
        if not self._has_art:
            self._paint_aurora(p, w, h, self._lerp_params())
        if self._sky_height and h > self._sky_height:
            # 化开区：把天幕底部渐隐进侧边栏底色。三个要求，缺一个都出过事。
            #
            # 一、**必须不透明**。这里原来把它渐隐到全透明，靠「反正下面就是
            #     侧边栏底色」蒙混过关。但半透明就意味着身后的东西会透出来
            #     —— 侧边栏下面正好压着已经隐藏的登录页品牌区，于是侧边栏上
            #     浮出一行读不清的白字（用户截图里那行）。半透明还让上面那句
            #     WA_OpaquePaintEvent 变成假话。
            #
            # 二、**起点必须逐列接住天幕的最后一行**。做法是把最后一行按列向下
            #     拉伸铺满整条化开区，再叠渐变。「用整行平均色铺底」试过：
            #     接缝处亮度跳变 142 —— 照片底部左右亮度本就不一样，一个平均
            #     值必然和某一列对不上，那就是一道肉眼可见的横线。
            #     tools/check_fade_opaque.py 会量这个跳变。
            #
            # 三、底色要从外面传（侧边栏传自己的底色）。落在页面底色上，
            #     化开区就会和侧边栏差出一条色带。
            #
            # 四、**接缝那一行不能比它上面更暗**。上面第二条「拉伸最后一行」
            #     本身是对的，但**只看最后一行**会出事：天幕的收尾如果是向
            #     下压暗的（程序化天幕的低空辉光中心在 h*1.02，最后一行正在
            #     衰减段），最后一行就比倒数第二行暗一点点。把它按比例拉到
            #     整条化开区的最上面，那点暗被原样放大，用户看到的就是
            #     「紫色那块底边有一道很细的黑边」。实测 220 宽的侧边栏天幕
            #     上，接缝处比上一行暗 5 个灰阶。
            #     所以这一行取**最后几行的列均值**：逐列信息全留着（这才是
            #     原来必须用「逐列」而不是「整行平均色」的原因），又不会被
            #     单独一行的偏差带跑。tools/check_fade_opaque.py 会量这一行。
            #
            # 五、**化开区只能一次性合成，不能先铺一层再盖一层**。上面第四条
            #     的修法是「先 drawPixmap 把最后一行拉伸铺满，再用平滑后的
            #     一行盖上去」。这在 dpr=1 下没问题，但**在 1.25/1.5 这类
            #     分数缩放下会漏**：把 1 像素源行拉成 30 像素是一次 30 倍
            #     放大，Qt 在分数 dpr 下的采样边界会算到源矩形之外，于是化开
            #     区最底下那一行拿到的不是天幕最后一行，而是一个明显更暗的
            #     采样结果。第二层盖的是「化开区整体」，最底那一行恰好落在
            #     两层之间的缝里没人管 —— 用户看到的就是「紫色那块底边有一道
            #     很细的黑边」，而且只在某些缩放比例下出现（作者在 dpr=1.5
            #     的真实窗口里复现到：那一行亮度 158，上一行 249）。
            #
            # 六、**渐变必须叠在不透明底上**。把「底色 + 半透明渐变」画在
            #     透明 QPixmap 上会得到一片白：ARGB32_Premultiplied 下
            #     「透明的半透明色」做 source-over，RGB 会被当成预乘值直接
            #     相加，结果是 255 而不是底色。实测逐行亮度变成
            #     66,255,249,255,252,...，比原来那道黑边还难看。
            #     所以先把接住行**不透明地**铺满整条化开区，再把渐变叠上去。
            # 化开区：从 fade_top 到底边，但要**多画 _FADE_TAIL 行**。
            #
            # 为什么多画：化开区底边正好落在 SkyBackdrop 控件的下边界上，
            # 而控件的最后一行会被合成器当成边缘重新采样，和控件外面的内容
            # 混一次 —— 于是那一行变成「天幕暗部 × 化开区末色」的混合色。
            # 实测（把整条化开区填成一个纯底色、完全没有渐变，那一行依然是
            # 暗的）：
            #     平铺 (252,251,254) -> 最后一行 (156,147,167)
            #     带渐变           -> 最后一行 (204,199,211)
            # 两次都偏紫、都不是我们画的颜色，所以问题不在渐变，在**控件边界**。
            #
            # 修法：让 SkyBackdrop 比视觉上的化开区多出 _FADE_TAIL 行，多出来
            # 的那几行全是纯底色。于是「控件最后一行」被推到视觉接缝下面，
            # 那条被污染的边缘就落在纯底色区域里，看不出来了。
            # SkyPanel 负责把 SkyBackdrop 撑高（见它的 resizeEvent），这里只管
            # 按自己的高度画满。
            fade_top = self._sky_height
            fade_h = max(1, h - fade_top)
            band = min(_FADE_ROW_BAND, max(1, fade_top))

            # 逐列取天幕最后几行的均值，作为化开区的起点色（保留逐列差异）
            row = self._static.toImage().copy(0, fade_top - band, w, band)
            row = row.scaled(w, 1, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)

            # 接住 + 铺底一次做完：把这一行按列拉伸铺满**整条**化开区
            # （一直铺到底边，逐列色差保留）。
            #
            # 注意源是「最后几行的列均值」这一行（宽 w、高 1 的 QImage），
            # 不是天幕里的原始单行 —— 不能退回 drawPixmap 去拉伸 _static
            # 的第 fade_top-1 行，那样在分数 dpr 下会漏出暗行（见第五条）。
            #
            # 这一笔必须**铺到底边**（dst 高 fade_h，不是 fade_h - _FADE_TAIL）：
            # 底边那一行是整个化开区唯一有可能露出天幕暗部的地方，第一笔就
            # 把它盖成不透明的天幕尾色，后面几笔无论怎么算都不会再漏出暗色。
            p.drawImage(QRect(0, fade_top, w, fade_h), row)
            # 再叠不透明渐变，收敛到侧边栏底色。
            #
            # 渐变终点是 **h - _FADE_TAIL**：视觉上的化开区只有
            # h - _FADE_TAIL 行（SkyPanel 把它撑高了 _FADE_TAIL 行，多出来的
            # 那几行是「挡箭牌」）。渐变到那里正好收满，剩下的行全是纯底色。
            g = QLinearGradient(0, fade_top, 0, h - _FADE_TAIL)
            g.setColorAt(0.00, T.rgba(self._fade_to, 0.00))
            g.setColorAt(0.14, T.rgba(self._fade_to, 0.09))
            g.setColorAt(0.34, T.rgba(self._fade_to, 0.24))
            g.setColorAt(0.62, T.rgba(self._fade_to, 0.52))
            g.setColorAt(0.85, T.rgba(self._fade_to, 0.86))
            g.setColorAt(1.00, T.qc(self._fade_to))
            p.fillRect(0, fade_top, w, fade_h, QBrush(g))
            # 收口：把「挡箭牌」那几行写死成不透明底色。
            #
            # 这几行在视觉上属于导航区，只是借用 SkyBackdrop 的绘制区，好让
            # 控件那条被合成器污染的边缘落在纯底色里（见上面 fade_h 那段）。
            # 写死成底色就与渐变采样无关了。
            p.fillRect(0, h - _FADE_TAIL, w, _FADE_TAIL,
                       QColor(self._fade_to))
        p.end()


class SkyPanel(QWidget):
    """
    侧边栏顶部的天幕。整块高度 = sky_h + fade_h。

    化开区把天幕底部渐隐进侧边栏底色，所以它和下面的导航之间不需要描边。
    子控件放进 `slot`，槽区只占 sky_h —— 化开区是纯装饰，不放内容。
    """

    def __init__(self, variant='violet', parent=None, sky_h=None, fade_h=None,
                 fade_to=None):
        super().__init__(parent)
        self._sky_h = sky_h if sky_h is not None else T.SKY_PANEL_H
        self._fade_h = fade_h if fade_h is not None else T.SKY_PANEL_FADE
        self.setFixedHeight(self._sky_h + self._fade_h)
        self.sky = SkyBackdrop(variant, self, sky_height=self._sky_h,
                               fade_to=fade_to)
        self.slot = QWidget(self)
        self.slot.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_variant(self, name, animate=True):
        self.sky.set_variant(name, animate)

    def set_animated(self, on):
        self.sky.set_animated(on)

    @property
    def content_height(self):
        return self._sky_h

    def resizeEvent(self, _ev):
        w = self.width()
        # SkyBackdrop 比 SkyPanel 本体的高度**多 _FADE_TAIL 行**。
        #
        # 多出来的那几行是「挡箭牌」：化开区底边正好压在 SkyPanel 的下边界
        # 上，而 SkyBackdrop 控件的最后一行会被合成器当成边缘重新采样，和
        # 控件外面的东西混一次，那一行就变成紫灰色（实测平铺纯底色也会变成
        # (156,147,167)）。把控件撑高，让这条被污染的边缘落到视觉接缝下面的
        # 纯底色里，接缝就干净了。见 SkyBackdrop.paintEvent 里 fade_h 那段。
        #
        # 超出的部分会盖到导航区上：它是纯不透明的侧边栏底色，正好等于导航
        # 区自己的底色，所以看不出来。
        #
        # 宽度**也多给 _FADE_TAIL 列**，理由和高度一样：化开区右边正好压在
        # 侧边栏右边界上，控件最后一列同样会被合成器当边缘重采样，那一列在
        # 化开区里比左邻列暗 20%~45%（实测 y=260 时 (45,40,69) vs
        # (69,65,91)，越靠近化开区末端差得越多），看着就是紫块右边一道竖线。
        # 把控件加宽，让被污染的边缘落到侧边栏外面的工作区上（那里是浅底，
        # 一列底色看不出来），侧边栏里那一列就干净了。
        self.sky.setGeometry(0, 0, w + _FADE_TAIL, self.height() + _FADE_TAIL)
        self.slot.setGeometry(0, 0, w, self._sky_h)