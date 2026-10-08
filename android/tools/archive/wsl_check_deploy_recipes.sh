#!/usr/bin/env bash
# 检查 deploy 工具生成的 recipe 是否还在
set -uo pipefail
W=/root/jmcomic-build
A="$W/src/android"
DR="$A/deployment/recipes"
SRC="$W/venv311/lib/python3.11/site-packages/PySide6/scripts/deploy_lib/android/recipes"

echo "=== 当前 $DR ==="
ls -la "$DR" 2>/dev/null || echo "(不存在)"

echo
echo "=== 每个 recipe 里的文件数 ==="
for d in "$DR"/*/; do
    [ -d "$d" ] || continue
    printf '  %-14s %s 个文件\n' "$(basename "$d")" "$(find "$d" -type f | wc -l)"
done

echo
echo "=== 工具自带的 recipe 模板 $SRC ==="
ls -la "$SRC" 2>/dev/null || echo "(不存在)"
for d in "$SRC"/*/; do
    [ -d "$d" ] || continue
    printf '  %-14s %s 个文件\n' "$(basename "$d")" "$(find "$d" -type f | wc -l)"
done

echo
echo "=== buildozer.spec 里的 p4a.local_recipes ==="
grep -E '^p4a\.local_recipes' "$A/buildozer.spec"

echo
echo "=== 日志里 recipe 搜索路径 ==="
grep -oE "Added recipe .*|Loading recipe.*|recipes? (dir|path).*" /tmp/bz3.txt 2>/dev/null | head -5
