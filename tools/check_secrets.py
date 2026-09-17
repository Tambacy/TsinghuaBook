# coding:utf-8
"""
凭据泄漏检查（离线，不联网）。发布前必跑。

为什么需要它：这个程序要用户把图书馆的登录 token 贴进来，所以仓库里到处
都是「token」这个词和长得像 JWT 的测试夹具。人工肉眼看不出哪个是真的、
哪个是假的，而一旦真的提交上去，就算事后删掉，历史里也还留着。

所以这里不靠「找某个已知的真实值」——那样等于把真实值本身写进仓库，
自相矛盾。改成两条更耐用的判据：

  1. 结构判据：真的 JWT 签名段一定很长（HS256 至少 43 字符，RS256 更长），
     真的 GitHub token 有固定前缀。测试夹具都是 `xxx.sig`、`.demo.token`
     这种短占位符，长度上过不去。
  2. 白名单判据：清华学号是 10 位、20 开头，测试里只允许用登记过的假号。
     任何没登记的 10 位数字都会被拦下来 —— 包括那个已经过期、但绝不该
     进仓库的真实学号。

用法：
    python tools/check_secrets.py              # 只查已纳入版本控制的文件
    python tools/check_secrets.py --history    # 连带查全部提交历史里的对象
"""
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

# 允许出现在仓库里的假学号。用真号当夹具是 v2.0 踩过的坑，已全部换掉；
# 新加的夹具请登记到这里，别偷偷放行。
FAKE_ACCOUNT_IDS = {
    '2024000001',
    '2021000000',
}

# 看起来像 JWT 就行，真假交给下面 _jwt_is_realistic() 判。
_JWT_RE = re.compile(r'eyJ[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]*')
_ACCOUNT_ID_RE = re.compile(r'(?<![0-9])20[0-9]{8}(?![0-9])')
_ID_CARD_RE = re.compile(r'(?<![0-9])[1-9][0-9]{16}[0-9Xx](?![0-9])')

# (名字, 正则, 说明)
_PATTERNS = [
    ('github-token', re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}'),
     'GitHub 访问令牌'),
    ('github-pat', re.compile(r'github_pat_[A-Za-z0-9_]{20,}'),
     'GitHub 细粒度令牌'),
    ('private-key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
     '私钥文件内容'),
    ('aws-key', re.compile(r'(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])'),
     'AWS Access Key ID'),
    ('slack-token', re.compile(r'xox[abp]-[A-Za-z0-9\-]{10,}'),
     'Slack 令牌'),
    ('id-card', _ID_CARD_RE, '身份证号'),
]

# 这些路径本来就不该扫，或者扫了必然误报。
_SKIP_DIRS = {'.git', 'venv', '.venv', 'build', 'dist', '__pycache__',
              '_smoke', '_cfgtest', 'node_modules', '.dsh'}
_SKIP_SUFFIX = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf',
                '.zip', '.exe', '.dll', '.pyd', '.pyc', '.woff', '.woff2')

FAILED = []


def check(ok, msg):
    print('  %s %s' % ('OK  ' if ok else 'FAIL', msg), flush=True)
    if not ok:
        FAILED.append(msg)


def _jwt_is_realistic(text):
    """
    真的 JWT 签名段一定够长；测试夹具都是短占位符。
    载荷段同理 —— 真实载荷里塞得下 userId/userName/exp 一堆声明。
    命中就返回 match 对象（要拿 start() 定位行号），否则 None。
    """
    for m in _JWT_RE.finditer(text):
        parts = m.group(0).split('.')
        if len(parts) != 3:
            continue
        payload, sig = parts[1], parts[2]
        if len(sig) >= 40 or len(payload) >= 120:
            return m
    return None


def _line_of(text, index):
    return text.count('\n', 0, index) + 1


