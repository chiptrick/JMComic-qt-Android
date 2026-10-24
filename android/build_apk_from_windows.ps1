<#
.SYNOPSIS
  从 Windows 一键调用 WSL 构建 JMComic Android APK(arm64-v8a + x86_64)。

.DESCRIPTION
  在 Windows 侧完成环境自检，然后进入 WSL 的指定发行版，在项目目录中执行
  APK 构建命令，最后把产物复制到输出目录(默认脚本所在目录)。

  默认走仓库里验证过的 WSL 一体化流程 android/tools/wsl_build_apk.sh：
  它会把仓库同步到 WSL ext4 构建树(避开 /mnt/c 的 9p 慢速挂载)、按架构
  分别构建、再自动把 APK 与构建日志收集回 Windows 仓库。本脚本按架构
  依次调用，并在每次构建后校验产物、复制到输出目录。

  也可用 -BuildScript build_android.sh 改走 android/build_android.sh
  (单次运行、--abi 逗号列表、产物在 android\dist)。注意：该模式直接用
  宿主编译，未走 ext4 缓存；且 pyside6-android-deploy 要求宿主
  Python <= 3.11(Ubuntu 26.04 自带的 3.14 不行，需要 venv311)。

  构建期间请保持本窗口打开(前台运行)：WSL 构建是 wsl.exe 的子进程，
  关闭终端会直接中断构建。单个架构冷构建约 40~60 分钟，缓存命中约 5 分钟。

.PARAMETER ProjectPath
  JMComic 仓库根目录(Windows 路径)。默认自动定位：从脚本所在目录逐级向上
  找含 android\build_android.sh 的目录，找不到再试当前工作目录。脚本被
  移动/复制到任何位置都能用。

.PARAMETER Distro
  WSL Linux 发行版名称。默认 Ubuntu；未指定时会自动挑选(优先 Ubuntu，
  只有一个发行版时用它，多个且无 Ubuntu 则报错并列出可选值)。

.PARAMETER OutputDir
  APK 产物输出目录(Windows 路径)。默认为脚本所在目录。

.PARAMETER Abi
  目标架构，可传多个或用逗号分隔：arm64-v8a / x86_64 / both(两者都构建，
  默认)。别名: arm64->arm64-v8a, x86-64->x86_64, all->both。

.PARAMETER AppVersion
  APK 版本号(versionName)。不传则用构建脚本默认值(tools/patch_buildozer_spec.py
  的 AppVersion)，也可用环境变量 APP_VERSION 指定(参数优先)。
  格式规则(语义化版本的数字核心子集)：MAJOR.MINOR(仓库简写，如 0.51) 或
  MAJOR.MINOR.PATCH(如 1.2.3)；每段纯数字、不允许前导零；不接受 -alpha.1 /
  +build.5 之类后缀(p4a 由 versionName 推导 versionCode，只按 "." 切数字段)。
  不合法会在动手前报错退出(退出码 2)。该值最终写进 buildozer.spec 的
  app.version，并出现在 APK 文件名(JMComic-<版本>-<abi>-<类型>.apk)里。

.PARAMETER BuildScript
  WSL 内执行的构建脚本(相对仓库根)。默认 tools/wsl_build_apk.sh
  (按架构分别构建 + 自动收集)；可改成 build_android.sh(单次多架构)。

.PARAMETER BuildWork
  WSL 内的构建树目录(对应 env.sh 的 JM_WORK，默认 ~/jmcomic-build)。
  用户的 shell profile 未导出 JM_WORK 时由本脚本显式传入。

.PARAMETER StopOnError
  某个架构失败立即停止(默认继续构建其余架构，最后汇总)。

.PARAMETER KeepTemp
  保留临时目录(默认构建成功后自动清理；失败时总会保留供排查)。

.PARAMETER DryRun
  只做环境自检并打印将要执行的 WSL 命令，不真正构建。

.PARAMETER LogDir
  执行日志目录。默认为脚本所在目录下的 logs\。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File android\build_apk_from_windows.ps1
  一键构建 arm64-v8a + x86_64，产物输出到脚本所在目录(android\)。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File android\build_apk_from_windows.ps1 -Abi x86_64 -OutputDir D:\apk
  只构建 x86_64(模拟器)，产物输出到 D:\apk。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File android\build_apk_from_windows.ps1 -DryRun
  自检 WSL/发行版/路径并打印将执行的命令，不构建。

