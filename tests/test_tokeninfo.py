# coding:utf-8
"""
Token 解析的离线测试。全用合成的 JWT，不需要真实凭证。

真实 Token 的声明结构还没见过，所以这里覆盖「有 exp / 没有 exp /
根本不是 JWT / 字段类型不对」这些分支 —— 任何一种都不能把程序搞崩，
最差也要退回 unknown。
"""
import base64
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

from tests._isolate import isolate  # noqa: E402

_CFG = isolate()

from xk_app.app.core import tokeninfo as ti  # noqa: E402

fails = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + '  ' + msg, flush=True)
    if not cond:
        fails.append(msg)


def make_jwt(payload, header=None):
    """造一个签名随便填的 JWT —— 我们只读声明，不验签。"""
    def seg(obj):
        raw = json.dumps(obj, separators=(',', ':')).encode('utf-8')
        return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    h = header if header is not None else {'alg': 'RS256', 'typ': 'JWT'}
    return '%s.%s.%s' % (seg(h), seg(payload), 'c2lnbmF0dXJl')


def main():
    now = time.time()

    print('=== 1. 正常 JWT，远期到期 ===', flush=True)
    t = make_jwt({'exp': int(now + 30 * 86400), 'iat': int(now),
                  'iss': 'ereserves.lib.tsinghua.edu.cn'})
    info = ti.TokenInfo(t)
    check(info.is_jwt, 'is_jwt = True')
    check(info.state(now) == 'valid', 'state = valid（30 天后到期）')
    check(abs(info.seconds_left(now) - 30 * 86400) < 2, 'seconds_left 正确')
    check(info.issuer == 'ereserves.lib.tsinghua.edu.cn', 'iss 读出来了')
    check('有效期至' in info.describe(now), 'describe 含到期时间')
    check('30 天' in info.describe(now), 'describe 含剩余天数')
    check(t not in info.describe(now), 'describe 不泄露 Token 原文')

    print('=== 2. 快过期（3 天内）→ soon ===', flush=True)
    t = make_jwt({'exp': int(now + 2 * 3600)})
    info = ti.TokenInfo(t)
    check(info.state(now) == 'soon', 'state = soon（2 小时后到期）')
    check('小时' in info.describe(now), 'describe 用小时表述')

    print('=== 3. 已过期 ===', flush=True)
    t = make_jwt({'exp': int(now - 60)})
    info = ti.TokenInfo(t)
    check(info.state(now) == 'expired', 'state = expired')
    check(info.is_expired(now) is True, 'is_expired = True')
    check(info.describe(now) == 'Token 已过期', 'describe = Token 已过期')

    # --- 真机教训：清华教参的 Token 寿命只有 63 分钟 ---
    # 拿真 Token 跑出来的：iat 1789549798 -> exp 1789553578，差 3780 秒。
    # 如果「快过期」的阈值写死成 3 天，那刚签发的全新 Token 也一直是
    # 快过期，侧边栏的提示就永远亮着，用户会直接无视它。
    print('=== 3b. 63 分钟寿命的短 Token（阈值跟着寿命走）===', flush=True)
    life = 63 * 60
    t = make_jwt({'iat': int(now), 'exp': int(now + life)})
    info = ti.TokenInfo(t)
    check(info.state(now) == 'valid',
          '刚签发的 63 分钟 Token = valid（不能一上来就报快过期）')
    check(abs(info.warn_seconds() - life * ti.WARN_RATIO) < 1,
          'warn_seconds = 寿命的 %d%%（%.0f 秒）'
          % (ti.WARN_RATIO * 100, info.warn_seconds()))
    # 剩余 10 分钟 < 12.6 分钟阈值 -> soon
    check(info.state(now + life - 600) == 'soon',
          '剩 10 分钟 -> soon')
    check(info.state(now + life - 1500) == 'valid',
          '剩 25 分钟 -> 仍然 valid')
    check('尽快重新登录' in info.describe(now + life - 600),
          'soon 时 describe 文字上也说清楚（不只靠颜色）')
    check(info.is_expired(now + life + 1) is True, '过点即 expired')

    print('=== 3c. 寿命长短不影响「新 Token 不报警」===', flush=True)
    for name, lf in (('5 分钟', 300), ('60 秒', 60), ('30 天', 30 * 86400)):
        t = make_jwt({'iat': int(now), 'exp': int(now + lf)})
        i2 = ti.TokenInfo(t)
        check(i2.state(now) == 'valid', '%s 寿命：新 Token = valid' % name)
    t = make_jwt({'iat': int(now), 'exp': int(now + 30 * 86400)})
    info = ti.TokenInfo(t)
    check(abs(info.warn_seconds() - ti.WARN_MAX) < 1,
          '30 天寿命：阈值封顶到 3 天（%.0f 秒）' % info.warn_seconds())
    # 没有 iat 时退回保守值，保证老 Token 依旧会提醒
    t = make_jwt({'exp': int(now + 2 * 3600)})
    info = ti.TokenInfo(t)
    check(abs(info.warn_seconds() - ti.WARN_MAX) < 1,
          '读不到 iat -> 退回 3 天阈值（保守）')

    print('=== 3d. 当前账号（侧边栏要显示登的是谁）===', flush=True)
    # 清华教参的 payload 里 userName 是姓名、userId 是学号，
    # sub 恒为 'JCClientUser'（不是人名，不能拿来当账号）
    t = make_jwt({'iat': int(now), 'exp': int(now + 3780),
                  'sub': 'JCClientUser', 'userId': '2024000001',
                  'userKey': '2024000001', 'userName': '张三'})
    info = ti.TokenInfo(t)
    check(info.account_label() == '张三', 'account_label 取到姓名')
    check(info.account_id == '2024000001', 'account_id 取到学号')
    check('张三' in info.account_tooltip()
          and '2024000001' in info.account_tooltip(),
          'tooltip 同时有姓名和学号')
    check('JCClientUser' not in info.account_tooltip(),
          '  不会把 sub 那个固定客户端标识当账号')

    # 别的平台用别的字段名，也得认
    for key in ('name', 'displayName', 'nickName', 'preferred_username'):
        i3 = ti.TokenInfo(make_jwt({'exp': int(now + 3600), key: '李四'}))
        check(i3.account_label() == '李四', '认 %s 这个字段名' % key)

    # 没有名字时返回 None，让界面自己去决定退回什么文案，别编一个假的
    i4 = ti.TokenInfo(make_jwt({'exp': int(now + 3600)}))
    check(i4.account_label() is None, '没有名字 -> None（不编造）')
    check(i4.account_tooltip() == '', '  tooltip 也是空的')
    i5 = ti.TokenInfo('not-a-jwt-at-all-but-long-enough')
    check(i5.account_label() is None, '非 JWT -> None')

    print('=== 3e. 侧边栏那行倒计时 ===', flush=True)
    info = ti.TokenInfo(make_jwt({'iat': int(now), 'exp': int(now + 3780)}))
    check(info.left_text(now) == '还剩 1 小时 3 分',
          'left_text：%s' % info.left_text(now))
    check(info.left_text(now + 3780 + 5) == '已过期，需重新登录',
          '过期后 left_text：%s' % info.left_text(now + 3780 + 5))
    i6 = ti.TokenInfo(make_jwt({'iat': int(now)}))
    check(i6.left_text(now) == '读不到到期时间', '读不到时不给假倒计时')

    print('=== 4. JWT 但没有 exp → unknown ===', flush=True)
    t = make_jwt({'iat': int(now), 'sub': 'someone'})
    info = ti.TokenInfo(t)
    check(info.is_jwt, '仍然认得出是 JWT')
    check(not info.has_expiry, 'has_expiry = False')
    check(info.state(now) == 'unknown', 'state = unknown')
    check(info.seconds_left(now) is None, 'seconds_left = None')
    check('失效时会在下载时提示' in info.describe(now), 'describe 说明只能靠服务器判断')

    print('=== 5. 根本不是 JWT ===', flush=True)
    for bad in ('', 'just-a-random-string', 'a.b', 'a.b.c.d',
                'eyJhbGciOiJIUzI1NiJ9', None):
        info = ti.TokenInfo(bad or '')
        check(not info.is_jwt, '认作非 JWT：%r' % (bad,))
        check(info.state(now) == 'unknown', '  且 state = unknown')
        check(info.describe(now) != '', '  describe 不崩且非空')

    print('=== 6. 畸形 payload 不能崩 ===', flush=True)
    for raw_payload in ('not-base64!!!', 'eyJ', 'e30', 'W10', 'bnVsbA'):
        t = 'eyJhbGciOiJIUzI1NiJ9.%s.c2ln' % raw_payload
        try:
            info = ti.TokenInfo(t)
            ok = True
        except Exception as e:                                       # noqa: BLE001
            ok = False
            print('     抛出 %s: %s' % (type(e).__name__, e), flush=True)
        check(ok, '畸形 payload 不抛异常：%r' % raw_payload)

    print('=== 7. exp 字段类型不对 ===', flush=True)
    for weird in ('2026-01-01', None, True, [1, 2], {'a': 1}):
        t = make_jwt({'exp': weird})
        info = ti.TokenInfo(t)
        check(not info.has_expiry,
              'exp=%r 视为读不到到期时间' % (weird,))
        check(info.state(now) == 'unknown', '  且 state = unknown')

    print('=== 8. 毫秒级时间戳也能认 ===', flush=True)
    t = make_jwt({'exp': int((now + 10 * 86400) * 1000)})
    info = ti.TokenInfo(t)
    check(info.state(now) == 'valid', '毫秒级 exp 解析为 10 天后')

    print('=== 9. 非 dict 的 header/payload ===', flush=True)
    t = 'W10.W10.c2ln'          # [] . [] . sig
    info = ti.TokenInfo(t)
    check(not info.is_jwt, '数组 payload 不算有效 JWT')

    print('=== 10. extract_token：从粘贴内容里抠 Token ===', flush=True)
    jwt = make_jwt({'exp': int(now + 86400)})
    url = 'https://ereserves.lib.tsinghua.edu.cn/index?token=%s' % jwt
    cases = [
        (url, jwt, '整条 URL'),
        (url + '&foo=1', jwt, 'URL 带其他参数'),
        ('  %s  ' % url, jwt, '两侧空白'),
        ('"%s"' % url, jwt, '带引号'),
        (jwt, jwt, '裸 JWT'),
        ('https://x\n%s' % url, jwt, '多行粘贴'),
        ('token=%s' % jwt, jwt, '只有 key=value 片段'),
        ('', '', '空串'),
        ('hello world', '', '普通短文本'),
        (None, '', 'None'),
        (url + '#hash', jwt, 'URL 带锚点'),
    ]
    for text, want, label in cases:
        got = ti.extract_token(text)
        check(got == want, '%s -> %s' % (label, '抠到' if want else '抠不到'))

    print('', flush=True)
    if fails:
        print('TOKENINFO FAIL (%d)' % len(fails), flush=True)
        for f in fails:
            print('  - ' + f, flush=True)
        return 1
    print('TOKENINFO PASS', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
