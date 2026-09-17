# coding:utf-8
"""
在真实显示上把界面渲染成 PNG 后退出，用于验收「打包之后界面确实是对的」，
不依赖人工点开看。

    TsinghuaBookCrawler.exe --screenshot <输出目录>

注意：这里会把配置目录顶到临时目录。窗口关闭时会把界面上的设置落盘，
而这个模块为了截图会往设置里填一个假的 token —— 不隔离的话，
这个假 token 就会写进用户真实的 config.json。
"""
import os
import sys


def render(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    cfg = os.path.join(out_dir, '_cfg')
    os.makedirs(cfg, exist_ok=True)
    os.environ['TSINGHUA_CRAWLER_DATA_DIR'] = cfg

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from .core import store
    from .gui import theme as T
    from .gui import login as login_mod
    from .gui.shell import MainWindow

    # 窗口一显示，登录页的 SSO 面板就会自动去加载认证页。截图只是要证明
    # 打包后内嵌浏览器能用，没必要真去请求清华服务器，所以顶成空白页。
    login_mod.PLATFORM_HOME = 'about:blank'

    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(T.WIN_W, T.WIN_H)
    win.show()

    # 填一点示意数据，让每个视图能看出真实观感
    win.settings_view.token.edit.setText(
        'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig')
    win.settings_view.set_verify_result(True, '有效')

    urls = ['https://ereserves.lib.tsinghua.edu.cn/bookDetail/'
            'c01e1db11c4041a39db463e810bac8f94af518935a1ec46ef',
            'https://ereserves.lib.tsinghua.edu.cn/bookDetail/'
            'aaa111bbb222ccc333ddd444eee555fff666']
    win.queue_view.entry.setPlainText('\n'.join(urls))
    win._add_urls(urls)
    jobs = win.queue.snapshot()
    for i, j in enumerate(jobs):
        j.title = ['大学俄语1（新版）', '高等数学 上册'][i % 2]
        j.pages, j.chapters, j.done_pages = 386, 12, 214
        j.state = 'downloading' if i == 0 else 'done'
    win.queue_view.set_jobs(jobs)
    win.queue_view.set_running(True)
    win.queue_view.set_counts(len(jobs), 1, 0, 1, 0.62)
    win.queue_view.set_batch_text('正在下载（1 本排队中）',
                                  '第 214/386 页 · 大学俄语1（新版）')
    # 书库示例记录只放在界面上，不写进真实书库
    SAMPLE = (('大学俄语1（新版）', '史铁强', 386, 48200000),
              ('高等数学 上册', '同济大学数学系', 428, 61400000),
              ('大学物理学', '张三慧', 512, 73900000))

    def fill_library():
        win.library_view.set_records([
            store.make_record(t, os.path.join(out_dir, '%s.pdf' % t), out_dir,
                              meta={'title': t, 'author': a}, pages=p, size=s,
                              chapters=12)
            for t, a, p, s in SAMPLE])

    fill_library()

    def shoot():
        """
        顺序拍：登录页(SSO) → 登录页(Token) → 主界面四页。

        必须一步步排下去，不能像以前那样一个 for 循环拍完就 quit —— 内嵌
        浏览器要等它渲染完才能拍，而 quit 会把还没到点的定时器一起带走。
        """
        win.login.set_mode('sso', animate=False)
        win.root_stack.setCurrentIndex(0)
        ok = win.login.sso.ensure_web()
        # 打包后这里必须是 True：为 False 说明 QtWebEngine 的资源没进包
        print('webengine available: %s' % ok, flush=True)
        QTimer.singleShot(2500 if ok else 0, shoot_sso)

    def shoot_sso():
        app.processEvents()
        win.grab().save(os.path.join(out_dir, 'packaged_0_login_sso.png'))
        shoot_token()

    def shoot_token():
        win.login.set_mode('token', animate=False)
        win.login.token.set_token('eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9'
                                  '.eyJleHAiOjQxMDc0NDAwMDB9.demo')
        win.root_stack.setCurrentIndex(0)
        app.processEvents()
        win.grab().save(os.path.join(out_dir, 'packaged_1_login_token.png'))
        shoot_views()

    def shoot_views():
        for i, key in enumerate(('queue', 'library', 'settings', 'help')):
            win.root_stack.setCurrentIndex(1)
            win.goto(key, animate=False)
            if key == 'library':
                # goto 会从真实书库重新加载，所以示例数据要再放一次
                fill_library()
            app.processEvents()
            win.grab().save(os.path.join(out_dir, 'packaged_%d_%s.png'
                                         % (i + 2, key)))
        print('screenshots -> %s' % out_dir, flush=True)
        print('config dir  -> %s (临时，不影响真实设置)' % store.data_dir(),
              flush=True)
        app.quit()

    QTimer.singleShot(1200, shoot)
    return app.exec()
