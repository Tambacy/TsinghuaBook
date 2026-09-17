"""
更新功能的测试。全程不联网 —— 网络那一层用假的 fetch 顶掉。

重点覆盖的是「比版本号」和「下载完整性」这两处最容易出错的地方：
  * 字符串比较会把 2.10 判成比 2.9 旧
  * 下到一半断线如果不检查大小，会装上一个坏包
"""

import os
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _isolate import isolate                                          # noqa: E402

isolate()

from crawler import version as V                                      # noqa: E402
from crawler.core import updater as U                                 # noqa: E402

FAILED = []


def check(ok, msg):
    print('  %s %s' % ('OK  ' if ok else 'FAIL', msg), flush=True)
    if not ok:
        FAILED.append(msg)


class FakeResp(object):
    """假的流式响应。按固定小块吐，好让 fail_after 能真的在中途炸掉。"""

    PIECE = 512

    def __init__(self, status=200, body=b'', total=None, fail_after=None):
        self.status_code = status
        self._body = body
        self._fail_after = fail_after
        n = len(body) if total is None else total
        self.headers = {'Content-Length': str(n)} if n else {}

    def iter_content(self, chunk):
        step = min(chunk, self.PIECE)
        sent = 0
        for i in range(0, len(self._body), step):
            if self._fail_after is not None and sent >= self._fail_after:
                raise U.requests.RequestException('connection reset')
            piece = self._body[i:i + step]
            sent += len(piece)
            yield piece


def rel_json(tag='v9.9', with_asset=True, size=1000):
    data = {
        'tag_name': tag,
        'name': '清华教参下载器 %s' % tag.lstrip('vV'),
        'body': '修复了一些问题',
        'html_url': 'https://github.com/%s/releases/tag/%s' % (V.REPO, tag),
        'assets': [],
    }
    if with_asset:
        data['assets'].append({
            'name': '%s%s%s' % (V.ASSET_PREFIX, tag.lstrip('vV'), V.ASSET_SUFFIX),
            'browser_download_url': 'https://example.invalid/setup.exe',
            'size': size,
        })
    return data


