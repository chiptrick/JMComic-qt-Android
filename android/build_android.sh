#!/usr/bin/env bash
# JMComic Android 打包脚本(多 ABI 一键构建)
#
# 要求(宿主机必须是 Linux 或 macOS；pyside6-android-deploy 目前不支持 Windows 主机)：
#   * Python 3.11/3.12 + venv
#   * JDK 17
#   * Android SDK(platform-tools, platforms;android-34, build-tools;35.0.0)
#   * Android NDK r26d (26.1.10909125)
#   * 已下载 PySide6 / shiboken6 的 android wheel(每个 ABI 一套，放 android/wheels/)：
#        qtpip download PySide6   --android --arch aarch64   # arm64-v8a 真机
#        qtpip download shiboken6 --android --arch aarch64
#        qtpip download PySide6   --android --arch x86_64    # x86_64 模拟器
#        qtpip download shiboken6 --android --arch x86_64
#     某个 ABI 的 wheel 缺失时，脚本会按该 ABI 自动 qtpip download；仍缺失则报出
#     缺少的文件名并指明架构，不会含糊地死在打包阶段。
#
# 用法：
#   export ANDROID_HOME=$HOME/Android/Sdk
#   export ANDROID_NDK_HOME=$HOME/Android/Sdk/ndk/26.1.10909125
#   ./build_android.sh                       # 一键构建 arm64-v8a + x86_64 两个 APK
#   ./build_android.sh --abi x86_64          # 只构建 x86_64(模拟器)
#   ./build_android.sh --abi arm64-v8a,x86_64# 逗号分隔，等价于上面第一种
#   ABIS="arm64-v8a x86_64" ./build_android.sh   # 显式指定架构集合
#   ABI=arm64-v8a ./build_android.sh         # 兼容旧用法：只构建单一 ABI
#   SKIP_NATIVE=1 ./build_android.sh         # 原生库已编好，只重新打包
#   REPACK=0 ./build_android.sh              # 打补丁后不重新打包(默认 REPACK=1)
#   CONTINUE_ON_ERROR=1 ./build_android.sh   # 某架构失败也继续构建其余架构
#   APP_VERSION=0.52 ./build_android.sh      # 指定版本号(默认取 patch_buildozer_spec.py)
#                                          # 版本号格式: MAJOR.MINOR 或 MAJOR.MINOR.PATCH
#                                          # (纯数字段、无前导零，如 0.51 / 1.2.3)，
#                                          # 会写进 buildozer.spec 的 app.version
#                                          # (=Android versionName)并参与 APK 文件名
#   ./build_android.sh --help                # 完整帮助
#
# 构建入口：android/build_android.sh(本脚本)
# 输出目录：android/dist/(可用 DIST_DIR 覆盖)
# 命名规则：<title>-<APP_VERSION>-<abi>-<BUILD_TYPE>.apk
#           一个 APK 只含一种 ABI(p4a 按 arch 分别构建，见 README §10)，例如：
#             dist/JMComic-0.51-arm64-v8a-debug.apk   (真机，QNN NPU)
#             dist/JMComic-0.51-x86_64-debug.apk      (模拟器，CPU EP)
# 日志：    每个架构一份完整日志 android/build_logs/build-<abi>.log；
#           任何失败都会打印 架构 + 步骤 + 原因 + 日志路径，便于定位。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"

# ------------------------------------------------------------------ 可调参数
ORT_VERSION="${ORT_VERSION:-1.29.0}"               # onnxruntime-android(-qnn) 版本
ANDROID_PLATFORM="${ANDROID_PLATFORM:-android-34}" # 最低 Android 14
BUILD_TYPE="${BUILD_TYPE:-debug}"                  # debug -> apk, release -> aab
PYTHON_BIN="${PYTHON_BIN:-python3}"
NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-}}"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
WHEEL_DIR="${WHEEL_DIR:-${HERE}/wheels}"
WORK_DIR="${WORK_DIR:-${HERE}/.work}"
DIST_DIR="${DIST_DIR:-${HERE}/dist}"
LOG_DIR="${LOG_DIR:-${HERE}/build_logs}"
APP_VERSION="${APP_VERSION:-}"
CONTINUE_ON_ERROR="${CONTINUE_ON_ERROR:-0}"

