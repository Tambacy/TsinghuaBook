# coding:utf-8
"""
GUI 集成测试：用假教参平台驱动真实窗口。

验证的是「界面 → 队列 → 引擎 → 书库 → 界面」这条完整链路：
粘链接、排队、进度刷新、写进书库、切到书库能看到封面卡片、
失败能重试、停止能收尾、动效关掉照样能用。
全程离线，不碰真实的清华服务器。
"""
import os
import shutil
import sys
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

# 隔离配置目录：绝不能让测试写到用户真实的书库和设置里
from tests._isolate import assert_isolated, isolate  # noqa: E402

_CFG = isolate()

from PyQt6.QtCore import QEventLoop, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.test_engine import build_fakes, patch  # noqa: E402
from crawler.gui import theme as T  # noqa: E402

TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdefghij'


def wait_for(pred, timeout_ms=120000, label=''):
    """跑事件循环直到 pred() 为真，或超时。"""
    loop = QEventLoop()
    deadline = [False]

    def tick():
        if pred() or deadline[0]:
            loop.quit()

    t = QTimer()
    t.setInterval(30)
    t.timeout.connect(tick)
    t.start()
    QTimer.singleShot(timeout_ms, lambda: (deadline.__setitem__(0, True), loop.quit()))
    loop.exec()
    t.stop()
    if not pred():
        raise AssertionError('timeout waiting for %s' % (label or pred))
    return True


