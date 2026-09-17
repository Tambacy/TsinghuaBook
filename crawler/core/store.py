# coding:utf-8
"""
本地持久化：设置、token、书库索引。

为什么要独立一层：token 是会话级凭证（抓一次能用很久），保存目录和质量这些
也是「设一次就一直用」的东西。它们是全局状态，不属于任何一次下载任务，
所以不能塞在任务对象里。

两个 JSON 文件分开存：
    config.json   设置 + token
    library.json  已下载的书

所有写入都是「先写临时文件再原子替换」，避免程序被强杀时留下半个坏 JSON。
"""
import json
import os
import tempfile
import time


# 显式覆盖配置目录。给测试和「绿色版」用：
# 测试必须能把书库和设置写到临时目录，绝不能碰到用户真实的 %LOCALAPPDATA%。
DATA_DIR_ENV = 'TSINGHUA_CRAWLER_DATA_DIR'


def data_dir():
    """配置与书库的存放位置（Windows 按惯例放 LOCALAPPDATA）。"""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        path = override
    else:
        base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
        if not base:
            base = os.path.join(os.path.expanduser('~'), '.local', 'share')
        path = os.path.join(base, 'TsinghuaBookCrawler')
    os.makedirs(path, exist_ok=True)
    return path


def covers_dir():
    path = os.path.join(data_dir(), 'covers')
    os.makedirs(path, exist_ok=True)
    return path


def _atomic_write_json(path, obj):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent or '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:                                                # noqa: BLE001
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _read_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        # 文件不存在或损坏都退回默认值 —— 配置坏了不该让程序打不开
        return default


# ------------------------------------------------------------------ 设置
DEFAULT_SETTINGS = {
    'token': '',
    'save_dir': '',            # 空 = 用 <cwd>/downloads
    'workers': 4,              # 1~16
    'quality': 10,             # 3~10
    'keep_images': True,       # False = 生成 PDF 后删临时图片
    'auto_resize': False,
    # 登录相关
    'login_mode': 'sso',       # 'sso' = 统一身份认证 / 'token' = 直接填 Token
    'auto_refresh': True,      # 统一身份认证模式下，Token 失效自动重新获取
    'last_login_at': 0,        # 上次登录成功的时间戳
}


class Settings:
    """设置 + token。改完调 save()。"""

    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), 'config.json')
        self._data = dict(DEFAULT_SETTINGS)
        loaded = _read_json(self.path, {})
        if isinstance(loaded, dict):
            for k in DEFAULT_SETTINGS:
                if k in loaded:
                    self._data[k] = loaded[k]
        self._data['workers'] = self._clamp_int(self._data['workers'], 1, 16, 4)
        self._data['quality'] = self._clamp_int(self._data['quality'], 3, 10, 10)
        # 配置文件是可以被手改坏的，登录模式只认这两个值
        if self._data.get('login_mode') not in ('sso', 'token'):
            self._data['login_mode'] = 'sso'
        self._data['auto_refresh'] = bool(self._data.get('auto_refresh', True))

    @staticmethod
    def _clamp_int(value, lo, hi, fallback):
        try:
            n = int(value)
        except (TypeError, ValueError):
            return fallback
        return max(lo, min(hi, n))

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def update(self, **kw):
        self._data.update(kw)

    def as_dict(self):
        return dict(self._data)

    @property
    def token(self):
        return self._data.get('token', '')

    @token.setter
    def token(self, value):
        self._data['token'] = (value or '').strip()

    def resolve_save_dir(self, fallback=None):
        """保存目录：设置里有就用，否则用 <cwd>/downloads。"""
        d = (self._data.get('save_dir') or '').strip()
        if d:
            return d
        return fallback or os.path.join(os.getcwd(), 'downloads')

    def save(self):
        try:
            _atomic_write_json(self.path, self._data)
            return True
        except OSError:
            return False


# ------------------------------------------------------------------ 书库
BOOK_FIELDS = ('book_id', 'title', 'author', 'publisher', 'year', 'isbn',
               'pdf_path', 'save_dir', 'pages', 'chapters', 'cover',
               'size', 'added_at', 'url')


def make_record(book_id, pdf_path, save_dir, url='', meta=None, pages=0,
                chapters=0, cover='', size=0):
    """构造一条书库记录。所有字段都有安全默认值。"""
    meta = meta or {}
    title = (meta.get('title') or '').strip() or book_id
    rec = {
        'book_id': book_id,
        'title': title,
        'author': (meta.get('author') or '').strip(),
        'publisher': (meta.get('publisher') or '').strip(),
        'year': (meta.get('year') or '').strip(),
        'isbn': (meta.get('isbn') or '').strip(),
        'pdf_path': pdf_path,
        'save_dir': save_dir,
        'pages': int(pages or 0),
        'chapters': int(chapters or 0),
        'cover': cover,
        'size': int(size or 0),
        'added_at': time.time(),
        'url': url,
    }
    return rec