# 支持的 ABI 与派生参数(与 android/tools/env.sh 保持一致)：
#   arm64-v8a 真机    Qt wheel=android_aarch64  deploy arch=aarch64
#                     ORT=onnxruntime-android-qnn(带 QNN EP，跑高通 NPU)
#   x86_64    模拟器  Qt wheel=android_x86_64   deploy arch=x86_64
#                     ORT=onnxruntime-android(普通版；模拟器没有 NPU，QNN EP 无意义)
SUPPORTED_ABIS="arm64-v8a x86_64"

CTX="common"        # 当前阶段/架构(日志前缀，失败信息里也能看到)
CURRENT_STEP="启动" # 当前步骤(失败定位用)

log()  { printf '\033[1;32m[build][%s]\033[0m %s\n' "${CTX}" "$*"; }
warn() { printf '\033[1;33m[warn ][%s]\033[0m %s\n' "${CTX}" "$*"; }
die()  { printf '\033[1;31m[error][%s]\033[0m %s\n' "${CTX}" "$*" >&2; exit 1; }
# 单架构失败：打印 架构 + 步骤 + 原因，返回 1(由调用方决定停不停)
Fail() { printf '\033[1;31m[error][%s]\033[0m 步骤「%s」失败: %s\n' "${CTX}" "${CURRENT_STEP}" "$*" >&2; return 1; }
Step() { CURRENT_STEP="$*"; log "===== [$(date +%H:%M:%S)] ${CURRENT_STEP} ====="; }

# 版本号格式校验：语义化版本的数字核心子集 MAJOR.MINOR[.PATCH]
# (与 tools/patch_buildozer_spec.py 的 VersionPattern 保持一致)：
#   * 每段纯数字、不允许前导零(段为 0 除外)
#   * 不接受 -alpha.1 / +build.5 之类后缀 —— 该值会写进 buildozer.spec 的
#     app.version(=Android versionName)，p4a 的 get_android_numeric_version()
#     只按 "." 切数字段推导 versionCode，带后缀会推导失败或产出错误 versionCode。
validate_version() {
    printf '%s' "$1" | grep -Eq '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))?$'
}

Usage() {
    cat <<EOF
JMComic Android 多 ABI 一键构建

用法: ./build_android.sh [选项]

选项:
  --abi <abi>           只构建指定 ABI(可重复或用逗号分隔: --abi arm64-v8a,x86_64)
  --abis "<abi> ..."    构建多个 ABI(空格分隔)
  --version <ver>       APK 版本号(默认取 tools/patch_buildozer_spec.py 的 AppVersion)；
                        格式 MAJOR.MINOR 或 MAJOR.MINOR.PATCH，纯数字段、无前导零
                        (如 0.51 / 1.2.3)，不接受 -alpha/+build 后缀
  -h, --help            显示本帮助

环境变量(均可选):
  ABI=<abi>             兼容旧用法：只构建单一 ABI
  ABIS="<abi> ..."      架构集合，默认 "arm64-v8a x86_64"(一键构建两种架构)
  APP_VERSION=<ver>     同上，等价 --version
  BUILD_TYPE=debug|release   debug->apk(默认), release->aab
  ORT_VERSION=<ver>     ONNX Runtime 版本(默认 1.29.0)
  ANDROID_PLATFORM=<api> 默认 android-34
  DIST_DIR=<dir>        输出目录(默认 android/dist)
  SKIP_NATIVE=1         跳过 libsr_qnn.so 编译(原生库已编好时)
  REPACK=0              打补丁后不重新打包(默认 REPACK=1)
  CONTINUE_ON_ERROR=1   某架构失败也继续构建其余架构(默认失败即停)

支持 ABI: arm64-v8a(真机/QNN NPU)  x86_64(模拟器/CPU EP)
输出命名: <title>-<version>-<abi>-<buildtype>.apk(一个 APK 只含一种 ABI)
EOF
}

# ------------------------------------------------------------------ 参数解析
ABI_CLI=""
VERSION_CLI=""
while [ $# -gt 0 ]; do
    case "$1" in
        --abi=*)    ABI_CLI+="${1#--abi=} " ;;
        --abi)      ABI_CLI+="${2:-} "; shift ;;
        --abis=*)   ABI_CLI+="${1#--abis=} " ;;
        --abis)     ABI_CLI+="${2:-} "; shift ;;
        --version=*) VERSION_CLI="${1#--version=}" ;;
        --version)   VERSION_CLI="${2:-}"; shift ;;
        -h|--help)  Usage; exit 0 ;;
        *) die "未知参数: $1(用法: ./build_android.sh --help)" ;;
    esac
    shift
