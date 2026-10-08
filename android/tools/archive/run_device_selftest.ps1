# 手动跑一次应用自检：装好的 APK + 标记文件 + 等它把自检块写完，然后拉日志
param(
    [string]$Serial = "<DEVICE_SERIAL>",
    [string]$Pkg = "org.jmcomic.jmcomic",
    [int]$WaitSec = 120
)
$ErrorActionPreference = "Continue"
$adb = "adb.exe"
$out = "C:\path\to\JMComic-qt\android\build_logs"

function Adb { param([Parameter(ValueFromRemainingArguments = $true)]$a) & $adb -s $Serial @a 2>&1 }

Adb shell input keyevent KEYCODE_WAKEUP | Out-Null
Adb shell wm dismiss-keyguard | Out-Null
Adb shell "run-as $Pkg touch files/device_verify" | Out-Null
Adb shell "run-as $Pkg touch files/device_keys" | Out-Null
Adb shell "run-as $Pkg touch files/device_reader" | Out-Null
Adb shell am force-stop $Pkg | Out-Null
Start-Sleep -Seconds 3
Adb logcat -c -b all | Out-Null
Adb shell am start -n "$Pkg/org.kivy.android.PythonActivity" | Out-Null
Start-Sleep -Seconds 4
Adb shell monkey -p $Pkg -c android.intent.category.LAUNCHER 1 | Out-Null
Write-Host "已启动，等 $WaitSec 秒让自检跑完…"
Start-Sleep -Seconds $WaitSec

$startup = (Adb shell "run-as $Pkg cat files/android_startup.log") -join "`n"
$startup | Out-File -Encoding utf8 "$out\device_startup_manual.log"
$appLog = (Adb shell "run-as $Pkg cat files/state/jmcomic-qt/logs/20261006.log") -join "`n"
$appLog | Out-File -Encoding utf8 "$out\device_app_manual.log"
$crash = (Adb logcat -d -b crash) -join "`n"
$crash | Out-File -Encoding utf8 "$out\device_crash_manual.txt"
Write-Host ("startup 行数=" + ($startup -split "`n").Count + " app 行数=" + ($appLog -split "`n").Count)
Write-Host ("crash 缓冲=" + ($crash.Length) + " 字节; 进程 pid=" + ((Adb shell "pidof $Pkg") -join ""))
Write-Host "=== 自检关键行 ==="
($startup -split "`n") | Select-String -Pattern "分割|真机样本|真机看图页|Pillow|解密自检|Qt分割|任务=|解密统计" | ForEach-Object { Write-Host ("  " + $_.Line.Trim()) }
