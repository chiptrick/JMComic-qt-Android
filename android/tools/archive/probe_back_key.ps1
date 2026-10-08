# Back-key behaviour probe on the real device (ASCII only on purpose)
$adb = "adb.exe"
$serial = "<DEVICE_SERIAL>"
$pkg = "org.jmcomic.jmcomic"
function A { param([Parameter(ValueFromRemainingArguments=$true)]$a) & $adb -s $serial @a 2>&1 }

function Focus {
    $f = (A shell dumpsys window | Select-String "mCurrentFocus" | Select-Object -First 1)
    $a = (A shell dumpsys activity activities | Select-String "topResumedActivity|ResumedActivity" | Select-Object -First 2)
    return ("focus: " + ($f -join "").Trim() + " | " + ($a -join " ; ").Trim())
}

Write-Host "== force-stop and start =="
A shell am force-stop $pkg | Out-Null
Start-Sleep -Milliseconds 500
A shell am start -n "$pkg/org.qtproject.qt.android.bindings.QtActivity" | Out-Null
Start-Sleep -Seconds 25
Write-Host ("after start : " + (Focus))
Write-Host ("pid         : " + ((A shell pidof $pkg) -join ""))
Write-Host "== clear logcat then press BACK =="
A logcat -c -b all | Out-Null
A shell input keyevent KEYCODE_BACK | Out-Null
Start-Sleep -Seconds 4
Write-Host ("after back 1: " + (Focus))
Write-Host ("pid         : " + ((A shell pidof $pkg) -join ""))
Start-Sleep -Seconds 3
Write-Host ("after +3s   : " + (Focus))
Write-Host ("pid         : " + ((A shell pidof $pkg) -join ""))
Write-Host "== recent app logcat =="
A logcat -d -v time | Select-String -Pattern "jmcomic|QtNative|QtActivity|ActivityManager.*jmcomic|back|Key" | Select-Object -Last 40 | ForEach-Object { $_.ToString() }
