#!/usr/bin/env bash
# 提取 gradle 失败的具体原因
set -uo pipefail
L=/root/jmcomic-build/logs/detached_build.log
echo "=== gradle 相关错误行 ==="
grep -nE "FAILURE:|What went wrong|Could not|Couldn't|error:|Caused by|Execution failed|> Task .*FAILED|A problem occurred" "$L" 2>/dev/null | tail -20 | cut -c1-200
echo
echo "=== gradle 命令与附近输出 ==="
N=$(grep -n 'gradlew failed' "$L" | head -1 | cut -d: -f1)
[ -n "${N:-}" ] && sed -n "$((N > 60 ? N - 60 : 1)),${N}p" "$L" | tr '\r' '\n' | grep -vE '^\s*$' | tail -30 | cut -c1-190
echo
echo "=== p4a gradle 工程是否生成 ==="
ls /root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic/ 2>/dev/null | head -12
echo "--- gradle 缓存/包装器 ---"
ls -d /root/.gradle 2>/dev/null && du -sh /root/.gradle 2>/dev/null
ls /root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic/gradle/wrapper 2>/dev/null
