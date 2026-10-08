#!/usr/bin/env bash
# 查看部署工具如何计算 local_libs / modules / recipe_dir / jars_dir / exe_dir
set -uo pipefail
WORK=/root/jmcomic-build
SP="$WORK/venv-host/lib/python3.14/site-packages/PySide6/scripts"
echo "===== AndroidConfig 其余部分 ====="
sed -n '80,220p' "$SP/deploy_lib/android/android_config.py"
echo
echo "===== local_libs 定义处 ====="
grep -rn "local_libs" "$SP" | head -20
