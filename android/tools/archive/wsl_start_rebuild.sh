#!/usr/bin/env bash
# 脱离式启动：重编原生库 + 重打 APK
set -uo pipefail
WORK=/root/jmcomic-build
LOG="$WORK/logs/detached_rebuild.log"
mkdir -p "$WORK/logs"

pkill -f pythonforandroid.toolchain 2>/dev/null || true
pkill -f 'buildozer android' 2>/dev/null || true
sleep 3

: > "$LOG"
setsid nohup bash /path/to/JMComic-qt/android/tools/wsl_rebuild_all.sh \
    >> "$LOG" 2>&1 < /dev/null &
echo "已启动, PID=$!"
echo "日志: $LOG"
sleep 8
ps -eo pid,ppid,cmd | grep -E 'wsl_rebuild_all|wsl_build_native|wsl_build_apk|cmake' | grep -v grep | head -4
echo "--- 日志前 6 行 ---"
head -6 "$LOG" 2>/dev/null || echo "(日志还没内容)"
