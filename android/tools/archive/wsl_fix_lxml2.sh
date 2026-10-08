#!/usr/bin/env bash
# lxml 编译时 -I 只给了 <libxml2>/include，但头文件在 <libxml2>/include/libxml2/libxml/*.h，
# 补充该目录后重启
set -uo pipefail
P4A=/root/jmcomic-build/p4a
R="$P4A/pythonforandroid/recipes/lxml/__init__.py"
B=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a
PY=/root/jmcomic-build/venv311/bin/python
exec > >(tee -a /root/jmcomic-build/logs/fix_lxml2.log) 2>&1

pkill -f pythonforandroid.toolchain 2>/dev/null || true
sleep 3

echo "== libxml2 头文件实际位置 =="
find "$B/build/other_builds/libxml2" -name 'xpath.h' -path '*libxml*' 2>/dev/null | head -3
echo "== libxslt 头文件 =="
find "$B/build/other_builds/libxslt" -name 'xslt.h' 2>/dev/null | head -2

echo
echo "== 打补丁：把 include/libxml2 加进包含路径 =="
"$PY" - "$R" <<'EOF'
import sys
path = sys.argv[1]
lines = open(path, encoding='utf-8').read().splitlines()
out, done = [], False
for line in lines:
    out.append(line)
    if not done and line.strip().startswith('env["WITH_XSLT_CONFIG"]'):
        ind = line[:len(line) - len(line.lstrip())]
        out.append(ind + "# lxml 里 #include <libxml/xpath.h>，而头文件装在 include/libxml2/ 下，")
        out.append(ind + "# 只给 include/ 会找不到，这里补上")
        out.append(ind + '_xml2_inc = join(libxml2_build_dir, "include", "libxml2")')
        out.append(ind + 'if exists(_xml2_inc):')
        out.append(ind + '    env["LXML_STATIC_INCLUDE_DIRS"] += ":" + _xml2_inc')
        out.append(ind + '    if env.get("INCLUDE"):')
        out.append(ind + '        env["INCLUDE"] += ":" + _xml2_inc')
        done = True
open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print('注入 include/libxml2:', done)
EOF
grep -n -A8 'WITH_XSLT_CONFIG' "$R" | head -14
"$PY" -c "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read());print('语法 OK')" "$R" || {
    cp -f "$R.orig" "$R"; echo "语法错误，已还原"; exit 1; }

echo
echo "== 清 lxml build 目录并重启 =="
rm -rf "$B/build/other_builds/lxml"
bash /path/to/JMComic-qt/android/tools/wsl_start_detached_build.sh
