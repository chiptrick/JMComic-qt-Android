<#
一键真机验证：安装 APK -> 启动 -> 拉取启动自检日志 -> 逐项判定修复是否生效

用法:
    pwsh -File android/tools/verify_on_device.ps1
    可选: -Apk <路径> -Serial <序列号> -SkipInstall

只安装自己构建的调试包 + 读日志，不做其它有副作用的操作。
#>
param(
    [string]$Apk = "",
    [string]$Serial = "",
    [string]$Pkg = "org.jmcomic.jmcomic",
    [switch]$SkipInstall,
    [int]$BootTimeoutSec = 180
)

. "$PSScriptRoot\env.ps1"

$ErrorActionPreference = "Continue"
$adb = $JmAdb
if (-not $Serial) { $Serial = $JmSerial }
if (-not $Serial) { Write-Error "没有可用设备：请连接手机，或用 -Serial 指定序列号"; exit 2 }
if (-not $Apk) {
    # 默认取 android/ 下最新的 apk
    $found = Get-ChildItem (Join-Path $JmRepo "android\*.apk") -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($found) { $Apk = $found.FullName }
}
if (-not $adb -or -not (Test-Path $adb)) { Write-Error "找不到 adb：请安装 platform-tools 或设置 JM_ADB"; exit 2 }
if (-not (Test-Path $Apk)) { Write-Error "找不到 APK: $Apk"; exit 2 }

$outDir = Join-Path (Split-Path $Apk) "build_logs"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Adb {
    param([Parameter(ValueFromRemainingArguments = $true)]$AdbArgs)
    & $adb -s $Serial @AdbArgs 2>&1
}

Write-Host "=== 设备状态 ==="
Write-Host ("get-state: " + ((Adb get-state) -join ""))
$focus = (Adb shell dumpsys window | Select-String "mCurrentFocus" | Select-Object -First 1)
$wake = (Adb shell dumpsys power | Select-String "mWakefulness=" | Select-Object -First 1)
Write-Host ("focus: " + $focus)
Write-Host ("power: " + $wake)
$locked = ("$focus" -match "Keyguard|NotificationShade") -or ("$wake" -match "Asleep")
if ($locked) {
    Write-Host ""
    Write-Host "注意: 设备处于锁屏/息屏。应用进程与自检日志仍会产出，但 UI(抽屉/交互框)需要解锁后人工确认。" -ForegroundColor Yellow
}

if (-not $SkipInstall) {
    Write-Host ""
    Write-Host "=== 安装 APK ($([math]::Round((Get-Item $Apk).Length/1MB,1)) MB) ==="
    # 息屏/锁屏时 vivo 会直接以 INSTALL_FAILED_ABORTED 拒绝安装，先唤醒再装
    Adb shell input keyevent KEYCODE_WAKEUP | Out-Null
    Start-Sleep -Seconds 2
    $r = Adb install -r $Apk
    if (("$r") -notmatch "Success") {
        Write-Host "  首次安装未成功，唤醒屏幕后重试一次…" -ForegroundColor Yellow
        Adb shell input keyevent KEYCODE_WAKEUP | Out-Null
        Adb shell input keyevent KEYCODE_MENU | Out-Null
        Start-Sleep -Seconds 3
        $r = Adb install -r $Apk
    }
    $r | ForEach-Object { Write-Host "  $_" }
    if (("$r") -notmatch "Success") { Write-Error "安装失败"; exit 3 }
}

Write-Host ""
Write-Host "=== 清理旧日志并启动 ==="
Adb logcat -c -b all | Out-Null
Adb shell "run-as $Pkg find files -name android_startup.log -delete" | Out-Null
Adb shell "run-as $Pkg find files/state/jmcomic-qt/logs -type f -delete" | Out-Null
Adb shell am force-stop $Pkg | Out-Null
Start-Sleep -Seconds 2
# 标记文件 -> 让应用自检：sr_selftest 真跑一次超分(证明 HTP 是否生效)，
#                        ui_selftest 用真实窗口几何验证抽屉(不遮挡顶栏 + 点空白处可关闭)
#                        device_verify 15s 后回报解密统计与竖屏排版几何
Adb shell "run-as $Pkg touch files/sr_selftest" | Out-Null
Adb shell "run-as $Pkg touch files/ui_selftest" | Out-Null
Adb shell "run-as $Pkg touch files/device_verify" | Out-Null
# device_keys: 把"应用收到的按键事件"与"窗口生命周期事件"写进日志
# (先确认返回键到底有没有到 Qt 窗口，再谈返回逻辑对不对)
Adb shell "run-as $Pkg touch files/device_keys" | Out-Null
Adb shell am start -n "$Pkg/org.kivy.android.PythonActivity" | Out-Null
Start-Sleep -Seconds 3
Adb shell monkey -p $Pkg -c android.intent.category.LAUNCHER 1 | Out-Null

Write-Host "等待应用写出启动自检日志(最多 $BootTimeoutSec 秒)…"
$startupLog = ""
$deadline = (Get-Date).AddSeconds($BootTimeoutSec)
while ((Get-Date) -lt $deadline) {
    $found = (Adb shell "run-as $Pkg find /data/data/$Pkg -name android_startup.log") -join "`n"
    $hit = ($found -split "`n" | Where-Object { $_ -match "android_startup\.log" } | Select-Object -First 1)
    if ($hit) { $startupLog = $hit.Trim(); break }
    Start-Sleep -Seconds 4
}

if (-not $startupLog) {
    Write-Host "!! 没等到 android_startup.log（应用可能启动就崩了）" -ForegroundColor Red
    Write-Host "--- crash.log ---"
    Adb shell "run-as $Pkg cat files/crash.log" | Select-Object -Last 40
    Write-Host "--- 崩溃缓冲 ---"
    Adb logcat -d -b crash | Select-Object -Last 40
    exit 4
}
Write-Host "自检日志: $startupLog"
# 抽屉自检是分 3 步 deferred 跑的(约 2.3s 后才写完)，等它落盘再读；
# device verify 分两块：(home) 要等首页 /promote+/latest 都解密成功(轮询)，
# (layout) 再把设置页切出来量排版 —— 所以这里等最晚的那块
Start-Sleep -Seconds 6
$verifyDeadline = (Get-Date).AddSeconds(150)
while ((Get-Date) -lt $verifyDeadline) {
    $probe = ((Adb shell "run-as $Pkg cat $startupLog") -join "`n")
    if ($probe -match "===== end device verify \(layout\) =====") { Write-Host "device verify 已落盘"; break }
    Start-Sleep -Seconds 5
}

