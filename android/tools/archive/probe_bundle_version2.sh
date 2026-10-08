#!/usr/bin/env bash
# 找到 APK 里应用源码(tools/tool.py 或 .pyc)到底在哪、是哪一版
set -u
D=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic
echo "== dist 顶层 =="
ls "$D" | head -30
echo "== 任何 private.tar / _python_bundle =="
find "$D" -maxdepth 3 -name "private.tar" -o -maxdepth 3 -name "_python_bundle*" | head -10
echo "== bundle 里的 tools 目录 =="
find "$D" -type d -name "tools" | head -10
echo "== APK 内 assets 前 20 项 =="
APK=$(ls -t /root/jmcomic-build/src/android/bin/*.apk 2>/dev/null | head -1)
echo "APK=$APK"
unzip -l "$APK" 2>/dev/null | grep -E "assets/" | head -20
echo "== APK 里 tool.pyc =="
unzip -l "$APK" 2>/dev/null | grep -E "tool\.pyc|mobile_ui" | head -10
