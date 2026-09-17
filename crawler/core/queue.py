# coding:utf-8
"""
批量下载队列。

一次可以粘多条链接进来，逐本处理。为什么逐本（而不是几本并行）：
一本之内已经有 workers 个线程在并发抓图了，再并行几本只会把带宽和对方
服务器一起压垮，而进度反而更难看清。批量下载要的是「排好队、一本本下完」，
不是「同时开十条线」。

线程模型：QueueManager 自己起一个守护线程跑整条队列，通过回调把状态变化
吐给调用方（GUI 用信号把它转成 Qt 信号）。加锁只保护 jobs 列表，
网络请求和写盘都在锁外做，避免界面卡住。
"""
import os
import threading
import time

from . import engine, store


class JobState:
    PENDING = 'pending'          # 排队中
    RESOLVING = 'resolving'      # 校验链接与 token
    DOWNLOADING = 'downloading'
    CONVERTING = 'converting'    # 合成 PDF
    DONE = 'done'
    FAILED = 'failed'
    SKIPPED = 'skipped'          # 已经下载过
    CANCELLED = 'cancelled'


class Job:
    """队列里的一本书。"""

    def __init__(self, url, order=0):
        self.url = url.strip()
        self.order = order
        self.state = JobState.PENDING
        self.book_id = ''
        self.title = ''
        self.author = ''
        self.pages = 0
        self.chapters = 0
        self.done_pages = 0
        self.failed_pages = 0
        self.pdf_path = ''
        self.error = ''
        self.meta = {}

    @property
    def label(self):
        """界面上显示什么：书名优先，没有就退回书号，再没有就显示链接。"""
        return self.title or self.book_id or self.url

    @property
    def fraction(self):
        if self.state in (JobState.DONE, JobState.SKIPPED):
            return 1.0
        if not self.pages:
            return 0.0
        return max(0.0, min(1.0, self.done_pages / float(self.pages)))

    @property
    def active(self):
        return self.state in (JobState.RESOLVING, JobState.DOWNLOADING,
                              JobState.CONVERTING)

    @property
    def finished(self):
        return self.state in (JobState.DONE, JobState.FAILED,
                              JobState.SKIPPED, JobState.CANCELLED)


