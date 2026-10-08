#!/usr/bin/env bash
# 定位 buildozer 里执行 "pip install --user ..." 的位置
set -uo pipefail
BZ=/root/jmcomic-build/venv311/lib/python3.11/site-packages/buildozer
echo "=== 含 --user 的文件 ==="
grep -rln -- "--user" "$BZ" 2>/dev/null
echo
echo "=== 上下文 ==="
grep -rn -B15 -- "--user" "$BZ/__init__.py" 2>/dev/null | head -50
echo
echo "=== targets/android.py 里的安装逻辑 ==="
grep -n -A25 "def install_android_packages\|_install_android_packages\|def _install_p4a" "$BZ/targets/android.py" 2>/dev/null | head -60
