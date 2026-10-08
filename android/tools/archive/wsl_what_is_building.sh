#!/usr/bin/env bash
# 看当前正在编译/写入的 recipe 与日志尾部
set -uo pipefail
B=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a
L=/root/jmcomic-build/logs/detached_build.log
echo "=== 最近 3 分钟被写入的文件(取前 10) ==="
find "$B" -newermt '-3 minutes' 2>/dev/null | head -10
echo
echo "=== other_builds 各 recipe 大小 ==="
for d in "$B"/build/other_builds/*/; do
    [ -d "$d" ] || continue
    printf '%-14s %s\n' "$(basename "$d")" "$(du -sh "$d" 2>/dev/null | cut -f1)"
done
echo
echo "=== 日志最后 12 行(过滤进度条) ==="
tail -c 3000 "$L" | tr '\r' '\n' | grep -vE '^- |^\s*$' | tail -12 | cut -c1-170
echo
echo "=== 编译进程 ==="
ps -eo etimes,cmd | grep -E 'clang|clang\+\+|make|configure|pythonforandroid' | grep -v grep | head -5 | cut -c1-150
