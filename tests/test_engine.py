# coding:utf-8
"""
离线端到端测试：用假教参平台跑通 解析 -> 下载 -> 合成 PDF -> 清理 的全流程，
顺带验证断点续传和停止。不联网。
"""
import io
import os
import re
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

import requests  # noqa: E402
from PIL import Image  # noqa: E402

from crawler.core import engine  # noqa: E402

CHAPTERS = 3
PAGES_PER_CHAPTER = 4
TOTAL = CHAPTERS * PAGES_PER_CHAPTER

# bookDetail/<view> -> 平台里的 READURL 与书名，用来模拟「不同的书」
VIEW_TO_BOOK = {
    'VIEW1': 'REALBOOK123',
    'AAA111': 'REALBOOKAAA',
    'BBB222': 'REALBOOKBBB',
}
BOOK_TITLES = {
    'VIEW1': '大学俄语1（新版）',
    'AAA111': '大学俄语1（新版）',
    'BBB222': '高等数学 上册',
}


def make_jpeg(w=600, h=800, color=(200, 200, 210)):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), color).save(buf, 'JPEG')
    return buf.getvalue()


class FakeResponse:
    def __init__(self, *, json_data=None, content=b'', text='', status=200,
                 headers=None, cookies=None):
        self._json = json_data
        self.content = content
        self.text = text
        self.status_code = status
        self.headers = headers or {}
        self.cookies = cookies or {}

    def json(self):
        if self._json is None:
            raise ValueError('not json')
        return self._json


class FakeCookies(dict):
    def get(self, k, default=None):
        return dict.get(self, k, default)


def build_fakes(state):
    """state 里记录每次请求，方便断言。"""

    def fake_get(url, **kw):
        state.setdefault('gets', []).append(url)
        if 'getBookDetail' in url:
            # 按 bookId 区分不同的书：批量下载要验证「两本书各自独立」，
            # 如果所有链接都解析成同一个书号就测不出东西。
            m = re.search(r'bookId=([^&]+)', url)
            view = m.group(1) if m else 'VIEW1'
            book_id = VIEW_TO_BOOK.get(view, 'REALBOOK123')
            return FakeResponse(json_data={'data': {'jc_ebook_vo': {
                # 平台上真实字段名不完全确定，这里混着放几个常见写法，
                # 用来验证 parse_book_meta 能挑出来
                'BOOKNAME': BOOK_TITLES.get(view, '大学俄语1（新版）'),
                'author': '史铁强',
                'PUBLISHER': '外语教学与研究出版社',
                'PUBLISHDATE': '2019-08-01',
                'ISBN': '9787513590123',
                'urls': [{'READURL': book_id}]}}})
        if url == 'https://fake.access/redirect':
            return FakeResponse(
                status=302,
                headers={'Location': 'https://ereserves.lib.tsinghua.edu.cn/read/index'},
                cookies=FakeCookies({'BotuReadKernel': 'KERNEL-TOKEN'}))
        if 'read/index' in url:
            return FakeResponse(text='<input type="hidden" id="scanid" '
                                     'name="scanid" value="SCAN-1">')
        if 'DownJPGJsNetPage' in url:
            state['downloads'] = state.get('downloads', 0) + 1
            # 颜色随 filePath 变，保证不同书的页面内容确实不同
            seed = sum(ord(c) for c in url) % 200
            return FakeResponse(content=make_jpeg(color=(120 + seed % 80,
                                                         130, 190)))
        raise AssertionError('unexpected GET %s' % url)

    def fake_post(url, **kw):
        state.setdefault('posts', []).append(url)
        if 'GetResourcesUrl' in url:
            return FakeResponse(json_data={'data': 'https://fake.access/redirect'})
        if 'selectJgpBookChapters' in url:
            return FakeResponse(json_data={'data': [{'EMID': 'EM%d' % i}
                                                    for i in range(CHAPTERS)]})
        if 'selectJgpBookChapter' in url:
            emid = kw.get('data', {}).get('EMID', 'EM0')
            n = int(emid.replace('EM', ''))
            return FakeResponse(json_data={'data': {'JGPS': [
                {'hfsKey': 'CH%d/PAGE%d.jpg' % (n, p)} for p in range(PAGES_PER_CHAPTER)]}})
        raise AssertionError('unexpected POST %s' % url)

    session_get = lambda self, url, **kw: fake_get(url, **kw)          # noqa: E731
    session_post = lambda self, url, **kw: fake_post(url, **kw)        # noqa: E731
    return fake_get, fake_post, session_get, session_post


