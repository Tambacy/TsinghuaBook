# coding:utf-8
"""
真实安装测试：走程序自己的更新代码路径，把本机装的版本装成最新版。

用的是 updater.download() + updater.launch()，和用户点「立即安装并重启」
时执行的完全是同一段代码（只是不传 exe，所以装完不会自动拉起程序，
方便这里接着做检查）。

两种情形都测：
  * 装的比最新版旧 -> 真正验证「升级」
  * 已经是最新版   -> 重装一遍，至少把「下载复用 + 静默安装」这套机制验掉

注意这个脚本会真的动本机安装的副本，只在需要验证安装链路时手动跑。
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler.core import updater as U                                   # noqa: E402
from crawler.version import VERSION                                     # noqa: E402

INSTALL_DIR = os.path.join(os.environ['LOCALAPPDATA'], 'Programs',
                           'TsinghuaBookCrawler')
EXE = os.path.join(INSTALL_DIR, 'TsinghuaBookCrawler.exe')
UNINS = os.path.join(INSTALL_DIR, 'unins000.exe')
NOTES = os.path.join(INSTALL_DIR, 'RELEASE_NOTES.md')


def installed_version():
    """装了哪个版本：先看卸载器元数据，再看随包发布的说明。"""
    if os.path.exists(UNINS):
        try:
            out = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 "(Get-Item '%s').VersionInfo.ProductVersion" % UNINS],
                capture_output=True, text=True, timeout=60)
            v = out.stdout.strip()
            if v:
                return v
        except Exception:                                         # noqa: BLE001
            pass
    if os.path.exists(NOTES):
        with open(NOTES, encoding='utf-8') as fh:
            return fh.readline().strip()
    return '?'


def setup_running():
    """
    有没有安装包进程在跑。

    注意：tasklist 会把映像名截断到 25 个字符，
    'TsinghuaBookCrawler-2.1-Setup.exe' 显示成 'TsinghuaBookCrawler-2.1-S'，
    所以按全名 /FI 过滤是匹配不到的（第一次就是栽在这儿，安装明明跑完了却报没起来）。
    这里改用「名字以 TsinghuaBookCrawler- 开头」判断 ——
    主程序叫 TsinghuaBookCrawler.exe，不带横杠，不会误判。
    """
    try:
        out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'],
                             capture_output=True, text=True, timeout=60)
    except Exception:                                             # noqa: BLE001
        return False
    return 'tsinghuabookcrawler-' in (out.stdout or '').lower()


def wait_for_install(timeout=600):
    """
    等安装跑完。

    判据是「安装包进程起来了、然后又没了」。
    不能用 exe 的修改时间：Inno 会把归档里的时间戳原样写到目标文件，
    所以重装同一个构建时 mtime 根本不变。
    也不能只看版本号：重装时版本号不变。
    """
    # 先等它起来 —— 这一步能抓到「命令拼错、安装包压根没被启动」这类问题
    deadline = time.time() + 120
    while time.time() < deadline:
        if setup_running():
            break
        time.sleep(2)
    else:
        return 'never-started'

    # 再等它退出
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        if not setup_running():
            return 'finished'
    return 'timeout'


def main():
    print('本地代码版本 : %s' % VERSION, flush=True)
    print('安装目录     : %s' % INSTALL_DIR, flush=True)
    before = str(installed_version()).strip()
    print('安装前版本   : %s' % before, flush=True)
    print('', flush=True)

    if not os.path.isdir(INSTALL_DIR):
        print('SKIP 这台机器上没有安装过，没法测安装链路', flush=True)
        return 0

    # 源码已经是 2.1 了，直接 check() 只会说「已是最新」。
    # 要验的正是「老版本的用户点更新」，所以把模块里的 VERSION 顶成
    # 已安装的那个版本，让 check() 按老版本判断。
    was = U.VERSION
    U.VERSION = before or was
    try:
        print('[1] updater.check()（假装自己是 %s）...' % U.VERSION, flush=True)
        rel = U.check()
    finally:
        U.VERSION = was

    if rel is None:
        print('    已是最新版，改为重装同一版本，验证安装机制', flush=True)
        rel = U.parse_release(U._get_json(U.API_LATEST, 20))
        upgrading = False
    else:
        print('    发现 %s，安装包 %s' % (rel.version, rel.asset_name), flush=True)
        upgrading = True

    print('[2] updater.download() ...', flush=True)
    marks = [0]

    def on_progress(done, total):
        if total and done - marks[0] > 48 * 1048576:
            marks[0] = done
            print('    %.0f%%' % (100.0 * done / total), flush=True)

    path = U.download(rel, on_progress=on_progress)
    size = os.path.getsize(path)
    print('    下好了 %s（%d 字节）' % (path, size), flush=True)
    if rel.asset_size and size != rel.asset_size:
        print('FAIL 大小对不上', flush=True)
        return 1

    print('[3] updater.launch() 静默安装 ...', flush=True)
    cmd = U.launch(path, exe='')          # 不传 exe = 装完不自动拉起
    print('    命令：%s' % cmd, flush=True)

    print('[4] 等安装结束 ...', flush=True)
    result = wait_for_install()
    after = str(installed_version()).strip()
    print('    安装后版本 : %s' % after, flush=True)
    print('', flush=True)

    ok = True
    if result == 'finished':
        print('  OK   安装包确实被启动并且跑完了', flush=True)
    elif result == 'never-started':
        print('  FAIL 安装包根本没被启动 —— launch() 拼的命令没执行', flush=True)
        ok = False
    else:
        print('  FAIL 安装包跑了 10 分钟还没结束', flush=True)
        ok = False

    if rel.version in after:
        print('  OK   安装目录里的版本是 %s' % rel.version, flush=True)
        if upgrading:
            print('       （从 %s 升上来的）' % before, flush=True)
    else:
        print('  FAIL 期望 %s，实际 %s' % (rel.version, after), flush=True)
        ok = False

    if os.path.exists(EXE):
        print('  OK   主程序还在', flush=True)
    else:
        print('  FAIL 主程序不见了', flush=True)
        ok = False

    internal = os.path.join(INSTALL_DIR, '_internal')
    if os.path.isdir(internal):
        n = sum(len(f) for _, _, f in os.walk(internal))
        print('  OK   _internal 依赖目录还在（%d 个文件）' % n, flush=True)
    else:
        print('  FAIL _internal 不见了', flush=True)
        ok = False

    if os.path.isdir(os.path.join(INSTALL_DIR, 'downloads')):
        print('  OK   用户的 downloads 目录还在（没被清掉）', flush=True)
    else:
        print('  WARN downloads 目录不在了', flush=True)

    # 装完能不能跑
    try:
        r = subprocess.run([EXE, '--selftest'], capture_output=True,
                           text=True, timeout=180)
        tail = [ln for ln in (r.stdout or '').splitlines() if 'SELFTEST' in ln]
        if r.returncode == 0 and tail:
            print('  OK   装好的程序自检通过：%s' % tail[-1].strip(), flush=True)
        else:
            print('  FAIL 装好的程序自检没过（exit=%s）' % r.returncode, flush=True)
            ok = False
    except Exception as e:                                        # noqa: BLE001
        print('  FAIL 跑不起来：%s' % e, flush=True)
        ok = False

    print('', flush=True)
    print('INSTALL OK' if ok else 'INSTALL FAIL', flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
