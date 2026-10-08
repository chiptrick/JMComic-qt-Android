#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 跑图片管线(分割还原/QImage 解码)宿主回归
set -u
REPO="$JM_REPO"
PY="$JM_WORK/venv311/bin/python3"
cd "$REPO" || exit 1
QT_QPA_PLATFORM=offscreen "$PY" -u android/tools/host_test_image_pipeline.py > /tmp/imgtest.txt 2>&1
echo "exit=$?"
grep -E "^(PASS|FAIL|---|ALL|FAILED)" /tmp/imgtest.txt
echo "---- tail ----"
tail -12 /tmp/imgtest.txt