def patch(fake_get, fake_post, session_get, session_post):
    requests.get = fake_get
    requests.post = fake_post
    requests.Session.get = session_get
    requests.Session.post = session_post


def main():
    tmp = tempfile.mkdtemp(prefix='xkc_test_')
    ok = True
    try:
        state = {}
        fg, fp, sg, sp = build_fakes(state)
        patch(fg, fp, sg, sp)

        cancel = threading.Event()
        logs = []

        # ---- 1 解析
        # 按字段名取。这里以前是位置解包，v3.0 加 meta 时有一处调用漏改，
        # 变成一颗「一被调用就 ValueError」的哑弹（见 engine.BookRef 的说明）。
        ref = engine.resolve_book(
            'https://x/bookDetail/VIEW1', 'TOKEN', log=logs.append)
        kernel, book_id, scan, meta = (
            ref.kernel, ref.book_real_id, ref.scan_id, ref.meta)
        assert ref._fields == ('kernel', 'book_real_id', 'scan_id', 'meta'), ref._fields
        assert kernel == 'KERNEL-TOKEN' and book_id == 'REALBOOK123' and scan == 'SCAN-1', \
            (kernel, book_id, scan)
        assert meta['title'] == '大学俄语1（新版）', meta
        assert meta['author'] == '史铁强', meta
        assert meta['publisher'] == '外语教学与研究出版社', meta
        assert meta['year'] == '2019', meta
        assert meta['isbn'] == '9787513590123', meta
        print('[1] resolve_book ok -> %s / %s' % (book_id, meta['title']))

        # ---- 1b 所有调用方都必须按名字取字段
        #
        # 为什么值得单测一条「代码长相」：resolve_book 的返回值在 v3.0 多了一个
        # meta，四个调用方分两批改的，worker.py 那一处漏了，写成
        # `a, b, c = engine.resolve_book(...)` —— 语法完全合法、测试也照过，
        # 但只要那个 worker 被真正跑一次就 ValueError。
        # 具名返回 + 这条断言把这类错位挡在门口。
        import re as _re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        callers = ('crawler/core/queue.py', 'crawler/core/cli.py',
                   'crawler/core/worker.py', 'crawler/core/engine.py')
        bad = []
        for rel in callers:
            with open(os.path.join(root, rel), 'r', encoding='utf-8') as fh:
                src = fh.read()
            # 只抓「左边是一串裸名字」（有逗号）的位置解包；
            # `ref = engine.resolve_book(...)` 这种单变量赋值是正确的用法
            for m in _re.finditer(r'^\s*[A-Za-z_]\w*\s*,\s*[A-Za-z_][\w,\s]*?'
                                  r'=\s*(?:engine\.)?resolve_book\(', src, _re.M):
                bad.append('%s: %s' % (rel, m.group(0).strip()))
        assert not bad, (
            '这些调用方还在按位置解包 resolve_book 的返回值，'
            '必须改用 .kernel / .book_real_id / .scan_id / .meta：%s' % bad)
        print('[1b] resolve_book 的调用方都按字段名取值（%d 处检查通过）'
              % len(callers))

        # ---- 2 章节 / 页
        emids = engine.fetch_chapters(kernel, scan, log=logs.append)
        page_urls = engine.fetch_page_urls(kernel, book_id, emids, log=logs.append)
        total = sum(len(x) for x in page_urls)
        assert len(emids) == CHAPTERS and total == TOTAL, (len(emids), total)
        print('[2] chapters=%d pages=%d ok' % (len(emids), total))

        # ---- 3 下载
        save_dir = os.path.join(tmp, 'downloads', book_id)
        prog = []
        done, failed, skipped = engine.download_all(
            kernel, page_urls, save_dir, 4, cancel,
            on_progress=lambda d, t, f: prog.append((d, t, f)), log=logs.append)
        files = sorted(os.listdir(save_dir))
        assert done == TOTAL and failed == 0, (done, failed)
        assert len([f for f in files if f.endswith('.jpg')]) == TOTAL, files
        assert not [f for f in files if f.startswith('.tmp')], files
        assert prog[-1] == (TOTAL, TOTAL, 0), prog[-1]
        print('[3] download ok  done=%d failed=%d files=%d' % (done, failed, len(files)))

        # ---- 4 断点续传：再跑一次应全部跳过
        state['downloads'] = 0
        done2, failed2, skipped2 = engine.download_all(
            kernel, page_urls, save_dir, 4, cancel, log=logs.append)
        assert done2 == 0 and skipped2 == TOTAL, (done2, skipped2)
        assert state['downloads'] == 0, state['downloads']
        print('[4] resume ok  skipped=%d new_requests=%d' % (skipped2, state['downloads']))

        # ---- 5 合成 PDF
        imgs = engine.list_images(save_dir)
        assert len(imgs) == TOTAL, len(imgs)
        assert os.path.basename(imgs[0]) == '0_0.jpg', imgs[0]
        assert os.path.basename(imgs[-1]) == '2_3.jpg', imgs[-1]
        pdf = os.path.join(save_dir, book_id + '.pdf')
        conv = []
        engine.images_to_pdf(imgs, pdf, 10, False, cancel,
                             on_progress=lambda d, t: conv.append((d, t)),
                             log=logs.append)
        assert os.path.exists(pdf) and os.path.getsize(pdf) > 1000
        import fitz
        with fitz.open(pdf) as doc:
            n = doc.page_count
        assert n == TOTAL, (n, TOTAL)
        assert conv[-1] == (TOTAL, TOTAL), conv[-1]
        assert not os.path.exists(os.path.join(save_dir, 'intermediate'))
        print('[5] pdf ok  pages=%d size=%d bytes' % (n, os.path.getsize(pdf)))

        # ---- 6 停止：取消后应抛 Cancelled，且不产生临时文件
        save2 = os.path.join(tmp, 'downloads2')
        cancel2 = threading.Event()
        cancel2.set()
        try:
            engine.download_all(kernel, page_urls, save2, 2, cancel2, log=logs.append)
            print('[6] FAIL: cancel did not raise')
            ok = False
        except engine.Cancelled:
            leftovers = os.listdir(save2) if os.path.isdir(save2) else []
            assert not [f for f in leftovers if f.startswith('.tmp')], leftovers
            print('[6] cancel ok  leftovers=%d' % len(leftovers))

        # ---- 7 book_info（GUI 的「校验 token」走这条）
        info = engine.book_info('https://x/bookDetail/VIEW1', 'TOKEN', log=logs.append)
        assert info['chapters'] == CHAPTERS and info['pages'] == TOTAL, info
        print('[7] book_info ok ->', {k: info[k] for k in ('chapters', 'pages')})

        # ---- 8 错误路径：token 失效
        requests.get = lambda url, **kw: (
            FakeResponse(json_data={'data': None}) if 'getBookDetail' in url
            else fg(url, **kw))
        try:
            engine.resolve_book('https://x/bookDetail/VIEW1', 'BAD', log=logs.append)
            print('[8] FAIL: bad token accepted')
            ok = False
        except ValueError as e:
            assert 'Token' in str(e), e
            print('[8] bad token rejected ok ->', e)

        print('\nE2E %s' % ('PASS' if ok else 'FAIL'))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())