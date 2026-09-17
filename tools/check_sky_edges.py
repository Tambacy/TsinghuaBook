# coding:utf-8
"""
量天幕 + 化开区**四条边**有没有「孤立暗行 / 暗列」。

为什么需要这个工具
------------------
`grab()` 是离屏渲染，看不到合成器在**控件边界**上做的那一次重采样 ——
所以这个缺陷以前一直躲过了所有守卫。只有抓真实窗口（或屏幕）才量得到。
本工具打开真实窗口，用 PrintWindow 抓整窗位图，再按标定好的边界逐行/逐列
量。判据都是「相邻两行/两列差多少」，与绝对颜色无关，所以换 dpr 也能用。

量什么
------
一、**接缝**（化开区底边）：逐列看「化开区最后一行 → 下一行」的亮度跳变，
    不允许出现「比上下两邻都暗」的行。
二、**右边**（侧边栏右边界）：化开区那几行里，侧边栏最后一列不允许比左邻列
    暗超过 EDGE_TOL。这一条以前是漏的 —— 用户的原话是「右边的边怎么不一并
    去掉」。
三、**左边**：化开区那几行里，第 0 列不允许比右邻列暗超过 EDGE_TOL。
四、**上边**：天幕上沿不允许比下面几行暗（那会是一道压在品牌区上的黑边）。

用法
----
    .\\venv\\Scripts\\python.exe tools\\check_sky_edges.py
退出码 0 = 通过。
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from tests._isolate import isolate  # noqa: E402

_CFG = isolate()

from PyQt6.QtWidgets import QApplication  # noqa: E402

from xk_app.app.gui import theme as T  # noqa: E402

# 侧边栏最后一列相对左邻列允许暗多少（灰阶）。合成器的边缘重采样会吃掉
# 20~45 个灰阶，正常绘制下这个值应当接近 0，留 4 个灰阶余量。
EDGE_TOL = 4.0
# 接缝那一行相对上下两邻允许的跳变
SEAM_TOL = 6.0
# 窗口最外圈这几列/行是 DWM 的圆角边框，不是我们画的内容，量内容边界时跳过
FRAME_PX = 2

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.SetProcessDPIAware()
PW_RENDERFULLCONTENT = 0x00000002


class RECT(ctypes.Structure):
    _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                ('right', ctypes.c_long), ('bottom', ctypes.c_long)]


class BIH(ctypes.Structure):
    _fields_ = [('biSize', wt.DWORD), ('biWidth', ctypes.c_long),
                ('biHeight', ctypes.c_long), ('biPlanes', wt.WORD),
                ('biBitCount', wt.WORD), ('biCompression', wt.DWORD),
                ('biSizeImage', wt.DWORD), ('biXPelsPerMeter', ctypes.c_long),
                ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', wt.DWORD),
                ('biClrImportant', wt.DWORD)]


def grab_window(hwnd, w, h):
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT)
    bi = BIH()
    bi.biSize = ctypes.sizeof(BIH)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    return Image.frombuffer('RGB', (w, h), buf, 'raw', 'BGRX', 0, 1)


def main():
    app = QApplication(sys.argv)
    T.install_app_font(app)
    from xk_app.app.gui.shell import MainWindow

    win = MainWindow()
    win.resize(T.WIN_W, T.WIN_H)
    win.show()
    for _ in range(40):
        app.processEvents()
    time.sleep(0.6)
    for _ in range(20):
        app.processEvents()

    hwnd = int(win.winId())
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    img = grab_window(hwnd, w, h)
    dpr = win.devicePixelRatio()
    sb_w = win.sidebar.width()
    sb_h = win.sidebar.height()

    out = os.path.join(_ROOT, '_smoke', 'sky_edges.png')
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        img.save(out)
    except Exception:
        out = None

    print('窗口 %dx%d  dpr=%.2f  侧边栏 %dx%d' % (w, h, dpr, sb_w, sb_h))
    if out:
        print('位图 -> %s' % out)

    # ---- 标定侧边栏右边界：找「一行里由暗突变到工作区浅色」的位置
    probe_y = int((T.TITLEBAR_H + T.SKY_PANEL_H * 0.5) * dpr)
    edge_x = None
    for x in range(int(sb_w * dpr) - 60, min(int(sb_w * dpr) + 60, w - 1)):
        if x < 1:
            continue
        l0 = sum(img.getpixel((x, probe_y))) / 3.0
        l1 = sum(img.getpixel((x + 1, probe_y))) / 3.0
        if l1 - l0 > 100:
            edge_x = x
            break
    if edge_x is None:
        print('!! 标定不到侧边栏右边界')
        return 1

    # ---- 标定天幕上沿
    top_y = None
    cx = max(2, int(sb_w * dpr * 0.5))
    for y in range(int(T.TITLEBAR_H * dpr) - 4, int(T.TITLEBAR_H * dpr) + 60):
        if y < 1 or y + 1 >= h:
            continue
        l0 = sum(img.getpixel((cx, y))) / 3.0
        l1 = sum(img.getpixel((cx, y + 1))) / 3.0
        if l0 > 180 and l1 < 120:
            top_y = y + 1
            break
    if top_y is None:
        print('!! 标定不到天幕上沿')
        return 1

    # 化开区在抓图里的行范围：天幕上沿 + sky_h*dpr .. +fade_h*dpr
    fade_top = top_y + int(T.SKY_PANEL_H * dpr)
    fade_bot = fade_top + int(T.SKY_PANEL_FADE * dpr)
    print('侧边栏右边界 x=%d   天幕上沿 y=%d   化开区 y=%d..%d'
          % (edge_x, top_y, fade_top, fade_bot))

    ok = True
    xs = [int(sb_w * dpr * f) for f in (0.2, 0.4, 0.6, 0.8)]

    # ---- 一、接缝：化开区底边不许有孤立暗行
    print()
    print('一、接缝（化开区底边）')
    worst_seam = 0.0
    for y in range(fade_bot - 3, min(fade_bot + 4, h - 1)):
        m = sum(sum(img.getpixel((x, y))) / 3.0 for x in xs) / len(xs)
        up = sum(sum(img.getpixel((x, y - 1))) / 3.0 for x in xs) / len(xs)
        dn = sum(sum(img.getpixel((x, y + 1))) / 3.0 for x in xs) / len(xs)
        if m < up - SEAM_TOL and m < dn - SEAM_TOL:
            print('  !! y=%d 是孤立暗行  本行 %.1f  上邻 %.1f  下邻 %.1f'
                  % (y, m, up, dn))
            ok = False
        worst_seam = min(worst_seam, m - up)
    print('  最负逐行跳变 %+.1f（阈值 %.1f）' % (worst_seam, -SEAM_TOL))

    # ---- 二、右边：侧边栏最后一列不许比左邻暗
    print()
    print('二、右边（侧边栏右边界）')
    worst_r = 0.0
    for y in range(fade_top, fade_bot + 1):
        last = sum(img.getpixel((edge_x, y))) / 3.0
        prev = sum(img.getpixel((edge_x - 1, y))) / 3.0
        worst_r = min(worst_r, last - prev)
        if last < prev - EDGE_TOL:
            print('  !! y=%d 最后一列比左邻暗 %.1f  (%.1f vs %.1f)'
                  % (y, prev - last, last, prev))
            ok = False
    print('  最后一列相对左邻最暗 %+.1f（阈值 -%.1f）' % (worst_r, EDGE_TOL))

    # ---- 三、左边：内容第 0 列不许比右邻暗
    #
    # 最外面 FRAME_PX 列是**窗口边框**：DWM 会在无边框窗口的最外圈做圆角
    # 抗锯齿，那几列永远是浅色（实测 (213,208,227) / (229,225,238)，整列
    # 不变），它不是我们画的内容。从 FRAME_PX 开始量才是真正的「内容左边界」。
    print()
    print('三、左边（内容左边界，跳过窗口边框 %d 列）' % FRAME_PX)
    worst_l = 0.0
    for y in range(fade_top, fade_bot + 1):
        first = sum(img.getpixel((FRAME_PX, y))) / 3.0
        nxt = sum(img.getpixel((FRAME_PX + 1, y))) / 3.0
        worst_l = min(worst_l, first - nxt)
        if first < nxt - EDGE_TOL:
            print('  !! y=%d 内容第 0 列比右邻暗 %.1f' % (y, nxt - first))
            ok = False
    print('  内容第 0 列相对右邻最暗 %+.1f（阈值 -%.1f）' % (worst_l, EDGE_TOL))

    # ---- 四、上边：天幕上沿不许比下面暗
    #
    # 上沿同理：顶上那几行是标题栏，天幕第一行由标定的 top_y 给出。
    print()
    print('四、上边（天幕上沿）')
    worst_t = 0.0
    for x in xs:
        first = sum(img.getpixel((x, top_y))) / 3.0
        nxt = sum(img.getpixel((x, top_y + 1))) / 3.0
        worst_t = min(worst_t, first - nxt)
        if first < nxt - EDGE_TOL:
            print('  !! x=%d 天幕第一行比下一行暗 %.1f' % (x, nxt - first))
            ok = False
    print('  天幕第一行相对下一行最暗 %+.1f（阈值 -%.1f）' % (worst_t, EDGE_TOL))

    print()
    print('SKY EDGES %s' % ('OK' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
