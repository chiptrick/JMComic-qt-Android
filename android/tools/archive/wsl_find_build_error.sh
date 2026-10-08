#!/usr/bin/env bash
# 从 buildozer 日志里挖出真正的失败原因
set -uo pipefail
L=/root/jmcomic-build/logs/buildozer_full.log
echo "=== 文件大小/行数 ==="
ls -sh "$L"; wc -l < "$L"

echo
echo "=== 关键字命中(带行号) ==="
grep -nE 'Command failed|ERROR|Error:|error:|Traceback|Exception|No such file|failed|FAILED|raise ' "$L" 2>/dev/null | head -30

echo
echo "=== 失败点前 60 行(去掉 buildozer 的环境 dump) ==="
# 环境 dump 以 'Environment variables' 或 '#     ' 开头，失败信息在它之前
LINE=$(grep -nE 'Command failed|Buildozer failed|Traceback \(most recent' "$L" | head -1 | cut -d: -f1)
echo "首个失败标记在第 ${LINE:-?} 行"
if [ -n "${LINE:-}" ]; then
    START=$(( LINE > 80 ? LINE - 80 : 1 ))
    sed -n "${START},${LINE}p" "$L" | cut -c1-180
fi