done

# 目标架构集合：优先级 命令行 > ABIS > ABI(旧用法) > 默认两种都构建
if [[ -n "${ABI_CLI}" ]]; then
    ABIS_STR="${ABI_CLI//,/ }"
elif [[ -n "${ABIS:-}" ]]; then
    ABIS_STR="${ABIS//,/ }"
elif [[ -n "${ABI:-}" ]]; then
    ABIS_STR="${ABI}"
else
    ABIS_STR="${SUPPORTED_ABIS}"
fi
[[ -n "${VERSION_CLI}" ]] && APP_VERSION="${VERSION_CLI}"

# 版本号来源追踪(用于日志与报错定位)：--version 参数 > APP_VERSION 环境变量 > 默认值
APP_VERSION_SRC="默认值(tools/patch_buildozer_spec.py 的 AppVersion)"
if [[ -n "${APP_VERSION:-}" ]]; then APP_VERSION_SRC="APP_VERSION 环境变量"; fi
if [[ -n "${VERSION_CLI}" ]]; then APP_VERSION_SRC="--version 参数"; fi

# 校验 + 去重(保持顺序)，拼写错在动手前就报出来
ABIS_CLEAN=""
for abi in ${ABIS_STR}; do
    hit=0
    for s in ${SUPPORTED_ABIS}; do [[ "${abi}" == "${s}" ]] && hit=1; done
    [[ ${hit} == 1 ]] || die "不支持的 ABI: ${abi}(支持: ${SUPPORTED_ABIS})"
    case " ${ABIS_CLEAN} " in *" ${abi} "*) ;; *) ABIS_CLEAN+="${abi} " ;; esac
done
[[ -n "${ABIS_CLEAN}" ]] || die "没有指定任何 ABI(支持: ${SUPPORTED_ABIS})"
ABIS_STR="${ABIS_CLEAN}"

# ------------------------------------------------------------------ APK 标题/版本号(先校验，再检查环境)
# 标题取 pysidedeploy.spec；版本号来源：--version 参数 > APP_VERSION 环境变量 > 默认值
# (默认值取 tools/patch_buildozer_spec.py 的 AppVersion，那边也会再校验一遍)
APP_NAME="$(sed -n 's/^title[[:space:]]*=[[:space:]]*//p' "${HERE}/pysidedeploy.spec" \
    | head -n1 | tr -d '\r' | tr -d '[:space:]')"
[[ -n "${APP_NAME}" ]] || APP_NAME="JMComic"
if [[ -z "${APP_VERSION}" ]]; then
    APP_VERSION="$(sed -n 's/^AppVersion[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
        "${HERE}/tools/patch_buildozer_spec.py" | head -n1 || true)"
    [[ -n "${APP_VERSION}" ]] || APP_VERSION="0.1"
    APP_VERSION_SRC="默认值(tools/patch_buildozer_spec.py 的 AppVersion)"
fi

# 版本号格式校验(写进 buildozer.spec / APK 元数据之前，不合法直接退出)
if ! validate_version "${APP_VERSION}"; then
    die "APK 版本号格式不合法: '${APP_VERSION}'(来源: ${APP_VERSION_SRC})
       规则: MAJOR.MINOR 或 MAJOR.MINOR.PATCH，每段纯数字、无前导零(如 0.51 / 1.2.3)
       不接受 -alpha / +build 之类后缀(p4a 推导 versionCode 只认数字段)
       修正: --version 0.52 或 APP_VERSION=0.52；不传则用默认值"
fi

# ------------------------------------------------------------------ 环境检查(公共)
Step "环境检查"
[[ "$(uname -s)" == "Linux" || "$(uname -s)" == "Darwin" ]] || \
    die "pyside6-android-deploy 只支持 Linux/macOS 主机(Windows 请用 WSL2 或 WSL+Docker)"
[[ -n "${NDK}" ]] || die "请设置 ANDROID_NDK_HOME 指向 NDK r26d"
[[ -d "${NDK}" ]] || die "NDK 目录不存在: ${NDK}"
[[ -n "${SDK}" ]] || warn "未设置 ANDROID_HOME，pyside6-android-deploy 可能找不到 SDK"
command -v cmake >/dev/null || die "缺少 cmake(>=3.20)"
command -v unzip >/dev/null || die "缺少 unzip(解包 ONNX Runtime AAR 用)"
command -v curl  >/dev/null || die "缺少 curl(下载 ONNX Runtime AAR / 头文件用)"
JOBS="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"

