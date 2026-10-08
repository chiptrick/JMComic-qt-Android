#!/usr/bin/env bash
# 找出 stdlib 里谁 import android
set -uo pipefail
W=/root/jmcomic-build
echo "=== CPython 源码 Lib 里搜 'import android' ==="
grep -rn '^ *\(import\|from\) android' "$W/Python-3.11.13/Lib/" 2>/dev/null | head -20
echo
echo "=== ctypes/util.py 头部 ==="
sed -n '1,25p' "$W/Python-3.11.13/Lib/ctypes/util.py" 2>/dev/null
echo
echo "=== ctypes/__init__.py 里 android 相关 ==="
grep -n 'android\|platform' "$W/Python-3.11.13/Lib/ctypes/__init__.py" 2>/dev/null | head -20
echo
echo "=== 全 stdlib 搜 android(含注释) ==="
grep -rln 'android' "$W/Python-3.11.13/Lib/" 2>/dev/null | head -20
echo
echo "=== 已安装 bundle 里的 stdlib.zip 是否含 android 模块 ==="
find "$W/src/android/.buildozer" -name 'stdlib.zip' 2>/dev/null | head -3
