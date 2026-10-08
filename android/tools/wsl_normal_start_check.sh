#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 普通启动路径检查：不创建任何标记文件，确认没有自检开销、也没有报错
set -uo pipefail
ADB="$JM_ADB"
PKG=org.jmcomic.jmcomic
S="${JM_SERIAL:?请设置 JM_SERIAL 或连接一台已授权设备}"
run() { "$ADB" -s "$S" shell "run-as $PKG $*" 2>&1; }

echo "=== 确认没有残留标记文件 ==="
run "ls -l files/sr_selftest files/ui_selftest" || echo "  (两个标记都不存在，正确)"

echo
echo "=== 清日志并普通启动 ==="
"$ADB" -s "$S" shell "run-as $PKG find files -name android_startup.log -delete" >/dev/null 2>&1
"$ADB" -s "$S" shell "run-as $PKG find files/state/jmcomic-qt/logs -type f -delete" >/dev/null 2>&1
"$ADB" -s "$S" shell am force-stop $PKG >/dev/null 2>&1
sleep 2
"$ADB" -s "$S" shell monkey -p $PKG -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
sleep 25

echo "=== 自检日志内容 ==="
run "cat files/android_startup.log"

echo
echo "=== 是否出现自检块(应全部为 0) ==="
echo "sr selftest 次数: $(run "cat files/android_startup.log" | grep -c 'sr selftest' || true)"
echo "ui selftest 次数: $(run "cat files/android_startup.log" | grep -c 'ui selftest' || true)"
echo "native 重定向次数: $(run "cat files/android_startup.log" | grep -c 'native 日志' || true)"

echo
echo "=== 应用日志里的错误(最近 15 条) ==="
LOG=$(run "sh -c 'ls -t files/state/jmcomic-qt/logs/*.log | head -1'" | tr -d '\r')
echo "日志: $LOG"
run "cat $LOG" | grep -E 'ERROR|Traceback|ImportError|AttributeError|Driver not loaded' | tail -15 || echo "  (无错误)"
