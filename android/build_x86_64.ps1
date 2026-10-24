<#
.SYNOPSIS
  JMComic Android 单架构一键构建 —— x86_64(Android 模拟器)，Windows PowerShell 经 WSL。

.DESCRIPTION
  本脚本只构建 x86_64 一种架构：在 Windows 侧自检 WSL/发行版/路径，
  然后进入 WSL 按 x86_64 调用 tools/wsl_build_apk.sh(同步到 ext4 构建树、
  只下 x86_64 的 wheel/AAR、只编 x86_64 的 libsr_qnn.so、只出 x86_64 一个 dist、
  不并入任何 QNN 运行库)，再用 wsl_collect_apk.sh 把产物收集回仓库，
  最后复制到输出目录(默认脚本所在目录)，构建成功自动清理临时文件。

  arm64 的相关步骤一律不执行。要构建 arm64-v8a(真机)请用 build_arm64.ps1；
  两种架构都要请用 build_apk_from_windows.ps1。

  x86_64 与 arm64 的差异(见 README §10.1)：
   * 超分走 ONNX Runtime CPU EP(模拟器没有高通 HTP；用于验证功能链路，勿评估性能)
   * curl_cffi 用 android/shims 纯 python 垫片(上游没有 x86_64 android wheel，
     无 Chrome TLS 指纹，严格校验场景需真机验证)

  构建是 wsl.exe 的前台子进程，构建期间请保持窗口打开；单架构冷构建约
  40~60 分钟，缓存命中约 5 分钟。

.PARAMETER Abi
  目标架构。默认 x86_64；只接受 x86_64 / x86-64 / x64。
  传 arm64-v8a 会报错并提示改用 build_arm64.ps1(本脚本不构建其它架构)。
  也可用环境变量 ABI 指定(参数优先级更高)。

.PARAMETER AppVersion
  APK 版本号(versionName)。不传则用构建脚本默认值(tools/patch_buildozer_spec.py
  的 AppVersion)，也可用环境变量 APP_VERSION 指定(参数优先)。
  格式规则(语义化版本的数字核心子集)：MAJOR.MINOR(仓库简写，如 0.51) 或
  MAJOR.MINOR.PATCH(如 1.2.3)；每段纯数字、不允许前导零；不接受 -alpha.1 /
  +build.5 之类后缀(p4a 由 versionName 推导 versionCode，只按 "." 切数字段)。
  不合法会在动手前报错退出(退出码 2)。该值最终写进 buildozer.spec 的
  app.version，并出现在 APK 文件名(JMComic-<版本>-<abi>-<类型>.apk)里。

.PARAMETER Distro
  WSL Linux 发行版名称。默认 Ubuntu；未指定时自动挑选(优先 Ubuntu，
  只有一个发行版时用它，多个且无 Ubuntu 则报错并列出可选值)。

.PARAMETER OutputDir
  APK 产物输出目录(Windows 路径)。默认为脚本所在目录。

.PARAMETER BuildWork
  WSL 内的构建树目录(对应 env.sh 的 JM_WORK，默认 ~/jmcomic-build)。
  用户的 shell profile 未导出 JM_WORK 时由本脚本显式传入。

.PARAMETER ProjectPath
  JMComic 仓库根目录(Windows 路径)。默认自动定位：从脚本所在目录逐级向上
  找含 android\build_android.sh 的目录，找不到再试当前工作目录。

.PARAMETER DryRun
  只做环境自检并打印将要执行的 WSL 命令，不真正构建。

.PARAMETER KeepTemp
  保留临时目录(默认构建成功后自动清理；失败时总会保留供排查)。

.PARAMETER LogDir
  执行日志目录。默认为脚本所在目录下的 logs\。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File android\build_x86_64.ps1 -DryRun
  先自检(不构建)：WSL/发行版/项目路径/构建树是否就绪。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File android\build_x86_64.ps1
  一键构建 x86_64(模拟器)，产物输出到脚本所在目录。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File android\build_x86_64.ps1 -AppVersion 0.52 -OutputDir D:\apk
  指定版本号与输出目录。

.NOTES
  版本: 1.0.0
  退出码: 0=构建成功; 1=构建失败; 2=环境自检失败(WSL/发行版/路径/架构)。
