# coding:utf-8
"""
书库封面的底图。

为什么成套而不是一张：书库网格里十几本书并排，共用一张底图看过去还是
「一片紫」。真正让它像一本书的，是每本底图各不相同、又同属一个色系 ——
所以 assets/covers/ 下放了 8 张，按书名哈希稳定分配，同一本书永远同一张。

底图里只有画、没有字（生成提示词反复强调 NO text）：标题和作者仍然由
widgets.py 排版叠上去，模型漏一个字母就会和真标题打架。

底图明暗差别很大 —— 实测标题带平均亮度 41 ~ 183。所以标题用深色还是白色
必须**按图算**，不能写死；写死的话，深色底图上的深色标题就是一团黑。
"""
import os
import sys

from PyQt6.QtGui import QPixmap

from . import theme as T

NAMES = ('arch', 'math', 'bio', 'cosmos', 'tech', 'lit', 'chem', 'geo')

_ASSET_DIRS = []
if getattr(sys, '_MEIPASS', None):
    # PyInstaller 把只读资源解到这里
    _ASSET_DIRS.append(os.path.join(sys._MEIPASS, 'assets'))
# 开发态：本文件在 crawler/gui/ 下，往上两层到仓库根，再进 crawler/assets
_ASSET_DIRS.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'crawler', 'assets'))

_pm_cache = {}
_lum_cache = {}

# 标题带取多高：标题块在封面高度的 20% 处起排，所以量 10%~45% 这一段
# 最能代表「标题压上去之后，底下到底是深是浅」。
_BAND = (0.10, 0.45)
# 低于这个亮度就认为底图是深的，标题得用白字
_DARK_BELOW = 132.0


def path(name):
    """找一张底图的路径；找不到返回空串。"""
    for d in _ASSET_DIRS:
        p = os.path.join(d, 'covers', '%s.jpg' % name)
        if os.path.exists(p):
            return p
    return ''


def pixmap(name):
    """带缓存地取一张底图的 QPixmap。"""
    if name in _pm_cache:
        return _pm_cache[name]
    p = path(name)
    pm = QPixmap(p) if p else QPixmap()
    _pm_cache[name] = pm
    return pm


def pick(seed):
    """
    给一本书挑底图。

    先按书名里的学科关键词对上号 —— 「高等数学」配数学曲线、「大学物理学」
    配星云，一眼就成立；纯哈希分出来的结果是随机的，俄语课本配一张分子
    结构图就很怪。

    关键词都对不上时才退回稳定哈希。用稳定哈希而不是内置 hash()：内置
    hash 对字符串逐进程随机加盐，同一本书重启一次就换封面，用户会以为是 bug。
    """
    s = seed or ''
    low = s.lower()
    for name, words in _KEYWORDS:
        for w in words:
            if w in s or w.lower() in low:
                return name
    h = 2166136261
    for ch in s:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return NAMES[h % len(NAMES)]


# 从「最专指」到「最宽泛」排。先命中的赢，所以「大学物理学」不会被
# 「大学」这种泛词抢走；这也意味着新增词条要放在合适的位置上。
_KEYWORDS = (
    ('chem', ('化学', '化工', '分子', '材料', 'chemistry')),
    ('bio', ('生物', '医学', '细胞', '遗传', '生态', '生命', '药学',
             'biology', 'medicine')),
    ('math', ('数学', '代数', '几何', '微积分', '统计', '概率', '线性',
              '数理', 'math', 'calculus', 'algebra')),
    ('cosmos', ('物理', '力学', '光学', '电磁', '量子', '天文', '宇宙',
                'physics')),
    ('tech', ('计算机', '程序', '软件', '电路', '电子', '信息', '网络',
              '控制', '通信', '人工智能', '算法', 'computer', 'circuit')),
    ('arch', ('建筑', '结构', '土木', '规划', '美术', '艺术', 'architecture')),
    ('geo', ('地理', '地质', '地图', '环境', '气象', '地球', '测绘',
             'geography')),
    ('lit', ('文学', '语言', '历史', '哲学', '俄语', '英语', '日语', '德语',
             '法语', '汉语', '写作', '阅读', '经济', '管理', '法律', '政治',
             '教育', '心理', '社会', '马克思主义', '毛泽东', '思想道德',
             '形势与政策', '军事', '体育', '音乐')),
)


def band_luminance(name, pm):
    """量底图标题带的平均亮度（0~255）。按图缓存，不重复算。"""
    if name in _lum_cache:
        return _lum_cache[name]
    lum = 128.0
    if pm is not None and not pm.isNull():
        img = pm.toImage()
        w, h = img.width(), img.height()
        y0, y1 = int(h * _BAND[0]), int(h * _BAND[1])
        # 抽样而不是逐像素：这里只要一个「深还是浅」的判断，几千个点足够，
        # 而 900x1200 全扫一遍是百万次 pixelColor，卡在滚动里看得出来。
        rs = n = 0
        step_x = max(1, w // 40)
        step_y = max(1, (y1 - y0) // 40)
        for y in range(y0, y1, step_y):
            for x in range(0, w, step_x):
                c = img.pixelColor(x, y)
                rs += (c.red() * 299 + c.green() * 587 + c.blue() * 114) // 1000
                n += 1
        if n:
            lum = rs / float(n)
    _lum_cache[name] = lum
    return lum


def is_dark(name, pm):
    return band_luminance(name, pm) < _DARK_BELOW


def ink(name, pm):
    """标题/作者该用的颜色。"""
    return T.ON_DARK if is_dark(name, pm) else T.PRIMARY_DEEP


def scrim(name, pm):
    """
    保证文字可读的那层压暗/提亮该用什么颜色。

    深底图压黑、浅底图提白 —— 方向反了就等于没压，标题照样糊在花纹里。
    """
    return '#000000' if is_dark(name, pm) else '#FFFFFF'