class QueueManager:
    """
    跑批。用法：

        q = QueueManager(settings, library, on_change=..., on_log=...)
        q.add(urls)
        q.start()
        q.cancel()
    """

    def __init__(self, settings, library, on_change=None, on_log=None,
                 on_library_changed=None):
        self.settings = settings
        self.library = library
        self.on_change = on_change
        self.on_log = on_log
        self.on_library_changed = on_library_changed
        self.jobs = []
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread = None

    # ------------------------------------------------------------ 查询
    def snapshot(self):
        with self._lock:
            return list(self.jobs)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def counts(self):
        """(已完成, 失败, 其余未结束) —— 给顶部总进度用。"""
        with self._lock:
            done = sum(1 for j in self.jobs
                       if j.state in (JobState.DONE, JobState.SKIPPED))
            failed = sum(1 for j in self.jobs if j.state == JobState.FAILED)
            left = sum(1 for j in self.jobs if not j.finished)
        return done, failed, left

    def progress(self):
        """
        整批的完成度 0~1，按每本书的页数加权而不是按本数 ——
        一本 500 页的书和一本 20 页的书各算一半是不合理的。

        失败/取消的书按它实际下到的进度算，不会假装完成。
        """
        with self._lock:
            if not self.jobs:
                return 0.0
            weighted = 0.0
            for j in self.jobs:
                # 下完的书直接算满分；其余一律按自身页数进度，
                # 失败/取消的书因此不会假装完成
                weighted += 1.0 if j.state in (JobState.DONE, JobState.SKIPPED) \
                    else j.fraction
            return max(0.0, min(1.0, weighted / len(self.jobs)))

    # ------------------------------------------------------------ 变更
    def add(self, urls):
        """加入一批链接，返回实际新增条数（去重：同一 URL 和已在队列里的不重复加）。"""
        if isinstance(urls, str):
            urls = [urls]
        added = 0
        with self._lock:
            existing = {j.url for j in self.jobs if not j.finished}
            for raw in urls:
                u = (raw or '').strip()
                if not u or u in existing:
                    continue
                self.jobs.append(Job(u, order=len(self.jobs)))
                existing.add(u)
                added += 1
        if added:
            self._changed()
        return added

    def remove(self, job):
        with self._lock:
            if job in self.jobs and not job.active:
                self.jobs.remove(job)
        self._changed()

    def clear_finished(self):
        with self._lock:
            self.jobs = [j for j in self.jobs if not j.finished]
        self._changed()

    def reset_failed(self):
        """失败的重新排队，方便 token 过期后重试。"""
        n = 0
        with self._lock:
            for j in self.jobs:
                if j.state in (JobState.FAILED, JobState.CANCELLED):
                    j.state = JobState.PENDING
                    j.error = ''
                    j.done_pages = 0
                    j.failed_pages = 0
                    n += 1
        if n:
            self._changed()
        return n

    def _changed(self):
        if self.on_change:
            self.on_change()

    def _log(self, msg, tone=''):
        if self.on_log:
            self.on_log(msg, tone)

    # ------------------------------------------------------------ 执行
    def start(self):
        if self.running:
            return False
        with self._lock:
            pending = [j for j in self.jobs if j.state == JobState.PENDING]
        if not pending:
            return False
        self._cancel.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name='download-queue')
        self._thread.start()
        return True

    def cancel(self):
        """停止：当前这本书也会在下一个检查点退出，队列里剩下的标记为已取消。"""
        self._cancel.set()
        with self._lock:
            for j in self.jobs:
                if j.state == JobState.PENDING:
                    j.state = JobState.CANCELLED
        self._changed()

    def wait(self, timeout=None):
        t = self._thread
        if t is not None:
            t.join(timeout)

    def _run(self):
        try:
            while not self._cancel.is_set():
                with self._lock:
                    nxt = next((j for j in self.jobs
                                if j.state == JobState.PENDING), None)
                if nxt is None:
                    break
                self._process(nxt)
        finally:
            self._changed()

    # ------------------------------------------------------------ 单本
    def _process(self, job):
        token = (self.settings.token or '').strip()
        if not token:
            job.state = JobState.FAILED
            job.error = '还没有设置 token，请先在「设置」里填好。'
            self._changed()
            return

        save_root = self.settings.resolve_save_dir()
        workers = int(self.settings.get('workers', 4) or 4)
        quality = int(self.settings.get('quality', 10) or 10)
        keep_images = bool(self.settings.get('keep_images', True))
        auto_resize = bool(self.settings.get('auto_resize', False))

        try:
            # ---- 1. 解析链接，拿到书号和书籍信息
            self._set(job, state=JobState.RESOLVING)
            self._log('开始处理：%s' % job.url)
            ref = engine.resolve_book(job.url, token, log=self._log)
            kernel, book_id, scan_id, meta = (
                ref.kernel, ref.book_real_id, ref.scan_id, ref.meta)
            job.book_id = book_id
            job.meta = meta or {}
            job.title = (job.meta.get('title') or '').strip() or book_id
            job.author = (job.meta.get('author') or '').strip()
            self._set(job)

            save_dir = os.path.join(save_root, book_id)
            pdf_path = os.path.join(save_dir, book_id + '.pdf')

            # ---- 2. 已经下过就直接跳过（和命令行行为一致）
            if os.path.exists(pdf_path):
                self._set(job, state=JobState.SKIPPED, pdf_path=pdf_path)
                self._log('《%s》已经下载过，跳过。' % job.title)
                self._record(job, save_dir, pdf_path, save_root)
                return

            # ---- 3. 章节与页数
            emids = engine.fetch_chapters(kernel, scan_id, log=self._log)
            page_urls = engine.fetch_page_urls(kernel, book_id, emids,
                                               log=self._log)
            total_pages = sum(len(x) for x in page_urls)
            self._set(job, chapters=len(emids), pages=total_pages)
            if self._cancel.is_set():
                raise engine.Cancelled()

            # ---- 4. 下载图片
            self._set(job, state=JobState.DOWNLOADING)

            def on_progress(done, total, failed):
                job.done_pages = done
                job.failed_pages = failed
                self._changed()

            ok, failed, skipped = engine.download_all(
                kernel, page_urls, save_dir, workers, self._cancel,
                on_progress=on_progress, log=self._log)
            self._log('《%s》图片下载完成：成功 %d，失败 %d，跳过 %d'
                      % (job.title, ok, failed, skipped),
                      'danger' if failed else '')

            # ---- 5. 合成 PDF
            self._set(job, state=JobState.CONVERTING)
            imgs = engine.list_images(save_dir)
            if not imgs:
                raise ValueError('没有找到任何已下载的图片，无法生成 PDF。')

            def on_convert(i, n):
                job.done_pages = i
                job.pages = n
                self._changed()

            engine.images_to_pdf(imgs, pdf_path, quality, auto_resize,
                                 self._cancel, on_progress=on_convert,
                                 log=self._log)

            # ---- 6. 清理临时图片（可关）
            if not keep_images:
                for img in imgs:
                    try:
                        os.remove(img)
                    except OSError:
                        pass
                self._log('已清理临时图片。')

            self._set(job, state=JobState.DONE, pdf_path=pdf_path,
                      pages=len(imgs))
            self._record(job, save_dir, pdf_path, save_root)

        except engine.Cancelled:
            self._set(job, state=JobState.CANCELLED)
            self._log('已停止：%s' % job.label, 'warn')
        except Exception as e:                                       # noqa: BLE001
            self._set(job, state=JobState.FAILED, error=str(e))
            self._log('《%s》失败：%s' % (job.label, e), 'danger')

    def _set(self, job, **kw):
        for k, v in kw.items():
            setattr(job, k, v)
        self._changed()

    def _record(self, job, save_dir, pdf_path, save_root):
        """写进书库，并生成封面缩略图。封面失败不影响入库。"""
        cover = ''
        try:
            base = engine.pdf_page_count(pdf_path) or job.pages
            job.pages = base or job.pages
        except Exception:                                            # noqa: BLE001
            pass
        try:
            cover_path = os.path.join(store.covers_dir(),
                                      '%s.jpg' % job.book_id)
            if engine.make_thumbnail(pdf_path, cover_path):
                cover = cover_path
        except Exception:                                            # noqa: BLE001
            cover = ''
        size = 0
        try:
            size = os.path.getsize(pdf_path)
        except OSError:
            pass
        rec = store.make_record(
            job.book_id, pdf_path, save_dir, url=job.url, meta={
                'title': job.title or job.book_id,
                'author': job.author,
                'publisher': (job.meta or {}).get('publisher', ''),
                'year': (job.meta or {}).get('year', ''),
                'isbn': (job.meta or {}).get('isbn', ''),
            }, pages=job.pages, chapters=job.chapters, cover=cover, size=size)
        self.library.upsert(rec)
        if self.on_library_changed:
            self.on_library_changed()


def extract_urls(text):
    """
    从粘贴的文本里挑出书籍链接。用户可能一次粘一堆，每行一条，
    也可能连标题一起粘进来，所以用正则抓而不是按行 split。
    """
    import re
    if not text:
        return []
    found = re.findall(r'https?://[^\s"\'<>]+', text)
    out, seen = [], set()
    for u in found:
        u = u.rstrip('.,;、，。')          # 中文标点常被一起粘进来
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def looks_like_book_url(url):
    """bookDetail 链接才可能是教参书籍；其余给出提示但不强行拒绝。"""
    return 'bookDetail' in (url or '')
