# coding:utf-8
"""
使用说明视图。

原设计稿里这是个「使用说明」弹窗；这里做成页面，因为内容偏多
（怎么抓 token、链接长什么样、卡住了怎么办），弹窗里得再滚一层。
"""
from PyQt6.QtWidgets import QHBoxLayout

from .. import theme as T
from .. import widgets as W
from .base import Workspace

STEPS = [
    ('第 1 步 · 拿到书籍链接',
     '在浏览器里打开清华教参平台的书籍详情页，复制地址栏里完整的链接。\n'
     '它长这样：https://ereserves.lib.tsinghua.edu.cn/bookDetail/c01e1db1...'),
    ('第 2 步 · 抓一个 token',
     '按 F12 打开开发者工具，切到 Network（网络）面板，保持它开着，然后登录教参平台。\n'
     '在请求列表里找到一条 index?token=eyJh... 的请求，把等号后面那一整串复制下来。\n'
     '注意：一定要先打开开发者工具再登录，否则抓不到这条请求。'),
    ('第 3 步 · 填进设置',
     '打开左侧「设置」，把 token 粘进去，点「校验 token」。\n'
     '校验通过就说明凭证可用，之后下载都不用再管它 —— 除非它过期了。'),
    ('第 4 步 · 排队下载',
     '回到「下载队列」，把链接粘进输入框，一行一条，可以一次粘很多本。\n'
     '点「添加到队列」再点「开始下载」，程序会一本一本地下完。\n'
     '中途可以点「停止」，已经下好的图片会保留，下次接着下。'),
    ('第 5 步 · 在书库里找书',
     '下完的书会出现在「书库」里，带封面、页数和体积。\n'
     '点封面打开 PDF，点文件夹图标定位到它的目录。'),
]

FAQ = [
    ('提示 token 不正确 / 已过期',
     'token 和登录会话绑定，会过期。重新按第 2 步抓一个，粘进设置再试。'),
    ('下载到一半失败了',
     '已在「下载队列」里点「重试失败」。成功下过的页面不会重复下载，'
     '所以重试很便宜。'),
    ('某本书一直失败',
     '先确认这本书在你的账号权限范围内，并且链接是 bookDetail 详情页链接。'
     '也可以在「设置」里把进程数调到 2 再试，有些网络环境并发高会被拒。'),
    ('PDF 太大 / 太糊',
     '在「设置」里调 PDF 质量。10 是最高最清晰，往小调会明显减小体积。'),
    ('想省磁盘',
     '在「设置」里取消勾选「保留临时图片」，生成 PDF 后会自动删掉图片。'),
    ('书库里的书显示「文件已丢失」',
     'PDF 被手动删掉或移动了。记录还在，点回收站图标可以清掉这一条。'),
]


class HelpView(Workspace):
    def __init__(self, parent=None):
        super().__init__('使用说明', '从拿到链接到打开 PDF，一共五步。', parent)

        for title, body in STEPS:
            card = W.Card(padding=(20, 16, 20, 16), gap=7)
            card.box.addWidget(W.section(title))
            txt = W.body(body, T.TEXT_DIM)
            card.box.addWidget(txt)
            self.box.addWidget(card)

        self.box.addSpacing(6)
        card = W.Card(padding=(20, 16, 20, 16), gap=10)
        card.box.addWidget(W.card_title('常见问题'))
        for q, a in FAQ:
            item = W.SoftBlock(padding=(15, 11, 15, 11), gap=4)
            item.box.addWidget(W.meta(q, T.TEXT))
            item.box.addWidget(W.body(a, T.TEXT_DIM))
            card.box.addWidget(item)
        self.box.addWidget(card)

        self.box.addSpacing(6)
        note = W.SoftBlock(padding=(16, 13, 16, 13), gap=5)
        note.box.addWidget(W.meta('关于版权', T.WARN))
        note.box.addWidget(W.body(
            '下载得到的电子书版权归原作者与出版方所有。请仅用于个人学习，'
            '不要传播，尤其是不要传播到校外；也请避免批量下载整库书籍。'
            '程序不提供任何绕过认证或授权的能力。', T.TEXT_DIM))
        self.box.addWidget(note)
        self.add_stretch()
