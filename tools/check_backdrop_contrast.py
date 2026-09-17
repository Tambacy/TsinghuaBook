# coding:utf-8
"""
量「压在天幕上的白字」够不够清楚。

天幕底下的画面是艺术，压在天幕上的字是可读性责任：只要有一行字落在画面
最亮的那一带，那行字就废了。这个工具把真实的控件树建出来、抓真实的天幕
渲染结果，然后按每个文字控件的真实几何去算 WCAG 对比度，取最差的那个像素。

阈值（WCAG 2.1 AA）：
  正常字号 4.5:1，大字号（>=18.66px 粗体 / >=24px）3:1。

为什么要建真实控件树：文字位置是布局算出来的（两个 stretch 夹着卖点，
页脚贴底），手写坐标迟早和实际渲染对不上。
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

from tests._isolate import isolate  # noqa: E402

isolate()

from PyQt6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from xk_app.app.gui import theme as T  # noqa: E402

# 登录页左栏在 1920 物理宽下量到的逻辑尺寸
BRAND_W, BRAND_H = 527, 822

FAILS = []


def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def rel_lum(rgb):
    r, g, b = (_lin(v) for v in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(c1, c2):
    l1, l2 = rel_lum(c1), rel_lum(c2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def parse_color(css, default=(255, 255, 255, 255)):
    """从样式表里抠出 color / rgba()。"""
    import re
    if not css:
        return default
    m = re.search(r'color\s*:\s*([^;]+)', css)
    if not m:
        return default
    v = m.group(1).strip()
    m = re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)', v)
    if m:
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(round(a * 255)))
    m = re.match(r'#([0-9a-fA-F]{6})', v)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
    return default


def _pixels(img):
    """QImage -> (bytes, stride)，Format_RGB32 每像素 4 字节 BGRA。"""
    im = img.convertToFormat(QImage.Format.Format_RGB32)
    ptr = im.constBits()
    ptr.setsize(im.sizeInBytes())
    return bytes(ptr), im.bytesPerLine(), im.width(), im.height()


def worst_contrast(buf, stride, iw, ih, rect, fg):
    """文字矩形内最差（最亮背景）的对比度。文字半透明时先和背景合成。"""
    worst = 99.0
    bright = None
    x0 = max(0, rect.left())
    y0 = max(0, rect.top())
    x1 = min(iw, rect.right() + 1)
    y1 = min(ih, rect.bottom() + 1)
    if x1 <= x0 or y1 <= y0:
        return None, None
    a = fg[3] / 255.0
    step = 1 if (x1 - x0) * (y1 - y0) <= 40000 else 2
    for y in range(y0, y1, step):
        row = y * stride
        for x in range(x0, x1, step):
            o = row + x * 4
            bg = (buf[o + 2], buf[o + 1], buf[o])
            # 半透明文字：实际看到的是它和背景的合成色
            eff = tuple(int(fg[i] * a + bg[i] * (1 - a)) for i in range(3))
            c = contrast(eff, bg)
            if c < worst:
                worst = c
                bright = bg
    return worst, bright


def check(tag, widget, rect, sky_img):
    buf, stride, iw, ih = _pixels(sky_img)
    fg = parse_color(widget.styleSheet())
    wc, bg = worst_contrast(buf, stride, iw, ih, rect, fg)
    if wc is None:
        return
    px = max(widget.font().pixelSize(), 1)
    large = px >= 24 or (px >= 18 and widget.font().bold())
    need = 3.0 if large else 4.5
    ok = wc >= need
    if not ok:
        FAILS.append('%s「%s」%.2f:1 < %.1f:1'
                     % (tag, widget.text(), wc, need))
    print('  %-4s %-22s %5.2f:1  (需要 %.1f:1)  %dpx%s  最亮背景 rgb%s'
          % ('OK' if ok else 'FAIL', widget.text()[:22], wc, need, px,
             ' 粗' if widget.font().bold() else '', bg))


def glyph_rect(lb, panel):
    """
    文字控件在 panel 坐标系里的**字形**矩形。

    不能用控件矩形：wrap=True 的 QLabel 会一路铺到布局右边，右半截明明
    是空白，却会被当成「背景太亮」——那是在量空白处，不是量字。字形矩形
    用 QFontMetrics 按真实换行和对齐算，量到的才是真正压在画上的那几行。
    """
    fm = lb.fontMetrics()
    local = fm.boundingRect(QRect(0, 0, lb.width(), lb.height()),
                            int(lb.alignment()) | int(Qt.TextFlag.TextWordWrap),
                            lb.text())
    # 宽度给一点余量：抗锯齿会让最右边一列笔画落在字形矩形之外
    local.adjust(0, 0, 2, 0)
    return QRect(lb.mapTo(panel, QPoint(0, 0)), lb.size()).intersected(
        QRect(lb.mapTo(panel, local.topLeft()), local.size()))


def walk(root, panel):
    out = []
    for lb in root.findChildren(QLabel):
        if not lb.isVisible() or not lb.text().strip():
            continue
        r = glyph_rect(lb, panel)
        if r.width() > 0 and r.height() > 0:
            out.append((lb, r))
    return out


def main():
    app = QApplication(sys.argv)
    ok = True

    print('=== 登录页左栏（%dx%d）===' % (BRAND_W, BRAND_H))
    from xk_app.app.gui.login import BrandPanel
    bp = BrandPanel()
    bp.resize(BRAND_W, BRAND_H)
    bp.show()
    app.processEvents()
    bp.sky.repaint()
    app.processEvents()
    sky_img = bp.sky.grab().toImage()
    for lb, r in walk(bp.overlay, bp):
        check('左栏', lb, r, sky_img)

    print()
    print('=== 侧边栏天幕（%dx%d）===' % (T.SIDEBAR_W, T.SKY_PANEL_H))
    from xk_app.app.gui.sidebar import Sidebar
    sb = Sidebar()
    sb.resize(T.SIDEBAR_W, 700)
    sb.show()
    app.processEvents()
    sb.sky.sky.repaint()
    app.processEvents()
    sky_img2 = sb.sky.sky.grab().toImage()
    # 文字在 slot 里，slot 和 sky 同一坐标系
    for lb in (sb.app_name, sb.app_sub):
        r = QRect(lb.mapTo(sb.sky.sky, QPoint(0, 0)), lb.size())
        check('侧栏', lb, r, sky_img2)

    print()
    if FAILS:
        ok = False
        print('CONTRAST FAIL  有 %d 处读不清：' % len(FAILS))
        for f in FAILS:
            print('   - ' + f)
    else:
        print('CONTRAST OK  白字全都压得住')
    from xk_app.app.gui import backdrop as BD
    print('  左栏主视觉: %s' % (BD._find_asset('login_hero') or '（无，退回 backdrop）'))
    print('  侧栏底图  : %s' % (BD._find_backdrop() or '（无，用程序化天幕）'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
