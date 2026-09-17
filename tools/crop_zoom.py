# coding:utf-8
"""把一张截图里的侧边栏顶部放大，用来核对品牌区的渲染。"""
import os
import sys

from PIL import Image

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

src = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(_ROOT, '_smoke', 'side_zoom.png')
box = tuple(int(v) for v in sys.argv[3].split(',')) if len(sys.argv) > 3 else (0, 30, 340, 320)
scale = int(sys.argv[4]) if len(sys.argv) > 4 else 3

im = Image.open(src).convert('RGB')
print('原图', im.size, ' 裁剪', box)
crop = im.crop(box)
crop = crop.resize((crop.width * scale, crop.height * scale), Image.NEAREST)
crop.save(out)
print('wrote', out, crop.size)