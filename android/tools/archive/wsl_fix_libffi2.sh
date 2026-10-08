#!/usr/bin/env bash
# 彻底绕开 libffi 的 autotools（新版 libtool 缺 LT_SYS_SYMBOL_USCORE，autoreconf 必失败）：
#   1) 用官方 release 包(自带 configure) 预置缓存
#   2) 补丁 recipe：只有缺少 configure 时才跑 autogen.sh/autoreconf
#   3) 删掉旧 build 目录，重启构建
set -uo pipefail
WORK=/root/jmcomic-build
P4A="$WORK/p4a"
B="$WORK/src/android/.buildozer/android/platform/build-arm64-v8a"
STORES=("$B/packages" "$WORK/.buildozer/android/platform/build-arm64-v8a/packages")
GH="https://ghproxy.net/https://github.com"
PY="$WORK/venv311/bin/python"
exec > >(tee -a "$WORK/logs/fix_libffi2.log") 2>&1

echo "===== [$(date +%T)] 停构建 ====="
pkill -f pythonforandroid.toolchain 2>/dev/null || true
pkill -f 'buildozer android' 2>/dev/null || true
sleep 4

VER=3.4.2
TMP="/tmp/libffi-release-$VER.tar.gz"
echo
echo "===== [$(date +%T)] 下载官方 release 包并确认含 configure ====="
ok=0
for u in "$GH/libffi/libffi/releases/download/v$VER/libffi-$VER.tar.gz" \
         "https://ghproxy.net/https://github.com/libffi/libffi/releases/download/v$VER/libffi-$VER.tar.gz"; do
    echo "尝试 $u"
    if curl -sSL --retry 2 -m 600 -o "$TMP" "$u" && [ -s "$TMP" ]; then
        if tar -tzf "$TMP" 2>/dev/null | grep -qE '/configure$'; then
            echo "  含 configure ✓ ($(du -h "$TMP" | cut -f1))"
            ok=1
            break
        else
            echo "  不含 configure，换源"
            rm -f "$TMP"
        fi
    fi
done
if [ "$ok" != "1" ]; then
    echo "未能取得带 configure 的 release 包"
    exit 1
fi

fname="v$VER.tar.gz"
for store in "${STORES[@]}"; do
    mkdir -p "$store/libffi"
    rm -f "$store/libffi/$fname" "$store/libffi/.mark-$fname"
    cp -f "$TMP" "$store/libffi/$fname"
    touch "$store/libffi/.mark-$fname"
    echo "  -> $store/libffi/$fname"
done

echo
echo "===== [$(date +%T)] 补丁 recipe：已有 configure 就完全不碰 autotools ====="
R="$P4A/pythonforandroid/recipes/libffi/__init__.py"
[ -f "$R.orig" ] || cp "$R" "$R.orig"
"$PY" - "$R" <<'EOF'
import re, sys
path = sys.argv[1]
lines = open(path, encoding='utf-8').read().splitlines()
out = []
for line in lines:
    s = line.strip()
    # 去掉之前注入的 ACLOCAL_PATH(不再需要)
    if s.startswith("env['ACLOCAL_PATH']") or s.startswith("env['LIBTOOLIZE']"):
        continue
    if s.startswith("if not exists('configure'):"):
        continue
    # 把 autogen.sh / autoreconf 两行都收进"缺少 configure 才执行"的分支
    if s.startswith("shprint(sh.Command('./autogen.sh')"):
        indent = line[:len(line) - len(line.lstrip())]
        out.append(indent + "if not exists('configure'):")
        out.append(indent + "    " + s)
        continue
    if s.startswith("shprint(sh.Command('autoreconf')"):
        out.append(" " * (len(line) - len(line.lstrip()) + 4) + s)
        continue
    out.append(line)
open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print('已写入')
EOF

echo "--- 补丁后片段 ---"
sed -n '24,40p' "$R"
echo "--- 语法校验 ---"
if ! "$PY" -c "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read());print('语法 OK')" "$R"; then
    cp -f "$R.orig" "$R"; echo "语法错误，已还原"; exit 1
fi

echo
echo "===== [$(date +%T)] 清掉 libffi 旧 build 目录(让新包重新解压) ====="
rm -rf "$B/build/other_builds/libffi"
ls "$B/build/other_builds" | tr '\n' ' '

echo
echo "===== [$(date +%T)] 重启脱离式构建 ====="
bash /path/to/JMComic-qt/android/tools/wsl_start_detached_build.sh
