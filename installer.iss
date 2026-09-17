; ============================================================================
;  清华教参下载器 —— Inno Setup 安装包脚本
;
;  编译：  ISCC.exe installer.iss
;  产物：  dist\TsinghuaBookCrawler-1.0-Setup.exe
;
;  文件名刻意用 ASCII：GitHub Releases 会把 asset 名里的非 ASCII 字符直接
;  丢掉（实测「清华教参下载器-1.0-安装包.exe」被存成「-1.0-.exe」），
;  而且 ASCII 名在各种浏览器 / 下载器下都不会乱码。
;
;  依赖：  先跑 PyInstaller 生成 dist\TsinghuaBookCrawler.exe
; ============================================================================

#define MyAppName "清华教参下载器"
#define MyAppNameEn "TsinghuaBookCrawler"
#define MyAppVersion "1.0"
#define MyAppPublisher "TsinghuaBookCrawler"
#define MyAppExeName "TsinghuaBookCrawler.exe"
; PyInstaller 的 onedir 输出目录名（= spec 里 COLLECT 的 name），
; 注意它和 exe 同名，所以不能用 MyAppExeName 拼路径
#define MyAppDirName "TsinghuaBookCrawler"
#define MyAppId "{{9C2A1E4B-7D3F-4A85-9B6E-2F1C8A0D5E73}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}

; 默认装到当前用户的本地程序目录，不需要管理员权限
DefaultDirName={localappdata}\Programs\{#MyAppNameEn}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

OutputDir=dist
OutputBaseFilename={#MyAppNameEn}-{#MyAppVersion}-Setup
SetupIconFile=xk_app\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AllowNoIcons=yes
DisableWelcomePage=no
LicenseFile=installer_terms.txt
; 下载目录放在 exe 旁边，程序需要能写自己的安装目录
UsedUserAreasWarning=no

[Languages]
Name: "chinese"; MessagesFile: "compiler:Default.isl,installer_lang\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
chinese.CreateDesktopIcon=创建桌面快捷方式
chinese.LaunchApp=立即运行 {#MyAppName}
chinese.AdditionalIcons=附加任务：
chinese.OpenDownloads=打开下载目录
english.CreateDesktopIcon=Create a desktop shortcut
english.LaunchApp=Launch {#MyAppName}
english.AdditionalIcons=Additional tasks:
english.OpenDownloads=Open the downloads folder

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; onedir 布局：exe 和它的依赖（_internal\）一起装进去。
; 加了 QtWebEngine 之后依赖有好几百 MB，摊在安装目录里比塞进单文件好 ——
; 单文件每次启动都要解压一遍，登录页得等好几秒。
Source: "dist\{#MyAppDirName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "RELEASE_NOTES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "installer_terms.txt"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
; 保证程序能往安装目录里写下载内容
Name: "{app}\downloads"; Permissions: users-modify

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\打开下载目录"; Filename: "{app}\downloads"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\downloads"; Description: "{cm:OpenDownloads}"; Flags: postinstall shellexec skipifsilent unchecked

[UninstallDelete]
; 卸载时只清掉程序自己的东西，用户的下载内容留着。
; dirifempty = 只在空目录时删除：{app}\downloads 里还有书就不会被动。
; onedir 之后程序文件都在 {app} 和 {app}\_internal 里，Inno 会自己删干净，
; 这里只补上它不认的那些（运行时产物、空目录）。
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
Type: dirifempty; Name: "{app}\downloads"
Type: dirifempty; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"
