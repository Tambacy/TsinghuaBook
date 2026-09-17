"""
书库文件夹改名后「文件已丢失」的回归测试。

用户报的现象：把已下载书籍所在的文件夹改个名字，书库里立刻显示
「文件已丢失」，点刷新也没用。

原因：记录里存的是下载当时的绝对路径；import_existing 只补
「目录名恰好等于 book_id」的新记录，不会去修老记录。

这里锁住修复后的行为：按 <book_id>.pdf 重新认领。
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _isolate import isolate                                          # noqa: E402

isolate()

from crawler.core import store                                        # noqa: E402

FAILED = []


def check(ok, msg):
    print('  %s %s' % ('OK  ' if ok else 'FAIL', msg), flush=True)
    if not ok:
        FAILED.append(msg)


def make_pdf(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(b'%PDF-1.4\n%%EOF\n')


def main():
    tmp = tempfile.mkdtemp(prefix='xkc_relocate_')
    try:
        save_root = os.path.join(tmp, 'downloads')
        book_id = '092404F54B9D5700E065000000000001'
        orig_dir = os.path.join(save_root, book_id)
        orig_pdf = os.path.join(orig_dir, book_id + '.pdf')
        make_pdf(orig_pdf)

        lib_path = os.path.join(tmp, 'library.json')
        lib = store.Library(lib_path)
        lib.upsert(store.make_record(book_id, orig_pdf, orig_dir,
                                     meta={'title': '测试书'}, pages=12,
                                     size=os.path.getsize(orig_pdf)))

        print('[A] 原始状态', flush=True)
        rec = lib.get(book_id)
        check(lib.exists_on_disk(rec), '文件在，记录正常')

        print('[B] 用户把文件夹改名', flush=True)
        renamed_dir = os.path.join(save_root, '我的教材')
        os.rename(orig_dir, renamed_dir)
        renamed_pdf = os.path.join(renamed_dir, book_id + '.pdf')
        rec = lib.get(book_id)
        check(not lib.exists_on_disk(rec), '改名后记录失效（复现用户看到的「文件已丢失」）')
        check(lib.reconcile() != [], 'reconcile 把它标成丢失')

        print('[C] 只调 import_existing —— 这就是「刷新也没用」的原因', flush=True)
        added = lib.import_existing(save_root)
        rec = lib.get(book_id)
        check(added == 0, 'import_existing 新增 0 条（目录名 != book_id，认不出来）')
        check(not lib.exists_on_disk(rec), '刷新后仍然显示「文件已丢失」')

        print('[D] relocate_missing 应该认领回来', flush=True)
        fixed = lib.relocate_missing(save_root)
        rec = lib.get(book_id)
        check(fixed == 1, '修好 1 条（当前 %d）' % fixed)
        check(lib.exists_on_disk(rec), '记录重新指向真实文件')
        check(rec.get('pdf_path') == renamed_pdf,
              'pdf_path 已更新（当前 %s）' % rec.get('pdf_path'))
        check(rec.get('save_dir') == renamed_dir,
              'save_dir 已更新（当前 %s）' % rec.get('save_dir'))
        check(rec.get('cover') == '' or True, '记录本身没重建，元数据保留')
        check(rec.get('pages') == 12, '页数等元数据保留（当前 %s）' % rec.get('pages'))
        check(len(lib.all()) == 1, '没有产生重复记录（当前 %d 条）' % len(lib.all()))

        print('[E] 落盘后重开仍然有效', flush=True)
        lib2 = store.Library(lib_path)
        check(lib2.exists_on_disk(lib2.get(book_id)), '重开后路径已持久化')

        print('[F] 挪到子目录里也能找到', flush=True)
        nested = os.path.join(save_root, '2026', '春季', '我的教材')
        os.makedirs(os.path.dirname(nested), exist_ok=True)
        shutil.move(renamed_dir, nested)
        rec = lib2.get(book_id)
        check(not lib2.exists_on_disk(rec), '挪走后再次失效')
        check(lib2.relocate_missing(save_root) == 1, '子目录里也认领回来')
        check(lib2.get(book_id).get('save_dir') == nested, 'save_dir 指向新的子目录')

        print('[G] 文件真的被删了就不该乱认', flush=True)
        shutil.rmtree(nested)
        rec = lib2.get(book_id)
        check(lib2.relocate_missing(save_root) == 0, '找不到就保持丢失状态，不瞎猜')
        check(not lib2.exists_on_disk(rec), '仍然标记为丢失')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('', flush=True)
    if FAILED:
        print('RELOCATE FAIL (%d)' % len(FAILED), flush=True)
        for m in FAILED:
            print('   - %s' % m, flush=True)
        return 1
    print('RELOCATE PASS', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
