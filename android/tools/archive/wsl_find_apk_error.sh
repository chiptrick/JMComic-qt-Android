#!/usr/bin/env bash
# 取出 apk 打包阶段的真实报错
set -uo pipefail
L=/root/jmcomic-build/logs/buildozer_full.log
T=/tmp/bz2.txt
tr '\r' '\n' < "$L" > "$T"
N=$(wc -l < "$T")
echo "展开后总行数: $N"
START=$(( N > 120 ? N - 120 : 1 ))
echo "=== 最后 120 行里从 'Package the application' 开始 ==="
LINE=$(grep -n 'Package the application' "$T" | tail -1 | cut -d: -f1)
echo "起始行: ${LINE:-?}"
if [ -n "${LINE:-}" ]; then
    sed -n "${LINE},$(( LINE + 90 ))p" "$T" | cut -c1-190
fi