def _scan_text(text):
    """
    返回 [(行号, 说明, 命中片段), ...]，同一行同一规则只报一次。

    逐行扫规则，JWT 例外 —— 测试里有跨行拼接出来的 JWT
    （'eyJ...' 换行 '.eyJ...'），按行切就漏了，所以整段判。
    """
    hits = []
    seen = set()

    def add(lineno, desc, frag):
        key = (lineno, desc)
        if key in seen:
            return
        seen.add(key)
        hits.append((lineno, desc, frag))

    m = _jwt_is_realistic(text)
    if m:
        add(_line_of(text, m.start()),
            '真实长度的 JWT（不是测试占位符）', m.group(0)[:24] + '...')

    for lineno, line in enumerate(text.splitlines(), 1):
        for _name, rx, desc in _PATTERNS:
            hit = rx.search(line)
            if hit:
                add(lineno, desc, hit.group(0)[:40])
        for hit in _ACCOUNT_ID_RE.finditer(line):
            val = hit.group(0)
            if val not in FAKE_ACCOUNT_IDS:
                add(lineno, '未登记的 10 位学号/工号', val)

    return hits


def _tracked_files():
    out = subprocess.run(['git', 'ls-files'], cwd=_ROOT,
                         capture_output=True)
    names = out.stdout.decode('utf-8', 'replace').splitlines()
    return [os.path.join(_ROOT, n) for n in names if n.strip()]


def _scan_worktree():
    print('扫描已纳入版本控制的文件', flush=True)
    files = _tracked_files()
    found = []
    for path in files:
        rel = os.path.relpath(path, _ROOT)
        if rel.lower().endswith(_SKIP_SUFFIX):
            continue
        try:
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, desc, frag in _scan_text(text):
            found.append((rel, lineno, desc, frag))
    check(not found, '工作区 %d 个受控文件里没有真实凭据（命中 %d）'
          % (len(files), len(found)))
    return found


def _all_blobs():
    """一次问出仓库里所有 blob，避免按提交逐个 cat-file。"""
    out = subprocess.run(
        ['git', 'cat-file', '--batch-all-objects',
         '--batch-check=%(objectname) %(objecttype)'],
        cwd=_ROOT, capture_output=True)
    shas = []
    for line in out.stdout.decode('utf-8', 'replace').splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == 'blob':
            shas.append(parts[0])
    return shas


def _cat_blobs(shas):
    if not shas:
        return {}
    payload = ('\n'.join(shas) + '\n').encode('ascii')
    out = subprocess.run(['git', 'cat-file', '--batch'], cwd=_ROOT,
                         input=payload, capture_output=True)
    data = out.stdout
    blobs = {}
    pos = 0
    for sha in shas:
        nl = data.find(b'\n', pos)
        if nl < 0:
            break
        header = data[pos:nl].decode('utf-8', 'replace').split()
        if len(header) != 3:
            break
        size = int(header[2])
        body = data[nl + 1:nl + 1 + size]
        blobs[sha] = body.decode('utf-8', 'replace')
        pos = nl + 1 + size + 1
    return blobs


def _scan_history():
    print('', flush=True)
    print('扫描全部提交历史里的对象', flush=True)
    shas = _all_blobs()
    blobs = _cat_blobs(shas)
    found = []
    for sha, text in blobs.items():
        for lineno, desc, frag in _scan_text(text):
            found.append(('%s:%d' % (sha[:10], lineno), 0, desc, frag))
    check(not found, '历史 %d 个对象里没有真实凭据（命中 %d）'
          % (len(shas), len(found)))
    return found


def main():
    print('凭据泄漏检查', flush=True)
    print('  仓库 = %s' % _ROOT, flush=True)
    print('', flush=True)

    findings = _scan_worktree()

    if '--history' in sys.argv:
        findings += _scan_history()
    else:
        print('', flush=True)
        print('  （加 --history 可连带扫描全部提交历史）', flush=True)

    if findings:
        print('', flush=True)
        print('命中明细：', flush=True)
        for loc, lineno, desc, frag in findings[:60]:
            where = '%s:%d' % (loc, lineno) if lineno else loc
            print('  %-28s %-22s %s' % (where, desc, frag), flush=True)
        if len(findings) > 60:
            print('  ... 另有 %d 条' % (len(findings) - 60), flush=True)

    print('', flush=True)
    if FAILED:
        print('SECRETS FAIL (%d)' % len(FAILED), flush=True)
        for x in FAILED:
            print('   - %s' % x, flush=True)
        return 1
    print('SECRETS PASS', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
