#!/usr/bin/env bash
# 取出 p4a 执行的完整 pip 命令与 python_modules 列表
set -uo pipefail
T=/tmp/bz3.txt
[ -f "$T" ] || tr '\r' '\n' < /root/jmcomic-build/logs/buildozer_full.log > "$T"

echo "=== RAN: 完整命令行 ==="
grep -n 'RAN:' "$T" | tail -3 | cut -c1-1200
echo
echo "=== 该命令拆成包名(取 install 之后的参数) ==="
LINE=$(grep 'RAN:.*pip3 install' "$T" | tail -1)
echo "$LINE" | sed 's/.*pip3 install //' | tr ' ' '\n' | sed '/^$/d' | sed 's/^/  /'
echo
echo "=== shiboken6 recipe 目录详情 ==="
find /root/jmcomic-build/src/android/deployment/recipes/shiboken6 -type f | sed 's/^/  /'
echo "--- 模板 ---"
find /root/jmcomic-build/venv311/lib/python3.11/site-packages/PySide6/scripts/deploy_lib/android/recipes/shiboken6 -type f | sed 's/^/  /'
echo
echo "=== PySide6 recipe 目录详情 ==="
find /root/jmcomic-build/src/android/deployment/recipes/PySide6 -type f | sed 's/^/  /'
echo "--- 模板 ---"
find /root/jmcomic-build/venv311/lib/python3.11/site-packages/PySide6/scripts/deploy_lib/android/recipes/PySide6 -type f | sed 's/^/  /'
