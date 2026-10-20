#!/bin/bash
# 自动定位应用所在显示器并截图：appshot.sh <名字>
set -u
SER=127.0.0.1:7555
PKG=org.jmcomic.jmcomic
ADB=/root/jmcomic-build/android-sdk/platform-tools/adb
OUT=/root/jmcomic-build/logs/repro_input
NAME="${1:-app}"
mkdir -p "$OUT"
"$ADB" connect "$SER" >/dev/null 2>&1

# 1) 应用窗口的逻辑 displayId
LOGICAL=$("$ADB" -s "$SER" shell dumpsys window 2>/dev/null | grep -A2 "Window{.*$PKG" | grep -oE "mDisplayId=[0-9]+" | head -1 | cut -d= -f2)
echo "应用窗口逻辑 displayId=$LOGICAL"
# 2) 逻辑 -> 物理(InputDispatcher viewport 里有 uniqueId)
PHYS=$("$ADB" -s "$SER" shell dumpsys input 2>/dev/null | grep "Viewport INTERNAL: displayId=$LOGICAL," | grep -oE "local:[0-9]+" | head -1 | cut -d: -f2)
echo "物理显示器=$PHYS"
if [ -z "$PHYS" ]; then echo "没找到物理显示器"; exit 1; fi
"$ADB" -s "$SER" shell screencap -d "$PHYS" -p /sdcard/jm_a.png >/dev/null 2>&1
"$ADB" -s "$SER" pull /sdcard/jm_a.png "$OUT/$NAME.png" >/dev/null 2>&1
"$ADB" -s "$SER" shell rm -f /sdcard/jm_a.png
echo "$NAME.png $(stat -c %s "$OUT/$NAME.png" 2>/dev/null || echo MISSING) bytes (display $LOGICAL)"
