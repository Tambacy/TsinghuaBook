# coding:utf-8
"""
版本号一致性检查（离线，不联网）。

版本号有两处必须相同：
    crawler/version.py   VERSION        程序自己认的版本，更新检查拿它比大小
    installer.iss        MyAppVersion   安装包的版本，也是 release 里的文件名

以前版本号只写在 iss 里，程序自己不知道自己是几点几；现在反过来，
iss 必须跟着 version.py 走。两边不一致的后果很隐蔽：安装包叫 2.1、
程序却以为自己还是 2.0，于是每次启动都提示「有新版本 2.1」，点进去装的
还是自己 —— 这种问题不写个检查是发现不了的。
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from crawler.version import ASSET_PREFIX, ASSET_SUFFIX, REPO, VERSION  # noqa: E402

FAILED = []


def check(ok, msg):
    print('  %s %s' % ('OK  ' if ok else 'FAIL', msg), flush=True)
    if not ok:
        FAILED.append(msg)


def main():
    print('版本号一致性', flush=True)
    print('  version.py VERSION = %s' % VERSION, flush=True)
    print('  仓库               = %s' % REPO, flush=True)
    print('', flush=True)

    iss_path = os.path.join(_ROOT, 'installer.iss')
    check(os.path.exists(iss_path), 'installer.iss 存在')
    if not os.path.exists(iss_path):
        return 1

    with open(iss_path, encoding='utf-8') as fh:
        iss = fh.read()

    m = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', iss)
    check(m is not None, 'installer.iss 里有 MyAppVersion')
    if m:
        iss_ver = m.group(1)
        print('  installer.iss      = %s' % iss_ver, flush=True)
        check(iss_ver == VERSION,
              'installer.iss 的版本和 version.py 一致（%s == %s）'
              % (iss_ver, VERSION))

    # 安装包文件名由 iss 拼出来：<ASSET_PREFIX><版本><ASSET_SUFFIX>
    m2 = re.search(r'OutputBaseFilename=(\S+)', iss)
    check(m2 is not None, 'installer.iss 里有 OutputBaseFilename')
    if m2:
        expect = '{#MyAppNameEn}-{#MyAppVersion}-Setup'
        check(m2.group(1) == expect,
              '安装包文件名模板没被改坏（%s）' % m2.group(1))
        # updater 按这个前缀+后缀从 release 资产里挑安装包，必须能对上
        # iss 产出的真实文件名 TsinghuaBookCrawler-2.1-Setup.exe
        sample = '%s%s%s' % (ASSET_PREFIX, VERSION, ASSET_SUFFIX)
        check(sample.startswith(ASSET_PREFIX) and sample.endswith(ASSET_SUFFIX),
              'updater 挑安装包的规则能匹配真实文件名：%s' % sample)

    # README 里写的安装包名
    readme = os.path.join(_ROOT, 'README.md')
    if os.path.exists(readme):
        with open(readme, encoding='utf-8') as fh:
            text = fh.read()
        want = '%s%s%s' % (ASSET_PREFIX, VERSION, ASSET_SUFFIX)
        stale = re.findall(r'TsinghuaBookCrawler-(\d+\.\d+)-Setup\.exe', text)
        bad = sorted({v for v in stale if v != VERSION})
        check(not bad, 'README 里没有残留的旧版本安装包名（发现 %s）' % (bad or '无'))

    print('', flush=True)
    if FAILED:
        print('VERSION FAIL (%d)' % len(FAILED), flush=True)
        for x in FAILED:
            print('   - %s' % x, flush=True)
        return 1
    print('VERSION PASS', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
