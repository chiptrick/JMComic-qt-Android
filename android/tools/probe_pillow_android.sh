#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 查看打好的 APK 里 Pillow 到底带了哪些编解码器(解释真机 "cannot identify image file")
set -u
D="$JM_WORK/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic"
echo "== PIL native extensions =="
find "$D" -name "*.so" | grep -i "PIL" | head -30
echo "== _imaging / _webp =="
find "$D" -name "_imaging*" | head -10
find "$D" -name "_webp*" | head -10
echo "== bundled libs =="
ls "$D/libs/arm64-v8a/" | head -40
echo "== PIL dir (non-pyc) =="
ls "$D/_python_bundle__arm64-v8a/_python_bundle/site-packages/PIL/" | grep -v "\.pyc$" | head -40
