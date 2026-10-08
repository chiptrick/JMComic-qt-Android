#!/usr/bin/env bash
# lxml 4.8.0 在 STATIC 模式下，setupinfo 的 library_dirs([])/include_dirs([]) 会回退读
# 环境变量 LIBRARY / INCLUDE；p4a 的 recipe 只设了 LXML_STATIC_*，于是断言失败。
# 这里补上这两个环境变量，然后重启构建。
set -uo pipefail
P4A=/root/jmcomic-build/p4a
R="$P4A/pythonforandroid/recipes/lxml/__init__.py"
PY=/root/jmcomic-build/venv311/bin/python
exec > >(tee -a /root/jmcomic-build/logs/fix_lxml.log) 2>&1

pkill -f pythonforandroid.toolchain 2>/dev/null || true
sleep 3

[ -f "$R.orig" ] || cp "$R" "$R.orig"
echo "== 打补丁 =="
"$PY" - "$R" <<'EOF'
import sys
path = sys.argv[1]
lines = open(path, encoding='utf-8').read().splitlines()
out, done = [], False
for line in lines:
    out.append(line)
    if not done and line.strip().startswith('return env'):
        ind = line[:len(line) - len(line.lstrip())]
        out.insert(len(out) - 1,
                   ind + "# lxml 在 STATIC 模式下会回退读 LIBRARY/INCLUDE 环境变量，")
        out.insert(len(out) - 1,
                   ind + "# 不设置的话 setupinfo 会断言 'Static build not configured'")
        out.insert(len(out) - 1,
                   ind + 'env["LIBRARY"] = env["LXML_STATIC_LIBRARY_DIRS"]')
        out.insert(len(out) - 1,
                   ind + 'env["INCLUDE"] = env["LXML_STATIC_INCLUDE_DIRS"]')
        done = True
open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print('注入 LIBRARY/INCLUDE:', done)
EOF
tail -12 "$R"
"$PY" -c "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read());print('语法 OK')" "$R" || {
    cp -f "$R.orig" "$R"; echo "语法错误，已还原"; exit 1; }

echo
echo "== 清 lxml build 目录并重启脱离式构建 =="
rm -rf /root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/build/other_builds/lxml
bash /path/to/JMComic-qt/android/tools/wsl_start_detached_build.sh
