#!/usr/bin/env bash
# 打印 buildozer.py / android_helper.py 全文关键部分，弄清 requirements 与 local_libs 的来源
set -uo pipefail
WORK=/root/jmcomic-build
SP="$WORK/venv-host/lib/python3.14/site-packages/PySide6/scripts"
echo "===== shiboken6 wheel 是否下载成功 ====="
ls -sh "$WORK/src/android/wheels/"
echo
echo "===== buildozer.py 全文 ====="
cat "$SP/deploy_lib/android/buildozer.py"
echo
echo "===== android_helper.py: local_libs / requirements 相关 ====="
grep -nE "local_libs|requirements|def create_recipe|def extract_and_copy_jar|ANDROID_DEPLOY_CACHE" "$SP/deploy_lib/android/android_helper.py" | head -40
