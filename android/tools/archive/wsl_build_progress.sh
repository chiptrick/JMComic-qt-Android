#!/usr/bin/env bash
# 构建进度详情：阶段、.buildozer 状态、编译进程
set -uo pipefail
W=/root/jmcomic-build
L="$W/logs/detached_build.log"
B="$W/src/android/.buildozer/android/platform/build-arm64-v8a"

echo "=== 日志: $(wc -l < "$L" 2>/dev/null || echo 0) 行 ==="
grep -nE '^=====' "$L" 2>/dev/null | tail -10
echo
echo "=== .buildozer 大小 ==="
du -sh "$W/src/android/.buildozer" 2>/dev/null || echo "(不存在)"
echo "--- platform/build-arm64-v8a 顶层 ---"
ls "$B" 2>/dev/null
echo "--- dists ---"
ls "$B/dists" 2>/dev/null || echo "(空)"
echo "--- build/other_builds ---"
ls "$B/build/other_builds" 2>/dev/null | head -20 || echo "(空)"
echo "--- packages(已预置源码) ---"
ls "$B/packages" 2>/dev/null | head -20
echo
echo "=== 编译进程 ==="
ps -eo pid,etime,cmd 2>/dev/null | grep -E 'buildozer|pythonforandroid|clang|gradle' | grep -v grep | head -6
echo
echo "=== 日志最后 12 行 ==="
tail -12 "$L" 2>/dev/null | cut -c1-160
