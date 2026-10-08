#!/usr/bin/env bash
# 修正：ACLOCAL 用系统 aclocal(2.4.7 前缀里没有 aclocal)，宏搜索路径指向 libtool 2.4.7
set -uo pipefail
P4A=/root/jmcomic-build/p4a
R="$P4A/pythonforandroid/recipes/libffi/__init__.py"
PY=/root/jmcomic-build/venv311/bin/python
exec > >(tee -a /root/jmcomic-build/logs/libtool247_fix.log) 2>&1

pkill -f pythonforandroid.toolchain 2>/dev/null || true
sleep 3

echo "== 修正 recipe 里的 ACLOCAL =="
"$PY" - "$R" <<'EOF'
import sys
path = sys.argv[1]
lines = open(path, encoding='utf-8').read().splitlines()
out = []
for line in lines:
    s = line.strip()
    if s.startswith("env['ACLOCAL']"):
        ind = line[:len(line) - len(line.lstrip())]
        out.append(ind + "# 注意: libtool 2.4.7 前缀里没有 aclocal，用系统的 aclocal，")
        out.append(ind + "# 靠 ACLOCAL_PATH 找到 2.4.7 的 libtool.m4/ltdl.m4(含 LT_SYS_SYMBOL_USCORE)")
        out.append(ind + "env['ACLOCAL'] = '/usr/bin/aclocal'")
        continue
    out.append(line)
open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print('已修正')
EOF
sed -n '24,38p' "$R"
"$PY" -c "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read());print('语法 OK')" "$R" || {
    cp -f "$R.orig" "$R"; echo "语法错误，已还原"; exit 1; }

echo
echo "== 确认 /usr/bin/aclocal 与 2.4.7 宏都在 =="
ls -l /usr/bin/aclocal /opt/libtool247/bin/libtoolize
grep -c 'AC_DEFUN(\[LT_SYS_SYMBOL_USCORE\]' /opt/libtool247/share/aclocal/ltdl.m4

echo
echo "== 清 libffi build 目录并重启脱离式构建 =="
rm -rf /root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/build/other_builds/libffi
bash /path/to/JMComic-qt/android/tools/wsl_start_detached_build.sh