.NOTES
  版本: 1.0.0
  退出码: 0=全部成功; 1=有架构构建失败; 2=环境自检失败(WSL/发行版/路径)。
#>
[CmdletBinding()]
param(
    [string]$ProjectPath = "",
    [string]$Distro = "",
    [string]$OutputDir = "",
    [string[]]$Abi = @("arm64-v8a", "x86_64"),
    [string]$AppVersion = "",
    [string]$BuildScript = "tools/wsl_build_apk.sh",
    [string]$BuildWork = "",
    [switch]$StopOnError,
    [switch]$KeepTemp,
    [switch]$DryRun,
    [string]$LogDir = "",
    [switch]$Help
)

$ScriptVersion = "1.0.0"
$ErrorActionPreference = "Continue"

# ------------------------------------------------------------------ 基础路径
if (-not $LogDir)    { $LogDir    = Join-Path $PSScriptRoot "logs" }
if (-not $OutputDir) { $OutputDir = $PSScriptRoot }
$Stamp    = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile  = Join-Path $LogDir ("build_apk_{0}.log" -f $Stamp)
$TempDir  = Join-Path $env:TEMP ("JMComicApkBuild_{0}_{1}" -f $Stamp, $PID)
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
JMComic APK 一键构建(Windows -> WSL)  v$ScriptVersion

用法:
  powershell -ExecutionPolicy Bypass -File <本脚本> [参数]

常用参数:
  -ProjectPath <仓库根>    默认: 自动定位(脚本目录逐级向上找 android\build_android.sh)
  -Distro <发行版>         默认: Ubuntu(自动检测/挑选)
  -OutputDir <目录>        产物输出目录, 默认: 脚本所在目录
  -Abi <架构...>           arm64-v8a / x86_64 / both(默认两者都构建)
  -AppVersion <版本号>     APK 版本号(versionName)；格式 MAJOR.MINOR 或
                          MAJOR.MINOR.PATCH，纯数字段、无前导零(如 0.51 / 1.2.3)，
                          不接受 -alpha/+build 后缀；也可用 APP_VERSION 环境变量
  -BuildScript <脚本>      默认 tools/wsl_build_apk.sh; 可传 build_android.sh
  -BuildWork <目录>        WSL 构建树(默认 ~/jmcomic-build)
  -StopOnError             某架构失败立即停止(默认继续)
  -KeepTemp                保留临时目录(默认成功后清理)
  -DryRun                  只自检 + 打印命令, 不真正构建
  -Help                    显示本帮助

示例:
  ... -DryRun                                  # 先验证环境
  ...                                          # 一键构建两种架构
  ... -Abi x86_64 -OutputDir D:\apk            # 只构建模拟器包

退出码: 0=全部成功  1=有架构失败  2=环境自检失败
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

Write-Log "JMComic APK 一键构建(Windows -> WSL) v$ScriptVersion" STEP
Write-Log "脚本:       $PSCommandPath"
Write-Log "执行日志:   $LogFile"
Write-Log "临时目录:   $TempDir(构建成功后自动清理; -KeepTemp 可保留)"
Add-Diag "===== JMComic APK build started (v$ScriptVersion) ====="
Add-Diag "PSVersion: $($PSVersionTable.PSVersion)  OS: $($PSVersionTable.OS)"

