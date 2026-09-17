# coding:utf-8
"""
SSO 面板的真机测试：真的起一个 QWebEngineView。

必须用真实显示（offscreen 下 Chromium 起不来），但**全程不联网**：
用 setHtml / 跳到带 token 的假地址来模拟「登录回调带回 Token」。

上一版把 after_load 接在 loadFinished 上，而 after_load 里又调 setUrl，
于是自己触发自己、无限重载，报告被刷了几十遍。这里改成一次性的
定时步骤，每一步只跑一次。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

from tests._isolate import isolate  # noqa: E402

# 这个脚本就是专门测内嵌浏览器的，别把开关关上
_CFG = isolate(webengine=True)

OUT = os.path.join(_ROOT, '_smoke')
fails = []
_lines = []

JWT = ('eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9'
       '.eyJleHAiOjQxMDc0NDAwMDB9.sig')
PAGE = '<html><head><meta charset="utf-8"></head><body><h1>mock</h1></body></html>'


def check(cond, msg):
    _lines.append(('  OK  ' if cond else '  FAIL') + '  ' + msg)
    if not cond:
        fails.append(msg)


class Runner(object):
    def __init__(self, app, scr):
        self.app = app
        self.scr = scr
        self.steps = []
        self.i = 0

    def add(self, fn, delay=0):
        self.steps.append((fn, delay))
        return self

    def run(self):
        self._next()

    def _next(self):
        if self.i >= len(self.steps):
            return finish()
        fn, delay = self.steps[self.i]
        self.i += 1
        if delay:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(delay, lambda: self._step(fn))
        else:
            self._step(fn)

    def _step(self, fn):
        try:
            fn()
        except Exception as e:                                       # noqa: BLE001
            import traceback
            check(False, '步骤抛异常：%s' % e)
            _lines.append(traceback.format_exc())
        self._next()


def main():
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from crawler.core import store
    from crawler.gui import login as L
    from crawler.gui import theme as T

    T.install_app_font(app)

    st = store.Settings()
    st.update(login_mode='token')          # 先瞄 token 模式，验证惰性
    scr = L.LoginScreen(st)
    scr.resize(1280, 820)

    captured = []
    scr.logged_in.connect(lambda t, s: captured.append((t, s)))

    check(scr.sso._view is None, '构造时（token 模式）没有创建浏览器')

    scr.set_mode('sso', animate=False, start=False)
    check(scr.sso._view is None,
          '切到 sso 模式但仍未 start 时，依然没有创建浏览器（真惰性）')

    scr.show()
    app.processEvents()

    state = {}

    r = Runner(app, scr)

    def step_ensure():
        ok = scr.sso.ensure_web()
        check(ok, 'ensure_web() 成功')
        if not ok:
            check(False, '内嵌浏览器不可用：%s' % scr.sso.placeholder.text())
            return
        view = scr.sso._view
        state['view'] = view
        check(view is not None, '拿到 QWebEngineView 实例')
        check(scr.sso._profile is not None, 'profile 已创建')
        prof_dir = os.path.join(store.data_dir(), 'webprofile')
        check(os.path.isdir(prof_dir), 'profile 目录存在')
        page = view.page()
        check(type(page).__name__ == 'PlatformPage',
              'page 是子类：%s' % type(page).__name__)
        check('certificateError' in type(page).__dict__,
              '子类覆写了 certificateError（Qt6 里是虚函数，不是信号）')
        check('createWindow' in type(page).__dict__, '子类覆写了 createWindow')

    def step_html():
        state['loads'] = []
        state['view'].loadFinished.connect(lambda ok: state['loads'].append(ok))
        state['view'].setHtml(PAGE)

    def step_after_html():
        loads = state.get('loads', [])
        check(len(loads) == 1 and loads[0] is True,
              'setHtml 加载完成且 ok=True（收到 %r）' % (loads,))
        check('请在窗口中完成登录' in scr.sso.status.text(),
              '状态文案：%s' % scr.sso.status.text())

    def step_token_url():
        state['n0'] = len(captured)
        from PyQt6.QtCore import QUrl
        state['view'].setUrl(QUrl(
            'https://ereserves.lib.tsinghua.edu.cn/index?token=' + JWT))

    def step_after_token():
        check(len(captured) == state['n0'] + 1,
              '清华域名带 token= 被截获（%d -> %d）'
              % (state['n0'], len(captured)))
        if len(captured) > state['n0']:
            tok, src = captured[-1]
            check(tok == JWT, '  Token 内容正确')
            check(src == 'sso', '  source = sso')

    def step_foreign():
        state['n1'] = len(captured)
        from PyQt6.QtCore import QUrl
        state['view'].setUrl(QUrl('https://example.com/index?token=' + JWT))

    def step_after_foreign():
        check(len(captured) == state['n1'],
              '非清华域名的 token= 不被当成凭证（%d -> %d）'
              % (state['n1'], len(captured)))

    def step_no_token_param():
        state['n2'] = len(captured)
        from PyQt6.QtCore import QUrl
        # 清华域名但地址里没有 token= 参数
        state['view'].setUrl(QUrl(
            'https://ereserves.lib.tsinghua.edu.cn/bookDetail/abc123'))

    def step_after_no_token():
        check(len(captured) == state['n2'], '没有 token= 参数时不发登录信号')

    def step_manual():
        # 手工检查：地址栏里没有 token 时，应给出提示而不是发信号
        state['msg'] = scr.sso.status.text()
        scr.sso._manual_check()
        check(len(captured) == state['n2'], '_manual_check 在无 Token 时不发信号')
        check('还没有 Token' in scr.sso.status.text(),
              '  并提示没有 Token：%s' % scr.sso.status.text())

    def step_reset():
        state['before'] = scr.sso._loaded_once
        scr.sso.reset_session()
        check(scr.sso._loaded_once is False, 'reset_session 重置加载标记')

    def step_msgguard():
        # set_status 的四种语气都得能用，别 KeyError
        ok = True
        for tone in ('dim', 'ok', 'warn', 'err'):
            try:
                scr.sso.set_status('x', tone)
            except Exception:                                        # noqa: BLE001
                ok = False
        check(ok, 'set_status 四种语气都可用')

    r.add(step_ensure).add(step_html).add(step_after_html, 1500)
    r.add(step_token_url).add(step_after_token, 1500)
    r.add(step_foreign).add(step_after_foreign, 1200)
    r.add(step_no_token_param).add(step_after_no_token, 1200)
    r.add(step_manual).add(step_reset).add(step_msgguard)

    from PyQt6.QtCore import QTimer
    QTimer.singleShot(600, r.run)
    QTimer.singleShot(40000, lambda: (check(False, '超时'), finish()))
    app.exec()
    return 1 if fails else 0


def finish():
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, 'weblogin.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(_lines) + '\n\n')
        fh.write('WEBLOGIN FAIL (%d)\n' % len(fails) if fails
                 else 'WEBLOGIN OK\n')
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        app.quit()
    return 0


if __name__ == '__main__':
    sys.exit(main())