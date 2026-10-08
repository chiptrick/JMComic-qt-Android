#!/usr/bin/env bash
# 探查 Qt 插件在构建环境里的位置，以及 pyside6-android-deploy 如何选择插件
set -u
B=/root/jmcomic-build

echo "=== 1. qsvg / plugin .so 位置 ==="
find "$B" -name '*qsvg*' 2>/dev/null | head -40

echo
echo "=== 2. 所有 android 相关的 plugins 目录 ==="
find "$B" -type d -name plugins 2>/dev/null | head -30

echo
echo "=== 3. 找到 imageformats 目录内容 ==="
for d in $(find "$B" -type d -name imageformats 2>/dev/null | head -10); do
    echo "--- $d"
    ls -la "$d" 2>/dev/null | head -30
done

echo
echo "=== 4. iconengines 目录内容 ==="
for d in $(find "$B" -type d -name iconengines 2>/dev/null | head -10); do
    echo "--- $d"
    ls -la "$d" 2>/dev/null | head -20
done

echo
echo "=== 5. 已打包进 APK 的 16 个 libs 来源 ==="
ls -la "$B/src/android/libs/arm64-v8a/" 2>/dev/null | head -40
echo "--- 仓库里的 libs 目录 ---"
ls -la /path/to/JMComic-qt/android/libs/arm64-v8a/ 2>/dev/null | head -40

echo
echo "=== 6. deploy 工具里跟 plugins 有关的代码 ==="
TOOL=$(find "$B" -path '*pyside6_android_deploy*' -name '*.py' 2>/dev/null | head -5)
echo "$TOOL"
for f in $TOOL; do
    echo "--- $f"
    grep -n "plugin" "$f" | head -40
done
