"""
确认打包进 exe 的 updater 就是修好的那份。

为什么非要查这个：更新功能已经坏过一次，而且是「静默失效」——
命令拼错、Popen 不报错、用户点了没反应。如果打包时用了旧代码，
光看安装包能装上、能自检通过，是发现不了的。
所以直接把 exe 里的字节码抠出来反汇编，看 launch() 到底怎么调的。
"""
import dis
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = 'crawler.core.updater'


def load_bundled(exe):
    """从 exe 里把 crawler.core.updater 的代码对象抠出来。"""
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    arch = CArchiveReader(exe)
    toc = list(arch.toc)
    print('CArchive 条目数: %d' % len(toc))
    pyz_names = [n for n in toc if n.lower().endswith('.pyz')]
    print('PYZ 条目: %s' % pyz_names)
    if not pyz_names:
        return None

    data = arch.extract(pyz_names[0])
    fd, tmp = tempfile.mkstemp(suffix='.pyz')
    os.close(fd)
    try:
        with open(tmp, 'wb') as fh:
            fh.write(data)
        z = ZlibArchiveReader(tmp)
        names = list(z.toc)
        hit = [n for n in names if n == MOD]
        print('PYZ 里模块数: %d，命中 %s' % (len(names), hit))
        if not hit:
            near = [n for n in names if 'updater' in n.lower()]
            print('  含 updater 的: %s' % near)
            return None
        return z.extract(MOD)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def main():
    exe = os.path.join(ROOT, 'dist', 'TsinghuaBookCrawler', 'TsinghuaBookCrawler.exe')
    print('exe: %s' % exe)
    if not os.path.exists(exe):
        print('FAIL exe 不存在')
        return 1

    code = load_bundled(exe)
    if code is None:
        print('FAIL 没抠出 %s' % MOD)
        return 1
    print('抠出来了，代码对象 %r' % (code.co_name,))
    print()

    # 不 exec 整个模块（它有相对导入，脱离包跑不起来），
    # 直接从代码对象的常量表里把 launch 的代码对象挑出来。
    funcs = {}
    for c in code.co_consts:
        if hasattr(c, 'co_name'):
            funcs[c.co_name] = c
    print('模块里的函数/类: %s' % ', '.join(sorted(funcs)))
    print()

    # 版本号常量也顺便从字节码里读出来
    ver = '?'
    for c in code.co_consts:
        if isinstance(c, str) and c[:1].isdigit() and '.' in c:
            ver = c
            break
    print('归档里的 VERSION = %s' % ver)
    print()

    launch = funcs.get('launch')
    if launch is None:
        print('FAIL 找不到 launch()')
        return 1

    bc = dis.Bytecode(launch)
    # 只取真正的常量（LOAD_CONST）。
    # 不能遍历所有指令的 argval —— 那样会把变量名（cmd/exe/flags…）
    # 也当成字符串常量收进来，于是把局部变量 cmd 误判成旧写法的指纹。
    consts = set()
    for ins in bc:
        if ins.opname == 'LOAD_CONST' and isinstance(ins.argval, str):
            consts.add(ins.argval)
    # Python 3.12 把关键字参数名放在一个元组常量里，由 KW_NAMES 引用
    kw_names = set()
    for ins in bc:
        if ins.opname == 'KW_NAMES' and isinstance(ins.argval, tuple):
            kw_names.update(ins.argval)
        elif ins.opname == 'LOAD_CONST' and isinstance(ins.argval, tuple):
            kw_names.update(x for x in ins.argval if isinstance(x, str))

    print('launch() 的字符串常量:')
    for c in sorted(consts):
        if len(c) < 70:
            print('    %r' % c)
    print('launch() 的关键字参数: %s' % (sorted(kw_names) or '无'))
    print()

    ok = True
    # 旧写法 Popen(['cmd', '/c', cmd], ...) 会把 'cmd' 和 '/c' 都作为常量编进去
    for fingerprint in ('cmd', '/c'):
        if fingerprint in consts:
            print('  FAIL 还带着旧写法的指纹 %r —— 打包的是没修的那份' % fingerprint)
            ok = False
    if ok:
        print('  OK   没有旧写法 Popen([\'cmd\', \'/c\', ...]) 的常量指纹')

    if 'shell' in kw_names:
        print('  OK   带 shell 关键字（shell=True 的新写法）')
    else:
        print('  FAIL 没看到 shell 关键字')
        ok = False

    print()
    print('BUNDLE OK' if ok else 'BUNDLE FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
