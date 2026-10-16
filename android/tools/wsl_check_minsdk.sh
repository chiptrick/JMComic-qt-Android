#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 从 AndroidManifest 读 minSdk / targetSdk / extractNativeLibs
set -uo pipefail
SDK="$JM_WORK/android-sdk"
BT=$(ls -d "$SDK"/build-tools/* 2>/dev/null | sort -V | tail -1)
# 取最新的 APK(版本号会随构建变化，不要写死文件名)
APK="${APK:-$(ls -t "$JM_WORK"/src/android/bin/*.apk "$JM_WORK"/src/android/*.apk 2>/dev/null | head -1)}"
[ -n "$APK" ] || { echo "还没有 APK(先跑 wsl_build_apk.sh)"; exit 1; }
echo "build-tools: $BT"
echo "APK: $APK"
echo
"$BT/aapt2" dump xmltree --file AndroidManifest.xml "$APK" 2>/dev/null \
    | grep -iE 'minSdkVersion|targetSdkVersion|extractNativeLibs|debuggable' | head -8
echo
echo "=== badging 里的 sdk 行 ==="
"$BT/aapt2" dump badging "$APK" 2>/dev/null | grep -iE "sdkVersion|native-code|package:" | head -5
