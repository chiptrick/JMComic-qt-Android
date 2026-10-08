#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 让 APK 构建在 WSL 内脱离式运行(setsid+nohup)，不受宿主会话/作业生命周期影响
# 进度: tail -f "$JM_WORK/logs/detached_build.log"
set -uo pipefail
WORK="$JM_WORK"
LOG="$WORK/logs/detached_build.log"
mkdir -p "$WORK/logs"

# 先确保没有残留的构建进程/作业
pkill -f pythonforandroid.toolchain 2>/dev/null || true
pkill -f 'buildozer android' 2>/dev/null || true
sleep 3

: > "$LOG"
setsid nohup bash "$JM_REPO/android/tools/wsl_build_apk.sh" \
    >> "$LOG" 2>&1 < /dev/null &
echo "已启动脱离式构建, PID=$!"
echo "日志: $LOG"
sleep 5
ps -eo pid,ppid,cmd | grep -E 'wsl_build_apk|pythonforandroid' | grep -v grep | head -3
