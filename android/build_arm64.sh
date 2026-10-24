#!/usr/bin/env bash
# JMComic Android 单架构构建脚本 —— arm64-v8a(真机 / 高通 QNN NPU)
#
# 本脚本只构建 arm64-v8a 一种架构，无关架构的编译步骤一律不执行：
#   * 只下载/解包 arm64 的 ONNX Runtime AAR(onnxruntime-android-qnn)
#   * 只编译 arm64 的 libsr_qnn.so(独立构建目录 sr_qnn/cpp/build-arm64-v8a)
#   * 只用 android_aarch64 的 Qt wheel；p4a 只出 arm64-v8a 一个 dist
#   * 产物只有 dist/JMComic-<版本>-arm64-v8a-debug.apk
#
# 用法：
#   ./build_arm64.sh                          # 构建 arm64-v8a(默认)
#   ./build_arm64.sh --version 0.52           # 指定 APK 版本号(格式 MAJOR.MINOR[.PATCH]，
#                                            # 纯数字段无前导零，如 0.51 / 1.2.3)
#   ABI=arm64-v8a ./build_arm64.sh            # 用环境变量显式指定(等价默认)
#   ./build_arm64.sh --dry-run                # 只校验环境+打印将执行的命令，不构建
#   SKIP_NATIVE=1 ./build_arm64.sh            # 原生库已编好，只重新打包
#
# 其它入口：
#   x86_64(模拟器)  -> ./build_x86_64.sh
#   两种架构都要    -> ./build_android.sh(多架构一键构建)
#   Windows 一键    -> ./build_arm64.ps1(经 WSL)
#
# 透传给 build_android.sh 的环境变量：
#   APP_VERSION / BUILD_TYPE / ORT_VERSION / ANDROID_PLATFORM /
#   SKIP_NATIVE / REPACK / PYTHON_BIN / ANDROID_NDK_HOME / ANDROID_HOME
#
# 宿主要求：Linux 或 macOS(pyside6-android-deploy 不支持 Windows 宿主，
# Windows 用户请用 build_arm64.ps1 经 WSL 构建)。
set -euo pipefail

SCRIPT_ABI="arm64-v8a"           # 本脚本唯一支持的架构
SIBLING_SH="build_x86_64.sh"     # 另一架构的 Unix 脚本
SIBLING_PS1="build_arm64.ps1"    # Windows 一键脚本(经 WSL)
MULTI_SH="build_android.sh"      # 多架构构建脚本(实际构建实现)

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_SH="${HERE}/${MULTI_SH}"

log()  { printf '\033[1;32m[build-arm64]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn ][build-arm64]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error][build-arm64]\033[0m %s\n' "$*" >&2; exit 1; }

# 版本号格式校验：语义化版本的数字核心子集 MAJOR.MINOR[.PATCH]
# (与 build_android.sh / tools/patch_buildozer_spec.py 的规则保持一致)：
# 该值会写进 buildozer.spec 的 app.version(=Android versionName)，p4a 再据此推导
# versionCode(只按 "." 切数字段)，故每段必须纯数字、无前导零，且不接受
# -alpha.1 / +build.5 之类后缀。
validate_version() {
    printf '%s' "$1" | grep -Eq '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))?$'
}

usage() {
    cat <<EOF
JMComic 单架构构建：arm64-v8a(真机)

用法: ./build_arm64.sh [选项]

选项:
  --abi <abi>     目标架构(只接受 arm64-v8a / arm64 / aarch64，默认 arm64-v8a)
  --version <v>   APK 版本号(等价 APP_VERSION=<v>)；格式 MAJOR.MINOR 或
                  MAJOR.MINOR.PATCH，纯数字段、无前导零(如 0.51 / 1.2.3)
  --dry-run       只校验环境并打印将执行的命令，不真正构建
  -h, --help      显示本帮助

环境变量:
  ABI=<abi>                   目标架构(等价 --abi)
  APP_VERSION / BUILD_TYPE / ORT_VERSION / ANDROID_PLATFORM /
  SKIP_NATIVE / REPACK / PYTHON_BIN   透传给 ${MULTI_SH}

其它入口:
  x86_64(模拟器)   -> ./${SIBLING_SH}
  两种架构都要     -> ./${MULTI_SH}
  Windows 一键     -> ./${SIBLING_PS1}(经 WSL)
EOF
}

# ---------------------------------------------------------------- 参数解析
# 架构来源优先级：--abi 参数 > ABI 环境变量 > 本脚本默认(arm64-v8a)
ABI_INPUT="${ABI:-}"
DRY_RUN="${DRY_RUN:-0}"
VERSION_INPUT=""                # --version 显式指定(用于提前校验，仍会透传)
FORWARD=()                      # 原样透传给 build_android.sh 的参数
while [ $# -gt 0 ]; do
    case "$1" in
        --abi=*) ABI_INPUT="${1#--abi=}"; shift ;;
        --abi)   ABI_INPUT="${2:-}"; shift 2 ;;
        --abis|--abis=*)
            # 多架构入口不是本脚本的职责，直接指路
            die "本脚本只构建单一架构(arm64-v8a)。两种架构都要请用: ./${MULTI_SH}" ;;
        --dry-run) DRY_RUN=1; shift ;;
        --version=*) VERSION_INPUT="${1#--version=}"; FORWARD+=("--version=${1#--version=}"); shift ;;
        --version)   VERSION_INPUT="${2:-}"; FORWARD+=("--version=${2:-}"); shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) FORWARD+=("$1"); shift ;;   # 其余参数原样透传
    esac
