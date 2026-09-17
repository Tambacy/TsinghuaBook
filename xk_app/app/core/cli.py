# coding:utf-8
"""
命令行模式。原来只在仓库根的 main.py 里，现在收进包里，
这样打包成 exe 之后也能直接用命令行跑：

    TsinghuaBookCrawler.exe <书籍链接> --token eyJhb...
    TsinghuaBookCrawler.exe -h

仓库根的 main.py 依然可用（`python main.py <url> --token ...`），
它只是转发到这里，行为完全一致。
"""
import argparse
import os
import sys


def _import_root_modules():
    """
    download_imgs / hhhimg2pdf / utils 仍在仓库根目录。

    开发态：仓库根本来就在 sys.path 上，直接 import。
    冻结态：这些模块被 PyInstaller 打进了包里，同样能 import。
    """
    try:
        from download_imgs import download_imgs
        from hhhimg2pdf import img2pdf
        from utils import get_chap_page, is_image
        return download_imgs, img2pdf, get_chap_page, is_image
    except ImportError:
        # 兜底：把仓库根挂到 sys.path 再试一次（源码直接运行的情况）
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        if root not in sys.path:
            sys.path.insert(0, root)
        from download_imgs import download_imgs
        from hhhimg2pdf import img2pdf
        from utils import get_chap_page, is_image
        return download_imgs, img2pdf, get_chap_page, is_image


def build_parser():
    parser = argparse.ArgumentParser(
        prog='TsinghuaBookCrawler',
        description='Download e-book from '
                    'http://ereserves.lib.tsinghua.edu.cn. '
                    'By default, the number of processes is four and the temporary '
                    'images WILL BE preserved. \nFor example, '
                    '"python main.py https://ereserves.lib.tsinghua.edu.cn/bookDetail/'
                    'c01e1db11c4041a39db463e810bac8f9 --token eyJhb...". \n'
                    'Note that you need to manually login the ereserves website and '
                    'obtain the token from the FIRST request after login, like '
                    '"/index?token=xxx", due to two-factor authentication (2FA).')
    parser.add_argument('url')
    parser.add_argument('-t', '--token', type=str, required=True,
                        help='Required. The token from the "/index?token=xxx".')
    parser.add_argument('-n', type=int, default=4,
                        help='Optional, [1~16] (4 by default). The number of processes.')
    parser.add_argument('-q', type=int, default=10,
                        help='Optional, [3~10] (10 by default). The quality of the '
                             'generated PDF. The bigger the value, the higher the resolution.')
    parser.add_argument('-d', '--del-img', action='store_true',
                        help='Optional. Delete the temporary images.')
    parser.add_argument('-r', '--auto-resize', action='store_true',
                        help='Optional. Automatically unify page sizes.')
    return parser


def run(argv):
    args = build_parser().parse_args(argv)
    # 延迟 import：requests / PyMuPDF 都不轻，GUI 模式不该为它们付启动代价
    from . import engine

    download_imgs, img2pdf, get_chap_page, is_image = _import_root_modules()

    url = args.url
    token = args.token
    processing_num = args.n
    quality = args.q
    del_img = args.del_img
    auto_resize = args.auto_resize

    ref = engine.resolve_book(url, token, log=print)
    botu_read_kernel, book_real_id, scan_id = (
        ref.kernel, ref.book_real_id, ref.scan_id)
    emids = engine.fetch_chapters(botu_read_kernel, scan_id, log=print)
    page_urls = engine.fetch_page_urls(botu_read_kernel, book_real_id, emids, log=print)

    save_dir = os.path.join('downloads', book_real_id)
    print('Book ID: %s' % book_real_id)
    pdf_path = os.path.join(save_dir, book_real_id + '.pdf')
    if os.path.exists(pdf_path):
        print('该书已经下载, 停止下载')
        return 0

    download_imgs(botu_read_kernel, page_urls, save_dir, processing_num)
    print('图片下载完成')

    print('原始大小 PDF 转换中... quality：%d' % quality)

    imgs = list(sorted(filter(is_image, os.listdir(save_dir)), key=get_chap_page))
    imgs = list(map(lambda x: os.path.join(save_dir, x), imgs))

    if len(imgs) == 0:
        print('图片格式可能未列入，请检查 utils.py 中的 IMG_SUFFIXES')
        return 1

    if os.path.exists(pdf_path):
        print('已经生成完毕, 跳过转换')
    else:
        img2pdf(imgs, pdf_path, quality, auto_resize)
        print('生成 PDF 成功：' + os.path.basename(pdf_path))

    if del_img:
        for img in imgs:
            if os.path.exists(img):
                os.remove(img)
        print('清理临时图片完成')
    return 0


def main(argv=None):
    return run(list(sys.argv[1:] if argv is None else argv))