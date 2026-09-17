# coding:utf-8
"""
生成应用图标 xk_app/assets/app.ico（以及 app.png / logo*.png）。

为什么用脚本画、而且**每个尺寸单独画**：
  1. 把一张 256 的图硬缩到 16px，细节会糊成一团。真实图标集都是「光学尺寸」——
     小尺寸减细节、加粗笔画。这里分三档：>=64 完整 / 32~48 中等 / <32 只留形状。
  2. 可复现。改品牌色、改造型都只改这个文件。

造型语义：一本白色的书（左边书脊 + 两条正文线），中间一个向下的箭头 ——
「把教参下下来」。底色用设计系统里的品牌紫（theme.PRIMARY 那一族）。
不用星空噪点：那东西在 16px 下只会变成一片脏点。

小尺寸用 DIB 内嵌、大尺寸用 PNG —— 部分老 shell 路径对全 PNG 的 ICO
支持不完整，而 PNG 能显著压小 256 那张的体积。

用法：
    python tools\\make_icon.py             # 生成
    python tools\\make_icon.py --preview   # 顺带拼一张各尺寸预览图
"""
import os
import struct
import sys

from PIL import Image, ImageDraw, ImageFilter

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
OUT_DIR = os.path.join(_ROOT, 'xk_app', 'assets')

# ---------------------------------------------------------------- 品牌色
TILE_TOP = (138, 120, 204)      # #8A78CC
TILE_BOT = (91, 74, 150)        # #5B4A96   —— 和 theme.PRIMARY #6F5CAD 同族
ARROW = (111, 92, 173)          # #6F5CAD
LINE = (201, 193, 226)          # #C9C1E2
PAPER = (255, 255, 255)

SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
SS = 8                          # 超采样倍数


def _tier(px):
    if px >= 64:
        return 'full'
    if px >= 32:
        return 'medium'
    return 'simple'


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def draw_icon(px):
    """画一张 px*px 的图标，内部按 SS 倍超采样再缩。"""
    N = px * SS
    tier = _tier(px)
    img = Image.new('RGBA', (N, N), (0, 0, 0, 0))

    # ---- 底板：斜向渐变 + 圆角
    # 斜着来是为了和天幕底图（assets/backdrop.jpg）同向 —— 那块的光也是从左上
    # 压下来的。竖向渐变单看没问题，和底图并排就不像同一个品牌里的东西。
    # 渐变先在 GS×GS 上算好再放大：它本身平滑，放大不丢东西，而在 2048² 上
    # 一像素一像素算纯属浪费。
    GS = 192
    small = Image.new('RGB', (GS, GS))
    sp = small.load()
    for y in range(GS):
        for x in range(GS):
            sp[x, y] = _lerp(TILE_TOP, TILE_BOT,
                             min(1.0, (x * 0.55 + y * 0.45) / (GS - 1.0)))
    grad = small.resize((N, N), Image.BILINEAR)

    radius = int(round(0.225 * N))
    mask = Image.new('L', (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, N - 1, N - 1),
                                           radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)

    # 左上角一团柔光 —— 给那道斜光一个来处。很淡，缩到 16px 就是一层平滑的
    # 明暗，不会变成噪点。
    glow = Image.new('L', (GS, GS), 0)
    gp = glow.load()
    gx, gy, gr = 0.30 * GS, 0.20 * GS, 0.95 * GS
    for y in range(GS):
        for x in range(GS):
            dd = ((x - gx) ** 2 + (y - gy) ** 2) ** 0.5 / gr
            if dd < 1.0:
                gp[x, y] = int(36 * (1.0 - dd) ** 2)
    light = Image.new('RGBA', (N, N), (255, 255, 255, 0))
    light.putalpha(glow.resize((N, N), Image.BILINEAR))
    img.alpha_composite(Image.composite(
        light, Image.new('RGBA', (N, N), (0, 0, 0, 0)), mask))

    # ---- 白色纸面；小尺寸把纸面放大，别浪费像素
    P = lambda v: int(round(v * N))                                  # noqa: E731
    if tier == 'simple':
        x0, y0, x1, y1, rr = 0.185, 0.115, 0.815, 0.885, 0.105
    else:
        x0, y0, x1, y1, rr = 0.245, 0.145, 0.755, 0.855, 0.080

    # 纸面投影：让白纸从底板上浮起来。只有完整档画 —— 小尺寸每一个像素都该
    # 用来画形状，糊一层灰只会让 16px 更脏，而这正是图标最容易做砸的地方。
    if tier == 'full':
        sh = Image.new('L', (N, N), 0)
        ImageDraw.Draw(sh).rounded_rectangle(
            [P(x0), P(y0 + 0.010), P(x1 + 0.004), P(y1 + 0.018)],
            radius=P(rr), fill=120)
        sh = sh.filter(ImageFilter.GaussianBlur(N * 0.016))
        ink = Image.new('RGBA', (N, N), (24, 15, 48, 0))
        ink.putalpha(sh)
        img.alpha_composite(ink)

    d = ImageDraw.Draw(img)
    d.rounded_rectangle([P(x0), P(y0), P(x1), P(y1)], radius=P(rr), fill=PAPER)

    # ---- 书脊（只有完整档才画）
    if tier == 'full':
        sx1 = x0 + 0.085
        d.rounded_rectangle([P(x0), P(y0), P(sx1), P(y1)],
                            radius=P(rr * 0.55), fill=LINE)
        d.rectangle([P(sx1 - 0.004), P(y0 + 0.01), P(sx1 + 0.02), P(y1 - 0.01)],
                    fill=PAPER)          # 书脊与正文之间那条白缝

    # ---- 正文两条短线（小了就是糊，只有完整档画）。
    # 要短、要细、要和箭头拉开距离，否则整张图会挤成一坨「汉堡菜单压箭头」。
    if tier == 'full':
        for i, (ty, tx1) in enumerate(((0.240, 0.655), (0.318, 0.575))):
            d.rounded_rectangle([P(x0 + 0.130), P(ty), P(tx1), P(ty + 0.042)],
                                radius=P(0.021), fill=LINE)

    # ---- 下载箭头（主角）。杆要细长、头要宽扁，才像「下载」而不是「图钉」。
    # 参考比例：杆长约等于 1.2 倍箭头高，箭头宽约为杆宽 3 倍。
    if tier == 'simple':
        stem, top, bot, hw, hh = 0.135, 0.290, 0.560, 0.450, 0.235
    elif tier == 'medium':
        stem, top, bot, hw, hh = 0.100, 0.300, 0.575, 0.370, 0.195
    else:
        stem, top, bot, hw, hh = 0.086, 0.388, 0.598, 0.288, 0.172

    cx = 0.50
    half = stem / 2.0
    d.rounded_rectangle([P(cx - half), P(top), P(cx + half), P(bot)],
                        radius=P(stem * 0.34), fill=ARROW)
    d.polygon([(P(cx - hw / 2), P(bot)), (P(cx + hw / 2), P(bot)),
               (P(cx), P(bot + hh))], fill=ARROW)

    return img.resize((px, px), Image.LANCZOS)


