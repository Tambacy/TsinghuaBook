# coding:utf-8
"""
工作线程测试：把 worker.py 里那两个 QThread worker 真正跑一遍。

为什么单独有这一块：worker.py 的 DownloadWorker 从来没被 GUI 用过
（界面走的是 core.queue.QueueManager），于是它长期是一段「没有任何调用方、
也没有任何测试」的代码 —— 而它恰恰藏着 v3.0 的一颗哑弹：

    kernel, book_real_id, scan_id = engine.resolve_book(...)   # 返回的是 4 个值

语法合法、import 也不会报错，只有真被跑一次才 ValueError。所以这里不测
「代码长相」，而是真的把 run() 跑完，让它自己证明能通。

全程离线：复用 test_engine 的假教参平台。不联网、不碰真实用户目录。
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

from tests._isolate import isolate  # noqa: E402

_CFG = isolate()

from PyQt6.QtWidgets import QApplication  # noqa: E402

from tests.test_engine import build_fakes, patch  # noqa: E402

fails = []


def check(cond, msg):
    print(('  OK  ' if cond else '  FAIL') + '  ' + msg, flush=True)
    if not cond:
        fails.append(msg)


def main():
    app = QApplication(sys.argv)                                       # noqa: F841
    tmp = tempfile.mkdtemp(prefix='xkc_worker_')
    try:
        state = {}
        patch(*build_fakes(state))

        from xk_app.app.core import engine, worker

        # ---------------------------------------------------- DownloadWorker
        print('=== 1. DownloadWorker 全流程（解析 -> 下载 -> PDF）===', flush=True)
        w = worker.DownloadWorker({
            'url': 'https://x/bookDetail/VIEW1',
            'token': 'TOKEN',
            'save_dir': tmp,
            'workers': 4,
            'quality': 10,
            'auto_resize': False,
            'del_img': False,
        })
        got = {'ok': [], 'failed': [], 'stages': [], 'logs': [], 'stopped': []}
        w.finished_ok.connect(got['ok'].append)
        w.failed.connect(lambda a, b: got['failed'].append((a, b)))
        w.stage_changed.connect(lambda k, t: got['stages'].append(k))
        w.log.connect(lambda m, lvl: got['logs'].append(m))
        w.stopped.connect(lambda: got['stopped'].append(True))

        # 同步直调 run()：这里要验的是「这条代码路径能不能跑通」，
        # 不是 Qt 的线程调度，所以不必绕 QThread
        w.run()

        check(not got['failed'],
              '没有报错（失败项 %d）' % len(got['failed']))
        if got['failed']:
            print(got['failed'][0][1], flush=True)
        check(len(got['ok']) == 1, 'finished_ok 触发了一次')
        if got['ok']:
            res = got['ok'][0]
            check(res['pages'] == 12, '页数 = %d' % res['pages'])
            check(res['downloaded'] == 12, '下载了 %d 张' % res['downloaded'])
            check(res['failed'] == 0, '失败 %d 张' % res['failed'])
            check(os.path.exists(res['pdf_path']), 'PDF 真的生成了')
            check(res['total_bytes'] > 0, 'PDF 非空（%d 字节）' % res['total_bytes'])

        # 阶段顺序：解析 -> 章节 -> 下载 -> 合成 -> 完成
        stages = [s for s in got['stages']]
        check(stages[:2] == ['resolve', 'chapters'], '阶段顺序 %s' % stages[:2])
        check('download' in stages and 'convert' in stages and stages[-1] == 'done',
              '阶段走完：%s' % stages)

        # 目录结构与 CLI / QueueManager 一致：<save_dir>/<book_id>/<book_id>.pdf
        book_dir = os.path.join(tmp, 'REALBOOK123')
        check(os.path.isdir(book_dir), '落在 <save_dir>/<book_id>/ 下')
        check(os.path.exists(os.path.join(book_dir, 'REALBOOK123.pdf')),
              'PDF 文件名 = <book_id>.pdf')

        # 已存在 PDF 时必须跳过（断点续传的语义）
        print('=== 2. 第二次跑：已下载过应当跳过 ===', flush=True)
        w2 = worker.DownloadWorker({
            'url': 'https://x/bookDetail/VIEW1', 'token': 'TOKEN',
            'save_dir': tmp, 'workers': 4, 'quality': 10,
            'auto_resize': False, 'del_img': False,
        })
        got2 = {'ok': [], 'failed': []}
        w2.finished_ok.connect(got2['ok'].append)
        w2.failed.connect(lambda a, b: got2['failed'].append((a, b)))
        w2.run()
        check(not got2['failed'], '第二次没报错')
        check(got2['ok'] and got2['ok'][0].get('skipped_book') is True,
              '识别为已下载并跳过')

        # ------------------------------------------------ del_img 清理分支
        print('=== 3. del_img=True 时清理临时图片 ===', flush=True)
        w3 = worker.DownloadWorker({
            'url': 'https://x/bookDetail/BBB222', 'token': 'TOKEN',
            'save_dir': tmp, 'workers': 2, 'quality': 10,
            'auto_resize': True, 'del_img': True,
        })
        got3 = {'ok': [], 'failed': []}
        w3.finished_ok.connect(got3['ok'].append)
        w3.failed.connect(lambda a, b: got3['failed'].append((a, b)))
        w3.run()
        check(not got3['failed'], '没报错')
        if got3['failed']:
            print(got3['failed'][0][1], flush=True)
        left = engine.list_images(os.path.join(tmp, 'REALBOOKBBB'))
        check(left == [], '临时图片被清干净（剩 %d 张）' % len(left))

        # -------------------------------------------------- CredCheckWorker
        print('=== 4. CredCheckWorker 只校验不下载 ===', flush=True)
        state['downloads'] = 0
        cw = worker.CredCheckWorker('https://x/bookDetail/VIEW1', 'TOKEN')
        out = {'done': [], 'failed': []}
        cw.done.connect(out['done'].append)
        cw.failed.connect(lambda a, b: out['failed'].append((a, b)))
        cw.run()
        check(not out['failed'], '没报错')
        check(out['done'] and out['done'][0]['pages'] == 12,
              '读到页数 = %s' % (out['done'][0]['pages'] if out['done'] else None))
        check(state.get('downloads', 0) == 0,
              '一张图都没下（校验阶段只读结构，%d 次下载请求）'
              % state.get('downloads', 0))

        # ---------------------------------------------- TaskRunner 收尾
        print('=== 5. TaskRunner 能起线程并收尾 ===', flush=True)
        cw2 = worker.CredCheckWorker('https://x/bookDetail/VIEW1', 'TOKEN')
        out2 = {'done': [], 'failed': []}
        cw2.done.connect(out2['done'].append)
        cw2.failed.connect(lambda a, b: out2['failed'].append((a, b)))
        tr = worker.TaskRunner(cw2)
        tr.start()
        import time
        end = time.time() + 20
        while time.time() < end and not (out2['done'] or out2['failed']):
            app.processEvents()
            time.sleep(0.02)
        check(bool(out2['done']), '线程里跑完并回到主线程')
        check(tr.running, '线程仍在跑（等调用方 finish）')
        tr.finish()
        app.processEvents()
        check(not tr.running, 'finish() 之后线程退出')

        print('', flush=True)
        print('WORKER %s (%d/%d)'
              % ('PASS' if not fails else 'FAIL',
                 0 if fails else 1, 1), flush=True)
        return 0 if not fails else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
