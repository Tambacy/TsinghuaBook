# 清华教参下载器 1.0

**发布日期**：2026 年 9 月
**适用平台**：Windows 10 64 位及以上
**安装包**：`TsinghuaBookCrawler-1.0-Setup.exe`（约 133 MB，无需管理员权限）

---

## 说明

将清华教参平台上的电子教材整本下载为 PDF 的 Windows 桌面应用。

本版本在上游脚本版（[lflame/TsinghuaBookCrawler](https://github.com/lflame/TsinghuaBookCrawler)）
的基础上重写为图形界面程序，使用不再需要安装 Python 或调用命令行。

## 功能

- **图形界面**：下载队列、书库、设置、使用说明四个页面
- **两种登录方式**：内嵌浏览器的统一身份认证（自动获取 Token）；手动填入 Token
- **Token 自动续期**：显示剩余有效时间；下载中失效时自动重新登录并续传
- **批量与断点**：一次可粘贴多条链接；中断后可续传，失败项可单独重试
- **书库**：自动记录书名、作者、页数与体积，支持搜索、打开 PDF、定位目录
- **无边框窗口**：拖动与缩放采用系统原生行为，支持边缘吸附

## 安装

1. 下载 `TsinghuaBookCrawler-1.0-Setup.exe`
2. 运行安装程序，按提示完成安装（默认路径 `%LOCALAPPDATA%\Programs\TsinghuaBookCrawler`）
3. 从开始菜单或桌面快捷方式启动

> 安装包未购买代码签名证书，Windows SmartScreen 可能提示"已保护你的电脑"。
> 选择"更多信息"→"仍要运行"即可。

## 系统要求

- Windows 10 64 位及以上
- 约 500 MB 磁盘空间
- 可访问 `*.tsinghua.edu.cn` 与 `*.lib.tsinghua.edu.cn`

## 修复

- 修复 `DownloadWorker` 对 `resolve_book()` 返回值的解包错误（按三个值解包，实际为四个）
- 修复侧边栏天幕化开区底边与右边出现的紫灰色接缝

## 数据与卸载

配置、书库记录与登录会话存放于 `%LOCALAPPDATA%\TsinghuaBookCrawler`。
卸载不会删除该目录，也不会删除已下载的 PDF。

## 版权

下载所得的电子书版权归原作者与出版方所有，仅供个人学习使用。
请勿传播，亦请避免批量下载。本程序不提供任何绕过认证或授权的能力。
因滥用本程序产生的一切后果，作者不承担责任。

---

完整使用说明见 [README](README.md)。
