# coding:utf-8
"""
更新检查与下载。**刻意不碰 Qt** —— 这样可以在没有界面的情况下测，
也保证这个模块里不会出现「在下载线程里改控件」那类问题。

流程：
    check()     打 GitHub 的 releases/latest 接口，返回 Release 或 None
    download()  把安装包下到临时目录，边下边回调进度
    launch()    把安装包跑起来（静默装），装完把程序重新拉起来

网络不通（国内直连 GitHub 经常不通）不是异常情况，check() 会抛
UpdateError，由界面提示「检查更新失败」，不影响其它功能。
"""
import os
import subprocess
import sys
import tempfile
import threading
from collections import namedtuple

import requests

from ..version import ASSET_PREFIX, ASSET_SUFFIX, REPO, VERSION, is_newer

API_LATEST = 'https://api.github.com/repos/%s/releases/latest' % REPO
CHUNK = 256 * 1024

# GitHub 要求带 User-Agent，不带直接 403
_HEADERS = {
    'User-Agent': 'TsinghuaBookCrawler-Updater',
    'Accept': 'application/vnd.github+json',
}


class UpdateError(Exception):
    """检查或下载失败。消息直接给用户看，所以要说人话。"""


Release = namedtuple('Release', (
    'version',      # '2.1'
    'tag',          # 'v2.1'
    'name',         # release 标题
    'notes',        # release 说明（markdown 原文）
    'asset_name',   # 安装包文件名，可能为空
    'asset_url',    # 安装包下载地址，可能为空
    'asset_size',   # 字节数，0 表示未知
    'page_url',     # release 页面，没有安装包时退回到这里
))


def _get_json(url, timeout):
    try:
        res = requests.get(url, headers=_HEADERS, timeout=timeout)
    except requests.RequestException as e:
        raise UpdateError('连接不上更新服务器（%s）' % _short(e))
    if res.status_code == 404:
        raise UpdateError('仓库里还没有发布版本')
    if res.status_code == 403:
        raise UpdateError('请求被 GitHub 拒绝（可能是访问频率限制）')
    if res.status_code != 200:
        raise UpdateError('更新服务器返回 %d' % res.status_code)
    try:
        return res.json()
    except ValueError:
        raise UpdateError('更新服务器返回的内容看不懂')


def _short(exc):
    """requests 的异常消息很长，截一下再给用户看。"""
    s = str(exc)
    if 'Name or service not known' in s or 'getaddrinfo' in s:
        return '域名解析失败'
    if 'timed out' in s or 'timeout' in s.lower():
        return '连接超时'
    if 'SSL' in s or 'certificate' in s.lower():
        return '证书校验失败'
    return s.split('\n')[0][:80]


def parse_release(data):
    """把 GitHub 的 JSON 变成 Release。抽出来是为了能脱离网络测。"""
    tag = (data.get('tag_name') or '').strip()
    version = tag.lstrip('vV')
    asset = None
    for a in data.get('assets') or []:
        name = a.get('name') or ''
        if name.startswith(ASSET_PREFIX) and name.endswith(ASSET_SUFFIX):
            asset = a
            break
    return Release(
        version=version,
        tag=tag or ('v' + version),
        name=(data.get('name') or tag or version).strip(),
        notes=(data.get('body') or '').strip(),
        asset_name=(asset or {}).get('name', ''),
        asset_url=(asset or {}).get('browser_download_url', ''),
        asset_size=int((asset or {}).get('size') or 0),
        page_url=(data.get('html_url') or '').strip(),
    )


def check(timeout=15, fetch=None):
    """
    有新版返回 Release；已经是最新返回 None。

    fetch 只是为了测试能塞一个假的进去，正常调用不用传。
    """
    data = (fetch or _get_json)(API_LATEST, timeout)
    rel = parse_release(data)
    if not rel.version:
        raise UpdateError('更新信息里没有版本号')
    if not is_newer(rel.version, VERSION):
        return None
    return rel


def dest_dir():
    """安装包下载到哪。放临时目录 —— 不能放安装目录，那个目录待会儿会被覆盖。"""
    d = os.path.join(tempfile.gettempdir(), 'TsinghuaBookCrawlerUpdate')
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def local_path(rel):
    name = rel.asset_name or ('%s%s%s' % (ASSET_PREFIX, rel.version, ASSET_SUFFIX))
    return os.path.join(dest_dir(), name)


