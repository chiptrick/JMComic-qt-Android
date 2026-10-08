#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 等脱离式构建真正结束再收集(踩过的坑：构建还没结束就 collect，拿到的是上一版 APK)
set -u
LOG="$JM_WORK/logs/detached_build.log"
TIMEOUT=${1:-2400}
i=0
while [ "$i" -lt "$TIMEOUT" ]; do
    if grep -q "===== .* 结束 =====" "$LOG" 2>/dev/null; then
        echo "构建已结束:"
        grep -E "===== \[.*\] [0-9]+\.|buildozer exit=|结束" "$LOG" | tail -5
        exit 0
    fi
    if ! pgrep -f wsl_build_apk.sh > /dev/null 2>&1; then
        echo "构建进程已不在(可能是失败退出):"
        tail -20 "$LOG"
        exit 1
    fi
    i=$((i + 10))
    sleep 10
done
echo "等待超时(${TIMEOUT}s)"
exit 1
