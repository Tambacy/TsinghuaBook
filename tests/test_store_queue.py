# coding:utf-8
"""
数据层与批处理测试：设置持久化、书库索引、批量下载队列。
全程离线，复用 test_engine 里的假教参平台。
"""
import os
import shutil
import sys
import tempfile
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

# 配置目录隔离：必须在任何 store 读写之前生效，否则会往用户真实的
# %LOCALAPPDATA%\TsinghuaBookCrawler 里塞测试数据。
from tests._isolate import isolate  # noqa: E402

_CFG = isolate()

from tests.test_engine import build_fakes, patch  # noqa: E402

from crawler.core import engine, queue, store  # noqa: E402


def wait_until(fn, timeout=30.0, interval=0.05):
    """轮询等待条件成立，避免依赖固定 sleep。"""
    import time
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(interval)
    return False


def main():
    tmp = tempfile.mkdtemp(prefix='xkc_store_')
    ok = True
    results = []

    def check(cond, label, extra=''):
        results.append(bool(cond))
        print(('  OK   ' if cond else '  FAIL ') + label + (('  ' + extra) if extra else ''))
        return cond

    try:
        # ---------------------------------------------------------- 设置
        cfg_path = os.path.join(tmp, 'config.json')
        s = store.Settings(cfg_path)
        check(s.get('workers') == 4, '默认进程数 4')
        s.token = '  TOKEN-ABC  '
        s.update(workers=99, quality=1, save_dir=os.path.join(tmp, 'dl'))
        s.save()

        s2 = store.Settings(cfg_path)
        check(s2.token == 'TOKEN-ABC', 'token 去空格并持久化', repr(s2.token))
        check(s2.get('workers') == 16, '进程数被夹到上限 16', str(s2.get('workers')))
        check(s2.get('quality') == 3, '质量被夹到下限 3', str(s2.get('quality')))
        check(s2.resolve_save_dir() == os.path.join(tmp, 'dl'), '保存目录持久化')

        # 损坏的配置不该让程序打不开
        with open(cfg_path, 'w', encoding='utf-8') as f:
            f.write('{ this is not json')
        s3 = store.Settings(cfg_path)
        check(s3.get('workers') == 4, '配置损坏时退回默认值')
        check(s3.token == '', '配置损坏时 token 为空而不是崩')

        # ---------------------------------------------------------- 书库
        lib_path = os.path.join(tmp, 'library.json')
        lib = store.Library(lib_path)
        check(lib.all() == [], '空书库')
        rec = store.make_record('BK1', os.path.join(tmp, 'BK1.pdf'),
                                os.path.join(tmp, 'BK1'), url='https://x/b/1',
                                meta={'title': '大学俄语1'}, pages=12, chapters=3)
        lib.upsert(rec)
        check(len(lib.all()) == 1, '写入一条记录')
        check(lib.get('BK1')['title'] == '大学俄语1', '按书号取回')

        # 同一本书重复入库应覆盖而不是新增，且保留最早加入时间
        first_added = lib.get('BK1')['added_at']
        lib.upsert(store.make_record('BK1', os.path.join(tmp, 'BK1.pdf'),
                                     os.path.join(tmp, 'BK1'),
                                     meta={'title': '大学俄语1（新版）'}, pages=14))
        check(len(lib.all()) == 1, '重复入库不产生第二条')
        check(lib.get('BK1')['title'] == '大学俄语1（新版）', '重复入库覆盖标题')
        check(lib.get('BK1')['added_at'] == first_added, '保留最早的加入时间')

        # 重新加载
        lib2 = store.Library(lib_path)
        check(len(lib2.all()) == 1 and lib2.get('BK1')['pages'] == 14, '书库持久化')

        # 断链检测：PDF 不在磁盘上应被标记出来
        missing = lib2.reconcile()
        check(len(missing) == 1, '标出 PDF 已丢失的记录')

        # ---------------------------------------------------------- 链接提取
        pasted = """大学俄语1
        https://ereserves.lib.tsinghua.edu.cn/bookDetail/AAA111
        高等数学 上册 https://ereserves.lib.tsinghua.edu.cn/bookDetail/BBB222。
        https://ereserves.lib.tsinghua.edu.cn/bookDetail/AAA111
        """
        urls = queue.extract_urls(pasted)
        check(len(urls) == 2, '从粘贴文本里提取出去重后的 2 条链接', str(len(urls)))
        check(urls[0].endswith('AAA111'), '第一条正确')
        check(urls[1].endswith('BBB222'), '中文句号被剥掉', urls[1])
        check(queue.extract_urls('') == [], '空文本返回空列表')

        # ---------------------------------------------------------- 批量队列
        state = {}
        fg, fp, sg, sp = build_fakes(state)
        patch(fg, fp, sg, sp)

        dl_root = os.path.join(tmp, 'batch')
        s3.update(save_dir=dl_root, workers=4, quality=8, keep_images=True)
        s3.token = 'TOKEN'
        lib3 = store.Library(os.path.join(tmp, 'library3.json'))

        changes = []
        logs = []
        q = queue.QueueManager(s3, lib3,
                               on_change=lambda: changes.append(1),
                               on_log=lambda m, t='': logs.append(m))
        added = q.add([urls[0], urls[1], urls[0], '', '   '])
        check(added == 2, '入队时去重并忽略空行', 'added=%d' % added)
        check(len(q.snapshot()) == 2, '队列里有 2 本')

        check(q.start() is True, '启动队列')
        done = wait_until(lambda: not q.running, timeout=60)
        check(done, '队列在超时内跑完')

        jobs = q.snapshot()
        check(all(j.state == queue.JobState.DONE for j in jobs),
              '两本都成功', str([j.state for j in jobs]))
        check(all(j.title for j in jobs), '每本都拿到了书名',
              str([j.title for j in jobs]))
        check(all(os.path.exists(j.pdf_path) for j in jobs), 'PDF 都生成了')
        check(all(j.pages == 12 for j in jobs), '页数都是 12',
              str([j.pages for j in jobs]))
        check(q.progress() == 1.0, '整批进度到 1.0', str(q.progress()))
        check(len(lib3.all()) == 2, '书库里有 2 本', str(len(lib3.all())))
        check(all(r.get('cover') and os.path.exists(r['cover'])
                  for r in lib3.all()), '封面缩略图都生成了')
        check(all(r.get('size', 0) > 0 for r in lib3.all()), '记录了文件大小')
        check(all(r.get('added_at') for r in lib3.all()), '记录了加入时间')
        check(len(changes) > 5, '状态变化有回调', 'changes=%d' % len(changes))

        dc, df, left = q.counts()
        check(dc == 2 and df == 0 and left == 0, '统计正确', str((dc, df, left)))

        # ---------------------------------------------------------- 跳过已下载
        q2 = queue.QueueManager(s3, lib3)
        q2.add([urls[0]])
        q2.start()
        wait_until(lambda: not q2.running, timeout=30)
        check(q2.snapshot()[0].state == queue.JobState.SKIPPED,
              '已下载过的书被跳过而不是重复下',
              q2.snapshot()[0].state)

        # ---------------------------------------------------------- 失败与重试
        requests_get_orig = __import__('requests').get
        import requests as _rq

        def bad_get(url, **kw):
            if 'getBookDetail' in url:
                from tests.test_engine import FakeResponse
                return FakeResponse(json_data={'data': None})
            return fg(url, **kw)

        _rq.get = bad_get
        q3 = queue.QueueManager(s3, lib3)
        q3.add([urls[0]])
        q3.start()
        wait_until(lambda: not q3.running, timeout=30)
        j = q3.snapshot()[0]
        check(j.state == queue.JobState.FAILED, 'token 失效时标记失败', j.state)
        check('Token' in j.error, '失败原因可读', j.error)
        n = q3.reset_failed()
        check(n == 1 and q3.snapshot()[0].state == queue.JobState.PENDING,
              '失败可以重新排队')

        # 恢复假平台，重试应当成功（这里已下载过，所以是 SKIPPED）
        _rq.get = fg
        q3.start()
        wait_until(lambda: not q3.running, timeout=30)
        check(q3.snapshot()[0].state == queue.JobState.SKIPPED,
              '重试后正常通过', q3.snapshot()[0].state)

        # ---------------------------------------------------------- 停止
        s3.update(save_dir=os.path.join(tmp, 'batch2'), keep_images=True)
        lib4 = store.Library(os.path.join(tmp, 'library4.json'))
        q4 = queue.QueueManager(s3, lib4)
        q4.add([urls[0], urls[1]])
        q4.start()
        import time
        time.sleep(0.15)
        q4.cancel()
        wait_until(lambda: not q4.running, timeout=30)
        states = [x.state for x in q4.snapshot()]
        check(not any(x.active for x in q4.snapshot()),
              '停止后没有还在跑的', str(states))
        check(all(x.state in (queue.JobState.CANCELLED, queue.JobState.DONE,
                              queue.JobState.SKIPPED,
                              queue.JobState.FAILED) for x in q4.snapshot()),
              '停止后状态都是终态', str(states))

        # ---------------------------------------------------------- 没有 token
        s5 = store.Settings(os.path.join(tmp, 'cfg5.json'))
        q5 = queue.QueueManager(s5, store.Library(os.path.join(tmp, 'lib5.json')))
        q5.add([urls[0]])
        q5.start()
        wait_until(lambda: not q5.running, timeout=15)
        check(q5.snapshot()[0].state == queue.JobState.FAILED,
              '没设 token 时给出明确失败')
        check('token' in q5.snapshot()[0].error.lower(),
              '提示指向设置里的 token', q5.snapshot()[0].error)

        # ---------------------------------------------------------- 导入已有下载
        lib6 = store.Library(os.path.join(tmp, 'library6.json'))
        n = lib6.import_existing(dl_root)
        check(n >= 1, '扫描保存目录能把没索引的书补进书库', 'imported=%d' % n)
        n2 = lib6.import_existing(dl_root)
        check(n2 == 0, '重复扫描不会重复导入', 'second=%d' % n2)

        print('\nSTORE/QUEUE %s (%d/%d)'
              % ('PASS' if all(results) else 'FAIL',
                 sum(1 for r in results if r), len(results)))
        return 0 if ok and all(results) else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