# ------------------------------------------------------------------ ABI 归一化
$AbiNorm = @()
foreach ($a in $Abi) {
    foreach ($piece in ($a -split "[,\s]+")) {
        if (-not $piece) { continue }
        switch ($piece.ToLower()) {
            "both"      { $AbiNorm += "arm64-v8a"; $AbiNorm += "x86_64" }
            "all"       { $AbiNorm += "arm64-v8a"; $AbiNorm += "x86_64" }
            "arm64"     { $AbiNorm += "arm64-v8a" }
            "arm64-v8a" { $AbiNorm += "arm64-v8a" }
            "x86_64"    { $AbiNorm += "x86_64" }
            "x86-64"    { $AbiNorm += "x86_64" }
            default {
                Write-Log "不支持的 ABI: '$piece'(支持 arm64-v8a / x86_64 / both)" ERROR
                Show-Usage
                exit 2
            }
        }
    }
}
# 去重(保持顺序)
$AbiUnique = @()
foreach ($a in $AbiNorm) { if ($AbiUnique -notcontains $a) { $AbiUnique += $a } }
$AbiNorm = $AbiUnique
if ($AbiNorm.Count -eq 0) {
    Write-Log "没有有效的 ABI" ERROR
    exit 2
}
Write-Log "目标架构: $($AbiNorm -join ', ')(一个 APK 只含一种 ABI，分别构建)" OK

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
    Write-Log "控制面板->程序->启用或关闭 Windows 功能->勾选 WSL 后重启" ERROR
    exit 2
}

