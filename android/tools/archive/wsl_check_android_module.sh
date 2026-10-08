#!/usr/bin/env bash
# 确认 android 模块已进入 python-installs 与最终 APK
set -uo pipefail
W=/root/jmcomic-build
A="$W/src/android"
D="$A/.buildozer/android/platform/build-arm64-v8a"
APK=$(ls -t "$A"/bin/*.apk "$A"/*.apk 2>/dev/null | head -1)

echo "=== APK ==="
ls -l --time-style=+%H:%M:%S "$APK"

echo
echo "=== requirements 里是否有 android ==="
grep -oE '^requirements = .*' "$A/buildozer.spec" | tr ',' '\n' | grep -n -E '^android$|android' | head -5

echo
echo "=== python-installs 里的 android 模块 ==="
ls -la "$D/build/python-installs/JMComic/arm64-v8a/android/" 2>/dev/null || echo "(没有 android 模块!)"

echo
echo "=== _ctypes_library_finder 是否存在 ==="
ls "$D/build/python-installs/JMComic/arm64-v8a/android/_ctypes_library_finder.py" 2>/dev/null && echo "  OK" || echo "  缺失!"

echo
echo "=== dist 的 _python_bundle 里是否有 android ==="
find "$D/dists/JMComic" -maxdepth 6 -type d -name android 2>/dev/null | head -5

echo
echo "=== APK 内 libpybundle 是否含 android/_ctypes_library_finder(查 python-installs 打包前状态) ==="
echo "(APK 内的 python 代码在 libpybundle.so 里，只能间接确认上一步)"