#>
[CmdletBinding()]
param(
    [string]$Abi = "",
    [string]$AppVersion = "",
    [string]$Distro = "",
    [string]$OutputDir = "",
    [string]$BuildWork = "",
    [switch]$DryRun,
    [switch]$KeepTemp,
    [string]$LogDir = "",
    [string]$ProjectPath = "",
    [switch]$Help
)

$ScriptVersion = "1.0.0"
$ScriptAbi     = "x86_64"        # 本脚本唯一支持的架构
$SiblingPs1    = "build_arm64.ps1"
$SiblingSh     = "build_arm64.sh"
$MultiScript   = "build_apk_from_windows.ps1"
$ErrorActionPreference = "Continue"

# ------------------------------------------------------------------ 基础路径
if (-not $LogDir)    { $LogDir    = Join-Path $PSScriptRoot "logs" }
if (-not $OutputDir) { $OutputDir = $PSScriptRoot }
$Stamp    = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile  = Join-Path $LogDir ("build_x86_64_{0}.log" -f $Stamp)
$TempDir  = Join-Path $env:TEMP ("JMComicApkBuild_x86_64_{0}_{1}" -f $Stamp, $PID)
$DiagFile = Join-Path $TempDir "diagnostics.txt"

# ------------------------------------------------------------------ 日志/输出
function Write-Log {
    param(
        [string]$Message = "",
        [ValidateSet("INFO","OK","WARN","ERROR","STEP")][string]$Level = "INFO"
    )
    $ts   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[{0}] [{1,-5}] {2}" -f $ts, $Level, $Message
    switch ($Level) {
        "OK"    { Write-Host $line -ForegroundColor Green }
        "WARN"  { Write-Host $line -ForegroundColor Yellow }
        "ERROR" { Write-Host $line -ForegroundColor Red }
        "STEP"  { Write-Host $line -ForegroundColor Cyan }
        default { Write-Host $line }
    }
    try { Add-Content -Path $LogFile -Value $line -Encoding UTF8 } catch { }
}

function Add-Diag {
    param([string]$Message)
    try {
        if (-not (Test-Path -LiteralPath $TempDir)) {
            New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
        }
        Add-Content -Path $DiagFile -Value ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message) -Encoding UTF8
    } catch { }
}

# 版本号格式校验：语义化版本的数字核心子集 MAJOR.MINOR[.PATCH]
# (与 android/build_android.sh、tools/patch_buildozer_spec.py 同一套规则)。
# 该值会写进 buildozer.spec 的 app.version(=Android versionName)，p4a 再据此推导
# versionCode(只按 "." 切数字段)，故每段必须纯数字、无前导零，且不接受
# -alpha.1 / +build.5 之类预发布/构建元数据后缀。
function Test-VersionFormat {
    param([string]$Version)
    return ($Version -match '^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))?$')
}

function Show-Usage {
    Write-Host @"
JMComic 单架构一键构建(x86_64 模拟器, Windows -> WSL)  v$ScriptVersion

用法:
  powershell -ExecutionPolicy Bypass -File <本脚本> [参数]

常用参数:
  -Abi <abi>           目标架构(只接受 x86_64/x86-64/x64，默认 x86_64)
  -AppVersion <版本号> APK 版本号(versionName)；格式 MAJOR.MINOR 或
                        MAJOR.MINOR.PATCH，纯数字段、无前导零(如 0.51 / 1.2.3)，
                        不接受 -alpha/+build 后缀；也可用 APP_VERSION 环境变量
  -Distro <发行版>     默认 Ubuntu(自动检测/挑选)
  -OutputDir <目录>    产物输出目录, 默认: 脚本所在目录
  -BuildWork <目录>    WSL 构建树(默认 ~/jmcomic-build)
  -ProjectPath <仓库根> 默认: 自动定位(脚本目录逐级向上找)
  -DryRun              只自检 + 打印命令, 不真正构建
  -KeepTemp            保留临时目录(默认成功后清理)
  -Help                显示本帮助

其它入口:
  arm64-v8a(真机)  -> .\$SiblingPs1   (Linux/macOS: .\$SiblingSh)
  两种架构都要     -> .\$MultiScript   (Linux/macOS: .\build_android.sh)

退出码: 0=构建成功  1=构建失败  2=环境自检失败
"@
}

# ------------------------------------------------------------------ 帮助/初始化
if ($Help) { Show-Usage; exit 0 }