$localStartup = Join-Path $outDir "device_android_startup.log"
((Adb shell "run-as $Pkg cat $startupLog") -join "`n") | Set-Content -Encoding utf8 $localStartup
$localApp = Join-Path $outDir "device_app.log"
$appLog = ((Adb shell "run-as $Pkg sh -c 'ls -t files/state/jmcomic-qt/logs/*.log 2>/dev/null | head -1'") -join "").Trim()
if ($appLog) {
    ((Adb shell "run-as $Pkg cat $appLog") -join "`n") | Set-Content -Encoding utf8 $localApp
    Write-Host "应用日志: $appLog -> $localApp"
}

$startupAll = Get-Content -Raw -Encoding utf8 $localStartup
# 本地副本是 Set-Content 写的 CRLF，会让 "(...)$" 这类锚定正则匹配不上，先去掉 \r
$startupAll = $startupAll -replace "`r", ""
$app = if (Test-Path $localApp) { (Get-Content -Raw -Encoding utf8 $localApp) -replace "`r", "" } else { "" }
# 抽屉自检结果按行取最后一条（比锚定正则稳）
$drawerLine = (($startupAll -split "`n") | Where-Object { $_ -match "^ui selftest:" } | Select-Object -Last 1)
if (-not $drawerLine) { $drawerLine = "" }
# 只保留最后一轮 diagnostics 块，避免历史内容干扰判定
$blocks = [regex]::Matches($startupAll, "(?s)===== diagnostics \(([^)]*)\) =====(.*?)===== end diagnostics =====")
if ($blocks.Count -gt 0) { $startup = $blocks[$blocks.Count - 1].Groups[2].Value } else { $startup = $startupAll }
# device_verify 块(接口解密统计 + 竖屏排版几何)。分两块写：
#   (home)   首页两个接口都解密成功后的统计与条目数(不切页面，避免取消在途请求)
#   (layout) 切到设置页之后量的排版几何
$homeBlock = ""
$layoutBlock = ""
$hb = [regex]::Match($startupAll, "(?s)===== device verify \(home\) =====(.*?)===== end device verify \(home\) =====")
if ($hb.Success) { $homeBlock = $hb.Groups[1].Value }
$lb = [regex]::Match($startupAll, "(?s)===== device verify \(layout\) =====(.*?)===== end device verify \(layout\) =====")
if ($lb.Success) { $layoutBlock = $lb.Groups[1].Value }
$verifyBlock = $layoutBlock + "`n" + $homeBlock

Write-Host ""
Write-Host "================ 修复项判定 ================"
$results = @()
function Check([string]$Name, [bool]$Ok, [string]$Detail) {
    $script:results += [pscustomobject]@{ 项 = $Name; 结果 = $(if ($Ok) { "PASS" } else { "FAIL" }); 证据 = $Detail }
}
function Field([string]$name) {
    $m = [regex]::Match($startup, "(?m)^\s*" + [regex]::Escape($name) + ":\s*(.*)$")
    return $m.Groups[1].Value.Trim()
}