class Library:
    """
    已下载的书。以 book_id 为主键，按加入时间倒序。

    import_existing() 会扫保存目录，把「下载了但索引里没有」的书补进来 ——
    用户可能用命令行下过、或者手动删过索引，界面不该因此对不上磁盘。
    """

    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), 'library.json')
        raw = _read_json(self.path, [])
        self._items = []
        if isinstance(raw, list):
            for rec in raw:
                if isinstance(rec, dict) and rec.get('book_id'):
                    clean = {k: rec.get(k, '') for k in BOOK_FIELDS if k in rec}
                    clean.setdefault('book_id', rec['book_id'])
                    # 补齐缺失字段，方便老版本索引直接升级
                    for k in BOOK_FIELDS:
                        clean.setdefault(k, '' if k != 'added_at' else 0)
                    self._items.append(clean)
        self._sort()

    def _sort(self):
        self._items.sort(key=lambda r: r.get('added_at') or 0, reverse=True)

    def all(self):
        return list(self._items)

    def get(self, book_id):
        for rec in self._items:
            if rec.get('book_id') == book_id:
                return rec
        return None

    def upsert(self, rec):
        """同一本书重复下载时覆盖旧记录，而不是变成两条。"""
        book_id = rec.get('book_id')
        for i, old in enumerate(self._items):
            if old.get('book_id') == book_id:
                merged = dict(old)
                merged.update(rec)
                # 保留最早的加入时间，书库排序才稳定
                merged['added_at'] = old.get('added_at') or rec.get('added_at')
                self._items[i] = merged
                self._sort()
                self.save()
                return merged
        self._items.append(rec)
        self._sort()
        self.save()
        return rec

    def remove(self, book_id):
        before = len(self._items)
        self._items = [r for r in self._items if r.get('book_id') != book_id]
        if len(self._items) != before:
            self.save()
            return True
        return False

    def exists_on_disk(self, rec):
        p = rec.get('pdf_path') or ''
        return bool(p) and os.path.exists(p)

    def reconcile(self):
        """
        标出哪些记录的 PDF 已经不在了（用户手动删了文件）。
        不自动删除记录 —— 让界面提示「文件已丢失」比悄悄消失更好。
        """
        return [r for r in self._items if not self.exists_on_disk(r)]

    def save(self):
        try:
            _atomic_write_json(self.path, self._items)
            return True
        except OSError:
            return False

    def import_existing(self, save_root):
        """
        扫描 save_root/<book_id>/<book_id>.pdf，把没索引过的补进来。
        返回新增数量。命令行下载过的书也能出现在书库里。
        """
        if not save_root or not os.path.isdir(save_root):
            return 0
        known = {r.get('book_id') for r in self._items}
        added = 0
        try:
            names = os.listdir(save_root)
        except OSError:
            return 0
        for name in names:
            sub = os.path.join(save_root, name)
            if not os.path.isdir(sub) or name in known:
                continue
            pdf = os.path.join(sub, name + '.pdf')
            if not os.path.exists(pdf):
                continue
            size = 0
            try:
                size = os.path.getsize(pdf)
            except OSError:
                pass
            self._items.append(make_record(
                name, pdf, sub, meta={'title': name},
                pages=pdf_page_count_safe(pdf), size=size))
            known.add(name)
            added += 1
        if added:
            self._sort()
            self.save()
        return added

    @staticmethod
    def _find_pdf(root, book_id, max_depth=4):
        """
        在 root 下面找 <book_id>.pdf。

        PDF 的文件名是程序自己按 book_id 起的，用户能改的只有外面那层目录名，
        所以按文件名找是可靠的。深度限制是防止 save_root 被指到一个很大的
        目录上时把整个盘扫一遍。
        """
        target = book_id + '.pdf'
        root = os.path.abspath(root)
        base_depth = root.rstrip(os.sep).count(os.sep)
        for cur, dirs, files in os.walk(root):
            if cur.count(os.sep) - base_depth >= max_depth:
                dirs[:] = []
            if target in files:
                return os.path.join(cur, target)
        return ''

    def relocate_missing(self, save_root):
        """
        把「文件已丢失」的记录按文件名重新认领回来，返回修好的条数。

        记录里存的是下载当时的绝对路径。用户把书库里的文件夹改个名，这个路径
        就失效了，而 import_existing 只补「目录名恰好等于 book_id」的新记录、
        不会去修老记录 —— 所以界面会一直显示「文件已丢失」，点刷新也没用
        （用户报的 bug）。这里按 <book_id>.pdf 在 save_root 下重新找一遍，
        找到就把 pdf_path / save_dir 改回去，记录本身不重建，封面和元数据都保住。
        """
        if not save_root or not os.path.isdir(save_root):
            return 0
        fixed = 0
        for rec in self._items:
            if self.exists_on_disk(rec):
                continue
            book_id = rec.get('book_id') or ''
            if not book_id:
                continue
            found = self._find_pdf(save_root, book_id)
            if not found:
                continue
            rec['pdf_path'] = found
            rec['save_dir'] = os.path.dirname(found)
            fixed += 1
        if fixed:
            self.save()
        return fixed


def pdf_page_count_safe(pdf_path):
    """避免 store 依赖 engine（engine 依赖 requests），出错就 0。"""
    try:
        import fitz
        with fitz.open(pdf_path) as doc:
            return doc.page_count
    except Exception:                                                # noqa: BLE001
        return 0
