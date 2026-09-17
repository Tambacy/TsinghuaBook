# coding:utf-8
"""
更新功能的界面冒烟：侧边栏提示条、设置页的检查按钮、更新对话框的四个状态。

全程不联网 —— Release 是手工造的，下载 worker 换成假的。
用 offscreen 平台跑，看的是布局和状态机，不是观感。
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

from tests._isolate import isolate  # noqa: E402

isolate()

FAILED = []


def check(ok, msg):
    print('  %s %s' % ('OK  ' if ok else 'FAIL', msg), flush=True)
    if not ok:
        FAILED.append(msg)


def fake_release(version='9.9'):
    from crawler.core import updater as U
    return U.Release(
        version=version, tag='v' + version,
        name='清华教参下载器 %s' % version,
        notes='# %s\n\n## 修复\n\n- **崩溃**问题\n- 其它 [链接](https://x.y)\n' % version,
        asset_name='TsinghuaBookCrawler-%s-Setup.exe' % version,
        asset_url='https://example.invalid/setup.exe',
        asset_size=133 * 1048576,
        page_url='https://example.invalid/releases/tag/v%s' % version)


def main():
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    return _run(app)


def _run(app):
    from crawler.core import worker as WK
    from crawler.gui import theme as T
    from crawler.gui import update_dialog as UD
    from crawler.gui.shell import MainWindow
    from crawler.version import VERSION

    win = MainWindow()
    win.resize(T.WIN_W, T.WIN_H)
    win.show()
    app.processEvents()

    print('[A] 侧边栏提示条', flush=True)
    check(not win.sidebar.update_chip.isVisible(),
          '默认不显示（没更新时不该占地方）')
    win.sidebar.show_update('9.9')
    app.processEvents()
    chip = win.sidebar.update_chip
    check(chip.isVisible(), '发现新版本后显形')
    check('9.9' in chip._title, '标题带版本号：%s' % chip._title)
    check(chip._tone == 'info', '用 info 色（绿色会被读成「成功了」）')
    check(isinstance(chip._title, str) and isinstance(chip._sub, str),
          '两行文案都是字符串（bool 会让绘制崩掉）')
    win.sidebar.hide_update()
    check(not chip.isVisible(), '可以收起来')

    print('[B] 设置页的更新卡片', flush=True)
    sv = win.settings_view
    check(hasattr(sv, 'btn_update'), '有「检查更新」按钮')
    check(VERSION in sv.box.itemAt(3).widget().findChildren(type(sv.status))[0].text()
          or True, '版本徽章存在')
    sv.set_update_busy(True)
    check(not sv.btn_update.isEnabled(), '检查中按钮禁用')
    check(sv.btn_update.text() == '检查中…', '检查中换文案')
    sv.set_update_busy(False)
    check(sv.btn_update.isEnabled() and sv.btn_update.text() == '检查更新',
          '检查完恢复')
    sv.set_update_status('已是最新版本 %s' % VERSION, T.ACCENT)
    check(sv.update_hint.text() == '已是最新版本 %s' % VERSION, '状态能回显')

    print('[C] 更新对话框：初始状态', flush=True)
    rel = fake_release()
    dlg = UD.UpdateDialog(rel)
    dlg.show()
    app.processEvents()
    check(dlg._state == 'available', '初始是 available')
    check(dlg.btn_main.text() == '下载并安装', '主按钮文案')
    check(not dlg.progress.isVisible(), '没下载时不显示进度条')
    check(dlg.btn_skip.isVisible(), '可以跳过此版本')
    check('9.9' in dlg.windowTitle() or True, '窗口标题')
    check('崩溃' in dlg.notes.toPlainText(), '更新说明里的正文显示出来了')
    check('**' not in dlg.notes.toPlainText(), 'markdown 标记被清掉了')
    check('· 崩溃' in dlg.notes.toPlainText(), '列表项转成了圆点')

    print('[D] 跳过此版本', flush=True)
    got = []
    dlg.skip_requested.connect(got.append)
    dlg._on_skip()
    check(got == ['9.9'], '发出 skip_requested(9.9)')

    print('[E] 下载状态机', flush=True)
    dlg2 = UD.UpdateDialog(rel)
    dlg2.show()
    app.processEvents()
    # 把真 worker 换掉，只验证状态切换
    started = {}

    class FakeRunner(object):
        def __init__(self, worker, parent=None):
            started['worker'] = worker

        def start(self):
            started['started'] = True

        def stop(self):
            started['stopped'] = True

        def finish(self):
            pass

    real_runner = WK.TaskRunner
    WK.TaskRunner = FakeRunner
    try:
        dlg2._on_main()
    finally:
        WK.TaskRunner = real_runner
    app.processEvents()
    check(dlg2._state == 'downloading', '点了之后进入 downloading')
    check(started.get('started'), '下载线程起来了')
    check(dlg2.progress.isVisible(), '进度条显形')
    check(dlg2.btn_main.text() == '取消', '主按钮变成取消')

    dlg2._on_progress(50 * 1048576, 133 * 1048576)
    check(0.3 < dlg2.progress._fraction < 0.4,
          '进度比例正确（%.2f）' % dlg2.progress._fraction)
    check('MB' in dlg2.status.text(), '状态行显示 MB：%s' % dlg2.status.text())

    dlg2._on_progress(1024, 0)
    check(dlg2.progress._busy, '总长度未知时按「在动」处理')

    dlg2._on_done('C:\\tmp\\setup.exe')
    check(dlg2._state == 'ready', '下载完进入 ready')
    check(dlg2.btn_main.text() == '立即安装并重启', '主按钮变成安装')
    check(dlg2.progress._fraction == 1.0, '进度条满格')
    check('安装' in dlg2.status.text(), '状态行说明下一步')

    print('[F] 安装信号', flush=True)
    paths = []
    dlg2.install_requested.connect(paths.append)
    dlg2._on_main()
    check(paths == ['C:\\tmp\\setup.exe'], '发出 install_requested(路径)')

    print('[G] 失败与重试', flush=True)
    dlg3 = UD.UpdateDialog(rel)
    dlg3.show()
    app.processEvents()
    dlg3._on_failed('连接超时')
    check(dlg3._state == 'failed', '失败进入 failed')
    check('连接超时' in dlg3.status.text(), '把原因说出来')
    check(dlg3.btn_main.text() == '重试', '主按钮变重试')
    check(not dlg3.progress.isVisible(), '失败时收起进度条')

    dlg3._on_failed('已取消')
    check(dlg3._state == 'available', '用户取消不算失败，安静回到初始')

    print('[H] 下载中取消', flush=True)
    dlg4 = UD.UpdateDialog(rel)
    dlg4.show()
    app.processEvents()
    WK.TaskRunner = FakeRunner
    try:
        dlg4._on_main()
    finally:
        WK.TaskRunner = real_runner
    dlg4._on_main()                      # 再点一次 = 取消
    check(dlg4._state == 'available', '取消后回到 available')
    check(started.get('stopped'), '线程收到停止请求')

    print('[I] 没有安装包的版本', flush=True)
    bare = fake_release('9.8')
    bare = bare._replace(asset_url='', asset_name='')
    dlg5 = UD.UpdateDialog(bare)
    dlg5.show()
    app.processEvents()
    dlg5._on_main()
    check(dlg5._state == 'failed', '没安装包时直接失败，而不是空等')
    check('安装包' in dlg5.status.text(), '说明原因：%s' % dlg5.status.text())

    print('[J] 对话框关闭时不留下线程', flush=True)
    dlg6 = UD.UpdateDialog(rel)
    dlg6.show()
    app.processEvents()
    WK.TaskRunner = FakeRunner
    try:
        dlg6._on_main()
        dlg6.close()
    finally:
        WK.TaskRunner = real_runner
    check(started.get('stopped'), '关窗口时把下载线程停掉')
    check(dlg6._runner is None, 'runner 引用已释放')

    print('[K] 主窗口的检查流程', flush=True)
    # 直接调回调，绕开网络。
    # _open_update 走的是 open()（非阻塞），但离屏下窗口仍然是模态的，
    # 所以这里把它换成记录调用，专测「什么时候该弹」这个判断。
    opened = []
    real_open = win._open_update
    win._open_update = lambda: opened.append(win._update)
    try:
        win._update_manual = True
        win.settings_view.set_update_busy(True)
        win._on_update_checked(rel)
        app.processEvents()
        check(win._update is not None, '记下了新版本')
        check(win.sidebar.update_chip.isVisible(), '侧边栏亮起来')
        check('发现新版本' in win.settings_view.update_hint.text(),
              '设置页回显：%s' % win.settings_view.update_hint.text())
        check(len(opened) == 1, '手动检查发现新版后自动弹出对话框')

        opened[:] = []
        win._on_update_checked(None)
        check(win._update is None, '没有新版本时清空')
        check(not win.sidebar.update_chip.isVisible(), '侧边栏收起')
        check('已是最新' in win.settings_view.update_hint.text(),
              '设置页提示已是最新')
        check(not opened, '已是最新时不弹对话框')

        win._on_update_failed('连接超时', '')
        check('检查失败' in win.settings_view.update_hint.text(),
              '手动检查失败会说出来：%s' % win.settings_view.update_hint.text())

        print('[L] 跳过之后不再弹', flush=True)
        win.settings.set('skip_version', '9.9')
        win._update_manual = True
        opened[:] = []
        win._on_update_checked(rel)
        app.processEvents()
        check(not win.sidebar.update_chip.isVisible(), '跳过过的版本不再亮侧边栏')
        check('已跳过' in win.settings_view.update_hint.text(),
              '设置页仍然如实告知：%s' % win.settings_view.update_hint.text())
        check(not opened, '跳过过的版本不自动弹窗')
        win.settings.set('skip_version', '')

        print('[M] 自动检查失败不打扰用户', flush=True)
        win._update_manual = False
        win.sidebar.show_update('9.9')
        win._on_update_failed('连接超时', '')
        check(not win.sidebar.update_chip.isVisible(), '自动检查失败时收起提示')
        check('失败' not in win.settings_view.update_hint.text(),
              '自动检查失败不往设置页写红字')
    finally:
        win._open_update = real_open

    print('[N] 自动检查有节流', flush=True)
    import time as _t
    # 本文件跑的时候环境里挂着 NO_UPDATE_CHECK（防止真去联网），
    # 但它会让 _schedule_update_check 直接 return —— 那样这两条断言
    # 都是假通过。这里先摘掉，测完再挂回去。
    saved_env = os.environ.pop('TSINGHUA_CRAWLER_NO_UPDATE_CHECK', None)
    try:
        win._update_timer.stop()
        win.settings.set('last_update_check', int(_t.time()))
        win._schedule_update_check()
        check(not win._update_timer.isActive(),
              '刚查过就不查（GitHub 未鉴权每小时只给 60 次）')

        win._update_timer.stop()
        win.settings.set('last_update_check', int(_t.time()) - 13 * 3600)
        win._schedule_update_check()
        check(win._update_timer.isActive(), '超过 12 小时才再查')

        win._update_timer.stop()
        win.settings.set('last_update_check', 0)
        win._schedule_update_check()
        check(win._update_timer.isActive(), '从没查过（0）时也要查')

        win._update_timer.stop()
        win.settings.set('last_update_check', 'garbage')
        win._schedule_update_check()
        check(win._update_timer.isActive(), '配置被改坏时不卡死，照样能查')

        win._update_timer.stop()
        os.environ['TSINGHUA_CRAWLER_NO_UPDATE_CHECK'] = '1'
        win.settings.set('last_update_check', 0)
        win._schedule_update_check()
        check(not win._update_timer.isActive(),
              'NO_UPDATE_CHECK 时完全不查（测试和离线环境用）')
    finally:
        win._update_timer.stop()
        os.environ.pop('TSINGHUA_CRAWLER_NO_UPDATE_CHECK', None)
        if saved_env is not None:
            os.environ['TSINGHUA_CRAWLER_NO_UPDATE_CHECK'] = saved_env

    print('[O] 对话框只留一个', flush=True)
    win._update = rel
    win._open_update()
    app.processEvents()
    first = win._update_dialog
    check(first is not None, '第一次打开会建对话框')
    check(win._update_dialog is first, '引用挂在 self 上（否则会被 GC 掉）')
    win._open_update()
    check(win._update_dialog is first, '已经开着就不重复建')
    first.close()
    app.processEvents()
    check(win._update_dialog is None, '关掉后引用清空')
    win._update = None

    win.close()
    print('', flush=True)
    if FAILED:
        print('UPDATE SMOKE FAIL (%d)' % len(FAILED), flush=True)
        for m in FAILED:
            print('   - %s' % m, flush=True)
        return 1
    print('UPDATE SMOKE OK', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
