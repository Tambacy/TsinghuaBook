# coding:utf-8
"""
下载引擎：把原来 CLI 的流程搬到 Qt 线程里，并把进度吐出来。

为什么没有直接复用 download_imgs.download_imgs()：
  它内部调用 signal.signal(SIGINT/SIGTERM)，而 signal 只能在主线程注册，
  在工作线程里会直接抛 ValueError。所以这里用 ThreadPoolExecutor 重写了一遍，
  下载逻辑（URL 模板、.tmp 原子改名、断点续传跳过已存在文件）与原版一致。
"""
import os
import random
import re
import threading
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# 与 utils.IMG_SUFFIXES 保持一致
IMG_SUFFIXES = ['jpeg', 'jpg', 'png']

CHUNK = 1

# requests.Session 不是线程安全的，所以每个工作线程各持一个。
_local = threading.local()


def thread_session():
    s = getattr(_local, 'session', None)
    if s is None:
        s = requests.Session()
        _local.session = s
    return s


class Cancelled(Exception):
    """用户点了停止。"""


def _randstr(n):
    h = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    return ''.join(random.choice(h) for _ in range(n))


# ------------------------------------------------------------------ 元数据
# getBookDetail 返回的 jc_ebook_vo 里字段很多，但具体叫什么名字我们不掌握全。
# 书库要显示书名/作者/出版社，所以按常见写法逐个试，全都拿不到就退回
# READURL（历史上它就是书名），保证任何情况下都有东西可显示。
_TITLE_KEYS = ('BOOKNAME', 'bookName', 'BOOK_NAME', 'TITLE', 'title',
               'NAME', 'name', 'EBOOKNAME', 'ebookName')
_AUTHOR_KEYS = ('AUTHOR', 'author', 'BOOKAUTHOR', 'bookAuthor', 'WRITER', 'writer')
_PUBLISHER_KEYS = ('PUBLISHER', 'publisher', 'PRESS', 'press', 'PUBLISHERNAME')
_YEAR_KEYS = ('PUBLISHYEAR', 'publishYear', 'YEAR', 'year', 'PUBLISHDATE', 'publishDate')
_ISBN_KEYS = ('ISBN', 'isbn', 'ISBNCODE')
_COVER_KEYS = ('COVER', 'cover', 'COVERURL', 'coverUrl', 'COVER_IMG',
               'IMGURL', 'imgUrl', 'PICURL', 'picUrl', 'THUMBNAIL')


def _first_str(node, keys):
    """在 dict 里按候选键名找第一个非空字符串；找不到返回 ''。"""
    if not isinstance(node, dict):
        return ''
    for k in keys:
        v = node.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
    return ''


def _guess_year(node):
    """出版年可能混在日期字符串里，取开头四位数字。"""
    raw = _first_str(node, _YEAR_KEYS)
    m = re.match(r'\s*(\d{4})', raw)
    return m.group(1) if m else ''


def parse_book_meta(payload):
    """
    从 getBookDetail 的响应里尽力提取书籍信息。

    刻意写成「拿不到就算了」：这些字段是锦上添花，缺任何一个都不该让
    下载流程失败。返回的 dict 里空字符串表示没取到，调用方自己兜底。
    """
    meta = {'title': '', 'author': '', 'publisher': '', 'year': '',
            'isbn': '', 'cover_url': ''}
    try:
        vo = payload['data']['jc_ebook_vo']
    except (TypeError, KeyError):
        return meta
    if not isinstance(vo, dict):
        return meta

    for key, cands in (('title', _TITLE_KEYS), ('author', _AUTHOR_KEYS),
                       ('publisher', _PUBLISHER_KEYS), ('isbn', _ISBN_KEYS),
                       ('cover_url', _COVER_KEYS)):
        meta[key] = _first_str(vo, cands)
    meta['year'] = _guess_year(vo)

    # 有些实现把书信息放在 urls[0] 那一层
    urls = vo.get('urls')
    if isinstance(urls, list) and urls and isinstance(urls[0], dict):
        row = urls[0]
        for key, cands in (('title', _TITLE_KEYS), ('author', _AUTHOR_KEYS),
                           ('publisher', _PUBLISHER_KEYS)):
            if not meta[key]:
                meta[key] = _first_str(row, cands)
    return meta