foreach ($d in @($LogDir, $OutputDir, $TempDir)) {
    try { New-Item -ItemType Directory -Force -Path $d -ErrorAction Stop | Out-Null } catch {
        Write-Host "[ERROR] 无法创建目录: $d ($($_.Exception.Message))" -ForegroundColor Red
        exit 2
    }
}

Write-Log "JMComic 单架构一键构建(x86_64 模拟器, Windows -> WSL) v$ScriptVersion" STEP
Write-Log "脚本:       $PSCommandPath"
Write-Log "执行日志:   $LogFile"
Write-Log "临时目录:   $TempDir(构建成功后自动清理; -KeepTemp 可保留)"
Add-Diag "===== JMComic x86_64 build started (v$ScriptVersion) ====="
Add-Diag "PSVersion: $($PSVersionTable.PSVersion)"

# ------------------------------------------------------------------ 架构判断
# 来源优先级：-Abi 参数 > ABI 环境变量 > 本脚本默认(x86_64)。
# 只接受本脚本架构(含别名)，其它一律拒绝并指路 —— 绝不静默构建别的架构。
$AbiInput = ""
if ($Abi)            { $AbiInput = $Abi }
elseif ($env:ABI)    { $AbiInput = $env:ABI }
switch ($AbiInput.ToLower()) {
    ""          { $TargetAbi = $ScriptAbi }
    "x86_64"    { $TargetAbi = "x86_64" }
    "x86-64"    { $TargetAbi = "x86_64" }
    "x64"       { $TargetAbi = "x86_64" }
    "arm64"     { Write-Log "本脚本只构建 x86_64(模拟器)，不接受 'arm64'。要构建 arm64-v8a(真机)请用: .\$SiblingPs1" ERROR; exit 2 }
    "arm64-v8a" { Write-Log "本脚本只构建 x86_64(模拟器)，不接受 'arm64-v8a'。要构建 arm64-v8a(真机)请用: .\$SiblingPs1" ERROR; exit 2 }
    "aarch64"   { Write-Log "本脚本只构建 x86_64(模拟器)，不接受 'aarch64'。要构建 arm64-v8a(真机)请用: .\$SiblingPs1" ERROR; exit 2 }
    "both"      { Write-Log "本脚本只构建单一架构。两种架构都要请用: .\$MultiScript" ERROR; exit 2 }
    "all"       { Write-Log "本脚本只构建单一架构。两种架构都要请用: .\$MultiScript" ERROR; exit 2 }
    default     { Write-Log "不支持的 ABI: '$AbiInput'(本脚本只支持 x86_64)" ERROR; exit 2 }
}
Write-Log "目标架构: $TargetAbi(仅此架构：wheel/AAR/原生库/dist 全部单架构，不编译 arm64)" OK

# ------------------------------------------------------------------ 版本号解析与校验
# 来源优先级：-AppVersion 参数 > APP_VERSION 环境变量 > 构建脚本默认值
# (tools/patch_buildozer_spec.py 的 AppVersion；不传则由构建脚本提取，那边也会再校验)。
# 这里提前校验，不合法在动手前就退出(退出码 2)，不会带进 WSL 构建。
$AppVersionSrc = ""
if ($AppVersion) {
    $AppVersionSrc = "-AppVersion 参数"
} elseif ($env:APP_VERSION) {
    $AppVersion = $env:APP_VERSION
    $AppVersionSrc = "APP_VERSION 环境变量"
}
if ($AppVersion -and -not (Test-VersionFormat $AppVersion)) {
    Write-Log "APK 版本号格式不合法: '$AppVersion'(来源: $AppVersionSrc)" ERROR
    Write-Log "规则: MAJOR.MINOR 或 MAJOR.MINOR.PATCH，每段纯数字、无前导零(如 0.51 / 1.2.3)" ERROR
    Write-Log "不接受 -alpha/+build 之类后缀(p4a 由 versionName 推导 versionCode，只认数字段)" ERROR
    Write-Log "不传则用构建脚本默认值(tools/patch_buildozer_spec.py 的 AppVersion)" ERROR
    Add-Diag "FATAL: bad AppVersion '$AppVersion' (from $AppVersionSrc)"
    exit 2
}
if ($AppVersion) { Write-Log "APK 版本号: $AppVersion(来源: $AppVersionSrc)" OK }
else { Write-Log "APK 版本号: 使用构建脚本默认值(tools/patch_buildozer_spec.py 的 AppVersion)" }
Write-Log "提醒: x86_64 无 QNN/HTP，超分走 CPU EP；curl_cffi 用纯 python 垫片(详见 README §10.1)" WARN

