# coding:utf-8
"""
生成登录页左栏的主视觉。

为什么不用侧边栏那张 backdrop.jpg：那张是按「方形底图、四边都要能裁」设计的，
铺到 537x860 的竖长条上会被裁掉大半，构图就散了 —— 实际效果是一大片几乎
看不见内容的暗色。左栏是用户打开应用看到的第一屏，而且是一整块空地，值得
单独出一张竖构图。

提示词里明确要求「左上一带和底部留安静的暗区」：标题在左上、页脚在底部，
留不出暗区的话，字就会压在画面最亮的花纹上。

    python tools\\make_hero.py --cand      # 出 3 张候选到 tools/art/ 供挑选
    python tools\\make_hero.py --pick 2    # 把 2 号裁成成品
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

from gen_image import generate  # noqa: E402

SRC_DIR = os.path.join(_HERE, 'art')
OUT = os.path.join(_ROOT, 'xk_app', 'assets', 'login_hero.jpg')

OUT_W, OUT_H = 1200, 1920        # 0.625，和左栏 537x860 同比例
SRC_SIZE = '2048x2048'

NO_TEXT = ('absolutely no text, no letters, no words, no numbers, no captions, '
           'no watermark, no logo, no signature, no UI elements')

TAIL = ('Cinematic depth, refined, elegant, editorial quality. Keep the upper-left '
        'area and the bottom band calm and dark so overlaid typography stays '
        'readable. ' + NO_TEXT)

CANDS = [
    ('A grand university library reading hall dissolving upward into a deep '
     'violet aurora night sky. Tall arched windows, long rows of desks receding '
     'into darkness, luminous dust motes and a few softly glowing floating '
     'pages drifting upward, deep indigo and amethyst with restrained warm gold '
     'accents. ' + TAIL),
    ('A quiet nocturnal campus: a tall gothic library facade and its reflection '
     'in still water, above it a vast violet and rose aurora with faint '
     'constellation lines, thin mist at the base, deep indigo and plum with '
     'pale gold glints. ' + TAIL),
    ('An abstract ascension of countless thin translucent book pages spiralling '
     'upward like a flock of birds, lit from within, against a deep violet to '
     'near-black graded sky with soft nebula haze and fine golden filament '
     'lines. ' + TAIL),
]


def build(src, out, box=None):
    """源图居中裁成 0.625 竖版，缩到成品尺寸。"""
    from PIL import Image
    im = Image.open(src).convert('RGB')
    w, h = im.size
    if box:
        im = im.crop(box)
        w, h = im.size
    want = OUT_W / float(OUT_H)
    have = w / float(h)
    if have > want:
        nw = int(round(h * want))
        x = (w - nw) // 2
        im = im.crop((x, 0, x + nw, h))
    elif have < want:
        nh = int(round(w / want))
        y = (h - nh) // 2
        im = im.crop((0, y, w, y + nh))
    im = im.resize((OUT_W, OUT_H), Image.LANCZOS)
    im.save(out, 'JPEG', quality=88, optimize=True, progressive=True)
    return os.path.getsize(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cand', action='store_true', help='出候选')
    ap.add_argument('--pick', type=int, default=0, help='把第几张裁成成品')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()

    os.makedirs(SRC_DIR, exist_ok=True)

    if a.cand:
        for i, prompt in enumerate(CANDS, 1):
            src = os.path.join(SRC_DIR, 'hero_%d.jpg' % i)
            if os.path.exists(src) and not a.force:
                print('[skip] hero_%d 已在' % i)
                continue
            print('[gene] hero_%d ...' % i, flush=True)
            generate(prompt, src, size=SRC_SIZE)
            print('       %d bytes' % os.path.getsize(src))
        return 0

    if a.pick:
        src = os.path.join(SRC_DIR, 'hero_%d.jpg' % a.pick)
        if not os.path.exists(src):
            raise SystemExit('没有 %s，先跑 --cand' % src)
        n = build(src, OUT)
        print('wrote %s  %d bytes' % (OUT, n))
    return 0


if __name__ == '__main__':
    sys.exit(main())