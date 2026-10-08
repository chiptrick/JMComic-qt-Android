#!/usr/bin/env bash
# 查清平台插件来源，为恢复 deploy recipe 做准备
set -uo pipefail
W=/root/jmcomic-build
A="$W/src/android"
DIST="$A/.buildozer/android/platform/build-arm64-v8a/dists/JMComic"
WHEEL=$(ls "$A/wheels/"pyside6-*-android_aarch64.whl 2>/dev/null | head -1)

echo "=== dist 的 libs/arm64-v8a ==="
ls "$DIST/libs/arm64-v8a" 2>/dev/null | sed 's/^/  /' || echo "  (不存在)"

echo
echo "=== android/libs/arm64-v8a 里有平台插件吗 ==="
ls "$A/libs/arm64-v8a" | grep -i platform || echo "  (没有)"

echo
echo "=== wheel 里的 platforms 插件 ==="
python3 - "$WHEEL" <<'PY'
import sys, zipfile, os
z = zipfile.ZipFile(sys.argv[1])
for n in z.namelist():
    if "/plugins/" in n and n.endswith(".so"):
        cat = n.split("/plugins/")[1].split("/")[0]
        if cat in ("platforms",):
            print("  ", n, z.getinfo(n).file_size)
PY

echo
echo "=== android_config.py 里 platforms_qtforandroid 的来源 ==="
grep -n 'platforms_qtforandroid\|qt_plugins\|local_libs' "$W/venv311/lib/python3.11/site-packages/PySide6/scripts/deploy_lib/android/android_config.py" | head -25

echo
echo "=== pysidedeploy.spec 当前内容 ==="
cat -n "$A/pysidedeploy.spec"
