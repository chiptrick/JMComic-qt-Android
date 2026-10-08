#!/usr/bin/env bash
# 找 deploy 工具的 cleanup 实现，判断重跑 --init 是否会清掉已编译的 .buildozer
set -uo pipefail
SP=/root/jmcomic-build/venv311/lib/python3.11/site-packages/PySide6/scripts
echo "=== 含 cleanup 的文件 ==="
grep -rn 'def cleanup' "$SP" 2>/dev/null | head

echo
echo "=== deploy_lib/android/*.py 里 cleanup / unlink / rmtree ==="
grep -rn 'cleanup\|rmtree\|unlink' "$SP/deploy_lib/android/"*.py 2>/dev/null | head -30

echo
echo "=== android_deploy.py 里的 cleanup 调用 ==="
grep -n 'cleanup' "$SP/android_deploy.py" 2>/dev/null

echo
echo "=== android_config.py 的 cleanup 定义(前后 40 行) ==="
LINE=$(grep -n 'def cleanup' "$SP/deploy_lib/android/android_config.py" 2>/dev/null | head -1 | cut -d: -f1)
if [ -n "${LINE:-}" ]; then
    sed -n "$((LINE)),$((LINE + 40))p" "$SP/deploy_lib/android/android_config.py"
else
    echo "(android_config.py 里没有 cleanup)"
fi
