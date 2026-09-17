# 清华教参下载器 2.0

**发布日期**：2026 年 9 月
**适用平台**：Windows 10 64 位及以上
**安装包**：`TsinghuaBookCrawler-2.0-Setup.exe`（约 133 MB，无需管理员权限）

---

## 本版修复

- **下载完成时程序崩溃。** 侧边栏状态文字被误赋成布尔值，绘制时抛异常；PyQt 在绘制回调里遇到未捕获异常会直接终止进程，不弹任何提示。表现就是「程序无响应 → 崩溃」，而书其实已经下载完成。
- **下载线程直接操作界面。** 界面刷新与下载跑在同一个线程上，现改为投递到主线程执行，并合并高频刷新。
- **修改书库文件夹名后显示「文件已丢失」**，且点刷新无效。现按 `<book_id>.pdf` 自动重新定位。

## 说明

将清华教参平台上的电子教材整本下载为 PDF 的 Windows 桌面应用。
在上游脚本版（[lflame/TsinghuaBookCrawler](https://github.com/lflame/TsinghuaBookCrawler)）
的基础上重写为图形界面程序，使用不再需要安装 Python 或调用命令行。

## 安装

1. 下载 `TsinghuaBookCrawler-2.0-Setup.exe`
2. 运行安装程序，按提示完成安装（默认路径 `%LOCALAPPDATA%\Programs\TsinghuaBookCrawler`）
3. 从开始菜单或桌面快捷方式启动

> 安装包未购买代码签名证书，Windows SmartScreen 可能提示"已保护你的电脑"。
> 选择"更多信息"→"仍要运行"即可。

## 系统要求

- Windows 10 64 位及以上
- 约 500 MB 磁盘空间
- 可访问 `*.tsinghua.edu.cn` 与 `*.lib.tsinghua.edu.cn`

## 数据与卸载

配置、书库记录与登录会话存放于 `%LOCALAPPDATA%\TsinghuaBookCrawler`。
卸载不会删除该目录，也不会删除已下载的 PDF。

## 版权

下载所得的电子书版权归原作者与出版方所有，仅供个人学习使用。
请勿传播，亦请避免批量下载。本程序不提供任何绕过认证或授权的能力。
因滥用本程序产生的一切后果，作者不承担责任。

---

完整使用说明见 [README](README.md)。
