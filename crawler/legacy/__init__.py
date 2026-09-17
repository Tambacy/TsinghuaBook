# coding:utf-8
"""
上游脚本版的原始实现，仅命令行模式仍在用。

这四个模块来自原作者 lflame 的 TsinghuaBookCrawler（v3.0 脚本版），
是 ereserves 新接口那一版的实现。图形界面走的是 `crawler/core` 里的重写版
（engine / queue / worker），**不依赖这里**。

保留原因：`crawler/core/cli.py` 的命令行模式（`python cli.py <url> --token xxx`、
以及打包后 `TsinghuaBookCrawler.exe <url> --token xxx`）至今仍调用它们。
如果要彻底去掉，需要把 cli.py 移植到 core 的实现上 —— 见 README「项目结构」。

    auth_get.py       自动认证（用学号密码换 ticket，2FA 之后已不适用）
    download_imgs.py  多进程下载页面图片
    hhhimg2pdf.py     图片合成 PDF
    utils.py          章节/页码解析与图片格式判断
"""
