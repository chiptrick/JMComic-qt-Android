# Back-key behaviour probe v2 (device must be awake, app in foreground)
$adb = "adb.exe"
$serial = "<DEVICE_SERIAL>"
$pkg = "org.jmcomic.jmcomic"
$act = "org.kivy.android.PythonActivity"
function A { param([Parameter(ValueFromRemainingArguments=$true)]$a) & $adb -s $serial @a 2>&1 }
function FocusText {
    $f = (A shell dumpsys window | Select-String "mCurrentFocus" | Select-Object -First 1)
    return ($f -join "").Trim()
}
function Pid { return ((A shell pidof $pkg) -join "").Trim() }

Write-Host ("wakefulness: " + ((A shell dumpsys power | Select-String "mWakefulness=" | Select-Object -First 1) -join "").Trim())
A shell input keyevent KEYCODE_WAKEUP | Out-Null
Start-Sleep -Milliseconds 800
A shell wm dismiss-keyguard | Out-Null
Start-Sleep -Milliseconds 800
A shell am force-stop $pkg | Out-Null
Start-Sleep -Milliseconds 500
Write-Host ("start result: " + ((A shell am start -n "$pkg/$act") -join " "))
Start-Sleep -Seconds 22
Write-Host ("focus now  : " + (FocusText))
Write-Host ("pid        : " + (Pid))
$focus = FocusText
if ($focus -notmatch "jmcomic") {
    Write-Host "APP NOT IN FOREGROUND - aborting back-key test (will not touch the phone)"
    exit 0
}
A logcat -c -b all | Out-Null
A shell input keyevent KEYCODE_BACK | Out-Null
Start-Sleep -Seconds 3
Write-Host ("after back : " + (FocusText))
Write-Host ("pid        : " + (Pid))
Start-Sleep -Seconds 3
Write-Host ("after +3s  : " + (FocusText))
Write-Host ("pid        : " + (Pid))
Write-Host "== activity state =="
A shell dumpsys activity activities | Select-String -Pattern "jmcomic" | Select-Object -First 12 | ForEach-Object { $_.ToString().Trim() }
