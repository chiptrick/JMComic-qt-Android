#!/usr/bin/env bash
# 检查打出来的 bundle 里到底装的是哪一版 tool.py/task_qimage.py
set -u
D=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic
echo "== bundle 里的 app 源码 =="
find "$D" -name "tool.py*" -path "*app*" | head -20
find "$D" -name "mobile_ui.py*" | head -10
echo "== 是否有 SegmentationPictureQt(新旧标志) =="
for f in $(find "$D" -name "tool.py" -o -name "tool.pyc" | head -20); do
  n=$(grep -c "SegmentationPictureQt" "$f" 2>/dev/null || true)
  echo "$n  $f  ($(stat -c %y "$f" 2>/dev/null))"
done
for f in $(find "$D" -name "mobile_ui.py" -o -name "mobile_ui.pyc" | head -10); do
  n=$(grep -c "图片分割自检" "$f" 2>/dev/null || true)
  echo "$n  $f  ($(stat -c %y "$f" 2>/dev/null))"
done
echo "== APK 里的 private.tar / assets =="
ls -la /root/jmcomic-build/src/android/bin/*.apk 2>/dev/null | head -3