# ------------------------------------------------------------------ 1. WSL 可执行文件
$wslCmd = Get-Command wsl.exe -ErrorAction SilentlyContinue
if (-not $wslCmd) {
    Write-Log "未找到 wsl.exe：本脚本需要 WSL(Windows 10 2004+ / Windows 11)" ERROR
    Write-Log "安装方式(管理员 PowerShell): wsl --install -d Ubuntu" ERROR
    Add-Diag "FATAL: wsl.exe not found"
    exit 2
}
Write-Log "wsl.exe: $($wslCmd.Source)" OK

# ------------------------------------------------------------------ 2. WSL 状态 + 发行版列表
& wsl.exe --status 2>&1 | Out-Null
$statusCode = $LASTEXITCODE
Add-Diag "wsl --status exit=$statusCode"
if ($statusCode -ne 0) {
    Write-Log "WSL 状态检查失败(退出码 $statusCode)" ERROR
    Write-Log "请确认: 1) 已启用“适用于 Linux 的 Windows 子系统功能” 2) 已启用虚拟化 3) 重启过电脑" ERROR
    exit 2
}

function Get-WslDistroList {
    $list = @()
    try {
        # wsl -l 输出是 UTF-16LE，中文代码页下直接读会乱码，临时切 Unicode，
        # 读完立刻恢复原编码(wsl.exe 普通输出会按控制台代码页自动转码，不能改)。
        $saved = [Console]::OutputEncoding
        try { [Console]::OutputEncoding = [System.Text.Encoding]::Unicode } catch { }
        $raw = & wsl.exe -l -q 2>$null
        try { [Console]::OutputEncoding = $saved } catch { }
        $list = @($raw | ForEach-Object { ($_ -replace "`0", "").Trim() } |
                  Where-Object { $_ -and ($_ -notmatch "[^\u0020-\u007E]") })
    } catch { }
    if ($list.Count -eq 0) {
        # 兜底：直接读注册表里的发行版名(Lxss 下每个子键的 DistributionName)
        try {
            Get-ChildItem "HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss" -ErrorAction SilentlyContinue |
                ForEach-Object {
                    $n = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DistributionName
                    if ($n) { $list += $n }
                }
        } catch { }
    }
    return $list
}

$Distros = @(Get-WslDistroList)
if ($Distros.Count -eq 0) {
    Write-Log "WSL 中没有可用的 Linux 发行版" ERROR
    Write-Log "安装: wsl --install -d Ubuntu(或在 Microsoft Store 搜索 Ubuntu 安装)" ERROR
    Add-Diag "FATAL: no WSL distro"
    exit 2
}
Write-Log "检测到发行版: $($Distros -join ', ')" OK
Add-Diag ("distros: {0}" -f ($Distros -join ", "))

if ($Distro) {
    $hit = $Distros | Where-Object { $_ -ieq $Distro } | Select-Object -First 1
    if (-not $hit) {
        Write-Log "指定的发行版 '$Distro' 不存在(可用: $($Distros -join ', '))" ERROR
        exit 2
    }
    $Distro = $hit
} else {
    if ($Distros -contains "Ubuntu") {
        $Distro = "Ubuntu"
    } elseif ($Distros.Count -eq 1) {
        $Distro = $Distros[0]
    } else {
        Write-Log "检测到多个发行版($($Distros -join ', '))，请用 -Distro 指定其中一个" ERROR
        exit 2
    }
    Write-Log "未指定 -Distro，自动选择: $Distro"
}
Write-Log "目标发行版: $Distro" OK

# ------------------------------------------------------------------ 3. 项目路径(自动定位)
# 从脚本目录逐级向上找含 android\build_android.sh 的目录；找不到再试当前目录。
function Find-RepoRoot {
    param([string]$StartDir)
    if (-not $StartDir) { return $null }
    $dir = $StartDir
    for ($i = 0; $i -lt 8 -and $dir; $i++) {
        foreach ($marker in @("android\build_android.sh", "android\tools\wsl_build_apk.sh",
                              "android/build_android.sh", "android/tools/wsl_build_apk.sh")) {
            if (Test-Path -LiteralPath (Join-Path $dir $marker)) { return $dir }
        }
        $parent = Split-Path -Parent $dir
        if ((-not $parent) -or ($parent -eq $dir)) { break }
        $dir = $parent
    }
    return $null
}

