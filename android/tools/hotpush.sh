#!/bin/bash
# 热更新 Python 模块到模拟器：hotpush.sh <模块名...>
set -u
SER=127.0.0.1:7555
PKG=org.jmcomic.jmcomic
ADB=/root/jmcomic-build/android-sdk/platform-tools/adb
SRC=/mnt/c/Users/WQ159/source/repos/JMComic-qt/src
if [ $# -lt 1 ]; then echo "用法: hotpush.sh <模块名...>"; exit 1; fi
"$ADB" connect "$SER" >/dev/null 2>&1

for mod in "$@"; do
    F="$SRC/tools/$mod.py"
    if [ ! -f "$F" ]; then echo "缺文件: $F"; exit 1; fi
    "$ADB" -s "$SER" push "$F" /data/local/tmp/mt.py >/dev/null 2>&1 || { echo "push 失败 $mod"; exit 1; }
    "$ADB" -s "$SER" shell run-as "$PKG" cp /data/local/tmp/mt.py "files/app/app_src/tools/$mod.py" || { echo "写入失败 $mod"; exit 1; }
    echo "已热更新 tools/$mod.py ($(stat -c %s "$F") bytes)"
done
"$ADB" -s "$SER" shell rm -f /data/local/tmp/mt.py

echo "=== 重启应用 ==="
"$ADB" -s "$SER" shell am force-stop "$PKG"
sleep 1
"$ADB" -s "$SER" shell am start -W -n "$PKG/org.kivy.android.PythonActivity" 2>&1 | tail -1
sleep 6
"$ADB" -s "$SER" shell pidof "$PKG"
