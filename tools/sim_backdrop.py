# coding:utf-8
"""
把候选背景按「真实裁剪规则」摆出来，并压上真实位置的文字，用来判断可读性。

裁剪规则来自 backdrop.py 的 _paint_base：
    scaled = image.scaled(w, sh, KeepAspectRatioByExpanding, Smooth)
    draw   = scaled[居中裁剪 w x sh]
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)
from tests._isolate import isolate  # noqa: E402
isolate()

from crawler.gui import theme as T  # noqa: E402

FONT = r'C:\Windows\Fonts\msyh.ttc'
FONT_B = r'C:\Windows\Fonts\msyhbd.ttc'
CAND = ['b1.jpg', 'b2.jpg', 'b3.jpg', 'c1.jpg', 'c2.jpg']


def crop_like(img, w, h):
    """复刻 KeepAspectRatioByExpanding + 居中裁剪。"""
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    sw, sh = max(w, int(round(iw * scale))), max(h, int(round(ih * scale)))
    s = img.resize((sw, sh), Image.LANCZOS)
    left = (sw - w) // 2
    top = (sh - h) // 2
    return s.crop((left, top, left + w, top + h))


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def text(d, xy, s, f, fill=(255, 255, 255), anchor='la'):
    d.text(xy, s, font=f, fill=fill, anchor=anchor)


def main():
    # 登录页左栏：逻辑 527x822（1920 物理宽下量出来的），按 1x 模拟
    LW, LH = 527, 822
    # 侧边栏天幕：220x104
    SW, SH = T.SIDEBAR_W, T.SKY_PANEL_H

    pad, gap = 16, 14
    cellw = LW + SW + 40
    colw = cellw + pad * 2
    rowh = LH + 40
    sheet = Image.new('RGB', (colw * len(CAND), 28 + rowh + pad * 2), (14, 14, 18))
    d = ImageDraw.Draw(sheet)

    f_title = font(FONT_B, 40)
    f_sub = font(FONT, 13)
    f_feat = font(FONT_B, 14)
    f_featd = font(FONT, 12)
    f_foot = font(FONT, 11)
    f_side = font(FONT_B, 15)
    f_sidesub = font(FONT, 11)

    for i, name in enumerate(CAND):
        src = Image.open(os.path.join(_ROOT, '_smoke', 'gen', name)).convert('RGB')
        ox = i * colw + pad
        oy = 28 + pad

        text(d, (ox, 8 + i * 0), name, font(FONT, 13), (230, 230, 236))

        # ---- 登录页左栏 ----
        big = crop_like(src, LW, LH)
        # 现有代码会压一层 PRIMARY_DEEP 45%
        scrim = Image.new('RGB', big.size, tuple(
            int(T.PRIMARY_DEEP.lstrip('#')[j:j + 2], 16) for j in (0, 2, 4)))
        big = Image.blend(big, scrim, 0.45)
        sheet.paste(big, (ox, oy))
        dd = ImageDraw.Draw(sheet)
        text(dd, (ox + 30, oy + int(LH * 0.115)), '清华教参下载器', f_title)
        text(dd, (ox + 30, oy + int(LH * 0.115) + 52), '电子教材 PDF 下载工具',
             f_sub, (232, 228, 245))
        for k, (t1, t2) in enumerate((('批量排队', '一次粘多条链接，一本一本下完'),
                                      ('书库管理', '封面、书名、页数，随时找回来'),
                                      ('Token 续期', '失效自动重新获取，不用重来'))):
            y = oy + int(LH * 0.47) + k * 62
            dd.ellipse((ox + 30, y + 4, ox + 38, y + 12), fill=(255, 255, 255))
            text(dd, (ox + 52, y - 4), t1, f_feat)
            text(dd, (ox + 52, y + 18), t2, f_featd, (226, 222, 240))
        text(dd, (ox + 30, oy + int(LH * 0.955)), '仅供个人学习研究使用 · 请遵守版权规定',
             f_foot, (216, 212, 232))

        # ---- 侧边栏天幕 ----
        sx = ox + LW + gap
        small = crop_like(src, SW, SH)
        scrim2 = Image.new('RGB', small.size, tuple(
            int(T.PRIMARY_DEEP.lstrip('#')[j:j + 2], 16) for j in (0, 2, 4)))
        small = Image.blend(small, scrim2, 0.45)
        sheet.paste(small, (sx, oy))
        dd2 = ImageDraw.Draw(sheet)
        text(dd2, (sx + SW // 2, oy + int(SH * 0.42)), '清华教参下载器',
             f_side, (255, 255, 255), anchor='mm')
        text(dd2, (sx + SW // 2, oy + int(SH * 0.66)), '电子教材 PDF',
             f_sidesub, (226, 222, 240), anchor='mm')

    out = os.path.join(_ROOT, '_smoke', 'gen', 'sim.png')
    sheet.save(out)
    print('wrote', out, sheet.size)


if __name__ == '__main__':
    main()
