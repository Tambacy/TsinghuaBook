# coding:utf-8
"""
版本号与发布信息的唯一来源。

为什么要单独一个文件：更新检查要拿本地版本和 GitHub 上的最新版比大小，
安装包脚本（installer.iss）也要写同一个号。以前版本号只写在 iss 里，
程序自己不知道自己是几点几，就没法提示更新。现在以这里为准，
`tools/check_version.py` 会校验 iss 和这里一致，防止两边各改各的。
"""

VERSION = '2.1.1'

# GitHub 仓库（owner/name）。更新检查打的是它的 releases 接口。
REPO = 'Tambacy/TsinghuaBook'

# 安装包在 release 里的文件名前缀，用来从 assets 里挑出该下哪个。
# 仓库页面上那个「下载安装包」按钮指的就是它。
ASSET_PREFIX = 'TsinghuaBookCrawler-'
ASSET_SUFFIX = '-Setup.exe'


def version_tuple(text):
    """
    把 '2.10.3' 这种串转成可以比大小的元组 (2, 10, 3)。

    故意不用字符串比较：字符串下 '2.10' < '2.9'，而版本号里 2.10 是比 2.9
    新的。非数字后缀（-beta、+build）直接丢掉，只比数字部分。
    """
    parts = []
    for chunk in str(text or '').strip().lstrip('vV').split('.'):
        digits = ''
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote, local=None):
    """remote 比 local 新才返回 True。相同或更旧都算「不用更新」。"""
    if local is None:
        local = VERSION
    return version_tuple(remote) > version_tuple(local)
