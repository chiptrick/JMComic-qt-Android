#!/usr/bin/env bash
# 显示重打包失败的上下文
set -uo pipefail
T=/tmp/bz3.txt
tr '\r' '\n' < /root/jmcomic-build/logs/buildozer_full.log > "$T"
LINE=$(grep -n 'Command failed' "$T" | head -1 | cut -d: -f1)
echo "Command failed 在第 ${LINE:-?} 行 / 共 $(wc -l < "$T") 行"
echo
echo "=== 之前 60 行 ==="
if [ -n "${LINE:-}" ]; then
    START=$(( LINE > 60 ? LINE - 60 : 1 ))
    sed -n "${START},${LINE}p" "$T" | grep -vE '^\s*$' | cut -c1-190
fi
