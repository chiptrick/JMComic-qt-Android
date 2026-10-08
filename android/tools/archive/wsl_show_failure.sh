#!/usr/bin/env bash
# 打印 detached_build.log 中失败点之前的上下文(过滤进度条)
set -uo pipefail
L=/root/jmcomic-build/logs/detached_build.log
N=$(grep -n 'Command failed' "$L" | head -1 | cut -d: -f1)
echo "失败行号: ${N:-未找到}"
[ -n "${N:-}" ] || exit 0
sed -n "$((N > 80 ? N - 80 : 1)),${N}p" "$L" | tr '\r' '\n' | grep -vE '^- |^\s*$' | tail -40 | cut -c1-190
