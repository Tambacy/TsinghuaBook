"""给侧边栏底部那一块拍一张，肉眼确认账号名和倒计时排版没坏。"""
import base64
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests._isolate import isolate  # noqa: E402

isolate()

from PyQt6.QtWidgets import QApplication  # noqa: E402

from crawler.core import store  # noqa: E402
from crawler.gui import theme as T  # noqa: E402
from crawler.gui.shell import MainWindow  # noqa: E402


def seg(o):
    raw = json.dumps(o, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def jwt(exp_offset, **extra):
    now = time.time()
    body = {'iat': int(now), 'exp': int(now + exp_offset)}
    body.update(extra)
    return '%s.%s.sig' % (seg({'alg': 'RS256', 'typ': 'JWT'}), seg(body))


app = QApplication(sys.argv)
T.install_app_font(app)
win = MainWindow()
win.resize(T.WIN_W, T.WIN_H)
win.show()

CASES = [
    ('account', jwt(3780, sub='JCClientUser', userId='2024000001',
                    userKey='2024000001', userName='张三')),
    ('account_soon', jwt(3780, iat_offset=-3200, userName='张三')),
    ('account_longname', jwt(3780, userName='欧阳梓萱·第二学位项目')),
    ('noname', jwt(3780)),
    ('expired', jwt(-600, userName='张三')),
    ('opaque', 'some-opaque-platform-token-1234567890'),
    ('none', ''),
]

for name, tok in CASES:
    win.settings.update(token=tok, login_mode='sso')
    win._sync_sidebar()
    win.root_stack.setCurrentIndex(1)
    app.processEvents()
    chip = win.sidebar.status_chip
    # 连侧边栏整条一起拍，方便看它在真实布局里的位置
    win.sidebar.grab().save(os.path.join('_smoke', 'side_%s.png' % name))
    print('%-18s title=%-22r sub=%-24r tip=%r'
          % (name, chip._title, chip._sub, chip.toolTip()[:60]))

# 队列页整窗一张，看整体
win.settings.update(token=CASES[0][1], login_mode='sso')
win._sync_sidebar()
win.goto('queue', animate=False)
app.processEvents()
win.grab().save(os.path.join('_smoke', 'win_with_account.png'))
print('done')
