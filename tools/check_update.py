# coding:utf-8
"""
真实联网跑一遍更新检查（发布前用）。

打的是真的 GitHub 接口，看到的就是用户点「检查更新」时会看到的东西。
不需要 token —— releases/latest 是公开接口。

用法：
    venv\\Scripts\\python tools\\check_update.py
    venv\\Scripts\\python tools\\check_update.py --download   # 顺便下安装包并校验大小
    venv\\Scripts\\python tools\\check_update.py --as 2.0     # 假装自己是 2.0

--as 是发布后验证用的：新版本刚发出去时，本地代码已经是最新的了，
拿它跑只会看到「已是最新」。要确认老用户那边真的能收到提示，
就得假装自己是上一个版本再查一次。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from crawler.core import updater as U                                   # noqa: E402
from crawler.version import VERSION                                     # noqa: E402


def human(n):
    if not n:
        return '未知'
    return '%.1f MB' % (n / 1048576.0)


def _arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    pretend = _arg('--as')
    local = pretend or VERSION
    print('本地版本 : %s%s' % (local, '（--as 模拟）' if pretend else ''), flush=True)
    print('接口     : %s' % U.API_LATEST, flush=True)
    print('', flush=True)

    try:
        data = U._get_json(U.API_LATEST, 20)
    except U.UpdateError as e:
        print('  检查失败：%s' % e, flush=True)
        print('', flush=True)
        print('  注意：国内直连 GitHub 经常不通。程序里这种情况只是提示一下，', flush=True)
        print('  不影响下载功能。', flush=True)
        return 1

    rel = U.parse_release(data)
    print('  最新版本 : %s' % rel.version, flush=True)
    print('  标题     : %s' % rel.name, flush=True)
    print('  安装包   : %s  (%s)' % (rel.asset_name or '（没有）',
                                     human(rel.asset_size)), flush=True)
    print('  发布页   : %s' % rel.page_url, flush=True)
    print('', flush=True)

    if not rel.version:
        print('  FAIL 接口里没有版本号', flush=True)
        return 1
    if not rel.asset_url:
        print('  FAIL release 里没有安装包资产 —— 用户点了会提示去发布页手动下载', flush=True)
        return 1
    print('  OK   接口可用，安装包资产也在', flush=True)

    # 走一遍程序里真正的判断逻辑，而不是在这里另写一遍
    if U.is_newer(rel.version, local):
        print('  -> 程序会提示「有新版本 %s」' % rel.version, flush=True)
        if pretend:
            print('  OK   %s 的用户能收到更新提示' % local, flush=True)
    else:
        print('  -> 程序会提示「已是最新版本 %s」' % local, flush=True)
        if pretend:
            print('  FAIL %s 的用户收不到提示 —— 版本号或 tag 可能不对' % local, flush=True)
            return 1

    if '--download' in sys.argv:
        print('', flush=True)
        print('下载安装包到 %s …' % U.dest_dir(), flush=True)
        last = [0]

        def on_progress(done, total):
            if total and done - last[0] > 8 * 1048576:
                last[0] = done
                print('  %s / %s' % (human(done), human(total)), flush=True)

        try:
            path = U.download(rel, on_progress=on_progress)
        except U.UpdateError as e:
            print('  下载失败：%s' % e, flush=True)
            return 1
        size = os.path.getsize(path)
        print('  下好了：%s  %s' % (path, human(size)), flush=True)
        if rel.asset_size and size != rel.asset_size:
            print('  FAIL 大小和接口报的对不上', flush=True)
            return 1
        print('  OK   大小和接口报的一致', flush=True)

    print('', flush=True)
    print('CHECK UPDATE OK', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