function Get-WslDistroList {
    $list = @()
    try {
        # wsl -l 输出是 UTF-16LE，中文代码页下直接读会乱码，临时切 Unicode，
        # 读完立刻恢复原编码(wsl.exe 的普通输出会按控制台代码页自动转码，
        # 不需要也不应该改成 UTF-8，否则 Write-Host 的中文会乱)。
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

# ------------------------------------------------------------------ 3. 项目路径
# 项目路径定位顺序：
#   1) -ProjectPath 显式指定
#   2) 从脚本所在目录逐级向上，找含 android\build_android.sh(或 android\tools\wsl_build_apk.sh)的目录
#   3) 再从当前工作目录逐级向上找一遍
# 这样脚本被移动/复制到仓库内外任何位置都能用(不再假设固定相对层数——
# 早先写死 $PSScriptRoot\..\..，脚本从 android\tools 挪到 android 就找不到仓库了)。
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
# 注意：wsl.exe 自己解析命令行时会吃掉反斜杠(PowerShell 走 CreateProcess 命令行，
# Git Bash 直接 exec argv 不会触发)，所以这里必须把 Windows 路径换成正斜杠再传。
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

$ScriptInWsl = "android/$BuildScript"
& wsl.exe -d $Distro -- test -f "$RepoWsl/$ScriptInWsl"
if ($LASTEXITCODE -ne 0) {
    Write-Log "WSL 中找不到构建脚本: $RepoWsl/$ScriptInWsl" ERROR
    Write-Log "检查仓库是否完整，或用 -BuildScript 指定其它脚本" ERROR
    exit 2
}
Write-Log "构建脚本(WSL):   $ScriptInWsl" OK

# ------------------------------------------------------------------ 4. 构建模式 + 构建树
$UseWslFlow = ($BuildScript -match "wsl_build_apk\.sh$")
if ($UseWslFlow) {
    Write-Log "构建模式: WSL 一体化流程(同步到 ext4 -> 按架构构建 -> 自动收集回仓库)"
} else {
    Write-Log "构建模式: 单次运行 $BuildScript(--abi 逗号列表)，产物取 android\dist"
    Write-Log "提醒: 该模式直接用宿主编译(不走 ext4 缓存)，且 pyside6-android-deploy 要求宿主 Python <= 3.11" WARN
}

if (-not $BuildWork) {
    $homeOut = & wsl.exe -d $Distro -- bash -lc 'echo $HOME' 2>$null
    $wslHome = ("$homeOut" -replace "`0", "").Trim()
    if (-not $wslHome) { $wslHome = "/home/$Distro" }
    $BuildWork = "$wslHome/jmcomic-build"
}
Write-Log "WSL 构建树(JM_WORK): $BuildWork"
if ($UseWslFlow) {
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
}

# ------------------------------------------------------------------ 5. 输出目录
try {
    New-Item -ItemType Directory -Force -Path $OutputDir -ErrorAction Stop | Out-Null
    $OutputDir = (Resolve-Path -LiteralPath $OutputDir -ErrorAction Stop).Path
} catch {
    Write-Log "输出目录不可用: $OutputDir($($_.Exception.Message))" ERROR
    exit 2
}
Write-Log "输出目录: $OutputDir" OK
if ($AppVersion) { Write-Log "APK 版本号: $AppVersion(来源: $AppVersionSrc)" OK }
else { Write-Log "APK 版本号: 使用构建脚本默认值(tools/patch_buildozer_spec.py 的 AppVersion)" }

$ScriptStart = Get-Date
Add-Diag "preflight OK: distro=$Distro repoWsl=$RepoWsl buildWork=$BuildWork out=$OutputDir abis=$($AbiNorm -join ',')"

# ------------------------------------------------------------------ WSL 命令执行器
# 退出码放全局变量 $global:LastWslExit，函数本身不 return 任何值。
# 两个坑都踩过，别再改回去：
#   1) 不能 `$rc = Invoke-WslCommand ...` —— native 命令的 stdout 会混进函数
#      返回值，$rc 拿到的不是退出码而是一堆输出文本；
#   2) 输出直接继承控制台(不走 PS 流水线) —— wsl.exe 会按控制台代码页转码，
#      中文不乱码；一旦被捕获(赋值/管道)就变成 UTF-8 裸字节，中文全乱。
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

# 收集某个架构本次新产出的 APK(仓库 android\ 或 android\dist)
function Get-NewArtifact {
    param(
        [string]$SubDir,
        [string]$Pattern,
        [datetime]$Since
    )
    $dir = Join-Path $ProjectPath $SubDir
    if (-not (Test-Path -LiteralPath $dir)) { return $null }
    return Get-ChildItem -LiteralPath $dir -Filter $Pattern -File |
        Where-Object { $_.LastWriteTime -gt $Since } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

$results = @()

# ------------------------------------------------------------------ DryRun
if ($DryRun) {
    Write-Log "================ DryRun：只自检，不构建 ================" STEP
    if ($UseWslFlow) {
        foreach ($abiName in $AbiNorm) {
            $cmd = "export JM_WORK='$BuildWork'; cd '$RepoWsl' && bash 'android/$BuildScript' --abi '$abiName'"
            if ($AppVersion) { $cmd += " --version '$AppVersion'" }
            Write-Log "[DryRun] 将执行($abiName): bash -lc `"$cmd`""
            $cmd2 = "export JM_WORK='$BuildWork'; cd '$RepoWsl/android' && bash 'tools/wsl_collect_apk.sh'"
            Write-Log "[DryRun] 将执行($abiName 收集): bash -lc `"$cmd2`""
        }
    } else {
        $abisArg = $AbiNorm -join ","
        $cmd = "export JM_WORK='$BuildWork'; cd '$RepoWsl/android' && bash '$BuildScript' --abi '$abisArg'"
        if ($AppVersion) { $cmd += " --version '$AppVersion'" }
        Write-Log "[DryRun] 将执行(全部架构一次): bash -lc `"$cmd`""
        Write-Log "[DryRun] 产物目录: $ProjectPath\android\dist\JMComic-*-<abi>-debug.apk"
    }
    Write-Log "DryRun 自检通过：WSL/发行版/项目路径/构建脚本/构建树均可用" OK
    Write-Log "去掉 -DryRun 即可开始真正构建" OK
    if (-not $KeepTemp) {
        try { Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction Stop } catch { }
    }
    exit 0
}

# ------------------------------------------------------------------ 构建
$overallOk = $true

if ($UseWslFlow) {
    # ---- 模式 A：按架构分别构建(wsl_build_apk.sh + wsl_collect_apk.sh) ----
    foreach ($abiName in $AbiNorm) {
        $abiSw = [System.Diagnostics.Stopwatch]::StartNew()
        $abiStart = Get-Date
        Write-Log "================ 开始构建架构: $abiName ================" STEP

        $buildCmd = "export JM_WORK='$BuildWork'; cd '$RepoWsl' && bash 'android/$BuildScript' --abi '$abiName'"
        if ($AppVersion) { $buildCmd += " --version '$AppVersion'" }
        Invoke-WslCommand $buildCmd "调用 WSL 构建($abiName)"
        $code = $global:LastWslExit

        $failed = $false
        $failNote = ""
        if ($code -ne 0) {
            $failed = $true
            $failNote = "WSL 构建失败(退出码 $code)"
        }

        # 收集回 Windows 仓库(成功才收；失败时下面统一归档日志)
        if (-not $failed) {
            $collectCmd = "export JM_WORK='$BuildWork'; cd '$RepoWsl/android' && bash 'tools/wsl_collect_apk.sh'"
            Invoke-WslCommand $collectCmd "收集产物回 Windows 仓库($abiName)"
            $ccode = $global:LastWslExit
            if ($ccode -ne 0) {
                $failed = $true
                $failNote = "wsl_collect_apk.sh 失败(退出码 $ccode)"
            }
        }

        # 找到本次新产出的 APK 并复制到输出目录
        if (-not $failed) {
            $apk = Get-NewArtifact -SubDir "android" -Pattern "JMComic-*-$abiName-*.apk" -Since $abiStart
            if (-not $apk) {
                $failed = $true
                $failNote = "构建后未在 $ProjectPath\android 找到 $abiName 的新 APK"
                $existing = Get-ChildItem -LiteralPath (Join-Path $ProjectPath "android") -Filter "*.apk" -File -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending | Select-Object -First 3 -ExpandProperty Name
                if ($existing) { Write-Log "仓库里现有的 APK(供比对): $($existing -join ', ')" WARN }
            } else {
                $dest = Join-Path $OutputDir $apk.Name
                $srcDir = Split-Path -Parent $apk.FullName
                if ((Resolve-Path -LiteralPath $srcDir).Path -eq $OutputDir) {
                    Write-Log "产物已在输出目录，跳过复制: $dest"
                } else {
                try {
                    Copy-Item -LiteralPath $apk.FullName -Destination $dest -Force -ErrorAction Stop
                    Write-Log "已复制产物: $apk.Name -> $dest"
                } catch {
                        $failed = $true
                        $failNote = "复制产物失败: $($_.Exception.Message)"
                    }
                }
                if (-not $failed) {
                    $abiSw.Stop()
                    Write-Log ("[OK] {0} 构建成功: {1} ({2:N1} MB, 耗时 {3})" -f $abiName, $dest, ($apk.Length/1MB), $abiSw.Elapsed.ToString("hh\:mm\:ss")) OK
                    $results += [pscustomobject]@{
                        Abi = $abiName; Success = $true; Artifact = $dest
                        SizeMB = [math]::Round($apk.Length/1MB, 1)
                        Elapsed = $abiSw.Elapsed.ToString("hh\:mm\:ss"); Note = ""
                    }
                }
            }
        }

        if ($failed) {
            $abiSw.Stop()
            Write-Log "[FAIL] $abiName 构建失败: $failNote(耗时 $($abiSw.Elapsed.ToString('hh\:mm\:ss')))" ERROR
            Write-Log "排查: WSL 侧日志见 $ProjectPath\android\build_logs\ ；本脚本日志: $LogFile" ERROR
            $results += [pscustomobject]@{
                Abi = $abiName; Success = $false; Artifact = ""
                SizeMB = 0; Elapsed = $abiSw.Elapsed.ToString("hh\:mm\:ss"); Note = $failNote
            }
            $overallOk = $false
            if ($StopOnError) {
                Write-Log "-StopOnError 已指定，停止后续架构构建" WARN
                break
            }
        }
    }
} else {
    # ---- 模式 B：单次运行(build_android.sh 等)，产物在 android\dist ----
    $abisArg = $AbiNorm -join ","
    $runSw = [System.Diagnostics.Stopwatch]::StartNew()
    $runStart = Get-Date
    Write-Log "================ 开始构建: $abisArg ================" STEP

    $cmd = "export JM_WORK='$BuildWork'; cd '$RepoWsl/android' && bash '$BuildScript' --abi '$abisArg'"
    if ($AppVersion) { $cmd += " --version '$AppVersion'" }
    Invoke-WslCommand $cmd "调用 WSL 构建(全部架构一次)"
    $code = $global:LastWslExit

    foreach ($abiName in $AbiNorm) {
        if ($code -ne 0) {
            $runSw.Stop()
            Write-Log "[FAIL] $abiName 构建失败: WSL 构建失败(退出码 $code)" ERROR
            $results += [pscustomobject]@{
                Abi = $abiName; Success = $false; Artifact = ""
                SizeMB = 0; Elapsed = $runSw.Elapsed.ToString("hh\:mm\:ss"); Note = "WSL 构建失败(退出码 $code)"
            }
            $overallOk = $false
            continue
        }
        $apk = Get-NewArtifact -SubDir "android\dist" -Pattern "JMComic-*-$abiName-*.apk" -Since $runStart
        if (-not $apk) {
            Write-Log "[FAIL] $abiName 构建后未在 android\dist 找到新 APK" ERROR
            $results += [pscustomobject]@{
                Abi = $abiName; Success = $false; Artifact = ""
                SizeMB = 0; Elapsed = $runSw.Elapsed.ToString("hh\:mm\:ss"); Note = "android\dist 中未找到新 APK"
            }
            $overallOk = $false
            continue
        }
        $dest = Join-Path $OutputDir $apk.Name
        try {
            Copy-Item -LiteralPath $apk.FullName -Destination $dest -Force -ErrorAction Stop
        } catch {
            Write-Log "[FAIL] $abiName 复制产物失败: $($_.Exception.Message)" ERROR
            $results += [pscustomobject]@{
                Abi = $abiName; Success = $false; Artifact = ""
                SizeMB = 0; Elapsed = $runSw.Elapsed.ToString("hh\:mm\:ss"); Note = "复制产物失败"
            }
            $overallOk = $false
            continue
        }
        $runSw.Stop()
        Write-Log ("[OK] {0} 构建成功: {1} ({2:N1} MB, 耗时 {3})" -f $abiName, $dest, ($apk.Length/1MB), $runSw.Elapsed.ToString("hh\:mm\:ss")) OK
        $results += [pscustomobject]@{
            Abi = $abiName; Success = $true; Artifact = $dest
            SizeMB = [math]::Round($apk.Length/1MB, 1)
            Elapsed = $runSw.Elapsed.ToString("hh\:mm\:ss"); Note = ""
        }
    }
}

# ------------------------------------------------------------------ 归档 WSL 侧构建日志
if ($UseWslFlow) {
    $logCmd = "export JM_WORK='$BuildWork'; mkdir -p '$RepoWsl/android/build_logs'; cp -f $BuildWork/logs/*.log '$RepoWsl/android/build_logs/' 2>/dev/null || true"
    & wsl.exe -d $Distro -- bash -lc $logCmd 2>$null | Out-Null
}
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
Write-Log ""
Write-Log "================ 构建结果 ================" STEP
$okCount   = 0
$failCount = 0
foreach ($r in $results) {
    if ($r.Success) {
        $okCount++
        Write-Log ("[OK]   {0,-10} {1}  ({2:N1} MB, 耗时 {3})" -f $r.Abi, $r.Artifact, $r.SizeMB, $r.Elapsed) OK
    } else {
        $failCount++
        Write-Log ("[FAIL] {0,-10} {1}  (耗时 {2})" -f $r.Abi, $r.Note, $r.Elapsed) ERROR
    }
}

if ($failCount -eq 0) {
    Write-Log "全部架构构建成功！" OK
    Write-Log "产物目录: $OutputDir" OK
    foreach ($r in $results) {
        Write-Log "  安装: adb install -r `"$($r.Artifact)`"" OK
    }
    Write-Log "提示: 两种 ABI 只能装一个，adb install -r 可直接互相覆盖" OK
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
    Write-Log "完成，耗时总计 $((New-TimeSpan -Start $ScriptStart -End (Get-Date)).ToString('hh\:mm\:ss'))" OK
    exit 0
} else {
    Write-Log "有 $failCount 个架构构建失败，$okCount 个成功" ERROR
    Write-Log "详细构建日志: $ProjectPath\android\build_logs\(已归档到 $OutputDir\logs\)" ERROR
    Write-Log "本脚本执行日志: $LogFile" ERROR
    Write-Log "诊断信息(保留供排查): $DiagFile" ERROR
    $failedAbis = $results | Where-Object { -not $_.Success } | ForEach-Object { $_.Abi }
    Write-Log "修复后可单独重跑失败架构，例如: -Abi $($failedAbis -join ' -Abi ')" ERROR
    Write-Log "完成(有失败)，总耗时 $((New-TimeSpan -Start $ScriptStart -End (Get-Date)).ToString('hh\:mm\:ss'))" ERROR
    exit 1
}
