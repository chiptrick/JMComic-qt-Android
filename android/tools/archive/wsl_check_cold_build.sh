#!/usr/bin/env bash
# 判断这次是冷构建还是热构建：找旧的编译产物在哪
set -uo pipefail
W=/root/jmcomic-build
echo "=== 两处可能的 .buildozer ==="
for d in "$W/src/android/.buildozer" "$W/.buildozer"; do
    echo "--- $d"
    du -sh "$d" 2>/dev/null || echo "  (不存在)"
    ls "$d/android/platform/build-arm64-v8a/" 2>/dev/null
done
echo
echo "=== 找 libpython3.11.so / libssl.a 等已编译产物 ==="
find "$W" -maxdepth 9 -name 'libpython3.11.so*' 2>/dev/null | head -5
find "$W" -maxdepth 9 -name 'libssl.a' 2>/dev/null | head -5
find "$W" -maxdepth 9 -type d -name 'python3' -path '*other_builds*' 2>/dev/null | head -5
echo
echo "=== dists/JMComic 内容 ==="
ls -la "$W/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic/" 2>/dev/null | head -20
echo
echo "=== 全盘找 .buildozer 目录 ==="
find "$W" -maxdepth 6 -type d -name '.buildozer' 2>/dev/null
echo
echo "=== 磁盘占用 top ==="
du -sh "$W"/* 2>/dev/null | sort -h | tail -12
