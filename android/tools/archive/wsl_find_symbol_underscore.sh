#!/usr/bin/env bash
# 定位 LT_SYS_SYMBOL_USCORE 应该由谁定义
set -uo pipefail
B=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/build/other_builds/libffi
F=$(find "$B" -maxdepth 3 -type d -name libffi 2>/dev/null | head -1)
echo "libffi 源码目录: ${F:-未解压}"

echo
echo "=== libtool m4 里所有含 SYMBOL_USCORE 的定义 ==="
grep -rln 'SYMBOL_USCORE' /usr/share/aclocal/ /opt/libtool247/share/aclocal/ 2>/dev/null
grep -rhn 'SYMBOL_USCORE' /usr/share/aclocal/*.m4 /opt/libtool247/share/aclocal/*.m4 2>/dev/null | head -8

echo
echo "=== libffi 源码里的引用 ==="
if [ -n "$F" ]; then
    grep -rn 'SYMBOL_USCORE' "$F"/configure.ac "$F"/acinclude.m4 2>/dev/null | head -10
    echo "--- configure.ac 205-220 行 ---"
    sed -n '205,220p' "$F"/configure.ac 2>/dev/null
fi

echo
echo "=== 当前构建是否又失败 ==="
grep -c 'Command failed' /root/jmcomic-build/logs/detached_build.log 2>/dev/null || echo 0
