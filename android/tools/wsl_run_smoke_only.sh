#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 只跑 Android 竖屏冒烟测试(gate 2)，输出到 /tmp/smoke.txt
set -u
REPO="$JM_REPO"
PY="$JM_WORK/venv311/bin/python3"
cd "$REPO" || exit 1
QT_QPA_PLATFORM=offscreen "$PY" -u android/tools/smoke_test_android.py > /tmp/smoke.txt 2>&1
echo "exit=$?"
tail -40 /tmp/smoke.txt
