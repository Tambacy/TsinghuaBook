# coding:utf-8
"""
生成书库封面底图。

为什么要成套而不是一张：书库网格里十几本书并排，如果共用一张底图，看过去
还是「一片紫」；而真正换来「像一本书」的关键，是每本书的底图各不相同、又
同属一个色系。所以这里出 8 张，按书名哈希稳定分配 —— 同一本书永远同一张。

成品是「底图」，标题和作者仍然由 widgets.py 排版叠上去，所以提示词里反复
强调 NO text：模型只要漏出一个字母，就会和真标题打架。

    python tools\\make_covers.py            # 只补缺的
    python tools\\make_covers.py --force    # 全部重出

源图放 tools/art/（不进包），成品放 xk_app/assets/covers/（进包）。
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

from gen_image import generate  # noqa: E402

SRC_DIR = os.path.join(_HERE, 'art')
OUT_DIR = os.path.join(_ROOT, 'xk_app', 'assets', 'covers')

# 成品尺寸：3:4 竖版，卡面宽 132pt 时 3x 屏也够清楚
OUT_W, OUT_H = 900, 1200
SRC_SIZE = '2048x2048'          # 服务端要求 >= 3686400 像素

NO_TEXT = ('absolutely no text, no letters, no words, no numbers, no captions, '
           'no watermark, no logo, no signature')

COVERS = [
    ('arch',
     'Abstract academic book cover background artwork. Fine architectural '
     'blueprint linework of arches, vaults and a staircase, drawn in thin pale '
     'gold and soft violet lines over a deep indigo field, faint paper grain, '
     'generous empty space in the upper half, elegant, restrained, editorial. '
     + NO_TEXT),
    ('math',
     'Abstract academic book cover background artwork. Flowing mathematical '
     'topology curves and interference wave patterns in luminous thin lines of '
     'violet, periwinkle and soft rose over a deep midnight indigo field, '
     'generous empty space, elegant, restrained, editorial. ' + NO_TEXT),
    ('bio',
     'Abstract academic book cover background artwork. Delicate botanical and '
     'cellular microscopy forms, translucent overlapping organic shapes in '
     'muted sage green and soft violet over a deep indigo field, generous empty '
     'space, elegant, restrained, editorial. ' + NO_TEXT),
    ('cosmos',
     'Abstract academic book cover background artwork. Deep space nebula with '
     'faint concentric orbital rings, dusty violet, magenta and pale gold dust '
     'over a near-black indigo field, generous empty space, elegant, '
     'restrained, editorial. ' + NO_TEXT),
    ('tech',
     'Abstract academic book cover background artwork. Precise technical '
     'schematic grid with thin circuit traces and small nodal dots, cool cyan '
     'and violet lines over a deep slate indigo field, generous empty space, '
     'elegant, restrained, editorial. ' + NO_TEXT),
    ('lit',
     'Abstract academic book cover background artwork. Soft torn paper collage '
     'and broad brushstroke washes, warm parchment cream and dusty mauve over a '
     'deep plum field, generous empty space, elegant, restrained, editorial. '
     + NO_TEXT),
    ('chem',
     'Abstract academic book cover background artwork. Crystalline molecular '
     'lattice and faceted translucent geometry, amethyst and deep teal light '
     'refractions over a deep violet field, generous empty space, elegant, '
     'restrained, editorial. ' + NO_TEXT),
    ('geo',
     'Abstract academic book cover background artwork. Layered topographic '
     'contour map lines with soft terrain shading, indigo violet and muted sand '
     'tones, generous empty space, elegant, restrained, editorial. ' + NO_TEXT),
]


def build(src, out):
    """源图居中裁成 3:4，缩到成品尺寸，存 JPEG。"""
    from PIL import Image
    im = Image.open(src).convert('RGB')
    w, h = im.size
    want = OUT_W / float(OUT_H)
    have = w / float(h)
    if have > want:                      # 太宽 -> 裁左右
        nw = int(round(h * want))
        x = (w - nw) // 2
        im = im.crop((x, 0, x + nw, h))
    elif have < want:                    # 太高 -> 裁上下
        nh = int(round(w / want))
        y = (h - nh) // 2
        im = im.crop((0, y, w, y + nh))
    im = im.resize((OUT_W, OUT_H), Image.LANCZOS)
    im.save(out, 'JPEG', quality=86, optimize=True, progressive=True)
    return os.path.getsize(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--only', default='')
    a = ap.parse_args()

    os.makedirs(SRC_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    made = skipped = 0
    for name, prompt in COVERS:
        if a.only and a.only != name:
            continue
        src = os.path.join(SRC_DIR, 'cover_%s.jpg' % name)
        out = os.path.join(OUT_DIR, '%s.jpg' % name)
        if os.path.exists(src) and not a.force:
            print('[skip] %-6s 源图已在' % name)
        else:
            print('[gene] %-6s ...' % name, flush=True)
            generate(prompt, src, size=SRC_SIZE)
            print('       %s  %d bytes' % (os.path.basename(src),
                                           os.path.getsize(src)))
        n = build(src, out)
        print('[out ] %-6s -> %s  %d bytes' % (name, os.path.basename(out), n))
        made += 1

    total = sum(os.path.getsize(os.path.join(OUT_DIR, f))
                for f in os.listdir(OUT_DIR) if f.endswith('.jpg'))
    print()
    print('成品 %d 张，合计 %.2f MB，在 %s'
          % (made, total / 1048576.0, OUT_DIR))
    return 0


if __name__ == '__main__':
    sys.exit(main())