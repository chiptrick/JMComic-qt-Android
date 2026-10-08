#!/usr/bin/env bash
# 检查 Pillow 等 PyPI 源码包的下载速率(判断是否卡在慢速源)
set -uo pipefail
B=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/packages
echo "=== 已下载包的目录 ==="
for d in "$B"/*/; do
    n=$(basename "$d")
    sz=$(du -sh "$d" 2>/dev/null | cut -f1)
    files=$(ls "$d" 2>/dev/null | tr '\n' ' ')
    printf '%-14s %-7s %s\n' "$n" "$sz" "${files:0:90}"
done
echo
echo "=== Pillow 下载速率(10s) ==="
if [ -d "$B/Pillow" ]; then
    s1=$(du -sb "$B/Pillow" | cut -f1)
    sleep 10
    s2=$(du -sb "$B/Pillow" | cut -f1)
    echo "速率 $(( (s2 - s1) / 10 / 1024 )) KB/s, 当前 $(( s2 / 1024 / 1024 )) MB"
else
    echo "没有 Pillow 目录，可能已经下载完"
fi
echo
echo "=== 当前 p4a 正在做什么(日志最后几行含进度条) ==="
tail -c 400 /root/jmcomic-build/logs/buildozer_full.log | tr '\r' '\n' | tail -4 | cut -c1-160