# resolve_book 的返回值。具名字段，调用方按名字取，不靠「记住是几个值」。
BookRef = namedtuple('BookRef', 'kernel book_real_id scan_id meta')


def resolve_book(url, token, log=None):
    """
    取 botu_read_kernel / book_real_id / scan_id，外加书籍元信息。

    返回 BookRef（具名字段），字段是：
        kernel / book_real_id / scan_id / meta
    meta 见 parse_book_meta，拿不到就是空串。

    为什么用 namedtuple 而不是普通元组：以前给它加 meta 的时候，调用方
    分两批改的，漏掉了一处仍然按三个值解包 —— 那是一颗一旦被调用就
    立刻 ValueError 的哑弹，而且没有任何测试覆盖得到（见 README「返回值的
    具名化」）。具名字段之后，取用一律走 .kernel / .meta，
    再也不会因为「谁记得是几个值」而错位。
    """
    def say(msg):
        if log:
            log(msg)

    book_view_id = url.strip().rstrip('/').split('/')[-1].split('?')[0]
    if not book_view_id:
        raise ValueError('无法从链接中解析出 bookId，请检查链接。')

    say('正在校验 Token ...')
    detail_url = ('https://ereserves.lib.tsinghua.edu.cn/userapi/'
                  'MyBook/getBookDetail?bookId=%s' % book_view_id)
    res = requests.get(detail_url, headers={'Jcclient': token}, timeout=30)
    try:
        payload = res.json()
    except ValueError:
        raise ValueError('教参平台返回了非 JSON 内容，可能是网络或认证问题。')
    # 用真·过期 Token 打过服务器，它返回的是：
    #   HTTP 200  {"code": -21, "effTime": null, "data": null, "info": "认证过期"}
    # 注意状态码是 200 而不是 401 —— 想靠 res.status_code 判断认证失败
    # 会静默漏掉。真正可靠的信号是 data 为 null。
    # 界面上的「Token 失效自动重新获取」也依赖下面这句文案里的
    # 'Token 不正确或已过期' 子串，改文案要一起改 shell._watch_for_expiry。
    if payload.get('data') is None:
        raise ValueError('Token 不正确或已过期，请重新获取。')

    urls = payload['data']['jc_ebook_vo']['urls']
    if not urls:
        raise ValueError('这本书没有可用的阅读链接。')
    book_real_id = urls[0]['READURL']
    meta = parse_book_meta(payload)
    # READURL 历史上就是书名，拿不到结构化标题时用它兜底
    if not meta['title']:
        meta['title'] = book_real_id

    say('正在获取阅读凭证 ...')
    res = requests.post('https://ereserves.lib.tsinghua.edu.cn/userapi/ReadBook/GetResourcesUrl',
                        json={'id': book_real_id}, headers={'Jcclient': token}, timeout=30)
    book_access_url = res.json()['data']
    res = requests.get(book_access_url, allow_redirects=False, timeout=30)
    cookies = res.cookies
    botu_read_kernel = cookies.get('BotuReadKernel')
    if not botu_read_kernel:
        raise ValueError('未能取得 BotuReadKernel，Token 可能无效。')
    location = res.headers.get('Location')
    if not location:
        raise ValueError('阅读页跳转地址缺失。')
    res = requests.get(location, cookies=cookies, timeout=30)
    m = re.search(r'<input type="hidden" id="scanid" name="scanid" value="([^"]+)">', res.text)
    if not m:
        raise ValueError('未能在阅读页中找到 scanid。')
    return BookRef(botu_read_kernel, book_real_id, m.group(1), meta)


def fetch_chapters(botu_read_kernel, scan_id, log=None):
    res = requests.post('https://ereserves.lib.tsinghua.edu.cn/readkernel/KernelAPI/BookInfo/selectJgpBookChapters',
                        headers={'BotuReadKernel': botu_read_kernel},
                        data={'SCANID': scan_id}, timeout=60)
    data = res.json()['data']
    emids = [x['EMID'] for x in data]
    if log:
        log('识别到 %d 个章节' % len(emids))
    return emids


