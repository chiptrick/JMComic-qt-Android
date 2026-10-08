# android/tools/env.ps1 —— 公共路径解析（被 android/tools 下的 .ps1 dot-source）
#
# 对应 env.sh，变量名保持一致：
#   $JmRepo   仓库根。默认＝本文件所在目录往上两级
#   $JmAdb    adb 可执行文件。默认从 PATH 找，找不到再按 ANDROID_HOME / 常见 SDK 路径找
#   $JmSerial 目标设备序列号。默认取 `adb devices` 里第一个已授权设备
#
# 用法（在 param() 块之后）：
#     . "$PSScriptRoot\env.ps1"
#
# 三个值都可以用同名环境变量 JM_REPO / JM_ADB / JM_SERIAL 覆盖。

$JmToolsDir = $PSScriptRoot
if (-not $env:JM_REPO) {
    $env:JM_REPO = (Resolve-Path (Join-Path $JmToolsDir '..\..')).Path
}

if (-not $env:JM_ADB) {
    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) { $env:JM_ADB = $cmd.Source }
    else {
        $roots = @($env:ANDROID_HOME, $env:ANDROID_SDK_ROOT,
                   (Join-Path $env:LOCALAPPDATA 'Android\Sdk')) | Where-Object { $_ }
        foreach ($r in $roots) {
            $p = Join-Path $r 'platform-tools\adb.exe'
            if (Test-Path $p) { $env:JM_ADB = $p; break }
        }
    }
}

if (-not $env:JM_SERIAL -and $env:JM_ADB -and (Test-Path $env:JM_ADB)) {
    $line = & $env:JM_ADB devices 2>$null |
        Where-Object { $_ -match '\sdevice\s*$' } | Select-Object -First 1
    if ($line) { $env:JM_SERIAL = ($line -split '\s+')[0] }
}

$JmRepo = $env:JM_REPO
$JmAdb = $env:JM_ADB
$JmSerial = $env:JM_SERIAL
