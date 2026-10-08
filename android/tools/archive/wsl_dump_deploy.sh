#!/usr/bin/env bash
# 查看 buildozer.py 剩余部分与 android_deploy.py 主流程
set -uo pipefail
WORK=/root/jmcomic-build
SP="$WORK/venv-host/lib/python3.14/site-packages/PySide6/scripts"
echo "===== buildozer.py 140 行之后 ====="
sed -n '140,260p' "$SP/deploy_lib/android/buildozer.py"
echo
echo "===== android_deploy.py ====="
cat "$SP/android_deploy.py"
