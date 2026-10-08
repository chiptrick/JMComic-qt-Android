#!/usr/bin/env bash
# 确认 _python_bundle 内容，以及 gradle 工程期望从哪里取 python 运行时
set -uo pipefail
D=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic
echo "=== _python_bundle 目录 ==="
ls -la "$D/_python_bundle__arm64-v8a" 2>/dev/null | head -6
ls "$D/_python_bundle__arm64-v8a/_python_bundle" 2>/dev/null | head -10
du -sh "$D/_python_bundle__arm64-v8a/_python_bundle" 2>/dev/null
echo
echo "=== dists/JMComic 下的归档/资产 ==="
find "$D" -maxdepth 2 -name '*.zip' -o -maxdepth 2 -name '*.tar' -o -maxdepth 2 -name '*.jar' 2>/dev/null | head -10
echo
echo "=== gradle 里对 python bundle 的引用 ==="
grep -rn "python_bundle\|private.tar\|assets" "$D/build.gradle" 2>/dev/null | head -10
echo
echo "=== p4a 期望的打包方式(bootstrap 源码) ==="
grep -rn "python_bundle" /root/jmcomic-build/p4a/pythonforandroid/bootstraps/qt/build/build.py 2>/dev/null | head -8
grep -rn "python_bundle\|private.tar" /root/jmcomic-build/p4a/pythonforandroid/bootstraps/common/build/build.py 2>/dev/null | head -12
