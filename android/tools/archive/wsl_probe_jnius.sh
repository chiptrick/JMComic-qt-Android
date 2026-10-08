#!/usr/bin/env bash
# 检查 p4a 的 python bundle 里有没有 pyjnius（sr_qnn 依赖它拿 nativeLibraryDir）
set -u
D=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic/_python_bundle__arm64-v8a/_python_bundle/site-packages
echo "=== site-packages 顶层条目 ==="
ls "$D" | head -80
echo
echo "=== 找 jnius ==="
find "$D" -maxdepth 1 -iname 'jnius*' 2>/dev/null
echo "=== 找 jnius 相关 so ==="
find "$D" -iname '*jnius*' 2>/dev/null | head
echo
echo "=== 同样看 python-installs 里 ==="
P=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/build/python-installs/JMComic/arm64-v8a
ls "$P" | head -60
echo "--- jnius? ---"
find "$P" -maxdepth 1 -iname 'jnius*' 2>/dev/null