def download(rel, on_progress=None, cancel=None, timeout=60, fetch=None):
    """
    下载安装包，返回本地路径。

    on_progress(done_bytes, total_bytes)：total 为 0 表示服务器没给长度。
    已经下完的（大小对得上）直接复用，重复点「下载」不会重下一遍。
    """
    if not rel.asset_url:
        raise UpdateError('这个版本没有提供安装包，请到发布页面手动下载')

    path = local_path(rel)
    part = path + '.part'

    if rel.asset_size and os.path.exists(path):
        try:
            if os.path.getsize(path) == rel.asset_size:
                if on_progress:
                    on_progress(rel.asset_size, rel.asset_size)
                return path
        except OSError:
            pass

    getter = fetch or requests.get
    try:
        res = getter(rel.asset_url, headers=_HEADERS, stream=True, timeout=timeout)
    except requests.RequestException as e:
        raise UpdateError('下载失败：%s' % _short(e))

    if getattr(res, 'status_code', 200) != 200:
        raise UpdateError('下载失败：服务器返回 %d' % res.status_code)

    total = int(res.headers.get('Content-Length') or rel.asset_size or 0)
    done = 0
    try:
        with open(part, 'wb') as fh:
            for chunk in res.iter_content(CHUNK):
                if cancel is not None and cancel.is_set():
                    raise UpdateError('已取消')
                if not chunk:
                    continue
                fh.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
    except UpdateError:
        _cleanup(part)
        raise
    # 注意顺序：requests.RequestException 继承自 OSError，所以它必须排在
    # OSError 前面，否则断线会被误报成「写文件失败」，用户完全看不出问题在哪。
    except requests.RequestException as e:
        _cleanup(part)
        raise UpdateError('下载中断：%s' % _short(e))
    except OSError as e:
        _cleanup(part)
        raise UpdateError('写文件失败：%s' % e)

    # 大小对不上说明下到一半断了，宁可报错也不要装一个坏包
    if total and done != total:
        _cleanup(part)
        raise UpdateError('下载不完整（%d/%d 字节）' % (done, total))

    try:
        if os.path.exists(path):
            os.remove(path)
        os.replace(part, path)
    except OSError as e:
        _cleanup(part)
        raise UpdateError('保存安装包失败：%s' % e)
    return path


def _cleanup(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def launch(installer, exe=None, silent=True):
    """
    运行安装包，并（可选）在装完后把程序重新拉起来。

    为什么用 cmd 而不是直接 Popen 安装包：安装包要覆盖的正是当前正在运行的
    这个程序，所以必须等本进程退干净。这里起一个独立的 cmd，它先 start /wait
    等安装结束，再 start 把程序拉起来 —— 本进程随后就可以放心退出了。

    安装包是 PrivilegesRequired=lowest（装到用户目录），所以 /SILENT 不会弹
    UAC，也不需要管理员。
    """
    if not os.path.exists(installer):
        raise UpdateError('安装包不见了：%s' % installer)

    args = ['"%s"' % installer]
    if silent:
        args.append('/SILENT')
        args.append('/NORESTART')

    cmd = 'start "" /wait ' + ' '.join(args)
    if exe and os.path.exists(exe):
        cmd += ' & start "" "%s"' % exe

    flags = 0
    if sys.platform == 'win32':
        # 脱离本进程的进程组，本进程退出不会把它带走
        flags = 0x00000008 | 0x00000200          # DETACHED_PROCESS | NEW_PROCESS_GROUP
    try:
        # 必须 shell=True，不能写成 Popen(['cmd', '/c', cmd])。
        #
        # 传 list 给 Popen 时，Windows 上 Python 会用 list2cmdline 再拼一遍
        # 命令行，于是我们自己写的引号又被包了一层，cmd.exe 解析不了 ——
        # 实测报「文件名、目录名或卷标语法不正确」，而且 Popen 本身不抛异常，
        # 安装包就这么被静默丢掉了，用户点了「立即安装」什么都不会发生。
        # shell=True 是把命令串原样交给 cmd /c，引号不会被二次处理。
        subprocess.Popen(cmd, creationflags=flags, close_fds=True, shell=True)
    except OSError as e:
        raise UpdateError('无法启动安装程序：%s' % e)
    return cmd


def current_exe():
    """
    当前程序自己的 exe 路径。打包后 sys.executable 就是它；
    源码运行时返回空串（那种情况下不该重启自己）。
    """
    if getattr(sys, 'frozen', False):
        return sys.executable
    return ''


def cancel_token():
    return threading.Event()
