# coding:utf-8
"""
Token 的本地解析：判断它是不是 JWT、能不能读出到期时间。

为什么要单独一层：Token 什么时候失效，只有两个可靠来源 ——
一是 JWT 自己声明的 exp，二是服务器真的拒绝了。前者能提前预警，
后者只能事后发现。两个都要用，而且都不能假设一定拿得到。

解析失败、不是 JWT、没有 exp，都不算错误：退回「靠服务器拒绝来判断」。
Token 是凭证，这个模块只读不写，也绝不把它写进日志。
"""
import base64
import binascii
import json
import math
import time

# 「当前是谁」的声明名，各平台叫法不一样，挨个试。
# 注意不用 sub：它常常只是个固定的客户端标识（清华这个平台就是恒定的
# 'JCClientUser'），拿来当账号名是错的。
CLAIMS_NAME = ('userName', 'name', 'displayName', 'nickName',
               'preferred_username')
CLAIMS_ACCOUNT = ('userId', 'userKey', 'studentId', 'employeeId',
                  'preferred_username')

# 只认这三种最常见的到期相关声明
CLAIM_EXP = 'exp'
CLAIM_IAT = 'iat'
CLAIM_NBF = 'nbf'

# 「快过期」的判定：取 Token 自身寿命的一段比例，并夹在上下限之间。
#
# 为什么不能用一个固定值：清华教参的 Token 实测寿命只有 63 分钟
# （iat 1789549798 -> exp 1789553578）。如果按「3 天内算快过期」，
# 那刚签发、还剩 63 分钟的全新 Token 也会被判成「快过期」——提示永远亮着，
# 用户很快就会学会无视它，真正要过期时反而看不见了。
#
# 按寿命的 20% 算：63 分钟的 Token 在剩余 12.6 分钟时开始提醒，刚好够
# 重新登录一次。寿命很长的 Token（比如 30 天）则封顶到 3 天。
WARN_RATIO = 0.2
WARN_MIN = 5 * 60                  # 再短的 Token 也至少提前 5 分钟提醒
WARN_MAX = 3 * 24 * 3600           # 寿命长的一律按 3 天


def _b64url_decode(seg):
    """base64url 解码，补齐 padding。JWT 的 padding 是被去掉的。"""
    pad = '=' * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def looks_like_jwt(token):
    """粗判：三段、点分隔、前两段是 base64url。"""
    if not token or not isinstance(token, str):
        return False
    parts = token.strip().split('.')
    if len(parts) != 3 or not all(parts):
        return False
    for seg in parts[:2]:
        try:
            _b64url_decode(seg)
        except (binascii.Error, ValueError):
            return False
    return True


def extract_token(text):
    """
    从用户粘进来的东西里抠出 Token。

    用户手上拿到的往往不是光秃秃的 Token，而是一整条
    「https://ereserves.lib.tsinghua.edu.cn/index?token=eyJh...」——
    要求他自己切掉前后半截是不合理的。所以这里三种都收：
    完整 URL、带 token= 的片段、以及本身就是 Token 的字符串。

    抠不出来返回 ''。
    """
    if not text or not isinstance(text, str):
        return ''
    s = text.strip().strip('"').strip("'").strip()
    if not s:
        return ''

    # 多行粘贴：逐行找第一条像 Token 的
    if '\n' in s:
        for line in s.splitlines():
            got = extract_token(line)
            if got:
                return got
        return ''

    # URL 或带查询串的片段
    if 'token=' in s:
        tail = s.split('token=', 1)[1]
        # 截到下一个分隔符为止
        for sep in ('&', '#', '?', ' ', '\t', '"', "'"):
            tail = tail.split(sep, 1)[0]
        tail = tail.strip()
        return tail if tail else ''

    # 已经是 Token 本身：JWT 形如三段点分
    if looks_like_jwt(s):
        return s

    # 兜底：没有任何分隔符的长串，当 Token 收下（有的平台不是 JWT）
    if len(s) >= 24 and not any(c in s for c in ' /\\'):
        return s
    return ''


def decode_jwt(token):
    """
    解出 JWT 的 header/payload。签名不验（我们也没有密钥），
    只是读声明 —— 到期时间是给用户看的提示，不是安全边界。
    解析不出来返回 None。
    """
    if not looks_like_jwt(token):
        return None
    parts = token.strip().split('.')
    out = {}
    for name, seg in (('header', parts[0]), ('payload', parts[1])):
        try:
            raw = _b64url_decode(seg)
            obj = json.loads(raw.decode('utf-8'))
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return None
        if not isinstance(obj, dict):
            return None
        out[name] = obj
    return out


def _as_ts(claims, key):
    v = claims.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    # 秒级时间戳。毫秒级（13 位）也容忍一下
    if v > 1e11:
        v = v / 1000.0
    return float(v)


def _first_str(claims, keys):
    """按顺序取第一个非空字符串声明。取不到返回 None。"""
    for k in keys:
        v = claims.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


