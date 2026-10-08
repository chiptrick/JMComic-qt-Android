#!/usr/bin/env bash
# 对比两处 packages 目录，找出可以直接复用的已下载源码包
set -uo pipefail
W=/root/jmcomic-build
A="$W/src/android/.buildozer/android/platform/build-arm64-v8a/packages"
B="$W/.buildozer/android/platform/build-arm64-v8a/packages"

for D in "$A" "$B"; do
    echo "=== $D ==="
    if [ -d "$D" ]; then
        du -sh "$D"
        find "$D" -mindepth 1 -maxdepth 2 -type f -printf '  %10s  %P\n' 2>/dev/null | sort -k2
    else
        echo "  (不存在)"
    fi
    echo
done

echo "=== 本地已有的 CPython 源码包 ==="
ls -sh "$W"/Python-3.11.13.tgz "$W"/Python-3.11.13 2>/dev/null
find "$W" -maxdepth 3 -name 'Python-3.11.13*.tgz' -o -maxdepth 3 -name 'v3.11.13.tar.gz' 2>/dev/null

echo
echo "=== hostpython3 / python3 recipe 期望的文件名 ==="
grep -nE "url =|version =|versioned_url|filenames|name = " "$W/p4a/pythonforandroid/recipes/hostpython3/__init__.py" | head -20
echo "--- python3 ---"
grep -nE "url =|version =|versioned_url|filenames|name = " "$W/p4a/pythonforandroid/recipes/python3/__init__.py" | head -20