# ---------------------------------------------------------------- 封装
def _bmp_entry(img):
    """
    内嵌 DIB。小尺寸用这个兼容性最好；AND 掩码在 32bpp 下不使用，
    但格式要求存在，每行按 4 字节对齐。
    """
    w, h = img.size
    px = img.load()
    rows = []
    for y in range(h - 1, -1, -1):          # DIB 自下而上
        row = bytearray()
        for x in range(w):
            r, g, b, a = px[x, y]
            row += bytes((b, g, r, a))
        rows.append(bytes(row))
    xor = b''.join(rows)
    stride = ((w + 31) // 32) * 4
    and_mask = b'\x00' * (stride * h)
    header = struct.pack('<IiiHHIIiiII', 40, w, h * 2, 1, 32, 0,
                         len(xor) + len(and_mask), 0, 0, 0, 0)
    return header + xor + and_mask


def _png_entry(img):
    import io
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def build_ico(out_path, sizes=SIZES):
    entries = []
    for px in sizes:
        img = draw_icon(px)
        entries.append((px, _png_entry(img) if px >= 64 else _bmp_entry(img)))

    n = len(entries)
    header = struct.pack('<HHH', 0, 1, n)
    offset = 6 + 16 * n
    dirs, blobs = b'', b''
    for px, data in entries:
        w = 0 if px >= 256 else px
        dirs += struct.pack('<BBBBHHII', w, w, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    with open(out_path, 'wb') as fh:
        fh.write(header + dirs + blobs)
    return [(px, len(d)) for px, d in entries]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    ico = os.path.join(OUT_DIR, 'app.ico')
    info = build_ico(ico)
    print('wrote', ico, os.path.getsize(ico), 'bytes')
    for px, size in info:
        print('   %3dx%-3d %8d B' % (px, px, size))

    for px, name in ((256, 'app.png'), (32, 'logo32.png'),
                     (64, 'logo64.png'), (256, 'logo256.png')):
        p = os.path.join(OUT_DIR, name)
        draw_icon(px).save(p)
        print('wrote', p)

    if '--preview' in sys.argv:
        sheet = Image.new('RGBA', (1040, 300), (244, 243, 249, 255))
        x = 24
        for px in SIZES:
            sheet.alpha_composite(draw_icon(px), (x, 40 + (128 - px) // 2))
            x += px + 24
        p = os.path.join(_ROOT, '_smoke', 'icon_sheet.png')
        os.makedirs(os.path.dirname(p), exist_ok=True)
        sheet.save(p)
        print('preview ->', p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