if ($ProjectPath) {
    try {
        # -ErrorAction Stop：Resolve-Path 默认抛非终止错误，try/catch 抓不到
        $ProjectPath = (Resolve-Path -LiteralPath $ProjectPath -ErrorAction Stop).Path
    } catch {
        Write-Log "项目路径不存在: $ProjectPath(用 -ProjectPath 指定 JMComic 仓库根)" ERROR
        exit 2
    }
} else {
    $repoRoot = Find-RepoRoot $PSScriptRoot
    $via = "脚本目录向上"
    if (-not $repoRoot) {
        $cwd = ""
        try { $cwd = (Get-Location).Path } catch { }
        if ($cwd) {
            $repoRoot = Find-RepoRoot $cwd
            $via = "当前目录向上"
        }
    }
    if (-not $repoRoot) {
        Write-Log "未能自动定位 JMComic 仓库根" ERROR
        Write-Log "已从脚本目录($PSScriptRoot)和当前目录逐级向上查找含 android\build_android.sh 的目录，均未找到" ERROR
        Write-Log "请用 -ProjectPath 显式指定仓库根，例如: -ProjectPath C:\Users\WQ159\source\repos\JMComic-qt" ERROR
        exit 2
    }
    $ProjectPath = $repoRoot
    Write-Log "自动定位仓库根($via): $ProjectPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectPath "android"))) {
    Write-Log "$ProjectPath 下没有 android 目录，不像 JMComic 仓库根(用 -ProjectPath 指定)" ERROR
    exit 2
}
Write-Log "项目路径(Windows): $ProjectPath" OK