done

# ---------------------------------------------------------------- 架构判断
# 只接受本脚本架构(含别名)；其它一律拒绝并指路，绝不静默构建别的架构
case "$(printf '%s' "${ABI_INPUT}" | tr 'A-Z' 'a-z')" in
    ""|arm64|arm64-v8a|aarch64)
        TARGET_ABI="${SCRIPT_ABI}" ;;
    x86_64|x86-64|x64)
        die "本脚本只构建 arm64-v8a(真机)，不接受 '${ABI_INPUT}'。
       要构建 x86_64(模拟器)请用: ./${SIBLING_SH}(Windows 用 build_x86_64.ps1)" ;;
    both|all)
        die "本脚本只构建单一架构。两种架构都要请用: ./${MULTI_SH}" ;;
    *)
        die "不支持的 ABI: '${ABI_INPUT}'(本脚本只支持 ${SCRIPT_ABI}；x86_64 请用 ${SIBLING_SH})" ;;
esac

# ---------------------------------------------------------------- 版本号校验
# 生效版本 = --version 参数 > APP_VERSION 环境变量；两者都没有则用 build_android.sh
# 提取的默认值(那边也会再校验一遍，这里提前校验是为了在动手前就报错)。
VERSION_EFF="${VERSION_INPUT:-${APP_VERSION:-}}"
VERSION_SRC=""
[[ -n "${VERSION_INPUT}" ]] && VERSION_SRC="--version 参数"
[[ -z "${VERSION_SRC}" && -n "${APP_VERSION:-}" ]] && VERSION_SRC="APP_VERSION 环境变量"
if [[ -n "${VERSION_EFF}" ]] && ! validate_version "${VERSION_EFF}"; then
    die "APK 版本号格式不合法: '${VERSION_EFF}'(来源: ${VERSION_SRC})
       规则: MAJOR.MINOR 或 MAJOR.MINOR.PATCH，每段纯数字、无前导零(如 0.51 / 1.2.3)
       不接受 -alpha/+build 后缀(p4a 推导 versionCode 只认数字段)"
fi

# ---------------------------------------------------------------- 宿主环境检查
[[ "$(uname -s)" == "Linux" || "$(uname -s)" == "Darwin" ]] || \
    die "本脚本要求在 Linux/macOS 执行(Windows 宿主请用 ./${SIBLING_PS1}，经 WSL 构建)"
[[ -f "${BUILD_SH}" ]] || die "找不到 ${BUILD_SH}(脚本被移动了？请从 android/ 目录运行)"
NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-}}"
[[ -n "${NDK}" ]] || die "请设置 ANDROID_NDK_HOME 指向 NDK r26d"
[[ -d "${NDK}" ]] || die "NDK 目录不存在: ${NDK}"
command -v cmake >/dev/null || die "缺少 cmake(>=3.20)"

# ---------------------------------------------------------------- 架构专属预检
# 只看本架构的产物，不碰另一架构的任何文件
WHEEL_DIR="${HERE}/wheels"
if ! ls "${WHEEL_DIR}"/PySide6-*-android_aarch64.whl >/dev/null 2>&1; then
    warn "wheels/ 下没有 android_aarch64 wheel，构建时会自动 qtpip download --arch aarch64"
fi
if ! compgen -G "${HERE}/libs/arm64-v8a/libQnnHtp.so" >/dev/null; then
    warn "libs/arm64-v8a 没有 QNN 运行库(libQnnHtp.so 等)，NPU 加速不可用(自动回落 CPU EP)"
    warn "需要 NPU 加速请先跑: bash android/tools/wsl_fetch_qnn.sh"
fi

# ---------------------------------------------------------------- 构建流程
log "目标架构: ${TARGET_ABI}(仅此架构：AAR/wheel/原生库/dist 全部单架构，不编译 x86_64)"
log "版本号:   ${VERSION_EFF:-<${MULTI_SH} 默认(自动提取并校验)>}${VERSION_SRC:+(来源: ${VERSION_SRC})}"
log "构建类型: ${BUILD_TYPE:-debug}"
[[ "${SKIP_NATIVE:-0}" == "1" ]] && log "SKIP_NATIVE=1：跳过 libsr_qnn.so 编译"
log "透传参数: ${FORWARD[*]:-<无>}"
log "实际构建由 ${MULTI_SH} --abi ${TARGET_ABI} 完成"

if [[ "${DRY_RUN}" == "1" ]]; then
    log "[dry-run] 将执行: ${BUILD_SH} --abi ${TARGET_ABI} ${FORWARD[*]:-}"
    log "[dry-run] 自检通过，未启动构建"
    exit 0
fi

# 把架构钉死传给 build_android.sh(它只会构建这一个 ABI)
export ABI="${TARGET_ABI}"
exec "${BUILD_SH}" --abi "${TARGET_ABI}" ${FORWARD[@]+"${FORWARD[@]}"}
