# coding:utf-8
"""
登录页的冒烟测试。

注意：QWebEngineView 在 offscreen 平台下起不来（Chromium 需要真实窗口），
所以这里只测 Token 模式的完整行为 + SSO 面板的「按需创建」逻辑，
不真的实例化浏览器。真机渲染由 render_real.py 负责。
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

from tests._isolate import isolate  # noqa: E402

_CFG = isolate()

from xk_app.app.core import store, tokeninfo  # noqa: E402
from xk_app.app.gui import login as L  # noqa: E402
from xk_app.app.gui import theme as T  # noqa: E402

fails = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + '  ' + msg, flush=True)
    if not cond:
        fails.append(msg)


def make_jwt(exp_offset, iat_offset=0):
    import base64
    import json as _json
    import time as _time

    def seg(obj):
        raw = _json.dumps(obj, separators=(',', ':')).encode('utf-8')
        return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')

    now = _time.time()
    return '%s.%s.sig' % (
        seg({'alg': 'RS256', 'typ': 'JWT'}),
        seg({'exp': int(now + exp_offset), 'iat': int(now + iat_offset),
             'iss': 'ereserves.lib.tsinghua.edu.cn'}))


def main():
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from xk_app.app.gui import theme as T
    T.install_app_font(app)
    from xk_app.app.gui import login as L

    st = store.Settings()
    st.update(login_mode='sso', token='')

    print('=== 1. 构造与默认模式 ===', flush=True)
    scr = L.LoginScreen(st)
    scr.resize(1180, 760)
    # 惰性：还没显示之前不该把 Chromium 拉起来
    check(scr.sso._view is None, 'show() 之前没有创建浏览器（惰性）')
    scr.show()
    app.processEvents()
    check(scr.mode() == 'sso', '默认模式 = sso')
    check(scr.tabs.currentIndex() == 0, '分段控件停在第 0 段')
    check(scr.stack.currentIndex() == 0, '堆栈停在 SSO 面板')
    check(scr.brand.width() >= L.BRAND_W_MIN
          and scr.brand.width() <= L.BRAND_W_MAX,
          '左栏宽度被夹在 [%d, %d]，实际 %d'
          % (L.BRAND_W_MIN, L.BRAND_W_MAX, scr.brand.width()))
    check(scr.stack.currentWidget() is scr.sso, '当前是 SSO 面板')
    # show() 之后 SSO 会自己去加载；能不能起来取决于这个环境有没有
    # 可用的内嵌浏览器，两种结果都算正常，报告一下是哪种
    web_ok = scr.sso._view is not None
    print('  (内嵌浏览器%s可用)' % ('' if web_ok else '不'), flush=True)

    print('=== 2. 切到 Token 模式 ===', flush=True)
    scr.set_mode('token', animate=False)
    app.processEvents()
    check(scr.mode() == 'token', 'mode = token')
    check(scr.stack.currentIndex() == 1, '堆栈切到 Token 面板')
    check(scr.tabs.currentIndex() == 1, '分段控件跟着切')

    p = scr.token
    print('=== 3. 有效期提示 ===', flush=True)
    p.set_token(make_jwt(30 * 86400))
    app.processEvents()
    check('有效期至' in p.status.text(), '远期 Token 显示有效期')
    check('30 天' in p.status.text(), '  且剩余天数正确：%s' % p.status.text())
    check(T.ACCENT in p.status.styleSheet(), '  用「有效」的颜色')

    # 临期：寿命 30 天、只剩 12 小时。阈值是寿命的 20%（封顶 3 天）= 3 天，
    # 所以 12 小时落在阈值内 -> soon
    _life = 30 * 86400
    p.set_token(make_jwt(12 * 3600, iat_offset=12 * 3600 - _life))
    app.processEvents()
    check('小时' in p.status.text(),
          '临期 Token 用小时表述：%s' % p.status.text())
    check(T.WARN in p.status.styleSheet(), '  用「警告」的颜色')

    # 回归：清华教参的 Token 实测只活 63 分钟（iat 1789549798 ->
    # exp 1789553578）。阈值如果写死成固定值，刚签发的全新 Token 也会被判成
    # 「快过期」，提示永远亮着，用户很快就会学会无视它。
    p.set_token(make_jwt(63 * 60))
    app.processEvents()
    check(T.ACCENT in p.status.styleSheet(),
          '  新签发的 63 分钟 Token 算「有效」：%s' % p.status.text())

    p.set_token(make_jwt(-3600))
    app.processEvents()
    check('过期' in p.status.text(), '过期 Token 明确提示：%s' % p.status.text())
    check(T.DANGER in p.status.styleSheet(), '  用「危险」的颜色')

    print('=== 4. 非 JWT 也要有交代 ===', flush=True)
    p.set_token('some-opaque-token-value-1234567890')
    app.processEvents()
    check('失效时会在下载时提示' in p.status.text(),
          '非 JWT 说明只能靠服务器判断：%s' % p.status.text())
    check(T.TEXT_DIM in p.status.styleSheet(), '  用中性颜色')

    print('=== 5. 粘贴整条 URL 自动识别 ===', flush=True)
    jwt = make_jwt(10 * 86400)
    p.set_token('https://ereserves.lib.tsinghua.edu.cn/index?token=' + jwt)
    app.processEvents()
    check(p.token() == jwt, '从 URL 里抠出了 Token')
    check('有效期至' in p.status.text(), '  并且识别为有效 JWT')

    print('=== 5b. QUrl 往返不能把 Token 改坏 ===', flush=True)
    # SSO 截获链路上，内嵌浏览器给的是 QUrl，我们喂给 extract_token 的是
    # qurl.toString()。如果 Qt 把 Token 里的字符做了百分号编码，就会静默
    # 拿到一个错的字符串 —— 本地全绿，真机上永远登不进去。
    # 用真实 Token 的字符构成造一个：base64url 会带 '-' 和 '_'。
    # 签名段一律用假串 —— 别把任何真实凭证片段留在仓库里。
    from PyQt6.QtCore import QUrl
    from xk_app.app.gui import login as L
    _sig = ('AAAA-BBBB_CCCC-DDDD_EEEE-FFFF_GGGG-HHHH_IIII-JJJJ'
            '_KKKK-LLLL_MMMM-NNNN_OOOO-PPPP_QQQQ-RRRR_SSSS')
    _real_like = ('eyJhbGciOiJSUzI1NiJ9'
                  '.eyJpc3MiOiJKQ0NsaWVudCIsImlhdCI6MTc4OTU0OTc5OCwiZXhwIjox'
                  'Nzg5NTUzNTc4fQ'
                  '.' + _sig)
    for _name, _u in (
            ('查询串 ?token=',
             'https://ereserves.lib.tsinghua.edu.cn/index?token=' + _real_like),
            ('片段 #token=',
             'https://ereserves.lib.tsinghua.edu.cn/index#token=' + _real_like)):
        _qu = QUrl(_u)
        check(L._is_platform_url(_qu), '%s：认得出是平台地址' % _name)
        check(_qu.toString() == _u, '  QUrl 往返逐字节不变')
        check(tokeninfo.extract_token(_qu.toString()) == _real_like,
              '  从 toString() 抠出的 Token 与原文一致')

    print('=== 6. 空输入与垃圾输入 ===', flush=True)
    p.set_token('')
    app.processEvents()
    check(p.status.text() == '', '空输入不报错、不显示提示')
    check(p.token() == '', '  取 Token 得空串')
    p.edit.setPlainText('!!!not a token!!!')
    app.processEvents()
    check('不是 Token' in p.status.text(), '垃圾输入给出提示')

    print('=== 7. 提交信号 ===', flush=True)
    got = []
    scr.logged_in.connect(lambda t, s: got.append((t, s)))
    p.set_token(jwt)
    p._submit()
    app.processEvents()
    check(len(got) == 1 and got[0] == (jwt, 'token'),
          '点了「验证并登录」发出 logged_in(token, "token")')
    got.clear()
    p.set_token('')
    p._submit()
    app.processEvents()
    check(len(got) == 0, '空 Token 不发出登录信号')
    check('请先粘贴 Token' in p.status.text(), '  而是提示先粘贴')

    print('=== 8. SSO 面板的降级行为 ===', flush=True)
    check(hasattr(scr.sso, 'ensure_web'), 'SSO 面板有 ensure_web')
    check(callable(getattr(scr.sso, 'reset_session', None)), 'SSO 面板能清会话')
    if scr.sso._view is not None:
        check(scr.sso._profile is not None, '有浏览器时有配套的持久化 profile')
        check(type(scr.sso._view.page()).__name__ == 'PlatformPage',
              '证书/弹窗覆写生效')
    else:
        check(scr.sso.placeholder.isVisibleTo(scr.sso),
              '没有内嵌浏览器时给出降级说明')
        check('不可用' in scr.sso.status.text() or 'Token' in scr.sso.status.text(),
              '  并指引改用 Token 登录：%s' % scr.sso.status.text())

    print('=== 9. 模式选择会落盘吗（由 shell 负责保存）===', flush=True)
    scr.set_mode('sso', animate=False)
    app.processEvents()
    check(scr.mode() == 'sso', '切回 sso 正常')

    print('=== 10. 窄窗口不崩，且卡片不能被挤爆 ===', flush=True)
    from PyQt6.QtCore import QPoint
    for w, h in ((980, 660), (1280, 820), (1600, 900), (1100, 700)):
        scr.resize(w, h)
        app.processEvents()
        card = scr.card
        # 用真实坐标判断有没有被裁掉，别只看宽度
        left = card.mapTo(scr, QPoint(0, 0)).x()
        right = left + card.width()
        check(scr.brand.width() >= L.BRAND_W_MIN,
              '%dx%d 左栏不塌：%d' % (w, h, scr.brand.width()))
        check(left >= scr.brand.width(),
              '  卡片没压到左栏：卡片左边 %d ≥ 左栏 %d' % (left, scr.brand.width()))
        check(right <= w,
              '  卡片没出右边：卡片右边 %d ≤ 窗口 %d' % (right, w))
        check(card.width() >= L.CARD_MIN_W,
              '  卡片不至于被压扁：%d' % card.width())

    print('=== 11. 登录卡片不能挂 QGraphicsEffect（内嵌浏览器会卡死） ===',
          flush=True)
    # 这张卡片里装着 QWebEngineView。QGraphicsEffect 挂在它的祖先上时，Qt 会
    # 强制整棵子树走「离屏 pixmap + 模糊 + 合成」，浏览器每一帧都要过一遍 ——
    # 表现就是里面那个小框滚动、点击都要反应很久。所以投影必须自绘。
    from xk_app.app.gui import widgets as _W
    scr.resize(1600, 900)
    app.processEvents()
    card = scr.card
    check(card.graphicsEffect() is None,
          '  卡片上没有 QGraphicsEffect')
    ml, mtop, mr, mbot = card.shadow_margins()
    check(ml > 0 and mr > 0 and mbot > mtop,
          '  自绘投影留了边距：左%d 上%d 右%d 下%d' % (ml, mtop, mr, mbot))
    check(mbot > mtop, '  投影偏下（dy>0）而不是上下一样')
    # 投影位图得真的画出来，不能是空的
    pm = _W.render_shadow('raised', T.R_CARD, 200, 300, (ml, mtop, mr, mbot))
    check(pm.width() == 200 + ml + mr and pm.height() == 300 + mtop + mbot,
          '  投影位图尺寸 = 本体 + 边距：%dx%d' % (pm.width(), pm.height()))
    from PyQt6.QtGui import qAlpha
    img = pm.toImage()
    # 本体正下方那一圈是投影最浓的地方，越往外越淡；因为 dy>0，上方比下方淡。
    # （位图在本体范围内也有像素 —— 每层都比本体大，本体是 paintEvent 盖上去的。）
    body_bot = mtop + 300
    near = qAlpha(img.pixel(ml + 100, body_bot + 4))
    far = qAlpha(img.pixel(ml + 100, body_bot + mbot - 2))
    top = qAlpha(img.pixel(ml + 100, mtop - 4))
    check(near > 0, '  投影在位图里真的画出来了（下方 %d）' % near)
    check(near > far, '  投影由内到外衰减：近 %d > 远 %d' % (near, far))
    check(near > top, '  投影偏下，上方比下方淡：%d < %d' % (top, near))

    print('=== 12. 可见卡面要长到 CARD_MAX_W，不能缩在最小宽度 ===', flush=True)
    # 之前卡片拿的是 sizeHint，窗口最大化时它反而只有 340 —— 里面那个内嵌
    # 浏览器只剩 280 逻辑像素宽，整个教参平台被挤成手机版。
    for w, h in ((1706, 913), (2400, 1200)):
        scr.resize(w, h)
        app.processEvents()
        face = scr.card.width() - ml - mr
        check(face >= L.CARD_MAX_W,
              '%dx%d 卡面长到上限：%d ≥ %d' % (w, h, face, L.CARD_MAX_W))
    scr.resize(1100, 700)
    app.processEvents()
    face = scr.card.width() - ml - mr
    check(L.CARD_MIN_W <= face <= L.CARD_MAX_W,
          '  窄窗口卡面仍在 [%d, %d] 内：%d'
          % (L.CARD_MIN_W, L.CARD_MAX_W, face))

    print('=== 13. 退出登录必须真的能重新登录 ===', flush=True)
    # 只调 deleteAllCookies() 是不够的：它是异步的，而且清不掉 localStorage
    # 和缓存。这里验证退出登录会换一代 profile 目录（新目录必然是空的），
    # 并且在此期间不会把旧会话的 Token 又抓回来。
    from PyQt6.QtCore import QUrl

    def _tok_url():
        return QUrl('https://ereserves.lib.tsinghua.edu.cn/index?token='
                    + make_jwt(3600))

    gen0 = int(scr.settings.get('webprofile_gen') or 0)
    dir0 = L._profile_dir(scr.settings)
    check(gen0 == 0, '  初始代际是 0：%d' % gen0)

    # 先伪造一次「已登录」：面板记下了 Token
    scr.sso._captured = True
    scr.sso._last_token = 'old'
    scr.sso._loaded_once = True
    # 注意变量名别叫 got —— 第 5 节那个 logged_in 的 lambda 闭包捕获的是
    # 变量本身，这里再绑一次 got 的话，那个 lambda 会往这个新列表里塞东西
    cap13 = []
    scr.sso.captured.connect(cap13.append)
    scr.sso.reset_session()
    check(scr.sso._captured is False, '  退出后 _captured 清掉了')
    check(scr.sso._last_token == '', '  退出后 _last_token 清掉了')
    check(scr.sso._loaded_once is False, '  退出后 _loaded_once 清掉（下次会重新加载）')
    check(scr.sso._suppress_capture is True, '  退出后进入「别抓 Token」状态')
    check(scr.sso._view is None, '  退出后浏览器已拆掉，下次会用新目录重建')

    gen1 = int(scr.settings.get('webprofile_gen') or 0)
    dir1 = L._profile_dir(scr.settings)
    check(gen1 == gen0 + 1, '  代际 +1：%d -> %d' % (gen0, gen1))
    check(dir1 != dir0, '  profile 目录换了一个（新目录是空的）')
    check(dir1.endswith('g%d' % gen1), '  新目录名带代际：%s'
          % os.path.basename(dir1))

    # 退出后旧会话残留的那次跳转不该把 Token 抓回来
    scr.sso._on_url(_tok_url())
    check(cap13 == [], '  退出后立刻截到 Token 也不上报')

    # 新会话的页面落地以后，截 Token 恢复
    scr.sso.reset_session  # noqa: B018  (只是提一下，别真的再调)
    scr.sso._suppress_capture = True
    scr.sso._on_load_finished(True)
    check(scr.sso._suppress_capture is False, '  新页面加载完，恢复截 Token')
    scr.sso._on_url(_tok_url())
    check(len(cap13) == 1, '  恢复后能正常截到 Token（%d 条）' % len(cap13))

    # 一次都没建过浏览器时也要能安全退出
    from xk_app.app.gui.login import SsoPanel
    bare = SsoPanel(scr.settings)
    bare.reset_session()
    check(True, '  没建过浏览器也能安全退出登录')

    # 旧的 profile 代际要清掉，不能退出登录几次就攒一堆 Chromium 目录。
    # 这段只在隔离出来的配置目录里跑，动不到真实数据。
    root = L._profile_root()
    os.makedirs(root, exist_ok=True)
    for name in ('g3', 'g4', 'g5'):
        os.makedirs(os.path.join(root, name), exist_ok=True)
        with open(os.path.join(root, name, 'x'), 'w') as fh:
            fh.write('x')
    # 顺手把旧扁平布局的文件也塞一个进去，应该一并清掉
    with open(os.path.join(root, 'legacy_file'), 'w') as fh:
        fh.write('old')
    scr.settings.update(webprofile_gen=5)
    L._cleanup_old_profiles(scr.settings, keep=2)
    names = set(os.listdir(root))
    check('g5' in names, '  当前代保留：%s' % sorted(names))
    check('g4' in names, '  上一代保留：%s' % sorted(names))
    check('g3' not in names, '  更早的代被清掉')
    check('legacy_file' not in names, '  旧的扁平布局文件也被清掉')

    print('', flush=True)
    if fails:
        print('LOGIN SMOKE FAIL (%d)' % len(fails), flush=True)
        for f in fails:
            print('  - ' + f, flush=True)
        return 1
    print('LOGIN SMOKE OK', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