# --- ⑤ Qt 插件 / 图像格式 / SQLite ---
foreach ($p in @("libplugins_imageformats_qsvg_arm64-v8a.so",
                 "libplugins_iconengines_qsvgicon_arm64-v8a.so",
                 "libplugins_imageformats_qjpeg_arm64-v8a.so",
                 "libplugins_imageformats_qgif_arm64-v8a.so",
                 "libplugins_imageformats_qwebp_arm64-v8a.so",
                 "libplugins_sqldrivers_qsqlite_arm64-v8a.so")) {
    $v = Field $p
    Check ("⑤ " + $p.Replace("libplugins_", "").Replace("_arm64-v8a.so", "") + " 已随包") `
          ($v -and $v -ne "NOT FOUND") $v
}
$fmts = Field "image formats"
foreach ($f in @("jpeg", "gif", "webp", "svg")) { Check "⑤ QImageReader 支持 $f" ($fmts -match $f) $fmts }
$drvCount = [regex]::Matches($app, "Driver not loaded").Count
Check "⑤ 无 'Driver not loaded'(SQLite 驱动生效)" ($drvCount -eq 0) ("命中 $drvCount 次（旧包为数十次）")

# --- ① NPU 超分后端 ---
$libsr = Field "libsr_qnn.so"
$mdir = [regex]::Match($startup, "(?m)^model dir .*$").Value.Trim()
$avail = Field "sr models available"
$err = Field "sr load error"
$engine = Field "sr engine"
$capable = Field "sr htp capable"
$backend = Field "sr backend"
$selftest = Field "selftest"
$realBackend = [regex]::Match($startup, "(?m)^\s*实际后端:\s*(.*)$").Groups[1].Value.Trim()
$selftestOut = [regex]::Match($startup, "(?m)^\s*输出 .*$").Value.Trim()
Check "① libsr_qnn.so 已定位(不再依赖 pyjnius)" ($libsr -and $libsr -ne "NOT FOUND") $libsr
Check "① 模型已落到设备(9 个 onnx)" ($avail -eq "9") ($mdir + " | available=" + $avail)
Check "① 超分后端加载成功" ($engine -match "loaded=True") ($engine + " | load error='" + $err + "'")
Check "① HTP 库存在(能力)" ($capable -eq "True") ("sr htp capable=" + $capable)
Check "① 真实推理自检通过" ($selftest -eq "PASS") ($selftestOut + " => " + $selftest)
Check "① NPU(HTP) 实际生效" ($realBackend -match "Hexagon") ("实际后端: " + $realBackend + " | " + $backend)

# --- ④ 抽屉(真机自检，用真实窗口几何) ---
$drawerBar = [regex]::Match($startupAll, "(?m)^不遮挡顶栏: (True|False) \((.*)\)$")
$drawerBox = [regex]::Match($startupAll, "(?m)^未超出容器: (True|False) \((.*)\)$")
$drawerScrim = [regex]::Match($startupAll, "(?m)^遮罩: (.*)$").Groups[1].Value.Trim()
$drawerClick = [regex]::Match($startupAll, "(?m)^点击后: (.*)$").Groups[1].Value.Trim()
$drawerResult = if ($drawerLine) { ($drawerLine -replace "^ui selftest:\s*", "").Trim() } else { "" }
Check "④ 抽屉不遮挡顶栏(真机几何)" ($drawerBar.Groups[1].Value -eq "True") $drawerBar.Groups[2].Value
Check "④ 抽屉不超出容器(真机几何)" ($drawerBox.Groups[1].Value -eq "True") $drawerBox.Groups[2].Value
Check "④ 遮罩层存在且覆盖" ($drawerScrim -match "visible=True") $drawerScrim
Check "④ 点空白处(遮罩)可关闭抽屉" ($drawerResult -eq "PASS" -and $drawerClick -match "nav.isHidden=True") `
      ($drawerClick + " => ui selftest: " + $drawerResult)

# --- ② 网络：垫片 CurlOpt ---
$curlErr = [regex]::Matches($app, "cannot import name 'CurlOpt'").Count
Check "② 无 CurlOpt ImportError" ($curlErr -eq 0) ("命中 $curlErr 次（旧包每次都命中）")

# --- ③ urllib.request ---
$urllibErr = [regex]::Matches($app, "has no attribute 'request'").Count
Check "③ 无 urllib.request AttributeError" ($urllibErr -eq 0) ("命中 $urllibErr 次")

# --- 追加：jmcomic 图片解密需要的 AsyncSession ---
$asyncErr = [regex]::Matches($app, "AsyncSession").Count
Check "附 jmcomic 图片解密可导入(AsyncSession)" ($asyncErr -eq 0) ("命中 $asyncErr 次")

# --- 追加：pycryptodome/AES 解密(依赖 p4a 的 android 模块) ---
$noAndroid = [regex]::Matches($app, "No module named 'android'").Count
$cffiReject = [regex]::Matches($app, "CFFI with optimize=2").Count
Check "附 图片解密可用(pycryptodome/AES)" ($noAndroid -eq 0 -and $cffiReject -eq 0) `
      ("android 缺失 $noAndroid 次, cffi 被拒 $cffiReject 次")

# --- ① (本轮) 接口解密链：真机上"登录/首页都报错"的根因 ---
# 真机上 AES 必须走 cffi 后端：
#   * p4a 的 Qt bootstrap 原来写死 PYTHONOPTIMIZE=2，pycryptodome 因此放弃 cffi，
#     回落到 ctypes 后端；而 ctypes 后端要 ctypes.pythonapi.PyObject_GetBuffer，
#     在 Android 上解析不到(libpython 是 RTLD_LOCAL 载入的) -> AES 全废
#   * 改成 PYTHONOPTIMIZE=1 后 cffi 后端可用(assert 仍被去掉，行为不变)
$dlopenErr = [regex]::Matches($app, "WebView_AndroidGetJNIEnv").Count
$dlopenErr += [regex]::Matches($app, "dlopen failed").Count
Check "① 无 android 模块 dlopen 失败" ($dlopenErr -eq 0) ("命中 $dlopenErr 次（旧包每次请求都命中）")
$optimize = Field "sys.flags.optimize"
Check "① PYTHONOPTIMIZE 不再是 2(p4a bootstrap 已改)" ($optimize -ne "2") ("sys.flags.optimize=" + $optimize)
$ctypesFinder = Field "ctypes find_library"
Check "① ctypes find_library 可用(p4a 补丁那一行)" ($ctypesFinder -match "^OK") $ctypesFinder
$ctypesUtil = Field "ctypes.util"
Check "① import ctypes.util 成功" ($ctypesUtil -match "^OK") $ctypesUtil
$cryptoBackend = Field "pycryptodome"
Check "① pycryptodome 后端可用(cffi)" ($cryptoBackend -match "backend=cffi") $cryptoBackend
$pyObjectErr = [regex]::Matches($app, "PyObject_GetBuffer").Count
Check "① 无 ctypes.pythonapi 符号缺失(ctypes 后端已不再使用)" ($pyObjectErr -eq 0) ("命中 $pyObjectErr 次")
$jmDecode = [regex]::Match($startup, "(?m)^jmcomic decode_resp_data:\s*(.*)$").Groups[1].Value.Trim()
Check "① jmcomic.decode_resp_data 能解出明文" ($jmDecode -match "^True") $jmDecode
$parseStats = [regex]::Match($verifyBlock, "(?m)^接口解密统计:\s*(.*)$").Groups[1].Value.Trim()
$parseOk = [regex]::Match($parseStats, "ok=(\d+)").Groups[1].Value
$parseFail = [regex]::Match($parseStats, "fail=(\d+)").Groups[1].Value
$parseShape = [regex]::Match($verifyBlock, "(?m)^\s*最后一次:\s*(.*)$").Groups[1].Value.Trim()
# ok=0 且 fail=0 = 一个加密响应都没回来(网络问题)；fail>0 = 解密真的失败
$parseWhy = if ($parseFail -ne "0") { "有解密失败" }
            elseif ($parseOk -eq "0") { "没有响应回来(网络超时? 见最后一处 ERROR)" }
            else { "正常" }
$lastErr = ([regex]::Match($app, "(?m)^\d{4}-\d{2}-\d{2} .*? - ERROR: (.*)$")).Groups[1].Value.Trim()
Check "① 真实接口响应解密成功(首页/登录)" ($parseOk -and [int]$parseOk -ge 1 -and "$parseFail" -eq "0") `
      ("ok=$parseOk fail=$parseFail [$parseWhy] | " + $parseShape)
$homeCount = [regex]::Match($homeBlock, "(?m)^首页列表条目数:\s*(\d+)").Groups[1].Value
Check "① 首页列表真的加载出内容" ($homeCount -and [int]$homeCount -ge 1) `
      ("首页条目数=" + $homeCount + " (等待轮次 " +
       [regex]::Match($homeBlock, "(?m)^等待轮次:\s*(\d+)").Groups[1].Value +
       "; 最后错误=" + $lastErr.Substring(0, [Math]::Min(60, $lastErr.Length)) + ")")
# 只看"解密链"的 Traceback：测速 ping / 网络超时本来就会按 IP 抛异常并记 Error，不算回归
$allTrace = [regex]::Matches($app, "Traceback").Count
$cryptoTrace = 0
foreach ($blk in ($app -split "(?m)^\d{4}-\d{2}-\d{2} ")) {
    if ($blk -match "Traceback" -and $blk -match "Crypto|_raw_api|ctypes|AES|_android") {
        $cryptoTrace++
    }
}
Check "① 应用日志无解密链 Traceback" ($cryptoTrace -eq 0) `
      ("解密链 $cryptoTrace 段 / 全日志 $allTrace 段(其余是测速与网络超时)")

# --- ③ (本轮) 左右并排界面在竖屏下的排版 ---
$settingsDir = [regex]::Match($verifyBlock, "(?m)^settings: outer\.direction=(\S+)").Groups[1].Value
Check "③ 设置页改为上下排列" ($settingsDir -eq "TopToBottom") ("outer.direction=" + $settingsDir)
$navAbove = [regex]::Match($verifyBlock, "(?m)^\s*nav 在内容之上:\s*(\w+)").Groups[1].Value
$navGeo = [regex]::Match($verifyBlock, "(?m)^\s*nav\(4 buttons\)=\((.*?)\) content=\((.*?)\)$")
$contentSize = [regex]::Match($navGeo.Groups[2].Value, "w=(\d+),h=(\d+)")
Check "③ 设置页导航在内容之上(不再挤占宽度)" `
      ($navAbove -eq "True" -and [int]$contentSize.Groups[2].Value -gt 400) `
      ("nav(" + $navGeo.Groups[1].Value + ") content(" + $navGeo.Groups[2].Value + ")")
$rowFit = [regex]::Match($verifyBlock, "(?m)^\s*最宽的横向布局需要 (\d+)px / 可用 (\d+)px .* -> (\S+)$")
Check "③ 设置页没有放不下的横向行" `
      ($rowFit.Groups[3].Value -eq "放得下" -and [int]$rowFit.Groups[2].Value -gt 300) `
      ($rowFit.Groups[1].Value + "px / 可用 " + $rowFit.Groups[2].Value + "px -> " + $rowFit.Groups[3].Value)
$srLayout = [regex]::Match($verifyBlock, "(?m)^sr tool: (.*)$").Groups[1].Value.Trim()
Check "③ 图片超分页改为上下堆叠" ($srLayout -match "上下堆叠") $srLayout
$wrapLine = [regex]::Match($app, "(?m)portrait: 拆分了 (\d+) 个放不下的横向行\(可用 (\d+)px\)")
$wrapCount = if ($wrapLine.Success) { [int]$wrapLine.Groups[1].Value } else { -1 }
Check "③ 单行超宽的工具栏已按竖屏宽度拆行" ($wrapCount -ge 1) `
      ("真机拆了 $wrapCount 行, 可用宽度=" + $wrapLine.Groups[2].Value + "px")

# --- ⑩ (本轮) 首页每行放得下 2 本漫画 ---
# 真机自检用 QListWidget 的真实几何(visualItemRect)数出"每一行几个"，
# 不是按封面宽度估算 —— 估算会被 item 自身的边距骗过去。
$gridLine = [regex]::Match($homeBlock, "(?m)^首页网格: (.*)$").Groups[1].Value.Trim()
Check "⑩ 首页网格几何(接口 403 时列表为空, 只作参考)" ($gridLine.Length -gt 0) $gridLine

# --- ③ (本轮) 分流设置页也改成上下堆叠(真机日志里的堆叠计数) ---
$stackLine = [regex]::Match($app, "(?m)portrait: (\d+) 个\[左导航\+右内容\]页面改为上下堆叠")
$stackCount = if ($stackLine.Success) { [int]$stackLine.Groups[1].Value } else { -1 }
Check "③ 分流设置页(左导航+右内容)已改为上下堆叠" ($stackCount -ge 2) `
      ("真机堆叠了 $stackCount 个这样的页面(设置页 + 分流设置页)")

# --- ② (本轮) 设置页滑动防误触：用 adb 发**真实**触摸事件 ---
# 应用先把目标勾选框的物理像素坐标写进日志，再用 input swipe/tap 打那个坐标，
# 最后读应用自己轮询出来的计数与设置值。三种手势各自验证一件事：
#   * 短距离拖动(位移超过阈值、release 仍在控件内) -> 必须被拦下、设置不变
#   * 长距离滑动 -> 必须仍然能滚动(scrollValue 变化)
#   * 点按 -> 必须仍然生效(设置翻转)
Write-Host ""
Write-Host "=== 阶段2: 滑动防误触(真实触摸事件) ==="
Adb shell input keyevent KEYCODE_WAKEUP | Out-Null
Adb shell wm dismiss-keyguard | Out-Null
Start-Sleep -Seconds 1
Adb shell "run-as $Pkg touch files/ui_touch_selftest" | Out-Null
Adb shell am force-stop $Pkg | Out-Null
Start-Sleep -Seconds 2
Adb shell am start -n "$Pkg/org.kivy.android.PythonActivity" | Out-Null
Start-Sleep -Seconds 3
Adb shell monkey -p $Pkg -c android.intent.category.LAUNCHER 1 | Out-Null

function DeviceText() {
    return (((Adb shell "run-as $Pkg cat $startupLog") -join "`n") -replace "`r", "")
}
function GuardTicks([string]$text) {
    return [regex]::Matches($text,
        "(?m)^\s*t=\s*(\d+)s presses=(\d+) drags=(\d+) suppressed=(\d+) replayed=(\d+) last=(\S*) checkbox=(\w+) Setting\.DownloadAuto=(-?\d+) scrollValue=(-?\d+)/(\d+) contentH=(\d+) target=(\S*) ?(.*)$")
}
function LastTick([string]$text) {
    $all = GuardTicks $text
    if ($all.Count -eq 0) { return $null }
    return $all[$all.Count - 1]
}
# 勾选框状态在 group 7，滚动值在 group 9
function TickChecked($t) { if ($null -eq $t) { return "?" } return $t.Groups[7].Value }
function TickScroll($t) { if ($null -eq $t) { return -1 } return [int]$t.Groups[9].Value }

$rect = $null
$phys = $null
$dpr = 1.0
$td = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $td) {
    $text = DeviceText
    # 用"控件与视口相交的那块"做目标：整行勾选框可能比视口还宽，取控件中心会落到屏幕外
    $m = [regex]::Match($text, "(?m)^\s*visible logical x=(-?\d+) y=(-?\d+) w=(\d+) h=(\d+)")
    $p = [regex]::Match($text, "(?m)^\s*tap point logical=\((-?\d+),(-?\d+)\) physical=\((\d+),(\d+)\) dpr=([\d.]+)")
    if ($m.Success -and $p.Success) {
        $rect = $m; $phys = $p; $dpr = [double]$p.Groups[5].Value
        break
    }
    Start-Sleep -Seconds 4
}

