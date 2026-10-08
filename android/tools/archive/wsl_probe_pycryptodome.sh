#!/usr/bin/env bash
# 查清 pycryptodome 在 Android 上为什么退化到 ctypes 又 import android 失败
set -uo pipefail
D=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/build/python-installs/JMComic/arm64-v8a
P="$D/Crypto/Util/_raw_api.py"

echo "=== Crypto/Util/ 下有什么(有没有编译好的 _raw_aes 等) ==="
ls -la "$D/Crypto/Util/" | head -25
echo "--- Crypto/Cipher ---"
ls "$D/Crypto/Cipher/" | head -25
echo "--- Crypto/Hash ---"
ls "$D/Crypto/Hash/" | grep -E '\.so|_raw' | head -10

echo
echo "=== _raw_api.py 里的 android / optimize 相关 ==="
grep -n 'android\|optimize\|cffi\|ctypes' "$P" | head -40

echo
echo "=== _raw_api.py 第 60-100 行 ==="
sed -n '60,100p' "$P"
echo "=== 第 160-200 行 ==="
sed -n '160,200p' "$P"

echo
echo "=== p4a 是否以 -OO 启动 python ==="
grep -rn 'OO\|PYTHONOPTIMIZE\|optimize' /root/jmcomic-build/p4a/pythonforandroid/bootstraps/common/build/templates/main.c 2>/dev/null | head -10
grep -rn 'OO\|PYTHONOPTIMIZE' /root/jmcomic-build/p4a/pythonforandroid/bootstraps/qt/build/templates/ 2>/dev/null | head -10
find /root/jmcomic-build/p4a/pythonforandroid/bootstraps -name 'main.c' | head -5