# 转成 WSL 路径并验证可见
# 注意：wsl.exe 自己解析命令行时会吃掉反斜杠(PowerShell 走 CreateProcess 命令行)，
# Windows 路径必须换成正斜杠再传。
$winPathFwd = $ProjectPath.Replace('\', '/')
$wslpathOut = & wsl.exe -d $Distro -- wslpath -u $winPathFwd 2>$null
$RepoWsl = ("$wslpathOut" -replace "`0", "").Trim()
if ((-not $RepoWsl) -or ($LASTEXITCODE -ne 0)) {
    Write-Log "wslpath 转换失败: $ProjectPath(退出码 $LASTEXITCODE)" ERROR
    exit 2
}
Write-Log "项目路径(WSL):   $RepoWsl" OK

& wsl.exe -d $Distro -- test -d $RepoWsl
if ($LASTEXITCODE -ne 0) {
    Write-Log "WSL 中访问不到项目目录: $RepoWsl" ERROR
    Write-Log "检查: 项目所在盘是否被 WSL 自动挂载(默认 /mnt/<盘符>)，或 automount 是否被关掉" ERROR
    exit 2
}

& wsl.exe -d $Distro -- test -f "$RepoWsl/android/tools/wsl_build_apk.sh"
if ($LASTEXITCODE -ne 0) {
    Write-Log "WSL 中找不到构建脚本: $RepoWsl/android/tools/wsl_build_apk.sh" ERROR
    Write-Log "检查仓库是否完整" ERROR
    exit 2
}

# ------------------------------------------------------------------ 4. 构建树(venv311)
if (-not $BuildWork) {
    $homeOut = & wsl.exe -d $Distro -- bash -lc 'echo $HOME' 2>$null
    $wslHome = ("$homeOut" -replace "`0", "").Trim()
    if (-not $wslHome) { $wslHome = "/home/$Distro" }
    $BuildWork = "$wslHome/jmcomic-build"
}
Write-Log "WSL 构建树(JM_WORK): $BuildWork"
& wsl.exe -d $Distro -- test -x "$BuildWork/venv311/bin/python"
if ($LASTEXITCODE -ne 0) {
    Write-Log "缺少宿主 venv311: $BuildWork/venv311/bin/python" ERROR
    Write-Log "请先在 WSL 里准备构建环境(pyside6-android-deploy 要求宿主 Python <= 3.11):" ERROR
    Write-Log "  wsl -d $Distro" ERROR
    Write-Log "  cd $RepoWsl && bash android/tools/wsl_build_py311_src.sh" ERROR
    Write-Log "或构建树在别处时用 -BuildWork 指定" ERROR
    exit 2
}
Write-Log "宿主 venv311: OK" OK

# ------------------------------------------------------------------ 5. 输出目录
try {
    New-Item -ItemType Directory -Force -Path $OutputDir -ErrorAction Stop | Out-Null
    $OutputDir = (Resolve-Path -LiteralPath $OutputDir -ErrorAction Stop).Path
} catch {
    Write-Log "输出目录不可用: $OutputDir($($_.Exception.Message))" ERROR
    exit 2
}
Write-Log "输出目录: $OutputDir" OK

$ScriptStart = Get-Date
Add-Diag "preflight OK: distro=$Distro repoWsl=$RepoWsl buildWork=$BuildWork out=$OutputDir abi=$TargetAbi"

# ------------------------------------------------------------------ WSL 命令执行器
# 退出码放全局变量 $global:LastWslExit，函数本身不 return 任何值：
#   1) native 命令的 stdout 会混进函数返回值，不能 `$rc = Invoke-WslCommand ...`；
#   2) 输出直接继承控制台(wsl.exe 按控制台代码页转码，中文不乱码)，不能被捕获。
$global:LastWslExit = 0
function Invoke-WslCommand {
    param(
        [Parameter(Mandatory=$true)][string]$Cmd,
        [string]$Description = ""
    )
    if ($Description) { Write-Log $Description }
    Write-Log "WSL 执行: bash -lc `"$Cmd`""
    Add-Diag "CMD: bash -lc `"$Cmd`""
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    & wsl.exe -d $Distro -- bash -lc $Cmd
    $global:LastWslExit = $LASTEXITCODE
    $sw.Stop()
    Add-Diag ("EXIT={0} ELAPSED={1}" -f $global:LastWslExit, $sw.Elapsed.ToString("hh\:mm\:ss"))
    Write-Log ("WSL 退出码: {0}(耗时 {1})" -f $global:LastWslExit, $sw.Elapsed.ToString("hh\:mm\:ss"))
}

# 收集本次新产出的 APK(mtime 大于构建开始时间，防误取旧包)
function Get-NewArtifact {
    param([string]$SubDir, [string]$Pattern, [datetime]$Since)
    $dir = Join-Path $ProjectPath $SubDir
    if (-not (Test-Path -LiteralPath $dir)) { return $null }
    return Get-ChildItem -LiteralPath $dir -Filter $Pattern -File |
        Where-Object { $_.LastWriteTime -gt $Since } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

# ------------------------------------------------------------------ DryRun
$buildCmd = "export JM_WORK='$BuildWork'; cd '$RepoWsl' && bash 'android/tools/wsl_build_apk.sh' --abi '$TargetAbi'"
if ($AppVersion) { $buildCmd += " --version '$AppVersion'" }
$collectCmd = "export JM_WORK='$BuildWork'; cd '$RepoWsl/android' && bash 'tools/wsl_collect_apk.sh'"

if ($DryRun) {
    Write-Log "================ DryRun：只自检，不构建 ================" STEP
    Write-Log "[DryRun] 将执行(构建): bash -lc `"$buildCmd`""
    Write-Log "[DryRun] 将执行(收集): bash -lc `"$collectCmd`""
    Write-Log "[DryRun] 产物目录: $ProjectPath\android\JMComic-*-$TargetAbi-*.apk -> $OutputDir"
    Write-Log "DryRun 自检通过：WSL/发行版/项目路径/构建脚本/构建树均可用" OK
    Write-Log "去掉 -DryRun 即可开始真正构建" OK
    if (-not $KeepTemp) {
        try { Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction Stop } catch { }
    }
    exit 0
}

# ------------------------------------------------------------------ 构建
Write-Log "================ 开始构建: $TargetAbi ================" STEP
$buildSw = [System.Diagnostics.Stopwatch]::StartNew()
$buildStart = Get-Date
Invoke-WslCommand $buildCmd "调用 WSL 构建($TargetAbi)"
$code = $global:LastWslExit
if ($code -ne 0) {
    $buildSw.Stop()
    Write-Log "[FAIL] $TargetAbi 构建失败: WSL 构建失败(退出码 $code，耗时 $($buildSw.Elapsed.ToString('hh\:mm\:ss')))" ERROR
    Write-Log "详细构建日志: $ProjectPath\android\build_logs\；本脚本执行日志: $LogFile" ERROR
    Write-Log "诊断信息(保留供排查): $DiagFile" ERROR
    Write-Log "修复后可重跑: powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Abi $TargetAbi" ERROR
    exit 1
}

# 收集产物回 Windows 仓库
Invoke-WslCommand $collectCmd "收集产物回 Windows 仓库($TargetAbi)"
$ccode = $global:LastWslExit
if ($ccode -ne 0) {
    $buildSw.Stop()
    Write-Log "[FAIL] wsl_collect_apk.sh 失败(退出码 $ccode)" ERROR
    Write-Log "诊断信息(保留供排查): $DiagFile" ERROR
    exit 1
}

# 找到本次新产出的 APK 并复制到输出目录
$apk = Get-NewArtifact -SubDir "android" -Pattern "JMComic-*-$TargetAbi-*.apk" -Since $buildStart
if (-not $apk) {
    $buildSw.Stop()
    Write-Log "[FAIL] 构建后未在 $ProjectPath\android 找到 $TargetAbi 的新 APK" ERROR
    $existing = Get-ChildItem -LiteralPath (Join-Path $ProjectPath "android") -Filter "*.apk" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 3 -ExpandProperty Name
    if ($existing) { Write-Log "仓库里现有的 APK(供比对): $($existing -join ', ')" WARN }
    Write-Log "诊断信息(保留供排查): $DiagFile" ERROR
    exit 1
}
$dest = Join-Path $OutputDir $apk.Name
$srcDir = Split-Path -Parent $apk.FullName
$copied = $false
if ((Resolve-Path -LiteralPath $srcDir).Path -eq $OutputDir) {
    Write-Log "产物已在输出目录，跳过复制: $dest"
    $copied = $true
} else {
    try {
        Copy-Item -LiteralPath $apk.FullName -Destination $dest -Force -ErrorAction Stop
        Write-Log "已复制产物: $apk.Name -> $dest"
        $copied = $true
    } catch {
        Write-Log "[FAIL] 复制产物失败: $($_.Exception.Message)" ERROR
    }
}
$buildSw.Stop()

# ------------------------------------------------------------------ 归档 WSL 侧构建日志
$logCmd = "export JM_WORK='$BuildWork'; mkdir -p '$RepoWsl/android/build_logs'; cp -f $BuildWork/logs/*.log '$RepoWsl/android/build_logs/' 2>/dev/null || true"
& wsl.exe -d $Distro -- bash -lc $logCmd 2>$null | Out-Null
$buildLogDir = Join-Path $ProjectPath "android\build_logs"
if (Test-Path -LiteralPath $buildLogDir) {
    $outLogs = Join-Path $OutputDir "logs"
    New-Item -ItemType Directory -Force -Path $outLogs -ErrorAction SilentlyContinue | Out-Null
    Get-ChildItem -LiteralPath $buildLogDir -Filter "*.log" -File |
        Where-Object { $_.LastWriteTime -gt $ScriptStart } |
        ForEach-Object {
            try {
                Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $outLogs $_.Name) -Force -ErrorAction Stop
                Write-Log "归档构建日志: $($_.Name) -> $outLogs"
            } catch { }
        }
}

# ------------------------------------------------------------------ 汇总
if ($copied) {
    Write-Log ""
    Write-Log "================ 构建结果 ================" STEP
    Write-Log ("[OK] {0}  {1}  ({2:N1} MB, 耗时 {3})" -f $TargetAbi, $dest, ($apk.Length/1MB), $buildSw.Elapsed.ToString("hh\:mm\:ss")) OK
    Write-Log "全部完成！产物目录: $OutputDir" OK
    Write-Log "  安装: adb install -r `"$dest`"" OK
    Write-Log "执行日志: $LogFile" OK
    if (-not $KeepTemp) {
        try {
            Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction Stop
            Write-Log "临时目录已清理: $TempDir" OK
        } catch {
            Write-Log "临时目录清理失败(可手动删除): $TempDir" WARN
        }
    } else {
        Write-Log "已保留临时目录(-KeepTemp): $TempDir" OK
    }
    Write-Log "完成，总耗时 $((New-TimeSpan -Start $ScriptStart -End (Get-Date)).ToString('hh\:mm\:ss'))" OK
    exit 0
} else {
    Write-Log "构建失败(产物复制环节)，诊断信息: $DiagFile" ERROR
    exit 1
}
