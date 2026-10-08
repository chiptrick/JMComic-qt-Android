#!/usr/bin/env bash
# 列出 android wheel 里所有 Qt 插件类别与文件，并定位 deploy 工具的插件选择逻辑
set -u
B=/root/jmcomic-build
PI="$B/src/android/.buildozer/android/platform/build-arm64-v8a/build/python-installs/JMComic/arm64-v8a/PySide6/Qt/plugins"

echo "=== A. android wheel 插件全清单 ==="
if [ -d "$PI" ]; then
    for d in "$PI"/*/; do
        echo "--- ${d#$PI}"
        ls -l "$d" | awk 'NR>1 {printf "    %10d  %s\n", $5, $9}'
    done
else
    echo "NOT FOUND: $PI"
    find "$B" -type d -name plugins 2>/dev/null
fi

echo
echo "=== B. APK 里现有的 libs 清单(buildozer 生成的 libs 目录) ==="
ls -l "$B/src/android/libs/arm64-v8a/" 2>/dev/null

echo
echo "=== C. deploy 工具入口 ==="
ls -l "$B/venv311/bin/" 2>/dev/null | grep -i -E "pyside|deploy|android"
echo "--- 在 site-packages 里找 deploy 脚本 ---"
find "$B/venv311" "$B/venv-host" -maxdepth 6 -name '*.py' -path '*scripts*' 2>/dev/null | head -20
find "$B" -maxdepth 8 -name 'android_deploy*.py' -o -maxdepth 8 -name 'deploy_lib*.py' 2>/dev/null | head

echo
echo "=== D. buildozer.spec 里跟 libs/plugins 有关的行 ==="
grep -n -E "add_libs|plugins|add_assets|requirements|android\." /path/to/JMComic-qt/android/buildozer.spec 2>/dev/null | head -40
