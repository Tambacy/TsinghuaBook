# coding:utf-8
"""
工作线程。所有网络 / 磁盘工作都在这里，主线程只负责画界面。

硬性排队（规范第八节）：
  * 停止 / 结束后，所有计时类动画必须冻结，不能继续累加
  * 重复推送同一份状态必须幂等：内容不变、行数不增长
"""
import os
import threading
import traceback

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from . import engine


class _BaseWorker(QObject):
    log = pyqtSignal(str, str)          # (文本, 级别 info/ok/warn/danger/dim)
    failed = pyqtSignal(str, str)       # (简短原因, 详细堆栈)

    def __init__(self):
        super().__init__()
        self.cancel = threading.Event()

    def stop(self):
        self.cancel.set()


class CredCheckWorker(_BaseWorker):
    """登录凭证那一步：只校验 token 并读出书的结构，不下载。"""

    done = pyqtSignal(dict)

    def __init__(self, url, token):
        super().__init__()
        self.url = url
        self.token = token

    def run(self):
        try:
            info = engine.book_info(self.url, self.token,
                                    log=lambda m: self.log.emit(m, 'info'))
            if self.cancel.is_set():
                return
            self.done.emit(info)
        except Exception as e:                                    # noqa: BLE001
            self.failed.emit(str(e), traceback.format_exc())


class DownloadWorker(_BaseWorker):
    """
    确认启动之后：解析 -> 下载 -> 生成 PDF。
    阶段推送 stage_changed；图片进度 push_progress；PDF 进度 push_convert。
    重复推送同一份状态是幂等的（页面自己判断值有没有变）。
    """

    stage_changed = pyqtSignal(str, str)      # (阶段键, 人类可读文案)
    push_progress = pyqtSignal(int, int, int)  # (done, total, failed)
    push_convert = pyqtSignal(int, int)        # (done, total)
    finished_ok = pyqtSignal(dict)             # 结果字典
    stopped = pyqtSignal()

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    def run(self):
        cfg = self.cfg
        say = lambda m, lvl='info': self.log.emit(m, lvl)          # noqa: E731
        try:
            self.stage_changed.emit('resolve', '正在获取书籍信息')
            ref = engine.resolve_book(cfg['url'], cfg['token'], log=say)
            kernel, book_real_id, scan_id = (
                ref.kernel, ref.book_real_id, ref.scan_id)

            # 和 CLI 版保持同一套目录结构：<选择的目录>/<书籍ID>/
            # 图片、intermediate 和 PDF 都在这个子目录里，互不干扰。
            base_dir = cfg['save_dir'] or os.path.join(os.getcwd(), 'downloads')
            save_dir = os.path.join(base_dir, book_real_id)
            pdf_path = os.path.join(save_dir, book_real_id + '.pdf')

            if os.path.exists(pdf_path):
                self.finished_ok.emit({
                    'pdf_path': pdf_path, 'save_dir': save_dir,
                    'skipped_book': True, 'downloaded': 0, 'failed': 0,
                    'pages': 0, 'total_bytes': 0,
                })
                self.stage_changed.emit('done', '该书已经下载完成')
                return

            self.stage_changed.emit('chapters', '正在解析章节')
            emids = engine.fetch_chapters(kernel, scan_id, log=say)
            page_urls = engine.fetch_page_urls(kernel, book_real_id, emids, log=say)
            total_pages = sum(len(x) for x in page_urls)
            self.push_progress.emit(0, total_pages, 0)

            self.stage_changed.emit('download', '正在下载图片')
            ok, failed, skipped = engine.download_all(
                kernel, page_urls, save_dir, cfg['workers'], self.cancel,
                on_progress=lambda d, t, f: self.push_progress.emit(d, t, f),
                log=say)

            self.stage_changed.emit('convert', '正在生成 PDF')
            imgs = engine.list_images(save_dir)
            if not imgs:
                raise RuntimeError('没有找到任何图片，请检查 utils.py 中的 IMG_SUFFIXES。')
            engine.images_to_pdf(imgs, pdf_path, cfg['quality'], cfg['auto_resize'],
                                 self.cancel,
                                 on_progress=lambda d, t: self.push_convert.emit(d, t),
                                 log=say)

            total_bytes = 0
            try:
                total_bytes = os.path.getsize(pdf_path)
            except OSError:
                pass

            if cfg['del_img']:
                say('正在清理临时图片 ...')
                for img in imgs:
                    try:
                        os.remove(img)
                    except OSError:
                        pass
                say('清理临时图片完成')

            self.stage_changed.emit('done', '已完成')
            self.finished_ok.emit({
                'pdf_path': pdf_path, 'save_dir': save_dir,
                'skipped_book': False, 'downloaded': ok, 'failed': failed,
                'skipped': skipped, 'pages': total_pages,
                'total_bytes': total_bytes,
            })
        except engine.Cancelled:
            self.stage_changed.emit('stopped', '已停止')
            self.stopped.emit()
        except Exception as e:                                    # noqa: BLE001
            self.stage_changed.emit('error', '出错了')
            self.failed.emit(str(e), traceback.format_exc())


class TaskRunner(QObject):
    """
    把 worker 放进 QThread 并在结束时清理。
    持有引用，避免 Python 侧提前回收导致线程还在跑。

    用法：worker 通过 done / finished_ok / stopped / failed 任一信号收尾后，
    调用方（主线程）再调用 finish() 退出线程。
    """

    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.thread = QThread()
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)

    def start(self):
        self.thread.start()

    def stop(self):
        self.worker.stop()

    def finish(self):
        """
        延迟一拍再退线程：QThread.quit() 会丢掉之后投递的信号，
        所以先把当前事件队列排空，保证 UI 侧已经收全收尾信号。
        """
        QTimer.singleShot(0, self._quit)

    def _quit(self):
        self.thread.quit()
        self.thread.wait(5000)

    @property
    def running(self):
        return self.thread.isRunning()