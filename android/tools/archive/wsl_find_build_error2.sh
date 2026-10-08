#!/usr/bin/env bash
# 展开 \r 后再定位 buildozer 的失败原因
set -uo pipefail
L=/root/jmcomic-build/logs/buildozer_full.log
T=/tmp/bz_expanded.txt
tr '\r' '\n' < "$L" > "$T"
echo "展开后行数: $(wc -l < "$T")"

echo
echo "=== 失败/异常关键行 ==="
grep -nE 'Buildozer failed|Command failed|Traceback \(most recent|p4a\.|ERROR:|Error:|error:|Exception' "$T" \
    | grep -v 'Download' | head -25 | cut -c1-190

echo
echo "=== ENVIRONMENT dump 起始行 ==="
ENVLINE=$(grep -n 'ENVIRONMENT' "$T" | head -1 | cut -d: -f1)
echo "ENVLINE=${ENVLINE:-未找到}"

echo
echo "=== 环境 dump 之前 70 行(真正的错误在这里) ==="
if [ -n "${ENVLINE:-}" ]; then
    START=$(( ENVLINE > 70 ? ENVLINE - 70 : 1 ))
    sed -n "${START},${ENVLINE}p" "$T" | grep -vE '^\s*$' | cut -c1-190
fi