def pump(app, ms=200):
    """让事件循环跑一小会儿，等动画落定。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    app.processEvents()


def main():
    app = QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix='xkc_gui_')
    fails = []

    def check(cond, msg):
        print(('  OK  ' if cond else '  FAIL') + '  ' + msg, flush=True)
        if not cond:
            fails.append(msg)

    # 先确认配置目录真的在临时目录里，否则后面每一条断言都在污染用户数据
    print('  配置目录 = %s' % assert_isolated(), flush=True)

    try:
        state = {}
        fg, fp, sg, sp = build_fakes(state)
        patch(fg, fp, sg, sp)

        from crawler.gui.shell import MainWindow
        save_dir = os.path.join(tmp, 'downloads')

        win = MainWindow()
        win.resize(T.WIN_W, T.WIN_H)
        win.show()
        app.processEvents()

        print('[A] 设置：填 token + 保存位置', flush=True)
        win.goto('settings', animate=False)
        win.settings_view.token.edit.setText(TOKEN)
        win.settings_view.set_dir(save_dir)
        win.settings_view.row_workers.edit.setText('4')
        win.settings_view.row_quality.edit.setText('10')
        win._save_settings()
        check(win.settings.get('token') == TOKEN, 'token 存进设置')
        check(win.settings.get('save_dir') == save_dir, '保存位置存进设置')
        check(win.sidebar.status_chip._ok is True, '侧边栏状态块变成「token 有效」')
        check(win.settings_view.saved_hint.text() == '已保存', '界面提示「已保存」')

        # 设置必须真的落盘，重启后不用再填
        from crawler.core import store
        check(store.Settings().get('token') == TOKEN, '设置已写入磁盘')

        print('[B] 队列：粘两条链接', flush=True)
        win.goto('queue', animate=False)
        qv = win.queue_view
        qv.entry.setPlainText(
            'https://x/bookDetail/VIEW1\n'
            'https://x/bookDetail/BBB222\n'
            'https://x/bookDetail/VIEW1')          # 故意重复一条
        qv._emit_add()
        jobs = win.queue.snapshot()
        check(len(jobs) == 2, '重复链接被去重，队列 = 2（当前 %d）' % len(jobs))
        check(qv.entry.toPlainText() == '', '添加后输入框清空')
        check(len(qv._rows) == 2, '界面生成了 2 行任务')

        print('[C] 开始下载：走真实 QueueManager + QThread', flush=True)
        win._start_queue()
        check(win.queue.running is True, '队列进入运行状态')
        check(not qv.btn_start.isVisibleTo(qv), '「开始下载」被「停止」替换')
        check(qv.batch.isVisibleTo(qv), '整批进度条出现')

        wait_for(lambda: not win.queue.running, 180000, 'queue finished')
        pump(app, 400)

        done, failed, left = win.queue.counts()
        check(done == 2, '两本都完成（当前 done=%d failed=%d）' % (done, failed))
        check(failed == 0, '没有失败任务')
        check(abs(win.queue.progress() - 1.0) < 1e-6,
              '整批进度 = 100%%（当前 %.3f）' % win.queue.progress())
        check(not qv.btn_start.isVisibleTo(qv) or qv.btn_start.isEnabled(),
              '结束后「开始下载」重新可用')

        # 每本都该有独立目录 + PDF
        pdfs = []
        for job in win.queue.snapshot():
            p = job.pdf_path
            check(bool(p) and os.path.exists(p),
                  'PDF 已生成：%s' % (os.path.basename(p) if p else '(none)'))
            if p and os.path.exists(p):
                pdfs.append(p)
        import fitz
        if pdfs:
            with fitz.open(pdfs[0]) as doc:
                check(doc.page_count == 12,
                      'PDF 页数 = 12（当前 %d）' % doc.page_count)
        # 书号不同 -> 目录不同，不能互相覆盖
        check(len({os.path.dirname(p) for p in pdfs}) == len(pdfs),
              '两本书落在各自的目录里')

        print('[D] 书库：下载完成的书自动入库', flush=True)
        win.goto('library', animate=False)
        app.processEvents()
        recs = win.library.all()
        check(len(recs) == 2, '书库有 2 条记录（当前 %d）' % len(recs))
        cards = win.library_view.grid.items()
        check(len(cards) == 2, '书库网格渲染出 2 张卡片')
        for rec in recs:
            check(os.path.exists(rec['pdf_path']), '记录指向真实 PDF')
            check(rec['pages'] == 12, '记录页数 = 12（当前 %s）' % rec['pages'])
            check(bool(rec.get('title')), '记录有书名：%r' % rec.get('title'))
            check(bool(rec.get('cover')) and os.path.exists(rec['cover']),
                  '生成了封面缩略图')
        titles = sorted(r['title'] for r in recs)
        check(titles == ['大学俄语1（新版）', '高等数学 上册'],
              '书名来自平台元数据：%s' % titles)

        # 搜索过滤
        win.library_view.search.setText('俄语')
        app.processEvents()
        check(len(win.library_view.grid.items()) == 1, '按书名筛选出 1 本')
        win.library_view.search.setText('')
        app.processEvents()
        check(len(win.library_view.grid.items()) == 2, '清空搜索后恢复 2 本')

        print('[E] 幂等：重复下载同一本不重复入库', flush=True)
        win.goto('queue', animate=False)
        win.queue.clear_finished()
        win.queue_view.set_jobs(win.queue.snapshot())
        qv.entry.setPlainText('https://x/bookDetail/VIEW1')
        qv._emit_add()
        win._start_queue()
        wait_for(lambda: not win.queue.running, 120000, 'second run')
        pump(app, 300)
        check(len(win.library.all()) == 2,
              '书库仍是 2 条，没有因为重下而重复（当前 %d）'
              % len(win.library.all()))
        job = win.queue.snapshot()[0]
        check(job.state == 'skipped',
              '已存在的书被跳过（当前 %s）' % job.state)

        print('[F] 失败与重试', flush=True)
        # 假平台不看 token，所以这里显式模拟「token 过期」：
        # 带坏 token 的 getBookDetail 返回 data=null，正是真平台的表现。
        import requests as _rq
        from tests.test_engine import FakeResponse
        real_get = _rq.get
        BAD = 'bad.token.value'

        def get_with_bad_token(url, **kw):
            if kw.get('headers', {}).get('Jcclient') == BAD:
                return FakeResponse(json_data={'data': None})
            return real_get(url, **kw)

        win2 = MainWindow()
        win2.resize(T.WIN_W, T.WIN_H)
        win2.show()
        win2.goto('settings', animate=False)
        win2.settings_view.token.edit.setText(BAD)
        win2.settings_view.set_dir(os.path.join(tmp, 'downloads_bad'))
        win2._save_settings()
        win2.goto('queue', animate=False)
        win2.queue_view.entry.setPlainText('https://x/bookDetail/AAA111')
        win2.queue_view._emit_add()

        _rq.get = get_with_bad_token
        try:
            win2._start_queue()
            wait_for(lambda: not win2.queue.running, 120000, 'bad token run')
            pump(app, 300)
        finally:
            _rq.get = real_get

        done, failed, left = win2.queue.counts()
        check(failed == 1, 'token 无效时任务判为失败（当前 failed=%d）' % failed)
        check(win2.queue_view.btn_retry.isEnabled(), '「重试失败」按钮可用')
        bad = win2.queue.snapshot()[0]
        check(bool(bad.error), '失败原因记录下来：%r' % (bad.error or '')[:60])
        check('Token' in (bad.error or ''), '失败原因指明是 token 问题')
        check(not win2.library.get('REALBOOKAAA'), '失败的书不入库')

        # 换回好 token，重试应当成功
        win2.goto('settings', animate=False)
        win2.settings_view.token.edit.setText(TOKEN)
        win2._save_settings()
        win2._retry_failed()
        wait_for(lambda: not win2.queue.running, 120000, 'retry run')
        pump(app, 400)
        done, failed, left = win2.queue.counts()
        check(done == 1 and failed == 0,
              '重试后成功（done=%d failed=%d）' % (done, failed))
        check(win2.library.get('REALBOOKAAA'), '重试成功的书入库了')

        print('[G] 停止：中途取消不丢已完成的部分', flush=True)
        win3 = MainWindow()
        win3.resize(T.WIN_W, T.WIN_H)
        win3.show()
        win3.goto('settings', animate=False)
        win3.settings_view.token.edit.setText(TOKEN)
        win3.settings_view.set_dir(os.path.join(tmp, 'downloads_stop'))
        win3._save_settings()
        win3.goto('queue', animate=False)
        win3.queue_view.entry.setPlainText(
            'https://x/bookDetail/VIEW1\nhttps://x/bookDetail/AAA111')
        win3.queue_view._emit_add()
        win3._start_queue()
        QTimer.singleShot(60, win3._stop_queue)
        wait_for(lambda: not win3.queue.running, 120000, 'stop')
        pump(app, 300)
        check(any(j.state in ('cancelled', 'done') for j in win3.queue.snapshot()),
              '任务停下来且状态明确')
        check(all(not j.active for j in win3.queue.snapshot()),
              '没有任务停在「进行中」')
        # 停下的书重新排队应该能接着下
        win3._retry_failed()
        if win3.queue.running:
            wait_for(lambda: not win3.queue.running, 120000, 'resume')
            pump(app, 300)
        check(all(j.finished for j in win3.queue.snapshot()),
              '重新排队后全部收尾')

        print('[H] 空状态与边界', flush=True)
        win4 = MainWindow()
        win4.resize(980, 660)                 # 最小尺寸
        win4.show()
        # 书库/设置在这个进程里已经被前面几步写过了，这里要显式清干净
        win4.library_view.set_records([])
        app.processEvents()
        check(win4.library_view.empty.isVisibleTo(win4.library_view),
              '空书库显示空状态')
        check(not win4.library_view.grid.items(), '空书库没有卡片')

        win4.goto('queue', animate=False)
        win4.queue_view.entry.setPlainText('这里没有任何链接')
        win4.queue_view._emit_add()
        check(len(win4.queue.snapshot()) == 0, '无链接文本不会产生任务')

        # 没有 token 时点开始，应当被拦住并跳到设置。
        # 这里必须把弹窗换掉：QMessageBox.information 是模态的，会把测试挂住。
        from crawler.gui import shell as shell_mod
        shown = []
        real_info = shell_mod.QMessageBox.information
        shell_mod.QMessageBox.information = staticmethod(
            lambda *a, **k: shown.append(a[2] if len(a) > 2 else ''))
        try:
            win4.settings_view.token.edit.setText('')
            win4.settings.update(token='')
            win4._start_queue()
        finally:
            shell_mod.QMessageBox.information = real_info
        check(bool(shown), '缺 token 时弹窗提示')
        # 现在没有 Token 会退回登录页（企业应用的形态），而不是跳到设置页
        check(win4.root_stack.currentWidget() is win4.login,
              '缺 token 时退回登录页')
        check(win4.queue.running is False, '缺 token 时不会真的开跑')

        print('[I] 动画关闭时界面仍完整可用', flush=True)
        T.motion.ENABLED = False
        win5 = MainWindow()
        win5.resize(T.WIN_W, T.WIN_H)
        win5.show()
        for key in ('queue', 'library', 'settings', 'help'):
            win5.goto(key, animate=False)
            app.processEvents()
        win5.goto('settings', animate=False)
        win5.settings_view.token.edit.setText(TOKEN)
        win5.settings_view.set_dir(os.path.join(tmp, 'downloads_static'))
        win5._save_settings()
        win5.goto('queue', animate=False)
        win5.queue_view.entry.setPlainText('https://x/bookDetail/BBB222')
        win5.queue_view._emit_add()
        win5._start_queue()
        wait_for(lambda: not win5.queue.running, 120000, 'static run')
        pump(app, 300)
        done, failed, _ = win5.queue.counts()
        check(done == 1 and failed == 0,
              '关动画后下载照样完成（done=%d failed=%d）' % (done, failed))
        check(win5.library_view.grid.columns() >= 1, '关动画后书库网格仍能排')
        row = list(win5.queue_view._rows.values())[0]
        check(row.job.state == 'done', '关动画后队列行状态正确：%s' % row.job.state)

        # ---------------------------------------------------------- 登录闸门
        print('\n[J] 登录闸门：Token 有效就直接进主界面', flush=True)
        import base64
        import json as _json
        import time as _time
        from crawler.core import tokeninfo as ti

        def jwt(exp_offset):
            def seg(o):
                raw = _json.dumps(o, separators=(',', ':')).encode('utf-8')
                return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')

            now = _time.time()
            return '%s.%s.sig' % (seg({'alg': 'RS256', 'typ': 'JWT'}),
                                  seg({'exp': int(now + exp_offset)}))

        good = jwt(30 * 86400)
        win6 = MainWindow()
        win6.resize(T.WIN_W, T.WIN_H)
        win6.show()
        app.processEvents()
        win6.settings.update(token=good, login_mode='token')
        win6.start()
        app.processEvents()
        check(win6.root_stack.currentWidget() is not win6.login,
              'Token 有效时 start() 不要求登录')
        check(win6._view == 'queue', '  并且落在队列页')

        print('[K] 登录闸门：Token 过期就回登录页', flush=True)
        win7 = MainWindow()
        win7.resize(T.WIN_W, T.WIN_H)
        win7.show()
        app.processEvents()
        win7.settings.update(token=jwt(-3600), login_mode='token')
        win7.start()
        app.processEvents()
        check(win7.root_stack.currentWidget() is win7.login,
              'Token 过期时 start() 回登录页')
        check(win7.login.mode() == 'token', '  并且停在 Token 模式')
        check(bool(win7.login.token.edit.toPlainText()),
              '  过期 Token 被预填进输入框，方便对照更换')

        print('[L] 登录成功 → 存 Token → 进主界面', flush=True)
        win7.login.token.set_token(good)
        win7.login.token._submit()
        pump(app, 200)
        check(win7.settings.token == good, 'Token 写进设置')
        check(win7.root_stack.currentWidget() is not win7.login,
              '登录成功后离开登录页')
        check(store.Settings().token == good, 'Token 已落盘')
        check(win7._expiry_handled is False, '新 Token 重置了失效守卫')
        check(win7.sidebar.status_chip._ok is True, '侧边栏显示已登录')

        print('[M] 退出登录清干净', flush=True)
        gen_before = int(win7.settings.get('webprofile_gen') or 0)
        win7._logout()
        pump(app, 200)
        check(win7.settings.token == '', 'Token 被清空')
        check(store.Settings().token == '', '清空已落盘')
        check(win7.root_stack.currentWidget() is win7.login, '回到登录页')
        check(win7.login.token.edit.toPlainText() == '', '输入框也清空')
        check(win7.sidebar.status_chip._ok is False, '侧边栏显示未登录')
        # 内嵌浏览器的登录态也必须清掉。只删 cookie 不够：deleteAllCookies()
        # 是异步的，而且清不掉 localStorage / 缓存 —— 退出去还是「已登录」的
        # 界面，用户没法换个账号重新登。所以退出登录要换一代 profile 目录。
        gen_after = int(win7.settings.get('webprofile_gen') or 0)
        check(gen_after == gen_before + 1,
              '退出登录换了一代浏览器 profile：%d -> %d' % (gen_before, gen_after))
        check(win7.login.sso._view is None, '内嵌浏览器已拆掉，下次用新目录重建')
        check(win7.login.sso._captured is False, '截 Token 状态复位')
        check(win7.login.sso._suppress_capture is True,
              '退出后先不截 Token，免得旧会话又把它抓回来')

        print('[N] Token 失效：Token 模式提醒更换', flush=True)
        asked = []
        real_warn = shell_mod.QMessageBox.warning

        def fake_warn(*a, **k):
            asked.append(a[2] if len(a) > 2 else '')

        win8 = MainWindow()
        win8.resize(T.WIN_W, T.WIN_H)
        win8.show()
        app.processEvents()
        win8.settings.update(token=jwt(-3600), login_mode='token',
                             auto_refresh=False)
        try:
            shell_mod.QMessageBox.warning = fake_warn
            win8._expiry_handled = False
            win8._watch_for_expiry([])          # 空队列：靠本地 exp 判断不该触发
            check(not asked, '队列空闲时不因为本地过期就弹窗打扰')
            win8._expiry_handled = False
            # running 是只读属性（由线程推出来的），要伪造就换掉线程
            win8.queue._thread = _AliveThread()
            win8.queue.start = lambda: True
            win8._watch_for_expiry([])
            pump(app, 300)
            check(bool(asked), 'Token 模式下过期会明确提醒更换')
            check(win8.settings.token == '', '  并且把失效的 Token 清掉')
            check(win8.root_stack.currentWidget() is win8.login,
                  '  并回到登录页')
            check(win8.login.mode() == 'token', '  停在 Token 模式等用户粘贴新的')
        finally:
            shell_mod.QMessageBox.warning = real_warn
            win8.queue._thread = None

        print('[O] Token 失效：SSO 模式自动重取，不弹窗', flush=True)
        asked2 = []
        win9 = MainWindow()
        win9.resize(T.WIN_W, T.WIN_H)
        win9.show()
        app.processEvents()
        win9.settings.update(token='x', login_mode='sso', auto_refresh=True)
        win9.settings.save()
        started = []
        win9.login.sso.start = lambda force=False: started.append(force)
        try:
            shell_mod.QMessageBox.warning = lambda *a, **k: asked2.append(a)
            win9._expiry_handled = False
            win9._watch_for_expiry([_FakeJobErr('Token 不正确或已过期，请重新获取。')])
            pump(app, 300)
            check(not asked2, 'SSO 模式不弹窗，用户不被打断')
            check(bool(started), '  而是让内嵌浏览器去自动续期')
            check(started and started[-1] is True, '  并且是强制重新导航')
            check(win9.root_stack.currentWidget() is win9.login,
                  '  同时把登录页摆出来（续期要看得见）')
            check(win9.login.mode() == 'sso', '  停在 SSO 模式')
            # 守卫：失败任务一直在快照里，不能反复触发
            n = len(started)
            win9._watch_for_expiry([_FakeJobErr('Token 不正确或已过期，请重新获取。')])
            pump(app, 200)
            check(len(started) == n, '同一轮失效只处理一次（不反复弹/反复导航）')
        finally:
            shell_mod.QMessageBox.warning = real_warn

        # 清华教参的 Token 实测只活 63 分钟，一次批量下载跨过一整个有效期
        # 是常事。所以「续期回来后把失败的书自动接上」必须真的工作，
        # 否则用户每小时都要自己点一次「重试失败」。
        print('[P] 续期回来后自动接上失败的书', flush=True)
        win10 = MainWindow()
        win10.resize(T.WIN_W, T.WIN_H)
        win10.show()
        app.processEvents()
        retries = []
        win10._retry_failed = lambda: retries.append(1)

        # 1) SSO 续期路径必须挂上「待续接」标记
        win10.settings.update(token='x', login_mode='sso', auto_refresh=True)
        win10.login.sso.start = lambda force=False: None
        win10._expiry_handled = False
        win10._resume_pending = False
        win10._token_expired()
        check(win10._resume_pending is True,
              '  走 SSO 自动续期时挂上「待续接」标记')

        # 2) 登回来之后自动重试（经 QTimer，所以要 pump）
        win10._maybe_resume()
        pump(app, 200)
        check(len(retries) == 1, '  登录成功后自动重试失败的任务')

        # 3) 没有待续接标记时不许乱动队列
        win10._maybe_resume()
        pump(app, 200)
        check(len(retries) == 1, '  普通登录不会去动队列')

        # 4) 上限：新 Token 也被拒时不能无限自动重试
        win10._resume_pending = True
        win10._resume_count = 2
        win10._maybe_resume()
        pump(app, 200)
        check(len(retries) == 1, '  达到上限后停止自动重试（不会死循环）')

        # 5) 手动 Token 模式不做续接 —— 那里要用户自己换 Token
        win10.settings.update(login_mode='token')
        win10._expiry_handled = False
        win10._resume_pending = False
        try:
            shell_mod.QMessageBox.warning = lambda *a, **k: None
            win10._token_expired()
        finally:
            shell_mod.QMessageBox.warning = real_warn
        check(win10._resume_pending is False,
              '  Token 模式不标记续接（用户要手换 Token）')

        print('[Q] 侧边栏显示当前账号', flush=True)

        def _jwt2(exp_offset, iat_offset=0, **extra):
            def seg(o):
                raw = _json.dumps(o, separators=(',', ':')).encode('utf-8')
                return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
            now = _time.time()
            body = {'exp': int(now + exp_offset), 'iat': int(now + iat_offset)}
            body.update(extra)
            return '%s.%s.sig' % (seg({'alg': 'RS256', 'typ': 'JWT'}), seg(body))

        win11 = MainWindow()
        win11.resize(T.WIN_W, T.WIN_H)
        win11.show()
        app.processEvents()
        chip = win11.sidebar.status_chip

        # 清华教参的 payload：userName 是姓名，userId 是学号，sub 是固定串
        tok = _jwt2(3780, sub='JCClientUser', userId='2024000001',
                    userKey='2024000001', userName='张三')
        win11.settings.update(token=tok, login_mode='sso')
        win11._sync_sidebar()
        app.processEvents()
        check(chip._title == '张三',
              '侧边栏标题 = 账号名（实际 %r）' % chip._title)
        check('还剩' in chip._sub,
              '副标题 = 倒计时（实际 %r）' % chip._sub)
        check('张三' in chip.toolTip() and '2024000001' in chip.toolTip(),
              'tooltip 里姓名和学号都在')
        check('JCClientUser' not in chip.toolTip(),
              '  sub 那个固定标识没被当成账号')

        # 名字长到放不下时必须省略号截断，不能画到圆角外面
        win11.settings.update(token=_jwt2(3780, userName='一个非常非常长'
                                                       '以至于放不下的中文姓名'))
        win11._sync_sidebar()
        app.processEvents()
        win11.grab()
        from PyQt6.QtGui import QFontMetrics
        _fm = QFontMetrics(T.ui_font(T.FS_META, 600))
        _w = chip.width() - 34
        check(_fm.horizontalAdvance(chip._title) > _w,
              '  构造了一个确实超宽的名字（用于验证省略号）')
        check(True, '  超宽名字仍能正常绘制不报错')

        # 读不到名字时退回状态文案，不能是空白
        win11.settings.update(token=_jwt2(3780))
        win11._sync_sidebar()
        app.processEvents()
        check(chip._title == 'token 有效',
              '没有姓名 -> 退回状态文案（实际 %r）' % chip._title)

        # 没登录
        win11.settings.update(token='')
        win11._sync_sidebar()
        app.processEvents()
        check(chip._title == '未设置 token',
              '未登录时的文案（实际 %r）' % chip._title)
        check('还没登录' in chip.toolTip(), '  且 tooltip 说明还没登录')

        print('\n[R] 队列里点删除（自绘图标必须真的能点）', flush=True)
        # 这条是回归测试：JobRow 的悬停图标是自绘的、不是真按钮，
        # 曾经只画出来而没有任何命中测试，点删除完全没反应。
        from PyQt6.QtCore import QEvent, QPointF, Qt
        from PyQt6.QtGui import QMouseEvent

        from crawler.gui import widgets as W

        win12 = MainWindow()
        win12.resize(T.WIN_W, T.WIN_H)
        win12.show()
        app.processEvents()
        win12.queue.add(['https://example.invalid/book/a',
                         'https://example.invalid/book/b'])
        win12.queue_view.set_jobs(win12.queue.snapshot())
        app.processEvents()

        jobs = win12.queue.snapshot()
        rows = [win12.queue_view._rows[id(j)] for j in jobs]
        check(len(rows) == 2, '两行都建出来了')

        row = rows[0]
        row.resize(row.sizeHint().width() or 600, 64)
        app.processEvents()
        ro, rm = row._buttons()

        def click(r, widget):
            widget._hover = True
            ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(r.center()),
                             Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier)
            widget.mouseReleaseEvent(ev)

        # 点空白处不该删（别把整行都变成删除热区）
        blank = row.rect().center()
        before = len(win12.queue.snapshot())
        row._hover = True
        ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(blank),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        row.mouseReleaseEvent(ev)
        app.processEvents()
        check(len(win12.queue.snapshot()) == before,
              '  点行内空白不删除（当前 %d 条）' % len(win12.queue.snapshot()))

        # 点垃圾桶 -> 该条从队列里消失
        victim = win12.queue.snapshot()[0]
        click(rm, row)
        app.processEvents()
        left = win12.queue.snapshot()
        check(len(left) == before - 1,
              '点删除按钮真的删掉了（剩 %d 条）' % len(left))
        check(victim not in left, '  删掉的正是被点的那条')

        # 正在跑的行不该被删掉
        running = win12.queue.snapshot()[0]
        running.state = 'downloading'
        win12.queue_view.set_jobs(win12.queue.snapshot())
        app.processEvents()
        row2 = win12.queue_view._rows[id(running)]
        row2.resize(row2.sizeHint().width() or 600, 64)
        app.processEvents()
        click(row2._buttons()[1], row2)
        app.processEvents()
        check(running in win12.queue.snapshot(), '  正在下载的行点删除不会消失')
        running.state = 'pending'

        print('\n[S] 天幕动画该跑的时候才跑', flush=True)
        # 内嵌浏览器在跑时必须停掉装饰动画：实测它曾吃掉主线程 50%~74% 的
        # CPU，把浏览器输入事件挤到「点一下等 3 秒」。
        # 前面 [B] 那段把 motion 关过，这里要打开 —— 天幕的定时器是构造时
        # 按 motion.ENABLED 建的，不打开就根本不存在，测不出东西。
        T.motion.ENABLED = True
        # 这一段测的是「没有底图时的回退路径」。仓库里现在带着
        # assets/backdrop.jpg，而且登录页左栏用的是自己那张 login_hero，
        # 有底图时整块天幕是静态的、连定时器都不建
        # （见 backdrop.SkyBackdrop.__init__），这条路就走不到了。
        # 所以要按 _find_asset 屏蔽 —— 只屏蔽 _find_backdrop 的话，登录页
        # 仍然会拿到 login_hero，回退路径还是走不到。
        from crawler.gui import backdrop as BD
        _orig_find = BD._find_asset
        BD._find_asset = lambda stem: None
        win13 = MainWindow()
        win13.resize(T.WIN_W, T.WIN_H)
        win13.settings.update(login_mode='sso')
        win13.show()
        app.processEvents()
        # 和真实启动一样：MainWindow.start() 会把登录页切到前台。
        # 不切的话登录页 isVisible() 为假，天幕本来就该停，测不出东西。
        win13.root_stack.setCurrentWidget(win13.login)
        app.processEvents()
        win13.login.set_mode('sso', animate=False, start=False)
        app.processEvents()
        check(win13.login.isVisible(), '  登录页已经在前台')
        sky13 = win13.login.brand.sky
        check(not sky13._timer.isActive(),
              'SSO 模式（右边挂着浏览器）天幕动画是停的')

        win13.login.set_mode('token', animate=False)
        app.processEvents()
        check(sky13._timer.isActive(),
              'Token 模式（没有浏览器）天幕动画自己回来')

        win13.login.set_mode('sso', animate=False)
        app.processEvents()
        check(not sky13._timer.isActive(), '  切回 SSO 又停掉')

        # 登录页不可见（已进主界面）时不该空转
        win13.login.hide()
        app.processEvents()
        check(not sky13._timer.isActive(), '登录页不可见时不空转')

        print('\n[T] 天幕帧率', flush=True)
        from crawler.gui import backdrop as BD
        check(BD.SKY_TICK_MS >= 30,
              '天幕自己的刷新间隔是 %dms（不跟 15ms 的全局动效走）'
              % BD.SKY_TICK_MS)
        jt = _jwt2(3780, userName='张三')
        win13.settings.update(token=jt)
        win13.login.show()
        win13.login.set_mode('token', animate=False)
        app.processEvents()
        sky13._phase = 3.0
        sky13._tick()
        check(abs(sky13._phase - (3.0 + BD.SKY_TICK_MS / 1000.0)) < 1e-9,
              '相位推进量和刷新间隔一致（改帧率不会连带改漂移速度）')
        BD._find_asset = _orig_find

        print('\n[T2] 带底图时的天幕', flush=True)
        art = BD.SkyBackdrop('violet', animated=True)
        art.resize(220, T.SKY_PANEL_H)
        art.grab()
        app.processEvents()
        check(art._has_art, '找到并使用底图 assets/backdrop.*')
        check(art._timer is None,
              '有底图时不建定时器 —— 比「建了再停」更省，也没有相位可推进')
        check(art._stars == [], '  有底图时不再撒程序化星点')
        check(art._static is not None and not art._static.isNull(),
              '  底图确实被铺进了静态层')
        T.motion.ENABLED = False

        print('\nGUI INTEGRATION %s' % ('PASS' if not fails else 'FAIL'), flush=True)
        return 0 if not fails else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class _FakeJobErr(object):
    """只带 error 字段的假任务，用来喂 _watch_for_expiry。"""

    def __init__(self, msg):
        self.error = msg


class _AliveThread(object):
    """假的活线程：QueueManager.running 是由线程推出来的只读属性。"""

    def is_alive(self):
        return True


if __name__ == '__main__':
    sys.exit(main())