def fetch_page_urls(botu_read_kernel, book_real_id, emids, log=None):
    url = 'https://ereserves.lib.tsinghua.edu.cn/readkernel/KernelAPI/BookInfo/selectJgpBookChapter'
    page_urls = []
    for i, emid in enumerate(emids):
        res = requests.post(url, headers={'BotuReadKernel': botu_read_kernel},
                            data={'EMID': emid, 'BOOKID': book_real_id}, timeout=60)
        page_urls.append([x['hfsKey'] for x in res.json()['data']['JGPS']])
        if log:
            log('章节 %d/%d：%d 页' % (i + 1, len(emids), len(page_urls[-1])))
    return page_urls


def book_info(url, token, log=None):
    """校验 token 用：拿到书籍信息与每章页数，不下载。"""
    ref = resolve_book(url, token, log=log)
    kernel, book_real_id, scan_id, meta = (
        ref.kernel, ref.book_real_id, ref.scan_id, ref.meta)
    emids = fetch_chapters(kernel, scan_id, log=log)
    total = 0
    for emid in emids:
        res = requests.post('https://ereserves.lib.tsinghua.edu.cn/readkernel/KernelAPI/BookInfo/selectJgpBookChapter',
                            headers={'BotuReadKernel': kernel},
                            data={'EMID': emid, 'BOOKID': book_real_id}, timeout=60)
        total += len(res.json()['data']['JGPS'])
    return {
        'kernel': kernel,
        'book_real_id': book_real_id,
        'scan_id': scan_id,
        'chapters': len(emids),
        'pages': total,
        'meta': meta,
    }


# ------------------------------------------------------------------ 图片下载
def build_tasks(page_urls, save_dir):
    """生成 (filename, img_path) 列表，已存在的文件跳过（断点续传）。"""
    tasks, skipped = [], 0
    for chap_num, img_urls in enumerate(page_urls):
        for page_num, img_path in enumerate(img_urls):
            ext = img_path.split('/')[-1].split('.')[-1]
            filename = '%d_%d.%s' % (chap_num, page_num, ext)
            if os.path.exists(os.path.join(save_dir, filename)):
                skipped += 1
                continue
            tasks.append((filename, img_path))
    return tasks, skipped


def download_one(kernel, img_path, save_dir, filename, cancel):
    if cancel.is_set():
        raise Cancelled()
    url = ('https://ereserves.lib.tsinghua.edu.cn/readkernel/JPGFile/'
           'DownJPGJsNetPage?filePath=' + requests.utils.quote(img_path))
    res = thread_session().get(url, cookies={'BotuReadKernel': kernel}, timeout=120)
    save_path = os.path.join(save_dir, filename)
    # 先写随机临时名再原子改名，和原版一致
    for _ in range(50):
        tmp_path = os.path.join(save_dir, '.tmp' + _randstr(16))
        if not os.path.exists(tmp_path):
            break
    with open(tmp_path, 'wb') as f:
        f.write(res.content)
    os.rename(tmp_path, save_path)
    return len(res.content)


def download_all(kernel, page_urls, save_dir, workers, cancel,
                 on_progress=None, log=None):
    """
    下载全部图片。返回 (ok, failed, skipped)。
    on_progress(done, total, failed)
    """
    os.makedirs(save_dir, exist_ok=True)
    tasks, skipped = build_tasks(page_urls, save_dir)
    total = len(tasks)
    if log:
        log('共需下载图片数：%d（已存在 %d 张，跳过）' % (total, skipped))
    if total == 0:
        return 0, 0, skipped

    ok = failed = done = 0

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(download_one, kernel, img_path, save_dir,
                               filename, cancel): filename
                   for filename, img_path in tasks}
        try:
            for fut in as_completed(futures):
                name = futures[fut]
                done += 1
                try:
                    fut.result()
                    ok += 1
                    if log:
                        log('下载图片成功：%s' % name)
                except Cancelled:
                    pass
                except Exception as e:                       # noqa: BLE001
                    failed += 1
                    if log:
                        log('失败：%s —— %s' % (name, e), 'danger')
                if on_progress:
                    on_progress(done, total, failed)
                if cancel.is_set():
                    for f in futures:
                        f.cancel()
                    break
        finally:
            if cancel.is_set():
                # 不再等待排队中的任务，尽快让 UI 拿到「已停止」
                pool.shutdown(wait=False, cancel_futures=True)
    if cancel.is_set():
        raise Cancelled()
    return ok, failed, skipped