log "构建入口: ${BASH_SOURCE[0]}"
log "目标架构: ${ABIS_STR}(一个 APK 只含一种 ABI，分别构建)"
log "输出目录: ${DIST_DIR}"
log "命名规则: ${APP_NAME}-${APP_VERSION}-<abi>-${BUILD_TYPE}.apk"
log "版本号:   ${APP_VERSION}(来源: ${APP_VERSION_SRC})"

# ------------------------------------------------------------------ 1. 业务源码(两种 ABI 共用)
Step "同步业务源码 -> android/app_src"
rm -rf "${HERE}/app_src"
mkdir -p "${HERE}/app_src"
cp -r "${ROOT}/src/." "${HERE}/app_src/" || die "拷贝 ${ROOT}/src 失败"
# 去掉开发机的缓存与日志
find "${HERE}/app_src" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "${HERE}/app_src/logs"

# ------------------------------------------------------------------ 2. ONNX Runtime 头文件(两种 ABI 共用)
ORT_INC="${WORK_DIR}/onnxruntime-include"
mkdir -p "${ORT_INC}" "${WORK_DIR}"
if [[ ! -f "${ORT_INC}/onnxruntime_c_api.h" ]]; then
    Step "获取 ONNX Runtime C 头文件(v${ORT_VERSION})"
    for name in onnxruntime_c_api.h onnxruntime_ep_c_api.h onnxruntime_float16.h \
                onnxruntime_session_options_config_keys.h onnxruntime_cxx_api.h; do
        curl -fL -o "${ORT_INC}/${name}" \
            "https://raw.githubusercontent.com/microsoft/onnxruntime/v${ORT_VERSION}/include/onnxruntime/core/session/${name}" \
            || warn "下载 ${name} 失败(可能该版本没有这个头文件)"
    done
fi

# ------------------------------------------------------------------ 3. 模型检查(两种 ABI 共用)
MODEL_DIR="${HERE}/sr_qnn/models"
MODEL_COUNT=$(find "${MODEL_DIR}" -maxdepth 1 -name '*.onnx' 2>/dev/null | wc -l | tr -d ' ')
if [[ "${MODEL_COUNT}" == "0" ]]; then
    warn "sr_qnn/models 下还没有 onnx 模型，超分功能会在手机上禁用。"
    warn "请先运行: python android/tools/prepare_models.py --src <waifu2x onnx 目录> --tile 192 --verify"
else
    log "发现 ${MODEL_COUNT} 个模型文件"
fi

# ------------------------------------------------------------------ 4. python 依赖(两种 ABI 共用)
Step "准备 python 依赖(pyside6-android-deploy + buildozer)"
if [[ ! -d "${HERE}/.venv" ]]; then
    "${PYTHON_BIN}" -m venv "${HERE}/.venv" || die "创建 venv 失败(${PYTHON_BIN})"
fi
# shellcheck disable=SC1091
source "${HERE}/.venv/bin/activate"
pip install -q --upgrade pip || die "pip 升级失败(网络问题?可配 PIP_INDEX_URL 换源)"
pip install -q pyside6-android-deploy buildozer cython \
    || die "安装 pyside6-android-deploy/buildozer/cython 失败(网络问题?可配 PIP_INDEX_URL 换源)"

