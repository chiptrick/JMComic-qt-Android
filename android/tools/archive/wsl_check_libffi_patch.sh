#!/usr/bin/env bash
# 校验 libffi recipe 补丁后的语法；若损坏则从 .orig 还原
set -uo pipefail
R=/root/jmcomic-build/p4a/pythonforandroid/recipes/libffi/__init__.py
echo "=== 补丁区域(24-42 行) ==="
sed -n '24,42p' "$R"
echo
echo "=== 语法检查 ==="
if /root/jmcomic-build/venv311/bin/python -c "import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read()); print('语法 OK')" "$R" 2>&1; then
    echo "保持补丁"
else
    echo "语法损坏，从 .orig 还原"
    [ -f "$R.orig" ] && cp -f "$R.orig" "$R" && echo "已还原" || echo "没有 .orig 备份!"
fi
