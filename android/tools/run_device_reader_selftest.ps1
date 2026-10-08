# 干净地跑一次"看图界面自检"：重新打标记 -> 启动 -> 轮询等自检块落盘
# 用法: pwsh -File android/tools/run_device_reader_selftest.ps1 [-Serial <序列号>]
param(
    [string]$Serial = "",
    [string]$Pkg = "org.jmcomic.jmcomic",
    [int]$TimeoutSec = 240
)
. "$PSScriptRoot\env.ps1"
if (-not $Serial) { $Serial = $JmSerial }
if (-not $Serial) { Write-Error "没有可用设备：请连接手机，或用 -Serial 指定序列号"; exit 2 }
$ErrorActionPreference = "Continue"
$adb = $JmAdb
$out = Join-Path $JmRepo "android\build_logs"
New-Item -ItemType Directory -Force -Path $out | Out-Null
function Adb { param([Parameter(ValueFromRemainingArguments = $true)]$a) & $adb -s $Serial @a 2>&1 }

Adb shell input keyevent KEYCODE_WAKEUP | Out-Null
Adb shell wm dismiss-keyguard | Out-Null
Adb shell input keyevent KEYCODE_HOME | Out-Null
Start-Sleep -Seconds 2
Write-Host "标记文件:"
Adb shell "run-as $Pkg ls -la files/" | Select-String -Pattern "device_|selftest"
foreach ($m in @("device_verify", "device_keys", "device_reader", "ui_selftest")) {
    Adb shell "run-as $Pkg touch files/$m" | Out-Null
}
Adb shell am force-stop $Pkg | Out-Null
Start-Sleep -Seconds 3
Adb logcat -c -b all | Out-Null
Adb shell am start -n "$Pkg/org.kivy.android.PythonActivity" | Out-Null
Start-Sleep -Seconds 5
Adb shell monkey -p $Pkg -c android.intent.category.LAUNCHER 1 | Out-Null

$deadline = (Get-Date).AddSeconds($TimeoutSec)
$got = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 10
    $txt = ((Adb shell "run-as $Pkg cat files/android_startup.log") -join "`n")
    $focus = ((Adb shell dumpsys window | Select-String "mCurrentFocus" | Select-Object -First 1) -join "")
    $hasReader = $txt -match "device verify \(reader\)"
    $hasSeg = $txt -match "真机看图页分割"
    Write-Host ("  [{0}] focus={1} reader块={2} 看图页对账={3}" -f (Get-Date -Format HH:mm:ss),
        ($focus -replace ".*mCurrentFocus=", "").Trim(), $hasReader, $hasSeg)
    if ($hasReader -and $hasSeg) { $got = $true; break }
    if (-not $hasReader -and $txt -match "没有可打开的漫画") { Write-Host "  (没有可打开的漫画: 网络/登录问题)"; break }
}
$txt = ((Adb shell "run-as $Pkg cat files/android_startup.log") -join "`n")
$txt | Out-File -Encoding utf8 "$out\device_startup_reader.log"
((Adb shell "run-as $Pkg cat files/state/jmcomic-qt/logs/20261006.log") -join "`n") |
    Out-File -Encoding utf8 "$out\device_app_reader.log"
Write-Host ("完成=$got  自检日志 -> device_startup_reader.log")
Write-Host "=== 关键行 ==="
($txt -split "`n") | Select-String -Pattern "分割|真机样本|真机看图页|Pillow|解密自检|Qt分割|reader t=" |
    Select-Object -Last 25 | ForEach-Object { Write-Host ("  " + $_.Line.Trim()) }