if ($null -eq $rect) {
    Check "② 触摸自检拿到目标坐标" $false "没等到 ui selftest (touch guard) 的坐标行"
} else {
    $tx = [int]$rect.Groups[1].Value; $ty = [int]$rect.Groups[2].Value
    $tw = [int]$rect.Groups[3].Value; $th = [int]$rect.Groups[4].Value
    $px = [int]$phys.Groups[3].Value; $py = [int]$phys.Groups[4].Value
    Write-Host ("目标可见区 logical=({0},{1}) {2}x{3} 点击点物理=({4},{5}) dpr={6}" -f `
        $tx, $ty, $tw, $th, $px, $py, $dpr)
    Check "② 触摸自检拿到可点坐标" `
          ($px -gt 0 -and $py -gt 0 -and $px -lt 4000 -and $py -lt 6000) `
          ("tap physical=($px,$py) dpr=$dpr")

    Start-Sleep -Seconds 3
    $before = LastTick (DeviceText)
    if ($null -eq $before) {
        Check "② 防误触计数器已开始轮询" $false "没读到 t=.. 轮询行"
        $beforeState = "?"; $beforeSuppressed = -1
    } else {
        $beforeState = TickChecked $before
        $beforeSuppressed = [int]$before.Groups[4].Value
        Check "② 防误触计数器已开始轮询" $true `
              ("presses=" + $before.Groups[2].Value + " suppressed=$beforeSuppressed 勾选框=" + $beforeState)
    }

    # 短距离拖动(位移超过阈值，但起点终点都还在控件命中区里)。
    # 勾选框整行都是命中区，所以横向拖动最稳；控件够高时也用一次纵向。
    $slopPx = [math]::Ceiling(16 * $dpr)
    $dragCount = 0
    $movedMax = 0
    $swipes = @()
    $swipes += @{ name = "横向"; x1 = [int](($tx + 0.15 * $tw) * $dpr); y1 = $py
                  x2 = [int](($tx + 0.85 * $tw) * $dpr); y2 = $py }
    if ((0.7 * $th) -gt 20) {
        $swipes += @{ name = "纵向"; x1 = $px; y1 = [int](($ty + 0.15 * $th) * $dpr)
                      x2 = $px; y2 = [int](($ty + 0.85 * $th) * $dpr) }
    }
    foreach ($s in $swipes) {
        $moved = [math]::Max([math]::Abs($s.x2 - $s.x1), [math]::Abs($s.y2 - $s.y1))
        if ($moved -gt $slopPx) {
            $movedMax = [math]::Max($movedMax, $moved)
            $dragCount++
            Adb shell input swipe $s.x1 $s.y1 $s.x2 $s.y2 300 | Out-Null
            Start-Sleep -Seconds 2
        }
    }
    Start-Sleep -Seconds 2
    Check "② 拖动位移超过阈值(测试本身有效)" ($dragCount -gt 0 -and $movedMax -gt $slopPx) `
          ("做了 $dragCount 次拖动, 最大位移 ${movedMax}px vs 阈值 ${slopPx}px")
    $afterDrag = LastTick (DeviceText)
    $dragSuppressed = [int]$afterDrag.Groups[4].Value
    # 判定看"结果"：勾选框状态没被改掉就说明误触被挡住了。
    # (可能是被守卫扣下 press 后丢弃，也可能是被 QScroller 收走手势，两种都算挡住)
    Check "② 短拖动没有把滑动当成点击(状态未变)" ((TickChecked $afterDrag) -eq $beforeState) `
          ("勾选框 " + $beforeState + " -> " + (TickChecked $afterDrag) +
           "; suppressed=$beforeSuppressed->$dragSuppressed, 守卫最后拦截=" + $afterDrag.Groups[6].Value)

    # --- ②b 下拉框/数值框"附近滑动"不再误触(本轮新报的问题) ---
    # 这两个控件在 **press** 时就生效(弹列表 / 加减数值)，所以守卫必须连 press 一起扣住。
    $comboM = [regex]::Match($text, "(?m)^\s*combo: (\S+) 值=(\S*) 可见 x=(-?\d+) y=(-?\d+) w=(\d+) h=(\d+)")
    $comboP = [regex]::Match($text, "(?m)^\s*combo 点击点 logical=\((-?\d+),(-?\d+)\) physical=\((\d+),(\d+)\) dpr=([\d.]+)")
    $spinM = [regex]::Match($text, "(?m)^\s*spin: (\S+) 值=(\S*) 可见 x=(-?\d+) y=(-?\d+) w=(\d+) h=(\d+)")
    $spinP = [regex]::Match($text, "(?m)^\s*spin 点击点 logical=\((-?\d+),(-?\d+)\) physical=\((\d+),(\d+)\) dpr=([\d.]+)")
    if ($comboM.Success -and $comboP.Success -and $spinM.Success -and $spinP.Success) {
        $comboName = $comboM.Groups[1].Value
        $spinName = $spinM.Groups[1].Value
        $cbx = [int]$comboP.Groups[3].Value; $cby = [int]$comboP.Groups[4].Value
        $sbx = [int]$spinP.Groups[3].Value; $sby = [int]$spinP.Groups[4].Value
        Write-Host ("下拉框 {0} 物理=({1},{2}) / 数值框 {3} 物理=({4},{5})" -f `
            $comboName, $cbx, $cby, $spinName, $sbx, $sby)
        $tick0 = LastTick (DeviceText)
        $comboValue0 = $comboM.Groups[2].Value
        $spinValue0 = $spinM.Groups[2].Value
        # 在这两个控件上/附近各横滑一次(位移远超阈值)
        Adb shell input swipe $cbx $cby ($cbx + [int](120 * $dpr)) $cby 250 | Out-Null
        Start-Sleep -Seconds 2
        Adb shell input swipe $sbx $sby ($sbx + [int](120 * $dpr)) $sby 250 | Out-Null
        Start-Sleep -Seconds 3
        $tick1 = LastTick (DeviceText)
        $extras = if ($null -ne $tick1) { $tick1.Groups[13].Value } else { "" }
        $comboOk = ($extras -match ([regex]::Escape($comboName) + "=" + [regex]::Escape($comboValue0)))
        $spinOk = ($extras -match ([regex]::Escape($spinName) + "=" + [regex]::Escape($spinValue0) + "(\s|$)"))
        Check "② 在下拉框上滑动不改它的值" ($comboOk -and $null -ne $tick1) `
              ("$comboName 期望 $comboValue0, 现在: " + $extras)
        Check "② 在数值框上滑动不改它的值" ($spinOk -and $null -ne $tick1) `
              ("$spinName 期望 $spinValue0, 现在: " + $extras)
        Check "② 这两次滑动被守卫/滚动收走(没有当成点击)" `
              ($null -ne $tick1 -and [int]$tick1.Groups[3].Value -gt [int]$tick0.Groups[3].Value) `
              ("drags " + $tick0.Groups[3].Value + " -> " + $tick1.Groups[3].Value)
    } else {
        Check "② 触摸自检拿到下拉框/数值框坐标" $false `
              ("combo=" + $comboM.Success + " spin=" + $spinM.Success)
    }

    # 长距离滑动：滚动必须照常工作(手指往上滑 = 内容往下翻)。
    # barMax=0 说明内容本来就没超出视口，这个页面天生滚不动，不能算失败。
    $screenH = 2800
    $sm = [regex]::Match((DeviceText), "(?m)^\s*screen logical=\d+x\d+ physical≈(\d+)x(\d+)")
    if ($sm.Success) { $screenH = [int]$sm.Groups[2].Value }
    $scrollBefore = TickScroll $afterDrag
    $barMax = [int]$afterDrag.Groups[10].Value
    $fromY = [math]::Min($py + 320, $screenH - 120)
    $toY = [math]::Max(120, $fromY - 300)
    $scrollAfter = $scrollBefore
    if ($barMax -le 0) {
        Check "② 长距离滑动仍然能滚动" $true `
              ("该页内容未超出视口(barMax=$barMax, contentH=" + $afterDrag.Groups[11].Value + ")，无可滚动空间")
    } else {
        for ($i = 0; $i -lt 2; $i++) {
            Adb shell input swipe $px $fromY $px $toY 300 | Out-Null
            Start-Sleep -Seconds 3
            $scrollAfter = TickScroll (LastTick (DeviceText))
            if ($scrollAfter -ne $scrollBefore) { break }
        }
        Check "② 长距离滑动仍然能滚动" ($scrollAfter -ne $scrollBefore) `
              ("scrollValue $scrollBefore -> $scrollAfter (max=$barMax, contentH=" +
               $afterDrag.Groups[11].Value + ", swipe y ${fromY}->${toY})")
    }
    $afterScroll = LastTick (DeviceText)
    Check "② 长距离滑动也没有把滑动当成点击" ((TickChecked $afterScroll) -eq $beforeState) `
          ("勾选框仍为 " + (TickChecked $afterScroll))

    # 点按：必须仍然生效(证明防误触没有把点击一起吃掉)。
    # 允许一次点按丢失(手指/系统都可能吞掉)，第二次仍然点不动才算失败。
    $tapState = TickChecked $afterScroll
    $tapOk = $false
    $afterTap = $null
    for ($i = 0; $i -lt 2; $i++) {
        Adb shell input tap $px $py | Out-Null
        Start-Sleep -Seconds 3
        $afterTap = LastTick (DeviceText)
        if ((TickChecked $afterTap) -ne $tapState) { $tapOk = $true; break }
    }
    if ($null -eq $afterTap) { $afterTap = $afterScroll }
    Check "② 正常点按仍然生效" $tapOk `
          ("勾选框 " + $tapState + " -> " + (TickChecked $afterTap) + " (target=" +
           $afterTap.Groups[12].Value + ")")
    Check "② 真实触摸确实走了防误触守卫" (([int]$afterTap.Groups[2].Value) -ge 1) `
          ("共记录 " + $afterTap.Groups[2].Value + " 次真实按下, " +
           $afterTap.Groups[3].Value + " 次判定为滑动, " +
           $afterTap.Groups[4].Value + " 次被守卫拦下, " +
           $afterTap.Groups[5].Value + " 次重放点按")
}

Write-Host ""
Write-Host "=== 阶段3: 看图界面(菜单整宽/滚动/返回键/图片解密) ==="
Adb shell input keyevent KEYCODE_WAKEUP | Out-Null
Adb shell wm dismiss-keyguard | Out-Null
Start-Sleep -Seconds 1
Adb shell "run-as $Pkg touch files/device_reader" | Out-Null
Adb shell am force-stop $Pkg | Out-Null
Start-Sleep -Seconds 2
$crashBefore = ((Adb logcat -d -b crash) -join "`n")
Adb shell am start -n "$Pkg/org.kivy.android.PythonActivity" | Out-Null
Start-Sleep -Seconds 3
Adb shell monkey -p $Pkg -c android.intent.category.LAUNCHER 1 | Out-Null

$readerBlock = ""
$rd = (Get-Date).AddSeconds(150)
while ((Get-Date) -lt $rd) {
    $text = DeviceText
    $rb = [regex]::Match($text, "(?s)===== device verify \(reader\) =====(.*?)===== end device verify \(reader\) =====")
    if ($rb.Success) { $readerBlock = $rb.Groups[1].Value; break }
    Start-Sleep -Seconds 5
}
if (-not $readerBlock) {
    Check "⑨ 看图自检块已写出" $false "没等到 device verify (reader)"
} else {
    # 图片解密：离线往返(分块倒序 -> SegmentationPicture -> QImage -> 逐像素)
    $decryptPass = [regex]::Match($readerBlock, "(?m)^\s*解密自检: (\w+)")
    $decryptDiff = [regex]::Match($readerBlock, "(?m)^\s*QImage 解码: (.*)$").Groups[1].Value.Trim()
    Check "⑨ 图片解密自检通过(分块倒序还原逐像素一致)" ($decryptPass.Groups[1].Value -eq "PASS") `
          ("解密自检=" + $decryptPass.Groups[1].Value + " | " + $decryptDiff)
    $qimageLine = [regex]::Match($readerBlock, "(?m)^\s*TaskQImage.ConverQImage: (.*)$").Groups[1].Value.Trim()
    Check "⑨ 走应用真实链路(TaskQImage)解码成功" ($qimageLine -match "PASS") $qimageLine
    # 图片分割(分块还原)：合成样本(rem≠0，不能只测 rem=0 的对合) + 真机缓存里的真 webp，
    # 都必须与**独立实现**的官方算法逐像素一致(这才是"错位"问题的真正判定)
    $segSyn = [regex]::Match($readerBlock, "(?m)^\s*图片分割自检\(合成[^)]*\): (\w+)")
    $segSynDetail = [regex]::Match($readerBlock, "(?m)^\s*SegmentationPicture\(合成\): (.*)$").Groups[1].Value.Trim()
    Check "⑨ 图片分割自检(合成样本, 余数 rem≠0, 对齐官方算法)" ($segSyn.Groups[1].Value -eq "PASS") `
          ($segSyn.Value.Trim() + " | " + $segSynDetail)
    $pilLine = [regex]::Match($readerBlock, "(?m)^\s*Pillow ([^:]*): (.*)$")
    if ($pilLine.Success) {
        Write-Host ("  Pillow 能力: " + $pilLine.Groups[1].Value.Trim() + " -> " + $pilLine.Groups[2].Value.Trim()) -ForegroundColor DarkGray
    }
    $segReal = [regex]::Match($readerBlock, "(?m)^\s*图片分割自检\(真机样本[^)]*\): (\w+)")
    if ($segReal.Success) {
        $segRealDetail = [regex]::Match($readerBlock, "(?m)^\s*真机样本还原: (.*)$").Groups[1].Value.Trim()
        Check "⑨ 真机样本(webp)分块还原与官方算法逐像素一致" ($segReal.Groups[1].Value -eq "PASS") `
              ($segReal.Value.Trim() + " | " + $segRealDetail)
    } else {
        Write-Host "  (跳过) 真机样本自检行缺失：应用缓存里还没有真图" -ForegroundColor Yellow
    }
    # 菜单整宽 + 看图区滚动接管
    $toolLine = [regex]::Match($readerBlock, "(?m)^reader tool: (.*)$").Groups[1].Value.Trim()
    Check "⑥ 看图菜单整宽且在屏内(不再超出屏幕)" ($toolLine -match "整宽") $toolLine
    $scrollLine = [regex]::Match($readerBlock, "(?m)^reader 滚动: (.*)$").Groups[1].Value.Trim()
    # 兼容两种行文(旧包写 qtTool:已接管, 新包写 菜单滚动区=已接管滚动)
    Check "⑥ 看图菜单滚动区/看图区滚动已接管" `
          ((($scrollLine -match "qtTool:已接管") -or ($scrollLine -match "菜单滚动区=已接管滚动")) -and `
           (($scrollLine -match "拖动滚动已接管") -or ($scrollLine -match "图片区"))) `
          $scrollLine
    # 图片解码统计(有本地/在线图片时应该 >0 成功)
    $pipeLine = [regex]::Match($readerBlock, "(?m)^图片解码: (.*)$").Groups[1].Value.Trim()
    # 首页网格：真机视口自检(接口 403 时首页列表是空的，所以自检自己临时放两个 item 量)
    $gridSelf = [regex]::Match($readerBlock, "(?m)^\s*首页网格自检: (\w+) \(一行 (\d+) 个")
    $gridGeo = [regex]::Match($readerBlock, "(?m)^\s*反算封面宽: (.*)$").Groups[1].Value.Trim()
    if ($gridSelf.Success) {
        Check "⑩ 首页每行放得下 2 本漫画(真机视口自检)" ($gridSelf.Groups[1].Value -eq "PASS") `
              ($gridSelf.Value.Trim() + " | " + $gridGeo)
    } else {
        Check "⑩ 首页每行放得下 2 本漫画(真机视口自检)" $false "没等到 首页网格自检 行"
    }
    Check "⑨ 图片解码管线有统计(没有线程死亡/失败)" `
          (($pipeLine -match "失败=0") -and ($pipeLine -notmatch "最后错误=[^-]")) $pipeLine

    # --- 用真实触摸驱动看图界面 ---
    $g = [regex]::Match($readerBlock, "(?m)^reader 看图区 global logical=\((-?\d+),(-?\d+)\) (\d+)x(\d+) dpr=([\d.]+)")
    if (-not $g.Success) {
        Check "⑥ 拿到看图区物理坐标" $false "reader 看图区 global 行缺失"
    } else {
        $gx = [int]$g.Groups[1].Value; $gy = [int]$g.Groups[2].Value
        $gw = [int]$g.Groups[3].Value; $gh = [int]$g.Groups[4].Value
        $rdpr = [double]$g.Groups[5].Value
        $cxp = [int](($gx + 0.5 * $gw) * $rdpr)
        $cy1 = [int](($gy + 0.75 * $gh) * $rdpr)
        $cy2 = [int](($gy + 0.25 * $gh) * $rdpr)
        Write-Host ("看图区 logical=({0},{1}) {2}x{3} dpr={4} -> 滑动 ({5},{6})->({5},{7})" -f `
            $gx, $gy, $gw, $gh, $rdpr, $cxp, $cy1, $cy2)
        Check "⑥ 看图区坐标可用" ($gw -gt 100 -and $gh -gt 100 -and $cxp -gt 0) `
              ("看图区 ${gw}x${gh} @($gx,$gy) dpr=$rdpr")
        $rt0 = [regex]::Matches((DeviceText), "(?m)^\s*reader t=\s*(\d+)s 页=(-?\d+)/(-?\d+) v=(-?\d+)/(-?\d+) h=(-?\d+)/(-?\d+) 菜单=(\S+) 拖动=(-?\d+) 滚动次数=(-?\d+)")
        $before = if ($rt0.Count -gt 0) { $rt0[$rt0.Count - 1] } else { $null }
        $swiped = 0
        for ($i = 0; $i -lt 3; $i++) {
            Adb shell input swipe $cxp $cy1 $cxp $cy2 300 | Out-Null
            Start-Sleep -Seconds 2
            $swiped++
            $rt1 = [regex]::Matches((DeviceText), "(?m)^\s*reader t=\s*(\d+)s 页=(-?\d+)/(-?\d+) v=(-?\d+)/(-?\d+) h=(-?\d+)/(-?\d+) 菜单=(\S+) 拖动=(-?\d+) 滚动次数=(-?\d+)")
            if ($rt1.Count -gt 0 -and $null -ne $before) {
                if ([int]$rt1[$rt1.Count - 1].Groups[10].Value -gt [int]$before.Groups[10].Value) { break }
            }
        }
        $rt = [regex]::Matches((DeviceText), "(?m)^\s*reader t=\s*(\d+)s 页=(-?\d+)/(-?\d+) v=(-?\d+)/(-?\d+) h=(-?\d+)/(-?\d+) 菜单=(\S+) 拖动=(-?\d+) 滚动次数=(-?\d+)")
        $last = if ($rt.Count -gt 0) { $rt[$rt.Count - 1] } else { $null }
        if ($null -eq $last) {
            Check "⑥ 看图区拖动滚动生效" $false "没读到 reader 轮询行"
        } else {
            Check "⑥ 看图区能手指拖动滚动" ([int]$last.Groups[10].Value -ge 1) `
                  ("拖动=" + $last.Groups[8].Value + " 次, 触发滚动=" + $last.Groups[10].Value +
                   " 次, v=" + $last.Groups[4].Value + "/" + $last.Groups[5].Value)
        }

        # 返回键：先收菜单 -> 再退看图 -> 最后退到后台(不再白屏)
        # 先看返回键有没有到 Qt 窗口(key diag 会记下来)。到不了就只能靠顶栏返回按钮。
        $keyDiag = [regex]::Match((DeviceText), "(?m)^key diag: 按键=(\d+) Key_Back=(\d+) 窗口事件=(\d+)")
        if ($keyDiag.Success) {
            Check "⑧ 返回键事件确实到达了应用(Key_Back)" ([int]$keyDiag.Groups[2].Value -ge 1) `
                  ("按键事件 " + $keyDiag.Groups[1].Value + " 个, 其中 Key_Back " +
                   $keyDiag.Groups[2].Value + " 个, 窗口事件 " + $keyDiag.Groups[3].Value + " 个")
        } else {
            Check "⑧ 返回键事件确实到达了应用(Key_Back)" $false "没有 key diag 统计行"
        }
        Adb shell input keyevent KEYCODE_BACK | Out-Null
        Start-Sleep -Seconds 3
        $back1 = [regex]::Match((DeviceText), "(?m)^back: (\S+).*$")
        $menus = [regex]::Matches((DeviceText), "(?m)^\s*reader t=\s*\d+s .*菜单=(\S+)")
        $menuLast = if ($menus.Count -gt 0) { $menus[$menus.Count - 1].Groups[1].Value } else { "?" }
        Check "⑦ 返回键能收起看图菜单(菜单在 release 后隐藏)" `
              (($back1.Groups[1].Value -eq "close-read-tool") -or ($menuLast -eq "隐藏")) `
              ("back=" + $back1.Groups[1].Value + " 菜单=" + $menuLast)
        Adb shell input keyevent KEYCODE_BACK | Out-Null
        Start-Sleep -Seconds 3
        $idx = [regex]::Match((DeviceText), "(?m)^\s*reader t=\s*\d+s 页=(-?\d+)/")
        $back2 = ([regex]::Matches((DeviceText), "(?m)^back: (\S+).*$") | Select-Object -Last 1)
        Check "⑧ 返回键能退出看图回到上级" `
              (($back2.Value -match "close-reader") -or ([int]$idx.Groups[1].Value -eq -1)) `
              ("最后一次 back=" + $back2.Value + " 页索引=" + $idx.Groups[1].Value)
        # 连按返回，直到退到根页面(根页面**不能**把 Qt 窗口藏起来)
        $rootOk = $false
        for ($i = 0; $i -lt 6; $i++) {
            Adb shell input keyevent KEYCODE_BACK | Out-Null
            Start-Sleep -Seconds 2
            if ((DeviceText) -match "(?m)^back: root-page") { $rootOk = $true; break }
        }
        $hideCount = [regex]::Matches((DeviceText), "ui: hideEvent").Count
        $minCount = [regex]::Matches((DeviceText), "back: minimize-desktop").Count
        # 关键：不能再出现"Qt 窗口被隐藏而 Activity 还在前台"(实测那正是白屏)
        Check "⑨ 根页面返回不再造成白屏(窗口没被藏起来, 也没用 showMinimized)" `
              ($rootOk -and $hideCount -eq 0 -and $minCount -eq 0) `
              ("back: root-page=$rootOk; hideEvent=$hideCount; showMinimized=$minCount; 最后一次 " +
               ([regex]::Matches((DeviceText), "(?m)^back: (\S+).*$") | Select-Object -Last 1).Value)
    }

    # 看图是否真的用 Qt 做了分割还原(真机上 Pillow 没有 webp 解码器，走 PIL 必然失败)
    $finalPipe = [regex]::Match((DeviceText), "(?m)^图片解码: (.*)$").Groups[1].Value.Trim()
    if (-not $finalPipe) { $finalPipe = $pipeLine }
    $openedOnline = ($readerBlock -match "打开首页第一本")
    if ($finalPipe -match "Qt分割=(\d+)") {
        $qtSeg = [int]$Matches[1]
        if ($openedOnline) {
            Check "⑨ 真机看图页确实走了 Qt 分割还原(Pillow 无 webp 解码器)" ($qtSeg -ge 1) $finalPipe
        } else {
            Write-Host ("  (提示) 打开的是本地漫画，无分割还原: " + $finalPipe) -ForegroundColor DarkGray
        }
    } else {
        Check "⑨ 真机看图页确实走了 Qt 分割还原(Pillow 无 webp 解码器)" $false ("统计行缺 Qt分割= : " + $finalPipe)
    }
    # 真数据对账：看图界面当前页(服务端原始字节) + 它自己的 saveParams，必须与官方算法逐像素一致
    $realPage = [regex]::Match((DeviceText), "(?m)^\s*真机看图页分割: (\w+)")
    $realPageDetail = [regex]::Match((DeviceText), "(?m)^\s*真机看图页还原: (.*)$").Groups[1].Value.Trim()
    $realPageInfo = [regex]::Match((DeviceText), "(?m)^\s*真机看图页: (.*)$").Groups[1].Value.Trim()
    if ($realPage.Success -and $realPage.Groups[1].Value -ne "SKIP") {
        Check "⑨ 真机看图页(真 webp + 真参数)分割与官方算法逐像素一致" `
              ($realPage.Groups[1].Value -eq "PASS") ($realPageInfo + " | " + $realPageDetail)
    } else {
        Write-Host ("  (跳过) 真机看图页对账: " + $realPageInfo) -ForegroundColor Yellow
    }
    # 老包在同样的操作下会刷 SegmentationPicture failed / cannot identify image file
    $segFail = [regex]::Matches((DeviceText), "SegmentationPicture failed").Count
    Check "⑨ 应用日志里没有 SegmentationPicture 失败(Pillow 缺 webp 解码器那条链已断开)" `
          ($segFail -eq 0) ("命中 $segFail 次")
}

# --- ⑩ 改设置不再崩溃(真机上原来改任何选项都会 SIGABRT) ---
$crashAfter = ((Adb logcat -d -b crash) -join "`n")
$crashNew = 0
foreach ($line in ($crashAfter -split "`n")) {
    if ($line -match "Fatal signal" -and $crashBefore -notmatch [regex]::Escape($line)) { $crashNew++ }
}
$deadlock = [regex]::Matches($app, "deadlock protector").Count
Check "⑩ 本轮没有新的 native 崩溃" ($crashNew -eq 0) ("新增崩溃记录 $crashNew 条")
Check "⑩ 应用日志里没有 eglSurface 死锁告警" ($deadlock -eq 0) ("deadlock protector 命中 $deadlock 次")
$deferLine = [regex]::Match($app, "(?m)window guard: 延后显示=(\d+) 已显示=(\d+) 延后隐藏=(\d+) 延后关闭=(\d+) 子控件覆盖层=(\d+)")
if ($deferLine.Success) {
    Check "⑩ 提示条/加载框/遮罩对话框已改成子控件(不再开第二个顶层窗口)" `
          ([int]$deferLine.Groups[5].Value -ge 2) `
          ("子控件覆盖层=" + $deferLine.Groups[5].Value + " 个; 延后显示=" +
           $deferLine.Groups[1].Value + " 已显示=" + $deferLine.Groups[2].Value +
           " 延后关闭=" + $deferLine.Groups[4].Value)
} else {
    Check "⑩ 提示条/加载框/遮罩对话框已改成子控件(不再开第二个顶层窗口)" $false "没找到 window guard 统计"
}
$backBtn = [regex]::Matches($app, "顶栏加了返回按钮").Count
Check '⑧ 顶栏已加"返回"按钮(返回键到不了 Qt 时的兜底入口)' ($backBtn -ge 1) ("命中 $backBtn 次")
$appAlive = ((Adb shell pidof $Pkg) -join "").Trim()
Check "⑩ 应用进程仍然存活(没有崩溃退出)" ($appAlive -ne "") ("pid=" + $appAlive)

Write-Host ""
$results | Format-Table -AutoSize -Wrap
$fails = @($results | Where-Object { $_.结果 -eq "FAIL" })
Write-Host ("通过 {0}/{1}" -f ($results.Count - $fails.Count), $results.Count)
if ($fails.Count -gt 0) {
    Write-Host "未通过项:" -ForegroundColor Red
    $fails | ForEach-Object { Write-Host ("  - " + $_.项 + "   证据: " + $_.证据) -ForegroundColor Red }
}

Write-Host ""
Write-Host "=== 网络相关日志(最近 10 条 error) ==="
($app -split "`n" | Select-String "ERROR" | Select-Object -Last 10) | ForEach-Object { Write-Host ("  " + $_.Line.Trim()) }

Write-Host ""
Write-Host "日志已保存: $localStartup"
if (Test-Path $localApp) { Write-Host "            $localApp" }
if ($fails.Count -gt 0) { exit 1 }
exit 0
