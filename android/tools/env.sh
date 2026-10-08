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
#
# 用法（在脚本最上面，紧跟在 shebang 之后）：
#     . "$(dirname "${BASH_SOURCE[0]}")/env.sh"
#
# 注意：本文件刻意不设置 shell 选项（不 set -e / -u / pipefail），以免改变调用方行为。

JM_TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${JM_REPO:=$(cd "$JM_TOOLS_DIR/../.." && pwd)}"
: "${JM_WORK:=/root/jmcomic-build}"
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

export JM_TOOLS_DIR JM_REPO JM_WORK JM_SRC JM_SDK JM_NDK JM_VENV JM_VPY JM_DEPLOY
export JM_ADB JM_USER JM_SERIAL
