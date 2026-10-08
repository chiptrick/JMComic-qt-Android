#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 判断构建是否还在推进(进程 + 目录增长 + 子进程)
set -uo pipefail
W="$JM_WORK"
B="$W/src/android/.buildozer/android/platform/build-arm64-v8a"
L="$W/logs/buildozer_full.log"

echo "=== 构建进程 ==="
ps -eo pid,ppid,etime,stat,cmd | grep -E 'buildozer|pythonforandroid|pip|java|gradle|ninja|cc1plus|clang' | grep -v grep | head -12

echo
echo "=== 日志行数 / 大小 ==="
wc -l < "$L"; ls -sh "$L"

echo
echo "=== dists/JMComic 大小(前后对比用) ==="
du -sh "$B/dists/JMComic" 2>/dev/null
find "$B/dists/JMComic" -maxdepth 2 -type d 2>/dev/null | head -20

echo
echo "=== 最近 15 行(原始，展开 \\r) ==="
tr '\r' '\n' < "$L" | tail -15 | cut -c1-170

echo
echo "=== 是否出现 gradle/打包关键字 ==="
tr '\r' '\n' < "$L" | grep -nE 'gradle|BUILD SUCCESSFUL|BUILD FAILED|apk|Package|zipalign|apksigner|Creating APK|android.py' | tail -10 | cut -c1-170
