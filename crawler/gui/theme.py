# coding:utf-8
"""
设计令牌（唯一来源）。

改设计请改这里，不要在页面里写死颜色和字号 —— 一旦散落，
docs/设计规范.md 就跟不上代码了。

令牌值来自设计规范第二节至第五节的表格。
"""
import sys

from PyQt6.QtGui import QColor, QFont

from ..version import VERSION

# ---------------------------------------------------------------- 主色（紫）
PRIMARY_DEEP = '#1B1236'
PRIMARY_INK = '#2A1F52'
PRIMARY = '#6F5CAD'
PRIMARY_2 = '#8B79C9'
PRIMARY_SOFT = '#A99AD8'
PRIMARY_MID = '#C6BCE6'
PRIMARY_LIGHT = '#E5E0F6'
PRIMARY_TINT = '#F5F2FD'
PRIMARY_DARK = '#57468C'

# ---------------------------------------------------------------- 天幕（深色区）
SKY_TOP = '#3A2A6E'
SKY_MID = '#241A4A'
SKY_BOTTOM = '#140D2B'
SKY_AURORA_A = '#A78CE6'   # 薰衣草
SKY_AURORA_B = '#E296BE'   # 暮粉
SKY_AURORA_C = '#786EDC'   # 蓝紫
SKY_GLOW = '#F3C9DE'       # 低空辉光

# 有底图（assets/backdrop.*）时，压在底图上的三层暗色系数。
# 白字落在三个高度上 —— 标题（顶）、卖点（中）、页脚（底），而底图最亮的
# 一带往往正好是页脚所在的位置，所以只压一层平铺的暗色是不够的。
BACKDROP_SCRIM = 0.42           # 基础压暗：只降明度，保住画面的颜色
BACKDROP_SCRIM_TOP = 0.30       # 顶部标题区额外压暗
BACKDROP_SCRIM_TOP_H = 0.34     # 上面那层覆盖的高度比例
BACKDROP_SCRIM_BOTTOM = 0.60    # 底部页脚区额外压暗
BACKDROP_SCRIM_BOTTOM_Y = 0.74  # 上面那层从哪个高度开始

# ---------------------------------------------------------------- 天幕上的白字
# 天幕（程序化夜空，或 assets/backdrop.*）是一张深色画面，白字按透明度分级。
# 透明度不能凭手感往低压：成品底图的中段和低空辉光都不算暗，0.62 的白字
# 压在页脚那一带只有 2.5:1，等于读不出来。下面这几个值是
# tools/check_backdrop_contrast.py 按真实控件几何量到全部 >= 4.5:1 才定的。
ON_DARK = '#FFFFFF'                          # 主标题、卖点小标题
ON_DARK_MUTED = 'rgba(255, 255, 255, 0.88)'  # 副标题
ON_DARK_DIM = 'rgba(255, 255, 255, 0.82)'    # 卖点说明
ON_DARK_FAINT = 'rgba(255, 255, 255, 0.76)'  # 页脚、侧栏版本号

# ---------------------------------------------------------------- 背景与文字
BG = '#F4F3F9'
BG_SOFT = '#EAE7F2'
BG_DEEP = '#E1DDEC'
CARD = '#FFFFFF'
CARD_SOFT = '#FCFBFE'
TEXT = '#1B1926'
TEXT_DIM = '#66626F'
TEXT_FAINT = '#96929E'
TEXT_GHOST = '#B6B2C0'

# ---------------------------------------------------------------- 品牌
# 应用名放在这里，是唯一来源：标题栏、侧边栏、登录页、安装包都要用，
# 以前散在 shell.py 里，titlebar 想用就会绕成循环导入。
APP_NAME = '清华教参下载器'

# 发布版本号。**界面上不显示** —— 用户明确要求去掉界面里的版本信息，
# 所以标题栏、侧边栏、登录页都不再印它。
# 唯一来源是 crawler/version.py：更新检查要拿它跟 GitHub 上的最新版比，
# 安装包脚本（installer.iss）也要写同一个号，散成两份必然对不上。
# 这里只是转出去给界面用，别在这里写死。
RELEASE_VERSION = VERSION

# ---------------------------------------------------------------- 窗口外壳
# 自绘标题栏的高度。40 比 Windows 默认的 32 略高一点，因为这个应用的
# 字号层级偏大，32 会显得挤。
TITLEBAR_H = 40
# 窗口最外圈那条 1px 描边。有它才不会在浅色桌面上「糊」成一片白边
# ——用户说的「突兀的白边」就是没有这条线导致的。
WINDOW_BORDER = '#D5D0E3'          # 窗口激活时
WINDOW_BORDER_IDLE = '#E6E3EF'     # 窗口失焦时（和系统行为一致：变淡）
WINDOW_RADIUS = 9                  # 和 Win11 系统窗口的圆角观感对齐

