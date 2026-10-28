#!/usr/bin/env bash
# android/tools/env.sh —— 公共路径解析（被 android/tools 下的脚本 source）
#
# 目的：所有脚本都不写死本机绝对路径。仓库放在哪里，脚本就认哪里。
#
# 可覆盖的环境变量（不设则用下面的默认值）：
#   JM_REPO    仓库根目录。默认＝本文件所在目录往上两级（android/tools -> 仓库根）
#   JM_WORK    WSL 内的构建树（ext4，避免 /mnt/c 慢）      默认 /root/jmcomic-build
#   JM_SRC     $JM_WORK/src —— 仓库同步过去的副本
#   JM_SDK     Android SDK                                 默认 $JM_WORK/android-sdk
#   JM_NDK     Android NDK                                 默认 $JM_SDK/ndk/26.1.10909125
#   JM_VENV    buildozer 宿主 venv（要求 python <= 3.11）   默认 $JM_WORK/venv311
#   JM_VPY     宿主 python                                默认 $JM_VENV/bin/python
#   JM_DEPLOY  pyside6-android-deploy                     默认 $JM_VENV/bin/pyside6-android-deploy
#   JM_ADB     adb 可执行文件。默认从 PATH 找，找不到再用 $JM_SDK/platform-tools/adb
#   JM_USER    WSL 里的非 root 用户（跑"非 root 回归"用）    默认 uid=1000 的用户名
#   JM_SERIAL  目标设备 adb 串号。默认取 `adb devices` 里第一个已授权设备
#   JM_ABI     目标 ABI：arm64-v8a（真机，默认）| x86_64（模拟器）
#
# 用法（在脚本最上面，紧跟在 shebang 之后）：
#     . "$(dirname "${BASH_SOURCE[0]}")/env.sh"
#
# 注意：本文件刻意不设置 shell 选项（不 set -e / -u / pipefail），以免改变调用方行为。

JM_TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${JM_REPO:=$(cd "$JM_TOOLS_DIR/../.." && pwd)}"
# 默认放在当前用户的 home 下：写死 /root/jmcomic-build 时非 root 用户(如 wq159)
# 跑任何脚本都会在 mkdir 那一步"Permission denied"，而错误信息和路径配置毫无关系，
# 很容易被误判成"权限/挂载"问题。
: "${JM_WORK:=$HOME/jmcomic-build}"
: "${JM_SRC:=$JM_WORK/src}"
: "${JM_SDK:=$JM_WORK/android-sdk}"
: "${JM_NDK:=$JM_SDK/ndk/26.1.10909125}"
: "${JM_VENV:=$JM_WORK/venv311}"
: "${JM_VPY:=$JM_VENV/bin/python}"
: "${JM_DEPLOY:=$JM_VENV/bin/pyside6-android-deploy}"

if [ -z "${JM_ADB:-}" ]; then
    JM_ADB="$(command -v adb 2>/dev/null || true)"
    [ -n "$JM_ADB" ] || JM_ADB="$JM_SDK/platform-tools/adb"
fi

if [ -z "${JM_USER:-}" ]; then
    JM_USER="$(id -un 1000 2>/dev/null || true)"
fi

if [ -z "${JM_SERIAL:-}" ]; then
    JM_SERIAL="$("$JM_ADB" devices 2>/dev/null | awk 'NR>1 && $2=="device" {print $1; exit}' || true)"
fi

# ---------------------------------------------------------------- 目标 ABI
# 一个 APK 只能有一种 ABI（p4a 按 arch 分别构建 dist），所以 x86_64 是"换一个
# 架构再打一次"，不是往同一个包里塞两份原生库：
#   arm64-v8a  真机（高通 SoC，有 QNN/HTP NPU）
#   x86_64     模拟器（Android Studio 的 x86_64 AVD；没有 QNN，超分走 ORT CPU）
#
# 由 ABI 派生三个下游变量，避免每个脚本各写一遍 case：
#   JM_WHEEL_TAG  Qt android wheel 的平台标签（pyside6-*-<tag>.whl）
#   JM_ARCH_NAME  pysidedeploy.spec 里 [buildozer] arch 的取值（deploy 工具自己的叫法）
#   JM_LIBS_KEY   buildozer 的 add_libs 键后缀（arm64_v8a / x86_64）
#   JM_QNN        该 ABI 是否有 QNN 运行库（1/0）
: "${JM_ABI:=arm64-v8a}"
case "$JM_ABI" in
    arm64-v8a)
        JM_WHEEL_TAG="android_aarch64"
        JM_ARCH_NAME="aarch64"
        JM_LIBS_KEY="arm64_v8a"
        JM_QNN="${JM_QNN:-1}"
        ;;
    x86_64)
        JM_WHEEL_TAG="android_x86_64"
        JM_ARCH_NAME="x86_64"
        JM_LIBS_KEY="x86_64"
        JM_QNN="${JM_QNN:-0}"
        ;;
    *)
        echo "env.sh: 不支持的 JM_ABI=$JM_ABI（可选 arm64-v8a / x86_64）" >&2
        exit 2
        ;;
esac

export JM_TOOLS_DIR JM_REPO JM_WORK JM_SRC JM_SDK JM_NDK JM_VENV JM_VPY JM_DEPLOY
export JM_ADB JM_USER JM_SERIAL
export JM_ABI JM_WHEEL_TAG JM_ARCH_NAME JM_LIBS_KEY JM_QNN
