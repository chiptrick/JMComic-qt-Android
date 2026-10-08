#!/usr/bin/env bash
# libffi 的 autogen.sh 在本环境跑不过(LT_SYS_SYMBOL_USCORE 未定义)，
# 改为：预置官方 release 包(自带 configure) + 让 recipe 在已有 configure 时跳过 autogen
set -uo pipefail
WORK=/root/jmcomic-build
P4A=$WORK/p4a
VER=3.4.2
STORES=(
  "$WORK/src/android/.buildozer/android/platform/build-arm64-v8a/packages"
  "$WORK/.buildozer/android/platform/build-arm64-v8a/packages"
)
GH="https://ghproxy.net/https://github.com"
exec > >(tee -a "$WORK/logs/fix_libffi.log") 2>&1

echo "===== [$(date +%T)] 下载 libffi 官方 release 包(含 configure) ====="
TMP="/tmp/libffi-$VER.tar.gz"
if [ ! -s "$TMP" ]; then
    for u in "$GH/libffi/libffi/releases/download/v$VER/libffi-$VER.tar.gz" \
             "$GH/libffi/libffi/archive/refs/tags/v$VER.tar.gz"; do
        echo "尝试 $u"
        curl -sSL --retry 2 -m 600 -o "$TMP" "$u" && [ -s "$TMP" ] && break
        rm -f "$TMP"
    done
fi
ls -sh "$TMP" || { echo "下载失败"; exit 1; }
# 校验是否是 release 包(含 configure)
tar -tzf "$TMP" | grep -qE '/configure$' && echo "包含 configure ✓" || echo "[warn] 该包不含 configure，autogen 仍需可用"

fname="v$VER.tar.gz"   # recipe 期望的缓存文件名
for store in "${STORES[@]}"; do
    mkdir -p "$store/libffi"
    rm -f "$store/libffi/$fname" "$store/libffi/.mark-$fname"
    cp -f "$TMP" "$store/libffi/$fname"
    touch "$store/libffi/.mark-$fname"
    echo "  -> $store/libffi/$fname"
done

echo
echo "===== [$(date +%T)] 打补丁：已有 configure 时跳过 autogen.sh ====="
R="$P4A/pythonforandroid/recipes/libffi/__init__.py"
cp -n "$R" "$R.orig" 2>/dev/null || true
python3 - "$R" <<'EOF'
import sys
path = sys.argv[1]
text = open(path, encoding='utf-8').read()
old = "shprint(sh.Command('./autogen.sh'), _env=env)"
new = ("if not exists('configure'):\n"
       "            shprint(sh.Command('./autogen.sh'), _env=env)\n"
       "        else:\n"
       "            info('configure already present, skipping autogen.sh')")
if old in text:
    text = text.replace(old, new)
    if 'from os.path import exists' not in text:
        text = text.replace('from pythonforandroid.recipe import Recipe',
                            'from os.path import exists\nfrom pythonforandroid.recipe import Recipe', 1)
    if 'info' not in text.split('\n')[0:25][-1] and 'from pythonforandroid.logger import info' not in text:
        text = text.replace('from pythonforandroid.recipe import Recipe',
                            'from pythonforandroid.logger import info\nfrom pythonforandroid.recipe import Recipe', 1)
    open(path, 'w', encoding='utf-8').write(text)
    print('已打补丁')
else:
    print('未找到目标行(可能已打过补丁)')
EOF
grep -n -A4 "autogen" "$R" | head -12

echo
echo "===== [$(date +%T)] 重启脱离式构建 ====="
bash /path/to/JMComic-qt/android/tools/wsl_start_detached_build.sh
