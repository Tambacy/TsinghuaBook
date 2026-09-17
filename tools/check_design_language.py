# coding:utf-8
"""核对 design.md 的视觉语言是否真的还在（业务无关的那部分）。"""
import io
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

from tests._isolate import isolate  # noqa: E402

isolate()

from xk_app.app.gui import theme as T  # noqa: E402

# 控制台默认编码在中文 Windows 上是 GBK，直接把报告写成 UTF-8 文件更可靠
REPORT = os.path.join(_ROOT, '_smoke', 'design_language.txt')
_LINES = []


def show(label, value):
    line = '  %-14s %s' % (label, value)
    _LINES.append(line)
    print(line, flush=True)


def head(text):
    _LINES.append(text)
    print(text, flush=True)


head('=== design.md 视觉语言（业务无关部分，应当全部保留）===')
show('单一主色', T.PRIMARY)
show('明度阶', 'LIGHT=%s  SOFT=%s  BG=%s' % (T.PRIMARY_LIGHT, T.BG_SOFT, T.BG))
for name in ('R_SM', 'R_IN', 'R_MD', 'R_CARD', 'R_PILL'):
    if hasattr(T, name):
        show(name, getattr(T, name))
for lvl in ('card', 'raised', 'glass'):
    show('投影 ' + lvl, T.shadow_spec(lvl))
show('留白', 'PAD_PAGE=%s  GAP_PAGE=%s  PAD_CARD=%s' % (T.PAD_PAGE, T.GAP_PAGE, T.PAD_CARD))
show('动效曲线', '%s  %s  DUR_CARD_IN=%d  DUR_HOVER=%d  DUR_DATA_IN=%d'
     % (T.motion.EASE_QT, T.motion.EASE_CSS, T.motion.DUR_CARD_IN,
        T.motion.DUR_HOVER, T.motion.DUR_DATA_IN))
show('天幕变体', list(T.SKY_VARIANTS))
show('侧边栏', 'SIDEBAR_W=%s  NAV_ITEM_H=%s' % (T.SIDEBAR_W, T.NAV_ITEM_H))
show('工作区', 'WORKSPACE_HEAD_H=%s' % T.WORKSPACE_HEAD_H)

head('')
head('=== 字体与数字等宽 ===')
f = T.ui_font(13)
show('ui_font(13)', '%s' % f.family())
fm = T.ui_font(13, mono=True)
show('ui_font(mono)', '%s' % fm.family())

head('')
head('=== 已删除的选课场景结构（应当为 0）===')
import subprocess
for token in ('StepRail', 'CourseCard', 'NavPillButton'):
    r = subprocess.run(['findstr', '/s', '/m', token, 'xk_app\\*.py',
                        'xk_app\\app\\gui\\*.py', 'xk_app\\app\\gui\\views\\*.py'],
                       capture_output=True, text=True)
    show(token, '命中文件数 %d' % len([x for x in r.stdout.splitlines() if x.strip()]))

os.makedirs(os.path.dirname(REPORT), exist_ok=True)
with io.open(REPORT, 'w', encoding='utf-8') as fh:
    fh.write('\n'.join(_LINES) + '\n')
print('report -> %s' % REPORT, flush=True)