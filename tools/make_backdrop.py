# coding:utf-8
"""
把生成出来的原图处理成可以发布的 crawler/assets/backdrop.jpg。

原图放 tools/art/backdrop_src.jpg（不进安装包），只有产物进 assets/。
分开是因为原图是「素材」，assets 里的是「成品」：素材留着是为了随时能换一版
处理方式重跑，而不必重新出图。

当前这张的出处（用 tools/gen_image.py 出图，1920x1920）：

    Abstract premium wallpaper, minimal. Deep midnight indigo background,
    one large soft radial bloom of dusty violet and pale rose light rising
    from the lower center, all edges falling away to near black. Extremely
    smooth gradients, fine film grain, matte finish. No objects, no stars,
    no text, no people.

为什么选这张：它的构图天生适配两处裁剪 —— 顶部很暗（登录页标题压得住），
而低空那团暮粉/薰衣草辉光正好呼应 theme 里原有的 SKY_GLOW / SKY_AURORA_B，
等于把程序化天幕想做的事用一张成品画面做出来了，品牌色没有换。

用法：
    python tools\\make_backdrop.py
    python tools\\make_backdrop.py --src 别的图.jpg
"""
import argparse
import os
import sys

from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
DEFAULT_SRC = os.path.join(_HERE, 'art', 'backdrop_src.jpg')
DEFAULT_OUT = os.path.join(_ROOT, 'crawler', 'assets', 'backdrop.jpg')

SIZE = 1920          # 够覆盖登录页左栏在 200% 缩放下的 1054x1644
QUALITY = 88


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=DEFAULT_SRC)
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--size', type=int, default=SIZE)
    ap.add_argument('--quality', type=int, default=QUALITY)
    a = ap.parse_args()

    if not os.path.exists(a.src):
        raise SystemExit('找不到原图：%s' % a.src)

    im = Image.open(a.src).convert('RGB')
    # 居中裁成正方形再缩 —— 两处用它的地方（侧栏取横向中段、登录页取竖向
    # 中段）都是从正方形里裁，所以正方形是最不用做取舍的形状。
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    if im.width != a.size:
        im = im.resize((a.size, a.size), Image.LANCZOS)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    im.save(a.out, 'JPEG', quality=a.quality, optimize=True, progressive=True)
    print('wrote %s  %dx%d  %d KB'
          % (a.out, im.width, im.height, os.path.getsize(a.out) // 1024))
    print()
    print('接下来一定要跑：')
    print('  python tools\\check_backdrop_contrast.py')
    print('换底图会改变每行白字底下的亮度 —— 对比度不量一遍就等于没验。')
    return 0


if __name__ == '__main__':
    sys.exit(main())