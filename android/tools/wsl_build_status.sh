#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 构建状态速查(供宿主会话调用)
set -uo pipefail
B="$JM_WORK/src/android/.buildozer/android/platform/build-arm64-v8a"
L="$JM_WORK/logs/detached_build.log"
echo "失败次数: $(grep -c 'Command failed' "$L" 2>/dev/null || echo 0)"
echo "编译进程: $(pgrep -c -f pythonforandroid.toolchain 2>/dev/null || echo 0)"
echo "构建目录: $(du -sh "$B" 2>/dev/null | cut -f1)"
echo "已解包 recipe: $(ls "$B/build/other_builds" 2>/dev/null | wc -l) 个"
echo "dists: $(ls "$B/dists" 2>/dev/null | tr '\n' ' ')"
APK=$(ls -t "$JM_WORK/src/android/bin/"*.apk \
            "$JM_WORK/src/android/"*.apk 2>/dev/null | head -1)
echo "APK: ${APK:-尚未生成}"
if [ -n "$APK" ]; then ls -sh "$APK"; fi
echo "--- 日志最后 5 行关键信息 ---"
grep -E '\[INFO\]|Command failed|ERROR|Traceback' "$L" 2>/dev/null | tail -5 | cut -c1-150
