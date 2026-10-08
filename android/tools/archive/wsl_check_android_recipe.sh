#!/usr/bin/env bash
# 确认 p4a 补丁过的 ctypes/util.py 需要 android 模块，以及 p4a 是否自带 android recipe
set -uo pipefail
W=/root/jmcomic-build
B="$W/src/android/.buildozer/android/platform/build-arm64-v8a/build/other_builds/python3/arm64-v8a__ndk_target_34/python3/Lib/ctypes/util.py"

echo "=== 构建出来的 ctypes/util.py 前 30 行 ==="
sed -n '1,30p' "$B" 2>/dev/null || echo "(找不到 $B)"

echo
echo "=== p4a 里跟 ctypes/util 相关的补丁 ==="
grep -rn 'ctypes/util\|ctypes_util\|import android' "$W/p4a/pythonforandroid/recipes/python3/"*.py "$W/p4a/pythonforandroid/recipes/python3/"*.patch 2>/dev/null | head -20
find "$W/p4a/pythonforandroid/recipes/python3" -type f | head -20

echo
echo "=== p4a 是否有 android recipe ==="
ls -la "$W/p4a/pythonforandroid/recipes/android/" 2>/dev/null || echo "(没有 android recipe 目录)"
grep -rn 'class AndroidRecipe\|name = ' "$W/p4a/pythonforandroid/recipes/android/__init__.py" 2>/dev/null | head

echo
echo "=== pycryptodome 的 _raw_aes 等编译模块是否存在 ==="
D="$W/src/android/.buildozer/android/platform/build-arm64-v8a/build/python-installs/JMComic/arm64-v8a/Crypto"
ls "$D/Cipher/" | grep -E '_raw_|\.so' | head -20
echo "--- AES.py 第 1-30 行 ---"
sed -n '1,30p' "$D/Cipher/AES.py"
