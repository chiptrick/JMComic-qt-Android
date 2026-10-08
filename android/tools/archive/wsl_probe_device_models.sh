#!/usr/bin/env bash
# 在设备上排查模型为什么没落到 waifu2x-models
set -uo pipefail
ADB=adb
PKG=org.jmcomic.jmcomic
S=DEVICE_SERIAL_HERE
run() { "$ADB" -s "$S" shell "run-as $PKG $*" 2>&1; }

echo "=== private.tar 的版本标记 ==="
run "cat files/app/private.version"
echo "--- 解包出来的目录 ---"
run "ls files/app/"

echo
echo "=== files/app/sr_qnn 下有什么 ==="
run "ls -la files/app/sr_qnn/"

echo
echo "=== files/waifu2x-models 下有什么(1 个条目是什么) ==="
run "ls -la files/waifu2x-models/"

echo
echo "=== 全盘找 onnx ==="
run "find files -name '*.onnx'"
echo "onnx 计数:"
run "find files -name '*.onnx' | wc -l"

echo
echo "=== 找 models.txt ==="
run "find files -name 'models.txt'"

echo
echo "=== android_startup.log 里模型相关行 ==="
run "cat files/android_startup.log" | grep -iE "model|EnsureModels|sr " | head -20

echo
echo "=== 应用目录总大小 / 磁盘 ==="
run "du -sh files"
"$ADB" -s "$S" shell "df -h /data | tail -2"
