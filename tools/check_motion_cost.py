"""
真实流程下的验收：按程序实际的方式构造登录页，不去手动 set_animated。
量主线程 CPU + 天幕真实重绘次数，并确认静态天幕照样画得完整。

天幕现在有两种形态：
  * 有 assets/backdrop.*  —— 静态底图，连定时器都不建（仓库里就是这个）
  * 没有底图            —— 程序化夜空，按模式开关动画
两种都要能量，所以下面跑了第二遍：把底图藏掉再建一个登录页来量动画那份开销。
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)
from tests._isolate import isolate  # noqa: E402

isolate(webengine=True)

from PyQt6.QtWidgets import QApplication  # noqa: E402

from xk_app.app.core import store  # noqa: E402
from xk_app.app.gui import backdrop as B  # noqa: E402
from xk_app.app.gui import login as L  # noqa: E402
from xk_app.app.gui import theme as T  # noqa: E402

L.PLATFORM_HOME = 'about:blank'
app = QApplication(sys.argv)
T.install_app_font(app)

STATS = {'n': 0}
_orig = B.SkyBackdrop.paintEvent


def timed(self, ev):
    STATS['n'] += 1
    _orig(self, ev)


B.SkyBackdrop.paintEvent = timed


def run(seconds=3.0):
    STATS['n'] = 0
    c0, w0 = time.process_time(), time.perf_counter()
    end = w0 + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)
    return ((time.process_time() - c0) / (time.perf_counter() - w0) * 100,
            STATS['n'] / (time.perf_counter() - w0))


def settle(ms):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def timer_state(sky):
    """天幕定时器的状态。有底图时根本不存在，不是「停了」。"""
    t = sky._timer
    if t is None:
        return '不存在（有底图，天幕是静态的）'
    return '在跑' if t.isActive() else '已停'


def new_screen():
    st = store.Settings()
    scr = L.LoginScreen(st)
    scr.resize(T.WIN_W, T.WIN_H)
    scr.show()
    scr.set_mode('sso', animate=False, start=False)   # 和 MainWindow.start() 一致
    settle(1200)
    return scr


def measure(scr, label):
    sky = scr.brand.sky
    print('  [%s] 天幕形态: %s' % (label, '静态底图' if sky._has_art else '程序化动画'))
    print('    SSO 模式下定时器: %s' % timer_state(sky))
    run(1.2)
    cpu, fps = run(3.0)
    print('    -> 主线程 CPU %5.1f%%   天幕重绘 %.1f 次/秒' % (cpu, fps))
    return cpu


print('登录页可见: True   （程序化天幕需要浏览器在跑，才看得出装饰动画的成本）')
scr = new_screen()
cpu_static = measure(scr, '有底图')

# 静态天幕必须还是完整的（不能因为不做动画就变成半成品）
os.makedirs(os.path.join(_ROOT, '_smoke'), exist_ok=True)
scr.brand.grab().save(os.path.join(_ROOT, '_smoke', 'brand_sso_static.png'))

# 再量三种画法的差。**统一在裸控件上量** —— 整个 LoginScreen 那个数里混着
# 内嵌浏览器自己的开销，拿它和裸控件横向比是没有意义的。
# （这里也不建第二个 LoginScreen：第二个内嵌浏览器会把这一步拖到分钟级。）
print()
from PyQt6.QtWidgets import QWidget  # noqa: E402


def bare_measure(label, hide_art, animated=True):
    _o = B._find_backdrop
    if hide_art:
        B._find_backdrop = lambda: None
    try:
        holder = QWidget()
        holder.resize(T.WIN_W, T.WIN_H)
        sky = B.SkyBackdrop('violet', holder, sky_height=None)
    finally:
        B._find_backdrop = _o
    sky.setGeometry(0, 0, 527, 822)          # 和登录页左栏同尺寸
    sky.set_animated(animated)
    holder.show()
    settle(500)
    run(1.0)
    cpu, fps = run(2.5)
    t = sky._timer
    print('  %-18s 形态=%-4s 定时器=%-3s  CPU %5.1f%%   重绘 %4.1f 次/秒'
          % (label, '底图' if sky._has_art else '程序化',
             '无' if t is None else ('跑' if t.isActive() else '停'), cpu, fps))
    holder.hide()
    holder.deleteLater()
    app.processEvents()
    return cpu


cpu_art = bare_measure('裸控件 · 底图', hide_art=False)
cpu_anim = bare_measure('裸控件 · 程序化+动画', hide_art=True, animated=True)
cpu_off = bare_measure('裸控件 · 程序化+停', hide_art=True, animated=False)

print()
print('同一块面板（527x822）：程序化+动画 %.1f%%  ->  停掉动画 %.1f%%  ->  静态底图 %.1f%%'
      % (cpu_anim, cpu_off, cpu_art))
print('整个登录页（含内嵌浏览器）: %.1f%% —— 这个数里主要是浏览器，不能和上面横向比'
      % cpu_static)
print('done')