#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 安装 Android cmdline-tools + platform 34 + build-tools 35 + 最新版 NDK
# (minSdk/targetSdk 34：用户明确不考虑 Android 14 以下；NDK 不写死版本，
#  用 "ndk" 这个包名装最新稳定版，16KB 页对齐从 r28 起是默认行为)
set -euo pipefail
WORK="${WORK:-"$JM_WORK"}"
SDK="${SDK:-$WORK/android-sdk}"
mkdir -p "$WORK/logs"
exec > >(tee -a "$WORK/logs/setup_android.log") 2>&1

# JDK 不写死：按 versions.env 的区间挑一个可用的（缺了就提示 apt 装哪个版本）
if ! jm_apply_jdk; then
    echo "[FATAL] 需要 JDK ${JM_JDK_MIN}~${JM_JDK_MAX}；bash tools/resolve_jdk.sh --check 看候选"
    exit 1
fi
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

# 版本不写死：优先用本地已装的最高版本（不需要联网/工具可用），
# 其次查 sdkmanager 列表，最后才退回 tools/versions.env 里配置的 API level。
PLATFORM_PKG=""
_pv="$(ls -1 "$SDK/platforms" 2>/dev/null | sed -n 's/^android-\([0-9][0-9]*\)$/\1/p' | sort -n | tail -1)"
[ -n "$_pv" ] && PLATFORM_PKG="platforms;android-$_pv"
[ -n "$PLATFORM_PKG" ] || PLATFORM_PKG="$(jm_sdk_latest_pkg "$SDKMANAGER" "platforms;android-")"
[ -n "$PLATFORM_PKG" ] || PLATFORM_PKG="platforms;android-${JM_API_LEVEL}"

BUILD_TOOLS_PKG=""
if [ "$JM_BUILD_TOOLS" = "auto" ]; then
    _bt="$(ls -1 "$SDK/build-tools" 2>/dev/null | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)"
    if [ -n "$_bt" ]; then
        BUILD_TOOLS_PKG="build-tools;$_bt"
    else
        BUILD_TOOLS_PKG="$(jm_sdk_latest_pkg "$SDKMANAGER" "build-tools;")"
    fi
    [ -n "$BUILD_TOOLS_PKG" ] || echo "[warn] 无法确定 build-tools 版本，本次跳过安装（构建前还会再校验一次）"
else
    BUILD_TOOLS_PKG="build-tools;${JM_BUILD_TOOLS}"
fi

echo "安装 platform-tools / $PLATFORM_PKG / ${BUILD_TOOLS_PKG:-<跳过 build-tools>} / ndk(最新稳定版)"
yes | "$SDKMANAGER" --sdk_root="$SDK" \
    "platform-tools" "$PLATFORM_PKG" ${BUILD_TOOLS_PKG:+"$BUILD_TOOLS_PKG"} "ndk" 2>&1 | tail -5

echo "=== 结果 ==="
ls "$SDK"
ls "$SDK/ndk" 2>/dev/null || true
"$SDK/platform-tools/adb" version 2>/dev/null | head -1 || true
ls "$SDK/build-tools" 2>/dev/null || true
echo "===== [$(date +%T)] 完成 ====="