def main():
    print('[A] 版本号比较', flush=True)
    check(V.version_tuple('2.10') == (2, 10), '2.10 -> (2, 10)')
    check(V.version_tuple('v2.0.1') == (2, 0, 1), 'v2.0.1 -> (2, 0, 1)')
    check(V.version_tuple('2.1-beta') == (2, 1), '非数字后缀被丢掉')
    check(V.version_tuple('') == (0,), '空串不炸')
    check(V.version_tuple(None) == (0,), 'None 不炸')
    # 这一条是关键：字符串比较会得到错误答案
    check(V.is_newer('2.10', '2.9'), '2.10 比 2.9 新（字符串比较会判反）')
    check(not V.is_newer('2.9', '2.10'), '2.9 不比 2.10 新')
    check(not V.is_newer('2.0', '2.0'), '同版本不算更新')
    check(not V.is_newer('1.9', '2.0'), '旧版本不算更新')
    check(V.is_newer('v2.1', '2.0'), '带 v 前缀也能比')

    print('[B] 解析 release JSON', flush=True)
    r = U.parse_release(rel_json('v9.9'))
    check(r.version == '9.9', 'version = %s' % r.version)
    check(r.tag == 'v9.9', 'tag = %s' % r.tag)
    check(r.asset_name.endswith('-Setup.exe'), '挑出安装包：%s' % r.asset_name)
    check(r.asset_size == 1000, '拿到体积')
    r2 = U.parse_release(rel_json('v9.9', with_asset=False))
    check(r2.asset_url == '', '没有安装包时 asset_url 为空（界面要退回发布页）')
    # 只有 .zip 之类别的资产时不能误认
    d = rel_json('v9.9')
    d['assets'] = [{'name': 'source.zip', 'browser_download_url': 'x', 'size': 1}]
    check(U.parse_release(d).asset_url == '', '不把无关资产当安装包')

    print('[C] check() 的判断', flush=True)
    got = U.check(fetch=lambda url, t: rel_json('v99.0'))
    check(got is not None and got.version == '99.0', '有新版本时返回 Release')
    check(U.check(fetch=lambda url, t: rel_json('v' + V.VERSION)) is None,
          '同版本返回 None')
    check(U.check(fetch=lambda url, t: rel_json('v0.1')) is None,
          '更旧的版本返回 None')

    def boom(url, t):
        raise U.UpdateError('连接不上更新服务器（连接超时）')

    try:
        U.check(fetch=boom)
        check(False, '网络失败应该抛 UpdateError')
    except U.UpdateError as e:
        check('连接不上' in str(e), '网络失败抛 UpdateError：%s' % e)

    def http404(url, t):
        raise U.UpdateError('仓库里还没有发布版本')

    try:
        U.check(fetch=http404)
        check(False, '404 应该抛 UpdateError')
    except U.UpdateError:
        check(True, '没有 release 时抛 UpdateError')

    print('[D] 下载', flush=True)
    tmp = tempfile.mkdtemp(prefix='xkc_upd_')
    U.dest_dir = lambda: tmp                      # 别写到真的临时目录
    body = b'X' * 5000
    r = U.parse_release(rel_json('v9.9', size=len(body)))
    seen = []
    p = U.download(r, on_progress=lambda d, t: seen.append((d, t)),
                   fetch=lambda url, **kw: FakeResp(body=body))
    check(os.path.exists(p), '文件下下来了')
    check(open(p, 'rb').read() == body, '内容完整')
    check(seen and seen[-1][0] == len(body), '进度回调走到 100%')
    check(seen[-1][1] == len(body), '总长度来自 Content-Length')
    check(not os.path.exists(p + '.part'), '临时 .part 已清掉')

    print('[E] 重复下载复用已有文件', flush=True)
    calls = []

    def counting(url, **kw):
        calls.append(1)
        return FakeResp(body=body)

    U.download(r, fetch=counting)
    check(not calls, '大小对得上就不重新下载')

    print('[F] 下载不完整必须报错', flush=True)
    os.remove(p)
    r2 = U.parse_release(rel_json('v9.8', size=9999))
    try:
        U.download(r2, fetch=lambda url, **kw: FakeResp(body=body, total=9999))
        check(False, '大小对不上应该报错')
    except U.UpdateError as e:
        check('不完整' in str(e), '大小不符抛 UpdateError：%s' % e)
    check(not os.path.exists(U.local_path(r2) + '.part'), '坏包已清掉')

    print('[G] 中途断线', flush=True)
    r3 = U.parse_release(rel_json('v9.7', size=len(body)))
    try:
        U.download(r3, fetch=lambda url, **kw: FakeResp(body=body, fail_after=1000))
        check(False, '断线应该报错')
    except U.UpdateError as e:
        check('中断' in str(e) or '下载' in str(e), '断线抛 UpdateError：%s' % e)
    check(not os.path.exists(U.local_path(r3) + '.part'), '断线残留已清掉')

    print('[H] 取消', flush=True)
    r4 = U.parse_release(rel_json('v9.6', size=len(body)))
    ev = threading.Event()
    ev.set()
    try:
        U.download(r4, cancel=ev, fetch=lambda url, **kw: FakeResp(body=body))
        check(False, '取消应该报错')
    except U.UpdateError as e:
        check('取消' in str(e), '取消抛 UpdateError：%s' % e)

    print('[I] 没有安装包的版本', flush=True)
    r5 = U.parse_release(rel_json('v9.5', with_asset=False))
    try:
        U.download(r5, fetch=lambda url, **kw: FakeResp(body=body))
        check(False, '没有 asset 应该报错')
    except U.UpdateError as e:
        check('手动下载' in str(e), '提示去发布页手动下载：%s' % e)

    print('[J] 启动安装包的命令行', flush=True)
    setup = os.path.join(tmp, 'setup.exe')
    open(setup, 'wb').write(b'MZ')
    # launch() 只在 exe 真实存在时才加「装完重启」，所以这里得造一个真的
    exe = os.path.join(tmp, 'TsinghuaBookCrawler.exe')
    open(exe, 'wb').write(b'MZ')
    captured = {}

    class FakePopen(object):
        def __init__(self, args, **kw):
            captured['args'] = args
            captured['kw'] = kw

    real = U.subprocess.Popen
    U.subprocess.Popen = FakePopen
    try:
        U.launch(setup, exe=exe)
    finally:
        U.subprocess.Popen = real
    cmd = captured['args']
    check(isinstance(cmd, str),
          '命令以字符串形式交给 Popen（传 list 会被 list2cmdline 二次加引号）')
    check(captured['kw'].get('shell') is True, '用 shell=True')
    check('/SILENT' in cmd, '静默安装（装到用户目录，不弹 UAC）')
    check('start "" /wait' in cmd, '先等安装结束再重启程序')
    check(exe in cmd, '装完把程序重新拉起来')
    check(captured['kw'].get('creationflags'), '脱离本进程进程组')

    captured.clear()
    U.subprocess.Popen = FakePopen
    try:
        U.launch(setup, exe='')                   # 源码运行：不重启自己
    finally:
        U.subprocess.Popen = real
    check('& start' not in captured['args'], '没有 exe 时不拼重启命令')

    try:
        U.launch(os.path.join(tmp, 'nope.exe'))
        check(False, '安装包不存在应该报错')
    except U.UpdateError as e:
        check('不见了' in str(e), '安装包不存在时抛 UpdateError：%s' % e)

    print('[J2] 命令真的能被执行（不只是字符串长得对）', flush=True)
    # 上面那组只检查了命令串的样子。真正的坑恰恰在这里：命令串看着完全正确，
    # 但 Popen 的传参方式让 cmd.exe 解析不了，于是安装包被静默丢掉。
    # 所以这里用一个「假装成安装包」的批处理真跑一遍，看它有没有留下痕迹。
    if sys.platform == 'win32':
        marker = os.path.join(tmp, 'ran.txt')
        fake_setup = os.path.join(tmp, 'fake-setup.bat')
        with open(fake_setup, 'w', encoding='ascii') as fh:
            fh.write('@echo off\r\necho ran > "%s"\r\n' % marker)
        got = []
        try:
            U.launch(fake_setup, exe='')
        except U.UpdateError as e:
            got.append(str(e))
        for _ in range(60):
            if os.path.exists(marker) or got:
                break
            time.sleep(0.1)
        check(os.path.exists(marker),
              'launch() 拼出来的命令确实被执行了（安装包不会静默丢掉）')
        if os.path.exists(marker):
            with open(marker, encoding='utf-8') as fh:
                check('ran' in fh.read(), '子进程正常跑完')
    else:
        check(True, '非 Windows 跳过')

    print('[K] 源码运行时不重启自己', flush=True)
    check(U.current_exe() == '' or os.path.exists(U.current_exe()),
          'current_exe 返回值合法（源码运行 = 空串）')

    shutil.rmtree(tmp, ignore_errors=True)

    print('', flush=True)
    if FAILED:
        print('UPDATER FAIL (%d)' % len(FAILED), flush=True)
        for m in FAILED:
            print('   - %s' % m, flush=True)
        return 1
    print('UPDATER PASS', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
