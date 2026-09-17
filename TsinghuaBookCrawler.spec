# -*- mode: python ; coding:utf-8 -*-
"""
PyInstaller 打包配置。

产物：dist/TsinghuaBookCrawler/TsinghuaBookCrawler.exe（onedir 目录模式）。
图标和天幕资源从 xk_app/assets 打进去（运行时经 sys._MEIPASS 取）。

命令行版本仍然可用：
    TsinghuaBookCrawler.exe <url> --token xxx

------------------------------------------------------------------ 为什么是 onedir
以前是单文件（onefile），因为那时整个程序才 54MB。加了 QtWebEngine 之后
不行了：Qt6WebEngineCore.dll 一个就 203MB，onefile 每次启动都要把整套
依赖解压到 %TEMP%，几百 MB 的磁盘写入，登录页得等好几秒才出来。

onedir 把依赖摊在安装目录里，启动时不需要解压 —— 装一次，之后每次都是
秒开。对最终用户来说安装包还是一个 exe，只是装出来是个文件夹。

------------------------------------------------------------------ WebEngine 的坑
1. 之前 excludes 里明确排掉了 QtWebEngine*，那是没有内嵌浏览器时的瘦身。
   现在登录页的「统一身份认证」模式就靠它，必须放出来。
2. WebEngine 的 C++ 依赖（Qt6WebEngineCore.dll、QtWebEngineProcess.exe、
   resources\、translations\qtwebengine_locales\）由 PyInstaller 自带的
   hook-PyQt6.QtWebEngineCore / hook-PyQt6.QtWebEngineWidgets 负责收集。
   它们会跟着 PyQt6 的 Qt6 目录一起进去，不需要手写 datas。
3. login.py 里 WebEngine 是**惰性 import**（放在 ensure_web() 内部），
   静态分析可能看不全，所以这里显式列进 hiddenimports。
"""
import os

block_cipher = None

ROOT = os.path.abspath(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'launcher.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'xk_app', 'assets'), 'assets'),
    ],
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PIL._tkinter_finder',
        # 登录页的内嵌浏览器。惰性 import，必须显式列出来
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',
        # 命令行模式的实现仍在仓库根目录，cli.py 里 import 它们 —— 显式列出来
        'download_imgs',
        'hhhimg2pdf',
        'utils',
        'auth_get',
        'xk_app.app.core.cli',
        # 视图是按需 import 的，列出来免得被静态分析漏掉
        'xk_app.app.gui.shell',
        'xk_app.app.gui.login',
        'xk_app.app.gui.views',
        'xk_app.app.gui.views.base',
        'xk_app.app.gui.views.queue_view',
        'xk_app.app.gui.views.library_view',
        'xk_app.app.gui.views.settings_view',
        'xk_app.app.gui.views.help_view',
        'xk_app.app.gui.icons',
        'xk_app.app.gui.sidebar',
        'xk_app.app.gui.backdrop',
        'xk_app.app.gui.widgets',
        'xk_app.app.core.store',
        'xk_app.app.core.queue',
        'xk_app.app.core.worker',
        'xk_app.app.core.tokeninfo',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 只为瘦身：这些 Qt 子系统这个程序完全用不到。
        # 注意 WebEngine 不在这里了 —— 登录页要用。
        'PyQt6.QtBluetooth', 'PyQt6.QtDesigner', 'PyQt6.QtHelp',
        'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets', 'PyQt6.QtNetworkAuth',
        'PyQt6.QtNfc', 'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets',
        'PyQt6.QtPositioning',
        # QML/Quick 是给 QtWebEngineQuick 用的，我们只用 Widgets 版，不需要
        'PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtQuick3D', 'PyQt6.QtQuickWidgets',
        'PyQt6.QtWebEngineQuick',
        'PyQt6.QtRemoteObjects', 'PyQt6.QtSensors', 'PyQt6.QtSerialPort',
        'PyQt6.QtSpatialAudio', 'PyQt6.QtSql', 'PyQt6.QtStateMachine',
        'PyQt6.QtSvgWidgets', 'PyQt6.QtTest', 'PyQt6.QtTextToSpeech',
        'PyQt6.QtWebSockets', 'PyQt6.QtCharts',
        'PyQt6.QtDataVisualization', 'PyQt6.QtGraphs',
        # 科学计算栈不该被拖进来
        'matplotlib', 'numpy', 'scipy', 'pandas', 'tkinter', 'PyQt5',
        'PySide2', 'PySide6', 'IPython', 'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# onedir：exe 只是个引导，依赖放在同目录的 _internal\ 里，启动不解压
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TsinghuaBookCrawler',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                  # 图形程序，不要黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'xk_app', 'assets', 'app.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TsinghuaBookCrawler',
)
