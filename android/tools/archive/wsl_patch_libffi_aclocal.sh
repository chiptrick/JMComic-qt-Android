#!/usr/bin/env bash
# 最小补丁：让 libffi 的 autogen/autoreconf 能找到 libtool 的 m4 宏
# (否则报 possibly undefined macro: LT_SYS_SYMBOL_USCORE)
# 只在 env 里加 ACLOCAL_PATH，不改结构；改完做语法校验，失败自动还原
set -uo pipefail
P4A=/root/jmcomic-build/p4a
R="$P4A/pythonforandroid/recipes/libffi/__init__.py"
VPY=/root/jmcomic-build/venv311/bin/python
[ -f "$R.orig" ] || cp "$R" "$R.orig"

echo "== 打补丁 =="
"$VPY" - "$R" <<'EOF'
import sys
path = sys.argv[1]
lines = open(path, encoding='utf-8').read().splitlines()
out, done = [], False
for line in lines:
    out.append(line)
    if not done and line.strip().startswith('env = self.get_recipe_env(arch)'):
        indent = line[:len(line) - len(line.lstrip())]
        out.append(indent + "# libtool 的 m4 宏(LT_SYS_SYMBOL_USCORE 等)由 acinclude 引入，")
        out.append(indent + "# 这里显式给出 aclocal 搜索路径，避免 autoreconf 报未定义宏")
        out.append(indent + "env['ACLOCAL_PATH'] = '/usr/share/aclocal:/usr/share/aclocal-1.18'")
        out.append(indent + "env['LIBTOOLIZE'] = 'libtoolize'")
        done = True
open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print('插入 ACLOCAL_PATH:', done)
EOF

echo "== 语法校验 =="
if "$VPY" -c "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read());print('语法 OK')" "$R"; then
    sed -n '24,34p' "$R"
else
    cp -f "$R.orig" "$R"; echo "已还原"
    exit 1
fi
echo
echo "== 预置 libffi 源码(用 GitHub 归档 + 之后靠 autogen；同时确保 autoconf 可用) =="
command -v autoreconf && command -v aclocal && ls /usr/share/aclocal/libtool.m4 2>/dev/null
echo
echo "== 重启脱离式构建 =="
bash /path/to/JMComic-qt/android/tools/wsl_start_detached_build.sh
