# coding:utf-8
"""把更新对话框和侧边栏提示条渲染成图，用来目视检查布局。"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

from tests._isolate import isolate  # noqa: E402

isolate()


def main():
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    from crawler.core import updater as U
    from crawler.gui import theme as T
    from crawler.gui.update_dialog import UpdateDialog

    out = os.path.join(_ROOT, '_smoke')
    os.makedirs(out, exist_ok=True)

    notes = """# 清华教参下载器 2.1

## 本版新增

**应用内更新。** 以后不用再来这个页面手动下载了：

- 发现新版本时，程序左下角会出现提示，点开就能看到更新说明。
- 点「下载并安装」直接在程序里下载，下完自动关闭、安装、重新打开。
- 也可以在 **设置 → 关于与更新** 里手动检查。
- 不想装就点「跳过此版本」，之后不会再为它弹提示。

检查更新在后台进行，12 小时最多一次，连不上服务器时安静跳过，不影响下载功能。

---

完整使用说明见 README。
"""
    rel = U.Release(
        version='2.1', tag='v2.1', name='清华教参下载器 2.1', notes=notes,
        asset_name='TsinghuaBookCrawler-2.1-Setup.exe',
        asset_url='https://example.invalid/x.exe',
        asset_size=139657573, page_url='https://example.invalid')

    shots = []
    for state, setup in (
            ('available', lambda d: None),
            ('downloading', lambda d: (d._set_state('downloading'),
                                       d.progress.set_fraction(0.42),
                                       d.status.setText('正在下载 55.8 MB / 133.2 MB'))),
            ('ready', lambda d: (d._set_state('ready'),
                                 d.progress.set_fraction(1.0))),
            ('failed', lambda d: d._fail('连接不上更新服务器（连接超时）'))):
        dlg = UpdateDialog(rel)
        setup(dlg)
        dlg.adjustSize()
        dlg.show()
        app.processEvents()
        path = os.path.join(out, 'update_%s.png' % state)
        dlg.grab().save(path)
        shots.append(path)
        dlg.close()

    # 侧边栏提示条
    from crawler.gui.shell import MainWindow
    win = MainWindow()
    win.resize(T.WIN_W, T.WIN_H)
    win.sidebar.show_update('2.1')
    win.goto('settings', animate=False)
    win.show()
    for _ in range(6):
        app.processEvents()
    p = os.path.join(out, 'update_sidebar.png')
    win.grab().save(p)
    shots.append(p)
    win.close()

    for s in shots:
        print('  %s' % os.path.relpath(s, _ROOT), flush=True)
    print('RENDER OK', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
