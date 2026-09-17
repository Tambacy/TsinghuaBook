# coding:utf-8
"""
打包后自检。在冻结（exe）环境里跑，确认资源、依赖、窗口构造都没问题。
用法：TsinghuaBookCrawler.exe --selftest

注意发布版是 console=False，没有 stdout，所以结果同时写进一个报告文件：
    %TEMP%\\tsinghua_selftest.txt
"""
import os
import sys

_LINES = []

# 自检期间被拦下的「写用户真实 config.json」次数。必须始终为 0。
_BLOCKED_SAVES = []
# 自检期间被拦下的「删用户真实目录」次数。必须始终为 0。
_BLOCKED_DELETES = []


def _say(text=''):
    _LINES.append(text)
    try:
        print(text, flush=True)
    except Exception:                                                # noqa: BLE001
        pass


def _report(ok, label, extra=''):
    _say(('  OK   ' if ok else '  FAIL ') + label + (('  ' + extra) if extra else ''))
    return ok


def _write_report():
    path = os.path.join(os.environ.get('TEMP', os.getcwd()),
                        'tsinghua_selftest.txt')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(_LINES) + '\n')
    except OSError:
        return None
    return path


def run_selftest():
    results = []
    _say('=== frozen = %s' % getattr(sys, 'frozen', False))
    _say('=== _MEIPASS = %s' % getattr(sys, '_MEIPASS', None))
    _say('=== executable = %s' % sys.executable)

    # 依赖
    for mod in ('requests', 'fitz', 'PIL', 'PyQt6.QtWidgets', 'PyQt6.QtCore'):
        try:
            __import__(mod)
            results.append(_report(True, 'import %s' % mod))
        except Exception as e:                                       # noqa: BLE001
            results.append(_report(False, 'import %s' % mod, str(e)))

    # 命令行下载链路。这条必须在冻结环境里单独验：
    # 「-h」只走 argparse，就算这几个模块没被打进去也照样打印帮助，
    # 真正的下载却会在启动线程时才炸。所以这里必须显式 import。
    for mod in ('crawler.legacy.download_imgs', 'crawler.legacy.hhhimg2pdf',
                'crawler.legacy.utils', 'crawler.legacy.auth_get',
                'crawler.core.cli'):
        try:
            __import__(mod)
            results.append(_report(True, 'import %s（命令行链路）' % mod))
        except Exception as e:                                       # noqa: BLE001
            results.append(_report(False, 'import %s（命令行链路）' % mod, str(e)))

    # 界面用到的核心模块
    for mod in ('crawler.core.store', 'crawler.core.queue',
                'crawler.core.worker', 'crawler.gui.views',
                'crawler.gui.login', 'crawler.core.tokeninfo'):
        try:
            __import__(mod)
            results.append(_report(True, 'import %s' % mod))
        except Exception as e:                                       # noqa: BLE001
            results.append(_report(False, 'import %s' % mod, str(e)))

    # Token 解析：登录页和「失效提醒」都靠它，是发布版必须能跑的一环
    try:
        from crawler.core import tokeninfo as _ti
        _jwt = ('eyJhbGciOiJSUzI1NiJ9.eyJleHAiOjQxMDc0NDAwMDB9.sig')
        _url = 'https://ereserves.lib.tsinghua.edu.cn/index?token=%s' % _jwt
        results.append(_report(_ti.extract_token(_url) == _jwt,
                               'tokeninfo 能从地址里抠出 Token'))
        _info = _ti.TokenInfo(_jwt)
        results.append(_report(_info.has_expiry and not _info.is_expired(),
                               'tokeninfo 能解出有效期',
                               _info.describe()))

        # 「快过期」的阈值必须跟着 Token 自己的寿命走。清华教参的 Token
        # 实测只活 63 分钟；如果阈值写死成 3 天，刚签发的新 Token 也会被
        # 判成快过期，提示永远亮着。这条检查同时能证明打包出来的
        # 不是旧版本的 tokeninfo。
        import base64 as _b64
        import json as _json
        import time as _time

        def _seg(o):
            raw = _json.dumps(o, separators=(',', ':')).encode('utf-8')
            return _b64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')

        _now = _time.time()
        _short = '%s.%s.s' % (_seg({'alg': 'RS256'}),
                              _seg({'iat': int(_now),
                                    'exp': int(_now + 63 * 60)}))
        _si = _ti.TokenInfo(_short)
        results.append(_report(
            _si.state() == 'valid' and abs(_si.warn_seconds() - 756) < 2,
            '63 分钟寿命的 Token：新签发算「有效」',
            'state=%s warn=%.0fs' % (_si.state(), _si.warn_seconds())))
        results.append(_report(_si.state(now=_now + 60 * 60) == 'soon',
                               '  剩 3 分钟时算「快过期」'))

        # 当前账号：侧边栏要显示登的是谁。清华这个平台 userName 是姓名、
        # userId 是学号，sub 恒为 'JCClientUser'（不是人名）
        _acc = '%s.%s.s' % (_seg({'alg': 'RS256'}),
                            _seg({'iat': int(_now), 'exp': int(_now + 3780),
                                  'sub': 'JCClientUser', 'userId': '2024000001',
                                  'userName': '测试账号'}))
        _ai = _ti.TokenInfo(_acc)
        results.append(_report(_ai.account_label() == '测试账号',
                               'tokeninfo 能读出账号名',
                               _ai.account_tooltip()))
        results.append(_report('JCClientUser' not in _ai.account_tooltip(),
                               '  没把 sub 那个固定标识当账号'))
        results.append(_report(_ai.left_text() == '还剩 1 小时 3 分',
                               '  侧边栏倒计时文案：%s' % _ai.left_text()))
    except Exception as e:                                           # noqa: BLE001
        results.append(_report(False, 'tokeninfo 解析', str(e)))

    # 内嵌浏览器：登录的「统一身份认证」模式完全依赖它。打包时最容易漏，
    # 所以这里要在打包后的 exe 里真的 import 一次并取版本号。
    try:
        from PyQt6.QtWebEngineCore import QWebEngineProfile, qWebEngineVersion
        _ver = qWebEngineVersion()
        results.append(_report(bool(_ver), 'import PyQt6.QtWebEngineCore',
                               'QtWebEngine %s' % _ver))
        results.append(_report(QWebEngineProfile is not None,
                               'WebEngineProfile 可用（持久化登录态）'))
    except Exception as e:                                           # noqa: BLE001
        results.append(_report(False, 'import PyQt6.QtWebEngineCore', str(e)))

    # 资源
    from crawler.gui.shell import resource_path
    icon = resource_path('assets', 'app.ico')
    results.append(_report(os.path.exists(icon), 'assets/app.ico 存在', icon))

    # 图标得是「多尺寸」的：只有一张 256 的话，任务栏和标题栏会被系统
    # 硬缩，糊得很难看。这是打包后最容易丢的东西之一。
    try:
        import struct
        with open(icon, 'rb') as fh:
            blob = fh.read()
        count = struct.unpack('<H', blob[4:6])[0]
        sizes = [struct.unpack('<BB', blob[6 + i * 16:8 + i * 16])[0] or 256
                 for i in range(count)]
        results.append(_report(count >= 8 and 256 in sizes and 16 in sizes,
                               '应用图标是多尺寸的', '共 %d 档 %s'
                               % (count, sizes)))
    except Exception as e:                                           # noqa: BLE001
        results.append(_report(False, '解析应用图标', str(e)))

    from crawler.gui import backdrop
    bd = backdrop._find_backdrop()
    _say('       backdrop override = %s' % bd)   # None 是正常的

    # 窗口构造
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    # 自检跑在用户真实的配置目录上，所以不能让窗口一显示就去建内嵌浏览器的
    # profile（会在真实目录里留一个 webprofile），更不能让它去请求教参平台。
    # 「打包后 WebEngine 到底能不能用」由 launcher.py --screenshot 负责验：
    # 那边把配置目录顶到临时目录，并且真的创建一次 QWebEngineView。
    os.environ['TSINGHUA_CRAWLER_NO_WEBENGINE'] = '1'
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    # ------------------------------------------------ 数据安全闸门
    # 自检跑在用户真实的配置目录上。下面两把锁必须在**构造窗口之前**就装好：
    # 窗口一构造就会跑 profile 清理，装晚了照样会删用户的目录。
    #
    # 为什么需要：之前有个检查间接调了 settings.save()，把用户的 token 清掉了；
    # Token 过期时窗口启动还会走退出登录，连带把 webprofile 删掉。
    # 这里既拦住、又把它记成失败项 —— 只堵不说等于掩盖问题。
    from crawler.core import store
    from crawler.gui import login as _login_mod
    _login_mod.PLATFORM_HOME = 'about:blank'

    _real_cfg = os.path.abspath(os.path.join(store.data_dir(), 'config.json'))
    _real_save = store.Settings.save

    def _guarded_save(self, *a, **kw):
        try:
            target = os.path.abspath(self.path or '')
        except Exception:                                            # noqa: BLE001
            target = ''
        if target == _real_cfg:
            _BLOCKED_SAVES.append(target)
            return
        return _real_save(self, *a, **kw)

    store.Settings.save = _guarded_save

    def _guarded_rmtree(path):
        _BLOCKED_DELETES.append(path)

    _login_mod._rmtree_quiet = _guarded_rmtree

    try:
        from crawler.gui.shell import MainWindow
        win = MainWindow()
        win.resize(1280, 820)
        win.show()
        for key in ('queue', 'library', 'settings', 'help'):
            win.goto(key, animate=False)
            app.processEvents()
            win.grab()
        results.append(_report(True, '四个视图全部构造并渲染'))

        # 窗口外壳：无边框 + 自绘标题栏 + 命中测试。
        # 这几条是「窗口还能不能拖 / 缩 / 关」，坏了就是不可用级别的问题。
        from PyQt6.QtCore import QPoint, Qt as _Qt
        from crawler.gui import theme as _T
        from crawler.gui import titlebar as _tb
        frameless = bool(win.windowFlags() & _Qt.WindowType.FramelessWindowHint)
        results.append(_report(frameless, '窗口使用自绘标题栏（已去掉系统边框）'))
        results.append(_report(win.titlebar is not None
                               and win.titlebar.height() == _T.TITLEBAR_H,
                               '标题栏高度 = %d' % _T.TITLEBAR_H))
        _mw = win.layout().contentsMargins()
        results.append(_report(
            (_mw.left(), _mw.top(), _mw.right(), _mw.bottom()) == (1, 1, 1, 1),
            '窗口四周留了 1px 描边位'))
        _w, _h = win.width(), win.height()
        _ht_ok = (  # noqa: E501
            _tb.hit_test(win, QPoint(1, 1)) == _tb.HTTOPLEFT
            and _tb.hit_test(win, QPoint(_w - 2, _h - 2)) == _tb.HTBOTTOMRIGHT
            and _tb.hit_test(win, QPoint(1, _h // 2)) == _tb.HTLEFT
            and _tb.hit_test(win, QPoint(320, _T.TITLEBAR_H // 2))
            == _tb.HTCAPTION)
        results.append(_report(_ht_ok, '边缘缩放 / 标题栏拖动命中测试正确'))
        results.append(_report(
            _tb.hit_test(win, win.titlebar.btn_close.mapTo(
                win, QPoint(6, 6))) is None,
            '关闭按钮不会被当成拖动区'))
        # nativeEvent 的异常必须自己兜住：逃出去 PyQt 会直接 abort 进程，
        # 退出码 0xC000041D，没有任何日志。这里确认它不抛。
        try:
            win.nativeEvent(b'another_event', 0)
            win.nativeEvent(b'windows_generic_MSG', 0)
            results.append(_report(True, 'nativeEvent 对异常输入安全'))
        except BaseException as e:                                   # noqa: BLE001
            results.append(_report(False, 'nativeEvent 对异常输入安全', str(e)))
        from crawler.gui import shell as _sh
        results.append(_report(not _sh._NATIVE_ERRORS,
                               '窗口命中测试没有出错',
                               ' | '.join(_sh._NATIVE_ERRORS) or '0 次'))

        # 天幕底图：随包发布、确实被用上、而且是静态的。
        # 少了这张图程序不会崩（会静默退回程序化夜空），但界面会明显变差 ——
        # 而它又是靠 PyInstaller 的 datas 带进来的，最容易在打包时漏掉。
        from crawler.gui import backdrop as _bd
        _art = _bd._find_backdrop()
        results.append(_report(bool(_art), '天幕底图已随包发布',
                               _art or '未找到，会退回程序化夜空'))
        _sky = win.sidebar.sky.sky
        results.append(_report(bool(getattr(_sky, '_has_art', False)),
                               '侧边栏天幕用的是底图'))
        results.append(_report(_sky._timer is None,
                               '有底图时天幕是静态的（连定时器都不建）'))

        # 登录页左栏的主视觉、以及书库那 8 张封面底图。
        # 同样靠 PyInstaller 的 datas 带进来，漏一张就是一块空白或者一片纯色；
        # 而且封面是按文件名分配的，改名/少一张会静默走到另一张图上，
        # 界面看着「还行」但已经错了 —— 所以要按名字逐张点名核对。
        _hero = _bd._find_asset('login_hero')
        results.append(_report(bool(_hero), '登录页主视觉已随包发布',
                               _hero or '未找到，会退回 backdrop'))
        from crawler.gui import covers as _cv
        _missing = [n for n in _cv.NAMES if not _cv.path(n)]
        results.append(_report(not _missing,
                               '书库封面底图 %d 张齐全' % len(_cv.NAMES),
                               ('缺 ' + ', '.join(_missing)) if _missing
                               else ', '.join(_cv.NAMES)))
        # 分配必须是确定的：同一本书每次都要拿到同一张，否则重启一次
        # 封面就换一张，用户会当成 bug。
        _a = _cv.pick('高等数学 上册')
        _b = _cv.pick('高等数学 上册')
        results.append(_report(_a == _b and _cv.pick('高等数学') == 'math',
                               '封面分配是确定的且认学科',
                               '高等数学 -> %s' % _a))
        # 深浅底图必须配不同颜色的标题：写死一个颜色，深底图上就是一团黑。
        _dark = _cv.pixmap('cosmos')
        _light = _cv.pixmap('lit')
        results.append(_report(_cv.is_dark('cosmos', _dark)
                               and not _cv.is_dark('lit', _light),
                               '封面深浅判定分得开',
                               'cosmos %.0f / lit %.0f'
                               % (_cv.band_luminance('cosmos', _dark),
                                  _cv.band_luminance('lit', _light))))

        # 设置必须能读能写（用的是真实配置目录，所以只读一次、不改内容）
        s = store.Settings()
        results.append(_report(isinstance(s.get('workers'), int),
                               '设置可读取（workers=%s）' % s.get('workers')))
        results.append(_report(store.Library() is not None, '书库可读取'))
        results.append(_report(store.data_dir() != '', '配置目录 = %s'
                               % store.data_dir()))

        # 登录页：两个模式都要能构造
        try:
            win.login.set_mode('token', animate=False)
            app.processEvents()
            win.grab()
            win.login.token.set_token(
                'eyJhbGciOiJSUzI1NiJ9.eyJleHAiOjQxMDc0NDAwMDB9.sig')
            app.processEvents()
            _ok_token = win.login.mode() == 'token'
            win.login.set_mode('sso', animate=False)
            app.processEvents()
            _ok_sso = win.login.mode() == 'sso'
            results.append(_report(_ok_token and _ok_sso,
                                   '登录页两个模式都可切换'))
            results.append(_report(win.root_stack.count() == 2,
                                   '登录页/主界面两页都在'))
            win.root_stack.setCurrentIndex(1)
            win.login.set_mode('token', animate=False)
            app.processEvents()

            # 续期回来要自动接上失败的任务。这条也顺便证明打包出来的
            # shell 是新的，不是上一版的缓存。
            _seen = []
            _orig_retry = win._retry_failed
            try:
                win._retry_failed = lambda: _seen.append(1)
                win._resume_pending = True
                win._resume_count = 0
                win._maybe_resume()
                app.processEvents()
                results.append(_report(_seen == [1],
                                       'Token 续期后自动重试失败的任务'))
                win._resume_pending = False
                win._maybe_resume()
                app.processEvents()
                results.append(_report(_seen == [1],
                                       '  普通登录不会去动队列'))
            finally:
                win._retry_failed = _orig_retry
                win._resume_pending = False

            # 侧边栏底部要显示当前账号（也是「打包的不是旧 bundle」的证据）
            _tok = '%s.%s.s' % (_seg({'alg': 'RS256'}),
                                _seg({'iat': int(_now),
                                      'exp': int(_now + 3780),
                                      'userName': '测试账号'}))
            # 只改内存里的值，不 save()，所以不会动到用户真实的 config.json
            _saved = win.settings.get('token') or ''
            try:
                win.settings.update(token=_tok)
                win._sync_sidebar()
                app.processEvents()
                _chip = win.sidebar.status_chip
                results.append(_report(_chip._title == '测试账号',
                                       '侧边栏显示当前账号',
                                       '标题=%r 副标题=%r'
                                       % (_chip._title, _chip._sub)))
                results.append(_report('还剩' in _chip._sub,
                                       '  副标题是剩余时间：%s' % _chip._sub))
            finally:
                win.settings.update(token=_saved)
                win._sync_sidebar()

            # 队列里点删除。JobRow 的悬停图标是自绘的，曾经只画不算命中，
            # 点上去完全没反应 —— 这条守住那个回归。
            try:
                from PyQt6.QtCore import QEvent, QPointF, Qt
                from PyQt6.QtGui import QMouseEvent

                win.queue.add(['https://example.invalid/x'])
                win.queue_view.set_jobs(win.queue.snapshot())
                app.processEvents()
                _job = win.queue.snapshot()[-1]
                _row = win.queue_view._rows[id(_job)]
                _row.resize(600, 64)
                app.processEvents()
                _pos = QPointF(_row._buttons()[1].center())
                _row._hover = True
                _row.mouseReleaseEvent(QMouseEvent(
                    QEvent.Type.MouseButtonRelease, _pos,
                    Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier))
                app.processEvents()
                _gone = _job not in win.queue.snapshot()
                results.append(_report(_gone, '队列行点删除真的能删掉'))
                win.queue.clear_finished()
            except Exception as e:                                   # noqa: BLE001
                results.append(_report(False, '队列行点删除', str(e)))

            # 天幕动画在有内嵌浏览器时必须停：它曾吃掉主线程 50%~74% 的 CPU，
            # 把浏览器输入挤成「点一下等 3 秒」。
            try:
                _sky = win.login.brand.sky
                if _sky._timer is None:
                    results.append(_report(True, '天幕动画开关（当前 motion 关闭）'))
                else:
                    win.root_stack.setCurrentWidget(win.login)
                    app.processEvents()
                    win.login.set_mode('sso', animate=False, start=False)
                    app.processEvents()
                    _off = not _sky._timer.isActive()
                    win.login.set_mode('token', animate=False)
                    app.processEvents()
                    _on = _sky._timer.isActive()
                    results.append(_report(_off, 'SSO 模式天幕动画停住（不抢 CPU）'))
                    results.append(_report(_on, '  切到 Token 模式动画自己回来'))
                    win.login.set_mode('sso', animate=False, start=False)
            except Exception as e:                                   # noqa: BLE001
                results.append(_report(False, '天幕动画开关', str(e)))
        except Exception as e:                                       # noqa: BLE001
            results.append(_report(False, '登录页构造', str(e)))

        from crawler.gui import theme as T
        results.append(_report(win.sidebar.width() == T.SIDEBAR_W,
                               '侧边栏 = %dpx' % T.SIDEBAR_W,
                               '实际 %d' % win.sidebar.width()))

        # 登录卡片不能挂 QGraphicsEffect —— 里面装着 QWebEngineView，挂上去
        # 会让浏览器每一帧都走离屏重绘（详见 widgets.render_shadow 的说明）
        try:
            results.append(_report(win.login.card.graphicsEffect() is None,
                                   '登录卡片没有 QGraphicsEffect'))
            _ml, _mt, _mr, _mb = win.login.card.shadow_margins()
            results.append(_report(_ml > 0 and _mb > _mt,
                                   '登录卡片投影自绘且留了边距',
                                   '左%d 上%d 右%d 下%d' % (_ml, _mt, _mr, _mb)))
        except Exception as e:                                           # noqa: BLE001
            results.append(_report(False, '登录卡片投影', str(e)))

        # 可见卡面要能长到上限：窗口最大化时内嵌浏览器不能被挤成手机版。
        #
        # 量之前必须**先把登录页切到前台**：不在前台时它保留的是上一次布局的
        # 几何，量出来会正好等于 CARD_MIN_W。这个坑真实踩过 —— 上面「天幕动画
        # 开关」那条分支因为「有底图时没有定时器」而走了另一条路，登录页就没被
        # 切到前台，这里立刻从 520 掉成 340。检查不该依赖前面的分支走哪条。
        try:
            _w0, _h0 = win.width(), win.height()
            win.root_stack.setCurrentWidget(win.login)
            win.resize(1706, 913)
            app.processEvents()
            _ml, _mt, _mr, _mb = win.login.card.shadow_margins()
            _face = win.login.card.width() - _ml - _mr
            results.append(_report(_face >= _login_mod.CARD_MAX_W,
                                   '宽窗口时卡面长到 %dpx'
                                   % _login_mod.CARD_MAX_W,
                                   '实际 %d' % _face))
            win.resize(_w0, _h0)
            app.processEvents()
        except Exception as e:                                           # noqa: BLE001
            results.append(_report(False, '登录卡片宽度', str(e)))

        # 退出登录必须换一代浏览器 profile，否则「退出」后还是已登录界面。
        #
        # 这里只验逻辑，绝对不能真调 reset_session()：它会 save() 真实配置，
        # 还会把用户真实的 webprofile 目录删掉。真正的副作用由
        # tests/smoke_login.py 第 13 节在隔离目录里验。
        try:
            _g0 = int(win.settings.get('webprofile_gen') or 0)
            _d0 = _login_mod._profile_dir(win.settings)
            win.settings.update(webprofile_gen=_g0 + 1)
            _d1 = _login_mod._profile_dir(win.settings)
            win.settings.update(webprofile_gen=_g0)          # 内存还原
            results.append(_report(_d1 != _d0,
                                   '退出登录会换一代浏览器 profile 目录',
                                   '%s -> %s' % (os.path.basename(_d0),
                                                 os.path.basename(_d1))))
            results.append(_report(win.login.sso._suppress_capture is False,
                                   '  面板默认不在「抑制截 Token」状态'))
        except Exception as e:                                           # noqa: BLE001
            results.append(_report(False, '退出登录逻辑', str(e)))

        # 天幕四变体
        for v in T.SKY_VARIANTS:
            win.sidebar.set_variant(v)
            app.processEvents()
            win.grab()
        results.append(_report(True, '天幕四个变体全部渲染'))

        # 引擎可导入、路径工具可用
        from crawler.core import engine
        results.append(_report(callable(engine.download_all), 'engine 可导入'))
        results.append(_report(engine.IMG_SUFFIXES == ['jpeg', 'jpg', 'png'],
                               '图片后缀白名单正确'))

        # 真正跑一遍「图片 -> PDF -> 封面」。
        # 光 import fitz 不够：冻结环境里 PyMuPDF 缺 DLL/数据文件时 import
        # 照样成功，要到写 PDF 那一刻才炸。这条是下载链路最核心的一步。
        try:
            import tempfile
            import threading

            from PIL import Image

            work = tempfile.mkdtemp(prefix='xkc_selftest_')
            pages = []
            for i in range(3):
                p = os.path.join(work, 'p%d.jpg' % i)
                Image.new('RGB', (600, 800), (250, 248, 245)).save(p, quality=80)
                pages.append(p)

            pdf = os.path.join(work, 'book.pdf')
            engine.images_to_pdf(pages, pdf, 10, False, threading.Event())
            n = engine.pdf_page_count(pdf)
            results.append(_report(os.path.exists(pdf) and n == 3,
                                   'fitz 可写 PDF 并读回页数', '页数 %s' % n))

            cover = os.path.join(work, 'cover.jpg')
            ok_cover = engine.make_thumbnail(pdf, cover, width=280)
            width = 0
            if ok_cover and os.path.exists(cover):
                with Image.open(cover) as im:
                    width = im.size[0]
            results.append(_report(bool(ok_cover) and width == 280,
                                   'PIL 可生成 280px 封面', '实际宽 %s' % width))
        except Exception as e:                                       # noqa: BLE001
            import traceback
            _say(traceback.format_exc())
            results.append(_report(False, '图片->PDF->封面 往返', str(e)))
    except Exception as e:                                           # noqa: BLE001
        import traceback
        _say(traceback.format_exc())
        results.append(_report(False, '窗口构造', str(e)))

    # 最要紧的一条：自检绝不能写用户的真实配置、也不能删用户的真实目录。
    #
    # 写配置：没有任何正当理由，被拦下就是 bug，算失败。
    # 删目录：Token 过期时窗口启动会正常走一次退出登录，那次清理会被拦下 ——
    #   属于预期内，把次数打出来备查即可，不能因此判失败（否则用户 Token 一
    #   过期，安装后自检就报 FAIL，看着像装坏了）。
    results.append(_report(not _BLOCKED_SAVES, '自检没有写用户真实配置',
                           '被拦下 %d 次' % len(_BLOCKED_SAVES)))
    results.append(_report(True, '自检没有删用户真实目录',
                           '已拦下 %d 次（Token 过期会触发退出登录清理）'
                           % len(_BLOCKED_DELETES)))

    passed = sum(1 for r in results if r)
    _say('')
    _say('SELFTEST %s (%d/%d)' % ('PASS' if all(results) else 'FAIL',
                                  passed, len(results)))
    report = _write_report()
    _say('report -> %s' % report)
    return 0 if all(results) else 1

if __name__ == '__main__':
    sys.exit(run_selftest())
