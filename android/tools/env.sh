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
#   JM_NDK     Android NDK                                 默认 $JM_SDK/ndk 下版本最高者
#              (不写死版本；要钉住某版用 JM_NDK_VERSION=<版本>，或直接给 JM_NDK=<目录>)
#   JM_NDK_VER 上面选中的 NDK 版本号(只读，从 source.properties 读)
#   JM_JDK     构建 JDK 目录(不盲信 PATH/JAVA_HOME)        默认 $JM_JDK > JAVA_HOME > 扫描
#              版本区间由 JM_JDK_MIN/JM_JDK_MAX 限定(默认 17~24，见 versions.env)
#   JM_JDK_VER 选中的 JDK 主版本(只读)
#   ---- 以下来自 tools/versions.env，只读 ----
#   JM_API_LEVEL(34) JM_MIN_SDK(34) JM_BUILD_TOOLS(auto) JM_CMAKE_MIN(3.20)
#   JM_GRADLE_MIN(8.14.6) JM_GRADLE_VERSION() JM_NDK_MIN_MAJOR(28) JM_ORT_VERSION
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

# 工具链版本号的唯一来源（API level / JDK 区间 / Gradle 下限 / NDK 下限 / ORT 版本）
# 这里只是"数据"，任何脚本都能覆盖：JM_API_LEVEL=35 ./build_android.sh
if [ -f "$JM_TOOLS_DIR/versions.env" ]; then
    # shellcheck source=versions.env
    . "$JM_TOOLS_DIR/versions.env"
fi
# 宿主平台抽象（nproc/stat/sed -i/sha256/路径归一化…）
# shellcheck source=resolve_host.sh
. "$JM_TOOLS_DIR/resolve_host.sh"
# 机器本地路径（不入库）：JM_JDK / ANDROID_HOME / TMPDIR 这类只对本机有效的值放这里，
# 免得每次都要 export。模板见 tools/local.env.example。
if [ -f "$JM_TOOLS_DIR/local.env" ]; then
    # shellcheck source=local.env
    . "$JM_TOOLS_DIR/local.env"
fi

: "${JM_REPO:=$(cd "$JM_TOOLS_DIR/../.." && pwd)}"
# 默认放在当前用户的 home 下：写死 /root/jmcomic-build 时非 root 用户(如 wq159)
# 跑任何脚本都会在 mkdir 那一步"Permission denied"，而错误信息和路径配置毫无关系，
# 很容易被误判成"权限/挂载"问题。
: "${JM_WORK:=$HOME/jmcomic-build}"
: "${JM_SRC:=$JM_WORK/src}"
: "${JM_SDK:=$JM_WORK/android-sdk}"
# 环境变量里可能是 Windows 写法（D:\Android_SDK）：统一归一化成正斜杠 POSIX 路径，
# 否则后面所有 [[ -d ... ]] 都会判假，报出来的错误却是"目录不存在"。
JM_WORK="$(jm_norm_path "$JM_WORK")"
JM_SRC="$(jm_norm_path "$JM_SRC")"
JM_SDK="$(jm_norm_path "$JM_SDK")"

# NDK 不写死版本（见 tools/resolve_ndk.sh）：
#   1) JM_NDK / ANDROID_NDK_HOME 显式给目录
#   2) JM_NDK_VERSION=<版本> 钉住 $JM_SDK/ndk/<版本>
#   3) 默认取 $JM_SDK/ndk/* 中版本号最高者 —— 装了新 NDK 不用改任何脚本
# 这里找不到 NDK 不退出：env.sh 也被纯 adb/同步类脚本 source，
# 真正需要 NDK 的调用方自己判空并给提示（用 jm_ndk_hint）。
# shellcheck source=resolve_ndk.sh
. "$JM_TOOLS_DIR/resolve_ndk.sh"
if [ -z "${JM_NDK:-}" ]; then
    JM_NDK="$(jm_resolve_ndk "$JM_SDK")"
fi
JM_NDK_VER=""
if [ -n "${JM_NDK:-}" ]; then
    JM_NDK="$(jm_norm_path "$JM_NDK")"
    JM_NDK_VER="$(jm_ndk_version_of "$JM_NDK")"
fi

# JDK 同理：不写死 17，也不盲信 PATH/JAVA_HOME（系统默认可能已是 27，
# 而 Gradle 8.14 只支持到 Java 24）。区间定义在 tools/versions.env。
# shellcheck source=resolve_jdk.sh
. "$JM_TOOLS_DIR/resolve_jdk.sh"
if [ -z "${JM_JDK:-}" ]; then
    # 显式指定的 JDK 越界时函数会返回 1（并打一行原因），这里不能让它中断 source
    JM_JDK="$(jm_resolve_jdk || true)"
fi
JM_JDK_VER=""
if [ -n "${JM_JDK:-}" ]; then
    JM_JDK="$(jm_norm_path "$JM_JDK")"
    JM_JDK_VER="$(jm_jdk_version_of "$JM_JDK")"
fi
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

export JM_TOOLS_DIR JM_REPO JM_WORK JM_SRC JM_SDK JM_NDK JM_NDK_VER JM_VENV JM_VPY JM_DEPLOY
export JM_JDK JM_JDK_VER JM_JDK_MIN JM_JDK_MAX
export JM_API_LEVEL JM_MIN_SDK JM_BUILD_TOOLS JM_CMAKE_MIN JM_GRADLE_MIN JM_GRADLE_VERSION
export JM_GH_MIRROR_PREFIX JM_ARIA2_CONN JM_USE_ARIA2 JM_GRADLE_DIST_URL_TEMPLATE
export JM_NDK_MIN_MAJOR JM_ORT_VERSION JM_PYTHON_MIN
export JM_ADB JM_USER JM_SERIAL
export JM_ABI JM_WHEEL_TAG JM_ARCH_NAME JM_LIBS_KEY JM_QNN
