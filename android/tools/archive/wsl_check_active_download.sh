#!/usr/bin/env bash
# 找出当前正在下载/编译的包与速率
set -uo pipefail
P=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/packages
echo "=== 最近 2 分钟写入的文件 ==="
find "$P" -newermt '-2 minutes' -type f 2>/dev/null | head -6
echo
echo "=== 各包(有 .mark 表示下载完成) ==="
for d in "$P"/*/; do
    n=$(basename "$d")
    files=$(ls -1 "$d" 2>/dev/null | tr '\n' ' ')
    mark=no
    ls "$d"/.mark-* >/dev/null 2>&1 && mark=yes
    printf '%-14s mark=%-4s %s\n' "$n" "$mark" "${files:0:70}"
done
echo
echo "=== 最近 30 秒的写入速率 ==="
s1=$(find "$P" -type f -printf '%s\n' 2>/dev/null | awk '{s+=$1} END {print s+0}')
sleep 30
s2=$(find "$P" -type f -printf '%s\n' 2>/dev/null | awk '{s+=$1} END {print s+0}')
echo "$(( (s2 - s1) / 30 / 1024 )) KB/s (总计 $(( s2 / 1024 / 1024 )) MB)"
echo
echo "=== 运行中的编译器/下载 ==="
ps -eo etimes,cmd | grep -E 'clang|gcc|make|configure|pythonforandroid' | grep -v grep | head -4 | cut -c1-140