# ------------------------------------------------------------------ 单架构构建
# 说明：所有可能失败的步骤都显式 `|| Fail ...`(带 架构 + 步骤 + 原因)，
# 不依赖 set -e 隐式退出——否则失败时看不到是哪个架构、哪一步、缺哪个依赖。
# 函数在子 shell 里执行(见主循环)，失败只影响该架构。
BuildOneAbi() {
    local abi="$1"
    CTX="${abi}"; CURRENT_STEP="初始化"
    local ABI_LOG_CUR="${LOG_DIR}/build-${abi}.log"

    # ---- ABI 派生参数(与 tools/env.sh 一致) ----
    local WHEEL_TAG ARCH_NAME ORT_VARIANT QTPIP_ARCH
    case "${abi}" in
        arm64-v8a)
            WHEEL_TAG="android_aarch64"; ARCH_NAME="aarch64"
            ORT_VARIANT="onnxruntime-android-qnn"; QTPIP_ARCH="aarch64" ;;
        x86_64)
            WHEEL_TAG="android_x86_64";  ARCH_NAME="x86_64"
            ORT_VARIANT="onnxruntime-android";     QTPIP_ARCH="x86_64" ;;
        *) Fail "不支持的 ABI: ${abi}(支持: ${SUPPORTED_ABIS})"; return 1 ;;
    esac

    local ABI_WORK="${WORK_DIR}/${abi}"
    local LIBS_DIR="${HERE}/libs/${abi}"
    local SPEC="${ABI_WORK}/pysidedeploy.spec"
    local MARKER="${ABI_WORK}/.deploy_start"
    mkdir -p "${ABI_WORK}" "${LIBS_DIR}" || { Fail "创建目录失败: ${ABI_WORK}"; return 1; }

    # ------------------------------------------------ 1. ONNX Runtime 原生库
    Step "[${abi}] 下载/解包 ONNX Runtime(${ORT_VARIANT} ${ORT_VERSION})"
    local AAR="${ABI_WORK}/${ORT_VARIANT}-${ORT_VERSION}.aar"
    if [[ ! -s "${AAR}" ]]; then
        local ok=0 base url
        for base in "https://maven.aliyun.com/repository/central/com/microsoft/onnxruntime" \
                    "https://repo1.maven.org/maven2/com/microsoft/onnxruntime"; do
            url="${base}/${ORT_VARIANT}/${ORT_VERSION}/${ORT_VARIANT}-${ORT_VERSION}.aar"
            log "下载 ${url}"
            curl -fL --retry 3 --connect-timeout 20 --max-time 900 -o "${AAR}" "${url}" && { ok=1; break; }
            rm -f "${AAR}"
        done
        [[ ${ok} == 1 ]] || { Fail "下载 ${ORT_VARIANT} ${ORT_VERSION} 失败(网络/版本号问题；arm64 用 -qnn 变体，x86_64 用普通变体，可换 ORT_VERSION)"; return 1; }
    fi
    rm -rf "${ABI_WORK}/aar" && mkdir -p "${ABI_WORK}/aar"
    unzip -q -o "${AAR}" -d "${ABI_WORK}/aar" || { Fail "解包 AAR 失败: ${AAR}(文件损坏?删掉重下)"; return 1; }
    if [[ ! -d "${ABI_WORK}/aar/jni/${abi}" ]]; then
        Fail "AAR 里没有 jni/${abi}(现有: $(ls "${ABI_WORK}/aar/jni" 2>/dev/null | tr '\n' ' '))——版本 ${ORT_VERSION} 可能没有 ${abi} 变体，换 ORT_VERSION 试试"
        return 1
    fi
    cp "${ABI_WORK}/aar/jni/${abi}/"*.so "${LIBS_DIR}/" || { Fail "拷贝 libonnxruntime.so 到 ${LIBS_DIR} 失败"; return 1; }
    log "ONNX Runtime 库就绪(${LIBS_DIR}): $(ls -1 "${LIBS_DIR}" | tr '\n' ' ')"

    # arm64 的 QNN 运行库：缺了 NPU 就静默失效，所以这里不再是"提醒一下"，
    # 而是硬闸门(缺库自动补，补不上直接失败)。x86_64 没有 NPU，闸门内部会跳过。
    Step "[${abi}] QNN 运行库闸门"
    bash "${HERE}/tools/qnn_guard.sh" --android "${HERE}" --abi "${abi}" \
        || { Fail "libs/${abi} 缺 QNN 运行库且无法自动补齐(NPU 会在真机上静默失效)。
       手动补: bash android/tools/wsl_fetch_qnn.sh --libs-dir ${LIBS_DIR}
       确实要打纯 CPU 对照包: JM_QNN=0 $0 --abi ${abi}"; return 1; }

    # ------------------------------------------------ 2. libsr_qnn.so
    if [[ "${SKIP_NATIVE:-0}" != "1" ]]; then
        Step "[${abi}] 编译 libsr_qnn.so"
        local BUILD="${HERE}/sr_qnn/cpp/build-${abi}"
        cmake -S "${HERE}/sr_qnn/cpp" -B "${BUILD}" \
            -DCMAKE_TOOLCHAIN_FILE="${NDK}/build/cmake/android.toolchain.cmake" \
            -DANDROID_ABI="${abi}" \
            -DANDROID_PLATFORM="${ANDROID_PLATFORM}" \
            -DONNXRUNTIME_INCLUDE_DIR="${ORT_INC}" \
            -DONNXRUNTIME_LIB_DIR="${LIBS_DIR}" \
            -DCMAKE_BUILD_TYPE=Release \
            || { Fail "cmake 配置失败(${abi})：检查 NDK(${NDK})、以及 ${LIBS_DIR} 下是否有 libonnxruntime.so"; return 1; }
        cmake --build "${BUILD}" -j"${JOBS}" \
            || { Fail "编译 libsr_qnn.so 失败(${abi})，详见上方输出与 ${ABI_LOG_CUR}"; return 1; }
        cp "${BUILD}/libsr_qnn.so" "${LIBS_DIR}/" || { Fail "拷贝 libsr_qnn.so 到 ${LIBS_DIR} 失败"; return 1; }
        log "原生库就绪: ${LIBS_DIR}/libsr_qnn.so"
    else
        warn "SKIP_NATIVE=1，跳过 libsr_qnn.so 编译(${abi})"
        [[ -f "${LIBS_DIR}/libsr_qnn.so" ]] || warn "${LIBS_DIR}/libsr_qnn.so 不存在，超分后端会不可用"
    fi

    # ------------------------------------------------ 3. Qt wheel(每个 ABI 一套)
    Step "[${abi}] 检查 Qt wheel(${WHEEL_TAG})"
    local PY_WHEEL SHI_WHEEL
    PY_WHEEL=$(ls "${WHEEL_DIR}"/PySide6-*-"${WHEEL_TAG}".whl 2>/dev/null | head -n1 || true)
    SHI_WHEEL=$(ls "${WHEEL_DIR}"/shiboken6-*-"${WHEEL_TAG}".whl 2>/dev/null | head -n1 || true)
    if [[ -z "${PY_WHEEL}" || -z "${SHI_WHEEL}" ]]; then
        warn "${WHEEL_DIR} 缺少 ${abi} 的 wheel，尝试 qtpip 下载(--arch ${QTPIP_ARCH})"
        mkdir -p "${WHEEL_DIR}"
        (cd "${WHEEL_DIR}" && qtpip download PySide6 --android --arch "${QTPIP_ARCH}" || true)
        (cd "${WHEEL_DIR}" && qtpip download shiboken6 --android --arch "${QTPIP_ARCH}" || true)
        PY_WHEEL=$(ls "${WHEEL_DIR}"/PySide6-*-"${WHEEL_TAG}".whl 2>/dev/null | head -n1 || true)
        SHI_WHEEL=$(ls "${WHEEL_DIR}"/shiboken6-*-"${WHEEL_TAG}".whl 2>/dev/null | head -n1 || true)
    fi
    [[ -n "${PY_WHEEL}" ]] || { Fail "缺少 PySide6 ${WHEEL_TAG} wheel(${abi})：请放 ${WHEEL_DIR}/PySide6-*-${WHEEL_TAG}.whl，或手动 qtpip download PySide6 --android --arch ${QTPIP_ARCH}"; return 1; }
    [[ -n "${SHI_WHEEL}" ]] || { Fail "缺少 shiboken6 ${WHEEL_TAG} wheel(${abi})：请放 ${WHEEL_DIR}/shiboken6-*-${WHEEL_TAG}.whl，或手动 qtpip download shiboken6 --android --arch ${QTPIP_ARCH}"; return 1; }
    log "PySide6 wheel: $(basename "${PY_WHEEL}")"
    log "shiboken wheel: $(basename "${SHI_WHEEL}")"

    # ------------------------------------------------ 4. 部署配置(每个 ABI 一份)
    Step "[${abi}] 生成部署配置(arch=${ARCH_NAME}, mode=${BUILD_TYPE})"
    cp "${HERE}/pysidedeploy.spec" "${SPEC}" || { Fail "拷贝 pysidedeploy.spec 失败"; return 1; }
    "${PYTHON_BIN}" "${HERE}/tools/fill_deploy_spec.py" "${SPEC}" \
        --wheel-pyside "${PY_WHEEL}" --wheel-shiboken "${SHI_WHEEL}" \
        --arch "${ARCH_NAME}" \
        ${NDK:+--ndk-path "${NDK}"} ${SDK:+--sdk-path "${SDK}"} \
        || { Fail "fill_deploy_spec.py 写入失败(${abi})，详见上方输出"; return 1; }
    sed -i "s|^mode[[:space:]]*=.*|mode = ${BUILD_TYPE}|" "${SPEC}" \
        || { Fail "设置 mode=${BUILD_TYPE} 失败"; return 1; }

    # ------------------------------------------------ 5. 打包
    cd "${HERE}" || { Fail "cd ${HERE} 失败"; return 1; }
    Step "[${abi}] pyside6-android-deploy 打包(首次会下载/编译 python-for-android，耗时较长)"
    : > "${MARKER}" || { Fail "创建时间基准文件失败: ${MARKER}"; return 1; }
    pyside6-android-deploy --config-file "${SPEC}" --keep-deployment-files --force \
        || { Fail "pyside6-android-deploy 失败(${abi})；常见原因：${abi} 的 Qt wheel 缺失/版本不匹配、NDK/SDK 路径错、python-for-android 编译错误。完整日志见 ${ABI_LOG_CUR}"; return 1; }

    # ------------------------------------------------ 6. 打补丁(minSdk/方向/local_libs/版本号)
    Step "[${abi}] 钉 minSdk/屏幕方向/原生库清单(pin_min_sdk.sh)"
    ABI="${abi}" bash "${HERE}/tools/pin_min_sdk.sh" \
        || { Fail "pin_min_sdk.sh 失败(${abi})：不补丁的话 APK 会缺 local_libs/minSdk，装上也起不来"; return 1; }
    # 让 APK 内部版本号与产物命名一致(buildozer.spec 的 app.version -> versionName/versionCode)
    if [[ -f "${HERE}/buildozer.spec" ]]; then
        if grep -qE '^version[[:space:]]*=' "${HERE}/buildozer.spec"; then
            sed -i "s|^version[[:space:]]*=.*|version = ${APP_VERSION}|" "${HERE}/buildozer.spec"
        else
            printf 'version = %s\n' "${APP_VERSION}" >> "${HERE}/buildozer.spec"
        fi
        log "buildozer.spec version = ${APP_VERSION}"
    fi

    # ------------------------------------------------ 7. 重新打包(让补丁生效)
    if [[ "${REPACK:-1}" == "1" ]]; then
        Step "[${abi}] 应用补丁后重新打包"
        pyside6-android-deploy --config-file "${SPEC}" --keep-deployment-files --force \
            || { Fail "第二次打包失败(${abi})，完整日志见 ${ABI_LOG_CUR}"; return 1; }
    fi

    # ------------------------------------------------ 8. 收集产物 + 校验架构
    Step "[${abi}] 收集产物 -> ${DIST_DIR}"
    local EXT="apk"
    [[ "${BUILD_TYPE}" == "release" ]] && EXT="aab"
    # 只收本次打包新产出的(MARKER 在打包前创建)，多个时取 mtime 最新的
    local best="" best_ts=0 f ts
    while IFS= read -r f; do
        [[ -n "${f}" ]] || continue
        ts=$(stat -c %Y "${f}" 2>/dev/null || stat -f %m "${f}" 2>/dev/null || echo 0)
        if [[ "${ts}" -ge "${best_ts}" ]]; then best="${f}"; best_ts="${ts}"; fi
    done < <(find "${HERE}" -maxdepth 8 -name "*.${EXT}" -newer "${MARKER}" \
        -not -path '*/.venv/*' -not -path "${DIST_DIR}/*" 2>/dev/null)
    [[ -n "${best}" ]] || { Fail "没有找到 ${abi} 新生成的 .${EXT}(打包可能没产出)，完整日志见 ${ABI_LOG_CUR}"; return 1; }
    log "打包产物: ${best}"

    # 校验 APK 里的原生库确实是本架构(经典事故：包装成另一个 ABI 的 .so，装完才闪退)
    if ! unzip -l "${best}" 2>/dev/null | grep -q "lib/${abi}/"; then
        Fail "APK 里没有 lib/${abi}/ 原生库(可能装错了架构)，用 unzip -l 检查 ${best}"
        return 1
    fi
    log "APK 原生库目录校验通过: lib/${abi}/"
    if [[ -f "${LIBS_DIR}/libsr_qnn.so" ]]; then
        if ! unzip -l "${best}" 2>/dev/null | grep -q "lib/${abi}/libsr_qnn.so"; then
            Fail "APK 里缺少 lib/${abi}/libsr_qnn.so(超分后端没打进包)。若为 x86_64：buildozer 1.6.0 的 add_libs 映射表缺 x86_64 键、会被静默忽略，先跑 bash tools/wsl_patch_buildozer_addlibs.sh；若为 arm64：先用 bash tools/qnn_guard.sh --abi arm64-v8a 体检 libs 目录"
            return 1
        fi
        log "APK 含 libsr_qnn.so(超分后端已打入)"
    fi
    # QNN 运行库不进 QtLoader 的清单(由 libsr_qnn 自己 dlopen)，必须单独断言：
    # 少一个 libQnnHtp.so 就是"真机能装能跑但超分纯 CPU"的静默事故。
    if ! "${PYTHON_BIN}" "${HERE}/tools/qnn_manifest.py" verify-apk --apk "${best}" --abi "${abi}" --quiet; then
        "${PYTHON_BIN}" "${HERE}/tools/qnn_manifest.py" verify-apk --apk "${best}" --abi "${abi}" | sed 's/^/    /'
        Fail "APK 里的 QNN 运行库不齐全(装到真机会静默退回 CPU 超分)"
        return 1
    fi
    log "APK 含 QNN 运行库(NPU 加速可用)"

    local OUT="${DIST_DIR}/${APP_NAME}-${APP_VERSION}-${abi}-${BUILD_TYPE}.${EXT}"
    mkdir -p "${DIST_DIR}" || { Fail "创建输出目录失败: ${DIST_DIR}"; return 1; }
    mv -f "${best}" "${OUT}" || { Fail "移动产物到 ${OUT} 失败"; return 1; }
    log "产物已就位: ${OUT} ($(du -h "${OUT}" | cut -f1))"
    return 0
}

