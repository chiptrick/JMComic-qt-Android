#!/usr/bin/env bash
# 重打包进度
set -uo pipefail
W=/root/jmcomic-build
A="$W/src/android"
L="$W/logs/buildozer_full.log"
T=/tmp/bz3.txt

echo "=== 进程 ==="
ps -eo pid,etime,cmd | grep -E 'buildozer|gradle|java|pythonforandroid' | grep -v grep | head -6
echo
echo "=== 日志行数 ==="
wc -l < "$L" 2>/dev/null
echo
echo "=== 打包阶段关键字 ==="
tr '\r' '\n' < "$L" 2>/dev/null > "$T"
grep -nE 'Package the application|BUILD SUCCESSFUL|BUILD FAILED|apk|zipalign|apksigner|Command failed|Error code|FileExistsError|# APK' "$T" | tail -14 | cut -c1-170
echo
echo "=== 最后 18 行 ==="
tail -18 "$T" | cut -c1-170
echo
echo "=== APK 产物 ==="
find "$A" -maxdepth 3 -name '*.apk' 2>/dev/null | while read -r f; do ls -sh "$f"; done
ls -sh "$A/bin" 2>/dev/null || echo "(bin 为空)"