# ------------------------------------------------------------------ PDF
def list_images(save_dir):
    """按 (章, 页) 排序的图片绝对路径列表。"""
    def key(path):
        m = re.match(r'(?P<chap>\d+)_(?P<page>\d+)\.[^.]*$', path)
        if not m:
            return (10 ** 9, 10 ** 9)
        return (int(m.group('chap')), int(m.group('page')))

    names = [n for n in os.listdir(save_dir)
             if any(re.match(r'\d+_\d+\.%s$' % s, n) for s in IMG_SUFFIXES)]
    names.sort(key=key)
    return [os.path.join(save_dir, n) for n in names]


def images_to_pdf(imgs, pdf_path, quality, auto_resize, cancel,
                  on_progress=None, log=None):
    """和 hhhimg2pdf.img2pdf 同一套做法，加了进度回调和取消。"""
    import shutil

    import fitz
    from PIL import Image

    intermediate_dir = os.path.join(os.path.dirname(pdf_path), 'intermediate')
    if not os.path.exists(intermediate_dir):
        os.makedirs(intermediate_dir, exist_ok=True)

    sample_size = {}
    for img in imgs:
        with Image.open(img) as im:
            key = im.size
        sample_size[key] = sample_size.get(key, 0) + 1
    common_size = max(sample_size, key=sample_size.get)

    n = len(imgs)
    try:
        with fitz.open() as doc:
            for i, img in enumerate(imgs):
                if cancel.is_set():
                    raise Cancelled()
                tmp_img = os.path.join(intermediate_dir, os.path.basename(img))
                with Image.open(img) as im:
                    w, h = common_size if auto_resize else im.size
                    im.convert('RGB').resize(
                        (max(1, int(w / 10 * quality)), max(1, int(h / 10 * quality)))
                    ).save(tmp_img, 'JPEG')
                with fitz.open(tmp_img) as imgdoc:
                    pdfbytes = imgdoc.convert_to_pdf()
                with fitz.open('pdf', pdfbytes) as imgpdf:
                    doc.insert_pdf(imgpdf)
                if on_progress:
                    on_progress(i + 1, n)
            doc.save(pdf_path)
    finally:
        shutil.rmtree(intermediate_dir, ignore_errors=True)
    if log:
        log('生成 PDF 成功：%s' % os.path.basename(pdf_path))


# ------------------------------------------------------------------ 书库
def make_thumbnail(pdf_path, out_path, width=280):
    """
    从 PDF 第一页生成书库用的封面缩略图。

    为什么不用平台给的封面图：一来不确定它一定存在、字段名也未知，
    二来这个做法离线也成立，而且渲染出来的就是这本书真实的首页。
    失败返回 False，书库退回纯文字卡片，不影响任何流程。
    """
    try:
        import fitz
        from PIL import Image
    except ImportError:
        return False
    try:
        parent = os.path.dirname(out_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with fitz.open(pdf_path) as doc:
            if doc.page_count == 0:
                return False
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
            img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        ratio = width / float(img.width)
        img = img.resize((width, max(1, int(img.height * ratio))), Image.LANCZOS)
        img.save(out_path, 'JPEG', quality=82)
        return True
    except Exception:                                                # noqa: BLE001
        # 封面只是好看，任何原因失败都静默跳过
        return False


def pdf_page_count(pdf_path):
    """页数取不准就返回 0，调用方显示成未知即可。"""
    try:
        import fitz
        with fitz.open(pdf_path) as doc:
            return doc.page_count
    except Exception:                                                # noqa: BLE001
        return 0