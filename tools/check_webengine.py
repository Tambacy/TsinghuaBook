# coding:utf-8
"""确认 QtWebEngine 能在这个环境里起来（打包前先验一次，免得白做）。"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu --no-sandbox')
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

from tests._isolate import isolate  # noqa: E402

_CFG = isolate()

print('=== 版本 ===', flush=True)
from PyQt6.QtWebEngineCore import QWebEngineProfile, qWebEngineVersion  # noqa: E402
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
print('  QtWebEngine 版本:', qWebEngineVersion(), flush=True)

from PyQt6.QtCore import QTimer, QUrl  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
print('=== WebEngine 是独立进程，需要能启动 ===', flush=True)
view = QWebEngineView()

# 持久化 profile：这样「信任此设备」在下次登录时还在，可以免掉 2FA
prof_dir = os.path.join(_CFG, 'webprofile')
os.makedirs(prof_dir, exist_ok=True)
profile = QWebEngineProfile('tsinghua', view)
profile.setPersistentStoragePath(prof_dir)
profile.setCachePath(os.path.join(prof_dir, 'cache'))
page = view.page()
print('  profile 持久化路径:', prof_dir, flush=True)

state = {'loaded': False, 'url': None}


def on_load(ok):
    state['loaded'] = ok
    state['url'] = view.url().toString()
    print('  loadFinished ok=%s url=%s' % (ok, state['url']), flush=True)
    app.quit()


view.loadFinished.connect(on_load)
view.resize(900, 700)
view.show()
# 用 data: URL 避免联网，只验渲染管线能不能跑
view.setHtml('<html><body style="font-family:sans-serif">'
             '<h1>WebEngine OK</h1><p>token 截获测试页</p></body></html>')

QTimer.singleShot(15000, app.quit)   # 超时兜底
app.exec()

# 验证「从 URL 里抠 token」这条路
from urllib.parse import parse_qs, urlparse  # noqa: E402

for u in ('https://ereserves.lib.tsinghua.edu.cn/index?token=eyJhbGciOiJSUzI1NiJ9.abc.def',
          'https://ereserves.lib.tsinghua.edu.cn/index?token=xyz&foo=1',
          'https://ereserves.lib.tsinghua.edu.cn/bookDetail/c01e1db1'):
    q = parse_qs(urlparse(u).query)
    print('  截获 %-28s -> %s' % (u[-28:], (q.get('token') or ['(无)'])[0][:24]), flush=True)

print('', flush=True)
print('WEBENGINE %s' % ('OK' if state['loaded'] else 'FAIL: 页面没加载成功'), flush=True)
sys.exit(0 if state['loaded'] else 1)