# ---------------------------------------------------------------- 描边与分隔
BORDER = '#E4E1EE'
BORDER_SOFT = '#EFEDF6'
BORDER_STRONG = '#D2CDE0'
HAIRLINE = (28, 20, 54, 18)          # rgba(28,20,54,7%)
HAIRLINE_DARK = (255, 255, 255, 31)  # rgba(255,255,255,12%)
GLASS = (255, 255, 255, 41)          # rgba(255,255,255,16%)

# ---------------------------------------------------------------- 状态色
ACCENT = '#3D8F6D'
ACCENT_LIGHT = '#E6F2EC'
WARN = '#96681C'
WARN_LIGHT = '#F8F0DF'
WARN_DARK = '#C79433'      # 深色面板上
DANGER = '#B03A4A'
DANGER_LIGHT = '#FAEAEC'
DANGER_DARK = '#FF8095'    # 深色面板上

# ---------------------------------------------------------------- 日志区
LOG_BG = '#171029'
LOG_TEXT = '#DAD6E6'
LOG_DIM = '#6E6A82'

# ---------------------------------------------------------------- 字体
FONT_FAMILY = ('"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", '
               '"Segoe UI", "Helvetica Neue", sans-serif')
FONT_STACK = ['Microsoft YaHei UI', 'Microsoft YaHei', 'PingFang SC',
              'Segoe UI', 'Helvetica Neue', 'sans-serif']
MONO_STACK = ['Cascadia Mono', 'Consolas', 'SF Mono', 'Menlo', 'monospace']


def ui_font(px: float, weight: int = 400, mono: bool = False,
            track: float = 0.0) -> QFont:
    """按规范的层级取字体。只有 400 / 600 / 700 三档，没有 500。

    track 是小字号承担「标签」角色时的字距（Qt 样式表不支持
    letter-spacing，所以只能用 QFont.setLetterSpacing）。
    """
    f = QFont()
    f.setFamilies(MONO_STACK if mono else FONT_STACK)
    # Qt 的 setPointSizeF 受 DPI 影响，用像素字号才能和规范的 px 对齐
    f.setPixelSize(max(1, int(round(px))))
    f.setWeight(QFont.Weight(weight))
    if track:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, track)
    return f


def install_app_font(app, px=None):
    """
    设一个全局默认字体。

    为什么需要：Qt 默认字体的中文回退在有些 Windows 上是宋体，正文会显得
    又细又散，和这套设计语言不符。这里统一成界面字体，中英文都由它回退。
    """
    f = ui_font(px or FS_BODY, 400)
    app.setFont(f)
    return f


# 字号层级（第三节表格）
FS_BRAND_TITLE = 40     # 700  只在登录页左栏
FS_PAGE_TITLE = 33      # 700  每页一个
FS_STAT_VALUE = 30      # 700  等宽数字
FS_BIG_STATE = 27       # 700  监听中 / 已完成
FS_FORM_TITLE = 26      # 700  登录卡片
FS_CARD_TITLE = 19      # 700
FS_SECTION = 15.5       # 600
FS_WORDMARK = 15.5      # 600
FS_BRAND_SUB = 14.5     # 400
FS_PAGE_SUB = 14        # 400
FS_BODY = 13            # 400 / 600
FS_META = 12.5          # 600  字距 1.2px

TRACK_META = 1.2        # 小字号承担「标签」角色时的字距

# ---------------------------------------------------------------- 圆角
R_SM = 8
R_IN = 11
R_MD = 14
R_CARD = 20
R_PILL = 22
R_ROUND = 999


def qc(value, alpha: float = 1.0) -> QColor:
    """把令牌转成 QColor。支持 '#RRGGBB' 和 (r, g, b, a) 两种写法。"""
    c = QColor(value) if isinstance(value, str) else QColor(*value)
    if alpha < 1.0:
        c.setAlphaF(c.alphaF() * alpha)
    return c


def rgba(value, alpha: float) -> QColor:
    """取某令牌颜色、指定透明度 —— 用于自绘时的分层叠加。"""
    c = QColor(value) if isinstance(value, str) else QColor(*value)
    c.setAlphaF(alpha)
    return c


# ---------------------------------------------------------------- 窗口骨架
# 侧边栏 + 主工作区。原设计稿是「顶部天幕 + 居中导航胶囊 + 步骤导轨」，
# 那是为一次性流程（选课提交）做的；下载器是重复使用的工具，
# 需要的是稳定的导航和尽量大的内容区，所以天幕收进侧边栏顶部。
SIDEBAR_W = 220
SKY_PANEL_H = 104       # 侧边栏顶部天幕的高度
SKY_PANEL_FADE = 30     # 天幕往下化开的高度
NAV_ITEM_H = 42         # 侧边栏导航项
NAV_ITEM_GAP = 3
WORKSPACE_HEAD_H = 62   # 工作区标题行
STATUS_STRIP_H = 46     # 底部全局进度条（仅在队列运行时出现）

WIN_W = 1280
# 860 = 820（原本的内容区高度）+ 40（自绘标题栏）。加了标题栏之后窗口要跟着
# 长高，否则设置页会平白多出一条滚动条 —— 加外壳不该吃掉内容的空间。
WIN_H = 860

