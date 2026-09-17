# coding:utf-8
"""
在真实显示上渲染登录页，用于肉眼验收。

需要在有桌面会话的环境跑（offscreen 下 QtWebEngine 起不来，中文也可能缺字形）。

内嵌浏览器那一栏不联网：给 WebEngine 喂一个本地 mock 的登录表单页，
这样能看清版面，又不会真的去请求清华服务器。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

from tests._isolate import isolate  # noqa: E402

# 这个脚本要截内嵌浏览器那一栏，必须开着 WebEngine
_CFG = isolate(webengine=True)

OUT = os.path.join(_ROOT, '_smoke')

# mock 的清华登录页：只为看版面，不上网
MOCK_SSO = """
<html><head><meta charset="utf-8"><style>
 body { margin:0; font-family:"Microsoft YaHei UI",sans-serif;
        background:#F4F3F9; color:#1B1926; }
 .wrap { padding:34px 38px; }
 .sys { font-size:19px; font-weight:700; line-height:1.5; }
 .sub { color:#66626F; font-size:12.5px; margin-top:6px; }
 label { display:block; font-size:12px; color:#66626F; margin:18px 0 6px; }
 input { width:100%; box-sizing:border-box; height:38px; border:1px solid #E4E1EE;
         border-radius:11px; padding:0 12px; font-size:13px; background:#EAE7F2; }
 .btn { margin-top:24px; height:42px; border-radius:14px; background:#6F5CAD;
        color:#fff; font-size:13px; font-weight:600; display:flex;
        align-items:center; justify-content:center; }
 .tip { margin-top:16px; font-size:12px; color:#96929E; }
</style></head><body><div class="wrap">
 <div class="sys">清华大学用户电子身份服务系统</div>
 <div class="sub">（本页为离线模拟，仅用于界面验收）</div>
 <label>用户名 / 学号</label><input value="2021000000">
 <label>密码</label><input type="password" value="********">
 <div class="btn">登 录</div>
 <div class="tip">登录后可能需要完成双因子认证</div>
</div></body></html>
"""


def main():
    os.makedirs(OUT, exist_ok=True)

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from crawler.core import store
    from crawler.gui import login as L
    from crawler.gui import theme as T

    T.install_app_font(app)
    # show() 会让 SSO 面板自动去加载认证页。截图不需要真联网，也不该为了
    # 截一张图就去请求清华服务器，所以把起始地址顶成空白页。
    L.PLATFORM_HOME = 'about:blank'

    st = store.Settings()
    st.update(login_mode='sso', token='')

    scr = L.LoginScreen(st)
    scr.resize(1280, 820)
    scr.show()

    shots = []

    def shoot_token():
        # Token 模式：三种有效期状态各截一张
        scr.set_mode('token', animate=False)
        for tag, exp in (('valid', 30 * 86400), ('soon', 2 * 3600), ('expired', -3600)):
            import base64
            import json as _json
            import time as _time

            def seg(o):
                raw = _json.dumps(o, separators=(',', ':')).encode('utf-8')
                return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')

            now = _time.time()
            jwt = '%s.%s.demo-signature' % (
                seg({'alg': 'RS256', 'typ': 'JWT'}),
                seg({'exp': int(now + exp), 'iss': 'ereserves.lib.tsinghua.edu.cn'}))
            scr.token.set_token(jwt)
            app.processEvents()
            path = os.path.join(OUT, 'login_token_%s.png' % tag)
            scr.grab().save(path)
            shots.append(path)
        # 非 JWT 的情况
        scr.token.set_token('opaque-token-without-jwt-structure-1234567890')
        app.processEvents()
        path = os.path.join(OUT, 'login_token_opaque.png')
        scr.grab().save(path)
        shots.append(path)

        # SSO 模式：等 WebEngine 把 mock 页渲染出来再截
        scr.set_mode('sso', animate=False)
        ok = scr.sso.ensure_web()
        if ok:
            scr.sso._view.setHtml(MOCK_SSO)
            QTimer.singleShot(2500, shoot_sso)
        else:
            path = os.path.join(OUT, 'login_sso_unavailable.png')
            scr.grab().save(path)
            shots.append(path)
            finish()

    def shoot_sso():
        for w, h, name in ((1280, 820, 'login_sso.png'),
                           (980, 660, 'login_sso_narrow.png'),
                           (1600, 900, 'login_sso_wide.png')):
            scr.resize(w, h)
            app.processEvents()
            path = os.path.join(OUT, name)
            scr.grab().save(path)
            shots.append(path)
        finish()

    def finish():
        for p in shots:
            print('  %s' % os.path.basename(p), flush=True)
        print('renders -> %s' % OUT, flush=True)
        app.quit()

    QTimer.singleShot(900, shoot_token)
    QTimer.singleShot(30000, app.quit)      # 兜底
    app.exec()

    # 报告写文件，避开 Windows 控制台编码问题
    with open(os.path.join(OUT, 'login_render.txt'), 'w', encoding='utf-8') as fh:
        for p in shots:
            fh.write('%s  %d bytes\n' % (os.path.basename(p),
                                         os.path.getsize(p) if os.path.exists(p) else -1))
    return 0 if len(shots) >= 5 else 1


if __name__ == '__main__':
    sys.exit(main())
