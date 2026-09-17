# coding:utf-8
"""
把所有测试和工具的配置目录顶到临时目录。

为什么必须有这个：设置和书库是真的会写盘的，而默认路径是用户的
%LOCALAPPDATA%\\TsinghuaBookCrawler。任何一个脚本忘了隔离，就会往用户
真实的书库里塞测试数据 —— 这发生过了，所以现在统一走这里。

用法：在任何 crawler 导入之前，第一件事就调 isolate()。
"""
import atexit
import os
import shutil
import tempfile

from crawler.core.store import DATA_DIR_ENV

_ISOLATED = None


def isolate(webengine=False):
    """
    返回本次运行的临时配置目录；重复调用只生效一次。

    webengine=False（默认）会顺带关掉内嵌浏览器：无头环境里 Chromium 要么
    起不来、要么刷几百行 GPU 报错，而且只是跑布局测试的话根本用不着它。
    真要测内嵌浏览器，用 tests/smoke_weblogin.py，它单独开真实显示。
    """
    global _ISOLATED
    if _ISOLATED is not None:
        return _ISOLATED
    d = tempfile.mkdtemp(prefix='xkc_cfg_')
    os.environ[DATA_DIR_ENV] = d
    # LOCALAPPDATA 也一起顶掉：错误日志和第三方库也可能读它
    os.environ['LOCALAPPDATA'] = d
    if not webengine:
        os.environ['TSINGHUA_CRAWLER_NO_WEBENGINE'] = '1'
    atexit.register(shutil.rmtree, d, ignore_errors=True)
    _ISOLATED = d
    return d


def assert_isolated():
    """自检：确认现在的配置目录确实在临时目录里。"""
    from crawler.core import store
    real = store.data_dir()
    tmp = os.path.normcase(tempfile.gettempdir())
    if not os.path.normcase(real).startswith(tmp):
        raise RuntimeError(
            '配置目录没有被隔离，测试会污染用户数据：%s\n'
            '请先调用 tests._isolate.isolate()' % real)
    return real