# ---------------------------------------------------------------- 组件内边距
PAD_CARD = (24, 22, 24, 22)
GAP_CARD = 14
PAD_STAT_TILE = (20, 17, 20, 17)
GAP_STAT_TILE = 9
PAD_PAGE = (32, 22, 32, 24)      # 工作区内容：左右 32、上 22、下 24
GAP_PAGE = 16
PAD_BOOK_CARD = (14, 14, 14, 14)
GAP_BOOK_CARD = 9
COVER_W = 132           # 书库封面的显示宽度
COVER_H = 176
GRID_GAP = 16           # 书库网格间距
GRID_MIN_W = 188        # 书库卡片最小宽度（响应式列数的依据）

# ---------------------------------------------------------------- 投影
# 淡紫主色下投影也必须偏紫，用中性灰会在卡片边缘泛出一圈脏灰。
SHADOW_SPECS = {
    #        blur, dx, dy, (r, g, b), alpha
    'card':    (30, 0, 7, (38, 28, 74), 22),
    'raised':  (48, 0, 17, (34, 24, 68), 42),
    'glass':   (22, 0, 8, (10, 6, 26), 48),
    'glow':    (28, 0, 9, (111, 92, 173), 78),
    'glow_hi': (38, 0, 14, (111, 92, 173), 120),
    'panel':   (40, 0, 14, (12, 8, 30), 62),
}


def shadow_spec(level: str):
    """shadow_spec(level) -> (blur, dx, dy, r, g, b, alpha)"""
    return SHADOW_SPECS[level]


# ---------------------------------------------------------------- 动效
class motion:
    """
    统一缓动：快出慢收，没有回弹。

    这里只留「说明发生了什么」的动效时长。页面切换的「粒子渐变揭示」已经
    删掉了（用户明确说切页时那层会动的雾看着不舒服）—— 它是纯装饰，
    不提示任何状态。所以 DUR_PAGE / REVEAL_BAND / REVEAL_MASK_DIV / TICK_MS
    这些只服务于它的令牌也一并去掉，免得留下一堆没人读的常量。
    """
    ENABLED = True
    EASE_QT = 'OutCubic'          # QEasingCurve.OutCubic
    EASE_CSS = 'cubic-bezier(.22, 1, .36, 1)'

    DUR_CARD_IN = 420             # 卡片入场
    DUR_HOVER = 230               # 悬停抬起
    DUR_DATA_IN = 340             # 数据入场
    DUR_COUNT_UP = 520            # 统计数字滚动


# ---------------------------------------------------------------- 天幕变体
SKY_VARIANTS = ['rose', 'cool', 'warm', 'violet', 'deep']

VARIANTS = {
    # ys_band: (cy, rx, ry, rot) 三段极光带
    'rose': dict(
        ys_band=[(0.10, 0.95, 0.34, -8), (0.46, 0.86, 0.30, 6), (0.82, 0.98, 0.32, -4)],
        alphas=(0.46, 0.34, 0.30), stars=1.0, top_shift=0.0,
        c1=SKY_AURORA_B, c2=SKY_AURORA_A, c3=SKY_AURORA_C, glow=SKY_GLOW, glow_a=0.20),
    'cool': dict(
        ys_band=[(0.06, 0.92, 0.30, -10), (0.44, 0.90, 0.34, 8), (0.80, 1.02, 0.30, -6)],
        alphas=(0.50, 0.40, 0.34), stars=1.55, top_shift=-0.02,
        c1=SKY_AURORA_C, c2=SKY_AURORA_A, c3=SKY_AURORA_C, glow=SKY_AURORA_A, glow_a=0.22),
    'warm': dict(
        ys_band=[(0.12, 0.98, 0.36, -6), (0.50, 0.82, 0.28, 10), (0.84, 0.94, 0.30, -2)],
        alphas=(0.52, 0.30, 0.26), stars=0.95, top_shift=0.01,
        c1=SKY_AURORA_B, c2=SKY_GLOW, c3=SKY_AURORA_A, glow=SKY_GLOW, glow_a=0.26),
    'violet': dict(
        ys_band=[(0.08, 0.94, 0.32, -8), (0.46, 0.88, 0.32, 6), (0.82, 0.98, 0.32, -4)],
        alphas=(0.48, 0.36, 0.30), stars=1.25, top_shift=0.0,
        c1=SKY_AURORA_A, c2=SKY_AURORA_C, c3=SKY_AURORA_B, glow=SKY_GLOW, glow_a=0.20),
    'deep': dict(
        ys_band=[(0.04, 0.90, 0.26, -12), (0.40, 0.94, 0.30, 9), (0.78, 1.04, 0.26, -7)],
        alphas=(0.34, 0.26, 0.22), stars=2.15, top_shift=-0.03,
        c1=SKY_AURORA_C, c2=SKY_AURORA_A, c3=SKY_AURORA_C, glow=SKY_AURORA_C, glow_a=0.14),
}

# 页面与变体的对应关系
PAGE_VARIANTS = ['rose', 'cool', 'warm', 'violet', 'deep']
