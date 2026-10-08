#!/usr/bin/env bash
# 查看 p4a 的 PythonRecipe 如何调用 pip(以便写 no-deps 的 jmcomic recipe)
set -uo pipefail
WORK=/root/jmcomic-build
echo "===== recipe.py: install_python_package / pip ====="
grep -n "pip install\|--no-deps\|install_python_package\|def install_python_package\|python_depends\|def get_recipe_env" \
  "$WORK/p4a/pythonforandroid/recipe.py" | head -30
echo
echo "--- install_python_package 函数体 ---"
python3 - <<'EOF'
import re
src = open('/root/jmcomic-build/p4a/pythonforandroid/recipe.py').read()
m = re.search(r"def install_python_package\(.*?\n(?=    def )", src, re.S)
print(m.group(0)[:3000] if m else "未找到")
EOF
echo
echo "===== 一个纯 python recipe 例子(如 certifi) ====="
cat "$WORK/p4a/pythonforandroid/recipes/certifi/__init__.py" 2>/dev/null
echo
echo "===== 已有 recipe 列表(部分) ====="
ls "$WORK/p4a/pythonforandroid/recipes" | tr '\n' ' ' | head -c 1500
