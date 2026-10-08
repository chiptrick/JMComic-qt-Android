#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 安装 Android cmdline-tools + platform 34 + build-tools 35 + NDK r26d
# (minSdk/targetSdk 34：用户明确不考虑 Android 14 以下)
set -euo pipefail
WORK="${WORK:-"$JM_WORK"}"
SDK="${SDK:-$WORK/android-sdk}"
mkdir -p "$WORK/logs"
exec > >(tee -a "$WORK/logs/setup_android.log") 2>&1

export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}"
export PATH="$JAVA_HOME/bin:$PATH"
echo "===== [$(date +%T)] Android SDK 安装 ====="
java -version 2>&1 | head -1

CMDLINE_ZIP="$WORK/tools/cmdline-tools.zip"
if [ ! -d "$SDK/cmdline-tools/latest/bin" ]; then
    echo "下载 cmdline-tools"
    curl -sSL -o "$CMDLINE_ZIP" https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
    mkdir -p "$SDK/cmdline-tools"
    python3 -m zipfile -e "$CMDLINE_ZIP" "$SDK/cmdline-tools/tmp"
    mv "$SDK/cmdline-tools/tmp/cmdline-tools" "$SDK/cmdline-tools/latest"
    rm -rf "$SDK/cmdline-tools/tmp"
fi
SDKMANAGER="$SDK/cmdline-tools/latest/bin/sdkmanager"
chmod +x "$SDKMANAGER"
export ANDROID_HOME="$SDK"
export ANDROID_SDK_ROOT="$SDK"

echo "接受许可协议"
yes | "$SDKMANAGER" --sdk_root="$SDK" --licenses >/dev/null 2>&1 || true

echo "安装 platform-tools / platforms;android-34 / build-tools;35.0.0 / ndk;26.1.10909125"
yes | "$SDKMANAGER" --sdk_root="$SDK" \
    "platform-tools" "platforms;android-34" "build-tools;35.0.0" "ndk;26.1.10909125" 2>&1 | tail -5

echo "=== 结果 ==="
ls "$SDK"
ls "$SDK/ndk" 2>/dev/null || true
"$SDK/platform-tools/adb" version 2>/dev/null | head -1 || true
ls "$SDK/build-tools" 2>/dev/null || true
echo "===== [$(date +%T)] 完成 ====="