class TokenInfo:
    """一个 Token 的「可读」视图。只保留展示需要的东西，不留原文。"""

    def __init__(self, token):
        self.is_jwt = False
        self.claims = {}
        self.expires_at = None
        self.issued_at = None
        self.not_before = None
        self.issuer = None
        self.subject = None
        self.display_name = None
        self.account_id = None
        self.error = None

        decoded = decode_jwt(token)
        if decoded is None:
            self.error = '不是 JWT，读不到到期时间'
            return

        self.is_jwt = True
        payload = decoded.get('payload') or {}
        self.claims = payload
        self.expires_at = _as_ts(payload, CLAIM_EXP)
        self.issued_at = _as_ts(payload, CLAIM_IAT)
        self.not_before = _as_ts(payload, CLAIM_NBF)
        iss = payload.get('iss')
        sub = payload.get('sub')
        self.issuer = iss if isinstance(iss, str) else None
        self.subject = sub if isinstance(sub, str) else None
        self.display_name = _first_str(payload, CLAIMS_NAME)
        self.account_id = _first_str(payload, CLAIMS_ACCOUNT)

    def account_label(self):
        """
        侧边栏那一行显示的「当前账号」。

        读不到名字就返回 None —— 让调用方自己决定退回到什么文案，
        而不是在这里编一个假的。
        """
        return self.display_name

    def account_tooltip(self):
        """账号的完整信息（名字 + 学号/工号），给 tooltip 用。"""
        parts = []
        if self.display_name:
            parts.append(self.display_name)
        if self.account_id and self.account_id != self.display_name:
            parts.append('账号 %s' % self.account_id)
        return ' · '.join(parts)

    # ---------------------------------------------------------------- 查询
    @property
    def has_expiry(self):
        return self.expires_at is not None

    def seconds_left(self, now=None):
        """剩余秒数；读不到到期时间返回 None。已过期返回负数。"""
        if self.expires_at is None:
            return None
        return self.expires_at - (time.time() if now is None else now)

    def is_expired(self, now=None):
        left = self.seconds_left(now)
        return None if left is None else left <= 0

    def warn_seconds(self):
        """
        「快过期」的阈值：Token 自身寿命的 WARN_RATIO，夹在上下限之间。

        读不到 iat 时退回 WARN_MAX（保守：宁可早点提醒）。
        """
        if self.expires_at is not None and self.issued_at is not None:
            life = self.expires_at - self.issued_at
            if life > 0:
                # 下限也不能超过寿命的一半，否则寿命极短的 Token 一签发
                # 就落在「快过期」里 —— 全新凭证不该一上来就报警
                floor = min(float(WARN_MIN), life * 0.5)
                return max(floor, min(float(WARN_MAX), life * WARN_RATIO))
        return float(WARN_MAX)

    def state(self, now=None, warn_seconds=None):
        """
        'expired'   已过期
        'soon'      快过期（阈值跟着 Token 自己的寿命走，见 warn_seconds）
        'valid'     还有效
        'unknown'   读不到到期时间，只能靠服务器判断
        """
        left = self.seconds_left(now)
        if left is None:
            return 'unknown'
        if left <= 0:
            return 'expired'
        limit = self.warn_seconds() if warn_seconds is None else warn_seconds
        if left <= limit:
            return 'soon'
        return 'valid'

    def left_text(self, now=None):
        """
        侧边栏那一行窄文字用的短句。

        和 describe() 的区别：describe() 是给 tooltip 的完整句子（含具体
        到期时刻），这个是给侧边栏一格像素用的，只保留最要紧的剩余时间。
        """
        left = self.seconds_left(now)
        if left is None:
            return '读不到到期时间'
        if left <= 0:
            return '已过期，需重新登录'
        return '还剩 ' + _fmt_left(left)

    def describe(self, now=None):
        """给界面用的一句话。"""
        left = self.seconds_left(now)
        if left is None:
            return '读不到到期时间，失效时会在下载时提示'
        if left <= 0:
            return 'Token 已过期'
        base = '有效期至 %s（还剩 %s）' % (_fmt_time(self.expires_at),
                                          _fmt_left(left))
        # 状态除了颜色，文字上也要说清楚 —— 只靠颜色区分对色觉障碍不友好
        if self.state(now) == 'soon':
            return base + '，建议尽快重新登录'
        return base


def _fmt_time(ts):
    try:
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
    except (OSError, ValueError, OverflowError):
        return '未知时间'


def _fmt_left(seconds):
    """
    向上取整再拆，并且去掉为 0 的那一段。

    为什么要取整：exp 是整数秒，减完往往是 2591999.5 这种值，直接截断会
    把「还剩 30 天」显示成「29 天 23 小时」，看着像快过期了。
    """
    seconds = max(0, int(math.ceil(seconds)))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return '%d 天' % days if not hours else '%d 天 %d 小时' % (days, hours)
    if hours:
        return '%d 小时' % hours if not minutes else '%d 小时 %d 分' % (hours, minutes)
    return '%d 分钟' % minutes
