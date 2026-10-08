#!/usr/bin/env bash
# 跑竖屏冒烟测试并把关键行打出来(避免在 PowerShell 里拼引号/管道)
set -uo pipefail
WORK="${WORK:-/root/jmcomic-build}"
SRC="$WORK/src"
VPY="$WORK/venv311/bin/python3"
LOG="${1:-/tmp/smoke.log}"
PATTERN="${2:-portrait:|grid|cover|traceback|Error|assert}"
cd "$SRC" || exit 1
QT_QPA_PLATFORM=offscreen "$VPY" android/tools/smoke_test_android.py > "$LOG" 2>&1
echo "smoke exit=$?"
grep -nE "$PATTERN" "$LOG" | tail -40