# ------------------------------------------------------------------ 多架构构建(主循环)
mkdir -p "${LOG_DIR}" "${DIST_DIR}"
OK_ABIS=""
FAILED_ABIS=""
for abi in ${ABIS_STR}; do
    ABI_LOG="${LOG_DIR}/build-${abi}.log"
    log "================ 开始构建架构: ${abi}(完整日志: ${ABI_LOG}) ================"
    rc=0
    # 子 shell 跑单架构构建；输出同时进终端和该架构的日志文件
    ( BuildOneAbi "${abi}" ) 2>&1 | tee "${ABI_LOG}" || rc=$?
    if [[ ${rc} -eq 0 ]]; then
        OK_ABIS+="${abi} "
        log "架构 ${abi} 构建成功"
    else
        FAILED_ABIS+="${abi} "
        if [[ "${CONTINUE_ON_ERROR}" != "1" ]]; then
            die "架构 ${abi} 构建失败(详见 ${ABI_LOG})；修好后可单独重跑: ./build_android.sh --abi ${abi}；或设 CONTINUE_ON_ERROR=1 继续构建其余架构"
        fi
        warn "架构 ${abi} 构建失败，继续构建其余架构(CONTINUE_ON_ERROR=1)"
    fi
done

# ------------------------------------------------------------------ 汇总
echo
log "================ 构建结果 ================"
for abi in ${OK_ABIS}; do
    ext="apk"; [[ "${BUILD_TYPE}" == "release" ]] && ext="aab"
    f="${DIST_DIR}/${APP_NAME}-${APP_VERSION}-${abi}-${BUILD_TYPE}.${ext}"
    log "[OK]   ${abi}: ${f} ($(du -h "${f}" 2>/dev/null | cut -f1))"
    log "       原生库(${HERE}/libs/${abi}): $(ls -1 "${HERE}/libs/${abi}" 2>/dev/null | tr '\n' ' ')"
done
for abi in ${FAILED_ABIS}; do
    warn "[FAIL] ${abi}: 失败详情见 ${LOG_DIR}/build-${abi}.log；单独重跑: ./build_android.sh --abi ${abi}"
done
[[ -z "${FAILED_ABIS}" ]] || exit 1

{
echo
echo "下一步："
n=1
for abi in ${OK_ABIS}; do
    ext="apk"; [[ "${BUILD_TYPE}" == "release" ]] && ext="aab"
    echo "  ${n}) adb install -r ${DIST_DIR}/${APP_NAME}-${APP_VERSION}-${abi}-${BUILD_TYPE}.${ext}   # ${abi}"
    n=$((n + 1))
done
cat <<EOF
     (两种 ABI 只能装一个；adb install -r 可直接互相覆盖)
  ${n}) 推送模型(如果模型没有打进 APK)
       adb push ${MODEL_DIR}/. /sdcard/Android/data/<package.name>/files/waifu2x-models/
       # 包名以 buildozer.spec 里的 package.name/domain 为准
  $((n + 1))) 查看日志
       adb logcat | grep -i -E "python|sr_qnn|Qt"

各架构完整构建日志：${LOG_DIR}/build-<abi>.log
EOF
}
