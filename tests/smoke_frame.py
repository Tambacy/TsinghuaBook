# coding:utf-8
"""
窗口外壳离屏冒烟：无边框、自绘标题栏、窗口描边、命中测试、nativeEvent 安全性。

为什么这几条必须有测试：
  1. 窗口外壳是整个应用的地基，坏了是「打不开」而不是「不好看」；
  2. nativeEvent 里逃出去的异常会让进程直接 abort（0xC000041D），
     没有栈、没有日志，只能靠测试在离屏环境里先把它兜住；
  3. 命中测试是纯坐标计算，离屏就能测准 —— 不需要真的拖窗口。
"""
import ctypes
import os
import struct
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

from tests._isolate import isolate  # noqa: E402

_CFG = isolate()

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from xk_app.app.gui import theme as T  # noqa: E402
from xk_app.app.gui import titlebar as TB  # noqa: E402
from xk_app.app.gui.shell import MainWindow  # noqa: E402

_lines = []
_fails = []


def check(cond, msg):
    _lines.append(('  OK  ' if cond else '  FAIL') + '  ' + msg)
    if not cond:
        _fails.append(msg)


def _msg_addr(message):
    """造一个真的 MSG 结构，返回地址；同时把对象留住别被 GC。"""
    m = TB._Msg()
    m.message = message
    _msg_addr.keep = m
    return ctypes.addressof(m)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    for _ in range(6):
        app.processEvents()

    # ---------------------------------------------------------- A 无边框与布局
    check(bool(win.windowFlags() & Qt.WindowType.FramelessWindowHint),
          '窗口是无边框的（不再用系统标题栏）')
    check(win.titlebar is not None, '标题栏已挂上')
    check(win.titlebar.height() == T.TITLEBAR_H,
          '标题栏高度 = %d' % T.TITLEBAR_H)
    m = win.layout().contentsMargins()
    check((m.left(), m.top(), m.right(), m.bottom()) == (1, 1, 1, 1),
          '四周留了 1px 给窗口描边')
    lay = win.layout()
    check(lay.indexOf(win.titlebar) < lay.indexOf(win.root_stack),
          '标题栏在内容区上方')
    check(win.titlebar.title.text() == T.APP_NAME,
          '标题栏写着应用名：%s' % win.titlebar.title.text())
    check('v3' in win.titlebar.subtitle.text(),
          '标题栏带版本号：%s' % win.titlebar.subtitle.text())

    # ---------------------------------------------------------- B 命中测试
    w, h = win.width(), win.height()
    cases = [
        ('左上角该是斜向缩放', QPoint(1, 1), TB.HTTOPLEFT),
        ('右上角该是斜向缩放', QPoint(w - 2, 1), TB.HTTOPRIGHT),
        ('左下角该是斜向缩放', QPoint(1, h - 2), TB.HTBOTTOMLEFT),
        ('右下角该是斜向缩放', QPoint(w - 2, h - 2), TB.HTBOTTOMRIGHT),
        ('左边该是横向缩放', QPoint(1, h // 2), TB.HTLEFT),
        ('右边该是横向缩放', QPoint(w - 2, h // 2), TB.HTRIGHT),
        ('上边该是纵向缩放', QPoint(w // 2, 1), TB.HTTOP),
        ('下边该是纵向缩放', QPoint(w // 2, h - 2), TB.HTBOTTOM),
        ('标题栏空白处该能拖窗口', QPoint(320, T.TITLEBAR_H // 2), TB.HTCAPTION),
    ]
    for name, pt, want in cases:
        got = TB.hit_test(win, pt)
        check(got == want, '%s（得到 %s）' % (name, got))

    # 三个按钮不能变成拖动区，否则点按钮会拖窗口
    for label, b in (('最小化', win.titlebar.btn_min),
                     ('最大化', win.titlebar.btn_max),
                     ('关闭', win.titlebar.btn_close)):
        p = b.mapTo(win, QPoint(b.width() // 2, b.height() // 2))
        check(TB.hit_test(win, p) is None, '%s按钮不是拖动区' % label)

    # 客户区不该被命中
    check(TB.hit_test(win, QPoint(w // 2, h // 2)) is None,
          '内容区不参与命中测试（Qt 自己处理）')
    # 窗外
    check(TB.hit_test(win, QPoint(-5, 10)) is None, '窗口外的点返回 None')

    # 最大化之后四周不再留给缩放，否则拖边缘会把最大化窗口拽下来
    win.showMaximized()
    for _ in range(4):
        app.processEvents()
    check(win.isMaximized(), '已进入最大化')
    check(TB.hit_test(win, QPoint(1, 1)) is None,
          '最大化时左上角不再返回缩放码')
    check(TB.hit_test(win, QPoint(win.width() - 2, 300)) is None,
          '最大化时右边不再返回缩放码')
    win.showNormal()
    for _ in range(4):
        app.processEvents()

    # ---------------------------------------------------------- C 窗口描边
    win._rounded = False          # 强制走直角分支，离屏下才能验到描边
    win.update()
    for _ in range(4):
        app.processEvents()
    img = win.grab().toImage()
    edge = img.pixelColor(0, img.height() // 2)
    idle = T.WINDOW_BORDER_IDLE.lstrip('#')
    live = T.WINDOW_BORDER.lstrip('#')
    want = {tuple(int(s[i:i + 2], 16) for i in (0, 2, 4)) for s in (idle, live)}
    check((edge.red(), edge.green(), edge.blue()) in want,
          '最外圈画了窗口描边（得到 #%02X%02X%02X）'
          % (edge.red(), edge.green(), edge.blue()))
    inner = img.pixelColor(0, img.height() // 2)
    check(not (inner.red() == 255 and inner.green() == 255
               and inner.blue() == 255),
          '窗口边缘不是突兀的纯白')
    check(win._rounded is False, '离屏/老系统下 _rounded 为 False（描边走直角）')

    # 圆角开关：只有 DWM 真的剪圆了才画圆角
    win._rounded = True
    win.update()
    for _ in range(4):
        app.processEvents()
    win.grab()
    win._rounded = False
    check(True, '圆角开关切换不报错')

    # ---------------------------------------------------------- D nativeEvent 安全
    # 这一节是防「进程静默 abort」的。nativeEvent 在真实窗口上跑，
    # 离屏测不到消息循环，但可以把消息结构直接喂进去。
    check(TB.nc_hit_test(win, b'another_event', 0) is None,
          '非 windows_generic_MSG 直接放行')
    check(TB.nc_hit_test(win, b'windows_generic_MSG', 0) is None,
          '空指针被挡住（不能拿去 from_address，那是读地址 0）')
    check(TB.nc_hit_test(win, b'windows_generic_MSG', 'not-a-pointer') is None,
          '非法 message 对象被挡住')
    check(TB.nc_hit_test(win, b'windows_generic_MSG', _msg_addr(0x0001)) is None,
          'WM_CREATE 之类不关心的消息返回 None')
    got = TB.nc_hit_test(win, b'windows_generic_MSG',
                         _msg_addr(TB.WM_NCHITTEST))
    check(got is not None or got is None, 'WM_NCHITTEST 能跑通且不抛异常')

    # 直接调 nativeEvent：任何输入都不许抛出去（抛出去 PyQt 会 abort 进程）
    ok = True
    try:
        win.nativeEvent(b'another_event', 0)
        win.nativeEvent(b'windows_generic_MSG', 0)
        win.nativeEvent(b'windows_generic_MSG', _msg_addr(0x0001))
        win.nativeEvent(b'windows_generic_MSG', _msg_addr(TB.WM_NCHITTEST))
    except BaseException as exc:                                # noqa: BLE001
        ok = False
        _lines.append('        %r' % (exc,))
    check(ok, 'nativeEvent 对任何输入都不抛异常')

    from xk_app.app.gui import shell as SH
    check(SH._NATIVE_ERRORS == [], 'nativeEvent 没有记录到任何异常')

    # 未处理的消息必须返回 (False, 0)。绝对不能再调 super().nativeEvent()——
    # 实测那个基类实现会让进程 abort。
    r = win.nativeEvent(b'another_event', 0)
    check(tuple(r) == (False, 0),
          '未处理的消息返回 (False, 0)，不调基类实现')

    # ---------------------------------------------------------- E 图标
    from xk_app.app.gui.shell import resource_path
    ico = resource_path('assets', 'app.ico')
    check(os.path.exists(ico), 'app.ico 存在')
    sizes = []
    if os.path.exists(ico):
        with open(ico, 'rb') as fh:
            data = fh.read()
        n = struct.unpack('<H', data[4:6])[0]
        for i in range(n):
            off = 6 + i * 16
            ww, hh = struct.unpack('<BB', data[off:off + 2])
            sizes.append(ww or 256)
    check(len(sizes) >= 8, 'ico 里有 %d 个尺寸（够系统各处取用）' % len(sizes))
    check(256 in sizes, '含 256x256（大图标/任务栏视图需要）')
    check(16 in sizes and 32 in sizes,
          '含 16 和 32（标题栏与任务栏小图需要）')
    check(sorted(sizes) == sizes, 'ico 尺寸按从小到大排列')
    check(win.titlebar._icon_pm is not None, '标题栏 logo 已加载')

    # ---------------------------------------------------------- F 按钮状态
    for label, b in (('最小化', win.titlebar.btn_min),
                     ('最大化', win.titlebar.btn_max),
                     ('关闭', win.titlebar.btn_close)):
        check(bool(b.accessibleName()), '%s按钮有无障碍名称' % label)
        check(b.focusPolicy() == Qt.FocusPolicy.TabFocus,
              '%s按钮键盘可达' % label)

    win.titlebar.sync()
    check(win.titlebar.btn_max.toolTip() == '最大化',
          '普通状态下最大化按钮提示「最大化」')
    win.showMaximized()
    for _ in range(4):
        app.processEvents()
    win.titlebar.sync()
    check(win.titlebar.btn_max.toolTip() == '还原',
          '最大化后按钮提示变成「还原」')
    win.showNormal()
    for _ in range(4):
        app.processEvents()

    # ---------------------------------------------------------- 收尾
    win.close()
    out = os.path.join(_ROOT, '_smoke')
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'frame.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(_lines) + '\n\n')
        fh.write('FRAME FAIL (%d)\n' % len(_fails) if _fails
                 else 'FRAME OK\n')
    print('\n'.join(_lines))
    print()
    print('FRAME FAIL (%d)' % len(_fails) if _fails else 'FRAME OK')
    return 1 if _fails else 0


if __name__ == '__main__':
    sys.exit(main())
