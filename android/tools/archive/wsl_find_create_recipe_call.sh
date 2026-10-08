#!/usr/bin/env bash
# 找出 create_recipe 的调用点与实参
set -uo pipefail
SP=/root/jmcomic-build/venv311/lib/python3.11/site-packages/PySide6/scripts
echo "=== create_recipe 调用点 ==="
grep -rn 'create_recipe' "$SP" 2>/dev/null | head
echo
for f in $(grep -rln 'create_recipe(' "$SP" 2>/dev/null); do
    LINE=$(grep -n 'create_recipe(' "$f" | tail -1 | cut -d: -f1)
    echo "--- $f : $LINE"
    START=$(( LINE > 30 ? LINE - 30 : 1 ))
    sed -n "${START},$(( LINE + 12 ))p" "$f"
    echo
done
