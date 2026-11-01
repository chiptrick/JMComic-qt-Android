#!/usr/bin/env bash
# JMComic Android 打包脚本(多 ABI 一键构建)
#
# 要求(宿主机必须是 Linux 或 macOS；pyside6-android-deploy 目前不支持 Windows 主机)：
#   * Python 3.11/3.12 + venv
#   * JDK 17
#   * Android SDK(platform-tools + 目标 platform + build-tools；具体版本见
#     tools/versions.env，build-tools 默认取已装的最高版本)
#   * JDK 17~25（默认用 25 LTS；不写死：tools/resolve_jdk.sh 自动发现并校验区间）
#   * Gradle 9.x（JDK 25 要求 >= 9.1；wrapper 在打包前由 tools/gradle_wrapper.py 预置）
#   * Android NDK r28 及以上(不写死版本：默认自动取 $ANDROID_HOME/ndk 下最高版本，
#     可用 JM_NDK_VERSION=<版本> 钉住某个版本，或用 ANDROID_NDK_HOME 指定目录)
#     r28+ 默认按 16KB 页对齐编译；产物打完会自动跑 16KB 门禁(tools/check_elf_page_align.py)
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
#   ./build_android.sh                       # NDK 自动取最新；一键构建 arm64-v8a + x86_64
#   JM_NDK_VERSION=28.2.13676358 ./build_android.sh   # 钉住某个 NDK 版本(回退用)
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

# 输出不缓冲：Python 写文件时是块缓冲，进程一旦被杀（OOM / 会话回收 / 沙箱策略），
# 最后几 KB 日志会整个丢失，只剩“停在某一步”的假象，真正的报错永远看不到。
# PYTHONUNBUFFERED=1 让 p4a / buildozer / python 的输出即时落盘。
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"

# 工具链版本号的唯一来源 + 宿主平台抽象层。
# 原则：本脚本里不出现 android-34 / 35.0.0 / openjdk-17 / nproc / sed -i 这类
# 与具体版本或平台绑定的字面量，全部走这两个文件里的函数与变量。
# shellcheck source=tools/versions.env
. "${HERE}/tools/versions.env"
# shellcheck source=tools/resolve_host.sh
. "${HERE}/tools/resolve_host.sh"
# 机器本地路径（不入库）：JM_JDK / ANDROID_HOME / TMPDIR 等只对本机有效的值放这里，
# 免得每次手动构建都要 export。模板见 tools/local.env.example
if [[ -f "${HERE}/tools/local.env" ]]; then
    # shellcheck source=tools/local.env
    . "${HERE}/tools/local.env"
fi

# ------------------------------------------------------------------ 可调参数
# 版本号一律来自 tools/versions.env（可用环境变量覆盖），脚本内不再写字面量
ORT_VERSION="${ORT_VERSION:-${JM_ORT_VERSION}}"                      # onnxruntime-android(-qnn) 版本
ANDROID_PLATFORM="${ANDROID_PLATFORM:-android-${JM_API_LEVEL}}"      # compileSdk/minSdk 见 versions.env
BUILD_TYPE="${BUILD_TYPE:-debug}"                                    # debug -> apk, release -> aab
PYTHON_BIN="${PYTHON_BIN:-python3}"
SDK="$(jm_norm_path "${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}")"
# 没显式给 SDK 时按常见位置找（仓库同级的 Android_SDK 是最常见的放法）
if [[ -z "${SDK}" ]]; then
    for _cand in "$(dirname "${ROOT}")/Android_SDK" "${HOME}/Android/Sdk" \
                 /opt/android-sdk /usr/local/android-sdk; do
        if [[ -d "${_cand}" ]]; then SDK="${_cand}"; break; fi
    done
fi
# NDK 不写死版本：统一交给 tools/resolve_ndk.sh
#   1) JM_NDK / ANDROID_NDK_HOME / ANDROID_NDK_ROOT 显式路径
#   2) JM_NDK_VERSION=<版本> 钉住 $SDK/ndk/<版本>
#   3) 默认取 $SDK/ndk/* 里版本号最高的 —— 以后装了新 NDK 不用改脚本
# shellcheck source=tools/resolve_ndk.sh
. "${HERE}/tools/resolve_ndk.sh"
NDK="$(jm_resolve_ndk "${SDK}")"
[[ -n "${NDK}" ]] || NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-}}"
NDK="$(jm_norm_path "${NDK}")"
NDK_VER="${JM_NDK_VER:-}"
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
  ORT_VERSION=<ver>     ONNX Runtime 版本(默认取 tools/versions.env 的 JM_ORT_VERSION)
  ANDROID_PLATFORM=<api> 默认 android-${JM_API_LEVEL}(=compileSdk)
  DIST_DIR=<dir>        输出目录(默认 android/dist)
  SKIP_NATIVE=1         跳过 libsr_qnn.so 编译(原生库已编好时)
  REPACK=0              打补丁后不重新打包(默认 REPACK=1)
  CONTINUE_ON_ERROR=1   某架构失败也继续构建其余架构(默认失败即停)
  ANDROID_NDK_HOME=<dir> / JM_NDK=<dir>   指定 NDK 目录(优先于自动发现)
  JM_NDK_VERSION=<ver>  钉住 NDK 版本，如 30.0.16248370 / 28.2.13676358
  JM_JDK=<dir> / JM_JDK_VERSION=<ver>     指定构建 JDK(默认自动选 17~25 内最高)
  JM_API_LEVEL=<api> / JM_MIN_SDK=<api>   compileSdk / minSdk(默认取 versions.env)
  JM_BUILD_TOOLS=auto|<ver>               auto=用已装的最高版本
  JM_GRADLE_MIN=<ver> / JM_GRADLE_VERSION=<ver>   Gradle 下限 / 改写目标版本
  ALLOW_UNALIGNED=1     放行未按 16KB 对齐的包(默认拦下，见 tools/check_elf_page_align.py)

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
# 宿主平台：不再用 uname 字面量判断，WSL 单独识别（错误提示能指到正确做法）
case "$(jm_host_os)" in
    linux|wsl|darwin) log "宿主平台: $(jm_host_desc)" ;;
    *) die "pyside6-android-deploy 只支持 Linux / WSL / macOS 主机(当前: $(jm_host_desc))；
       Windows 请在 WSL2 里运行: wsl --cd /mnt/c/<路径>/android -e ./build_android.sh" ;;
esac
jm_require_cmds unzip curl || die "缺少基础命令（unzip/curl）"

# p4a 编 libffi/openssl 时会跑 autogen.sh（autoreconf），缺 autotools 的报错是
# `sh.ErrorReturnCode_127 ... exec: autoreconf: not found`，藏在 300 行 traceback 里，
# 看起来像 p4a 的 bug。这里提前拦，并给出各发行版的装法。
if ! jm_require_cmds autoreconf automake libtoolize pkg-config make; then
    die "主机缺少 autotools（p4a 的 libffi/openssl recipe 需要）:
       Fedora : dnf install autoconf automake libtool pkgconf-pkg-config
       Debian : apt install autoconf automake libtool pkg-config
       macOS  : brew install autoconf automake libtool pkg-config
       没有 root 时：源码装到任意前缀，并在 tools/local.env 里把它的 bin 加进 PATH"
fi

# openssl 的 recipe 用 perl 跑 Configure，里面 use 了一串 **Perl 核心模块**。
# 精简安装的 perl（只有解释器、不带 perl-core）会在这里炸：
#   Can't locate FindBin.pm in @INC ... BEGIN failed--compilation aborted at Configure line 15
# 报错发生在 openssl 的 Configure 里，看起来和 Android/NDK 毫无关系，很容易误判。
PERL_CORE_MODULES="FindBin File::Basename File::Copy Cwd Text::ParseWords"
_missing_perl=""
for _m in ${PERL_CORE_MODULES}; do
    perl -M"${_m}" -e1 2>/dev/null || _missing_perl="${_missing_perl} ${_m}"
done
if [[ -n "${_missing_perl}" ]]; then
    die "Perl 缺少核心模块:${_missing_perl}（openssl recipe 的 Configure 需要）
       Fedora : sudo dnf install perl-core          # 一次补齐所有核心模块
                或最小安装: sudo dnf install perl-FindBin
       Debian : sudo apt install perl               # 完整版自带这些核心模块
       macOS  : 自带 perl 已包含，若报错说明 PATH 里的 perl 不是系统 perl"
fi
PYVER="$("${PYTHON_BIN}" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
[[ -n "${PYVER}" ]] || die "找不到 ${PYTHON_BIN}（pyside6-android-deploy 需要 Python >= ${JM_PYTHON_MIN}）"
jm_ver_ge "${PYVER}" "${JM_PYTHON_MIN}" || \
    die "Python 版本过低: ${PYVER}(需要 >= ${JM_PYTHON_MIN}；可用 PYTHON_BIN=python3.11 指定)"

# JDK：不盲信 PATH / JAVA_HOME —— 系统默认 java 可能已是 27，而 Gradle 8.14 只能跑在 17~24
# shellcheck source=tools/resolve_jdk.sh
. "${HERE}/tools/resolve_jdk.sh"
jm_resolve_jdk >/dev/null || true
if [[ -z "${JM_JDK:-}" ]]; then
    printf '\033[1;31m[error]\033[0m 找不到落在 %s~%s 区间的构建 JDK\n' \
        "${JM_JDK_MIN}" "${JM_JDK_MAX}" >&2
    jm_jdk_hint
    exit 1
fi
jm_apply_jdk || die "设置 JAVA_HOME 失败: ${JM_JDK}"

# 把系统 CA 根导入本 JDK 的 cacerts（幂等）：精简 JDK 的信任库在证书链不完整
# 的网络下会让所有 Java 侧下载报 PKIX——Gradle wrapper 拉 9.8.2 分发包就栽在这里。
if [[ -f "${HERE}/tools/patch_java_cacerts.sh" ]]; then
    bash "${HERE}/tools/patch_java_cacerts.sh" "${JAVA_HOME}" | sed 's/^/    /' || true
fi

# cmake / build-tools：版本不够就早失败，别等到编 libsr_qnn 或打包末期才暴露
CMAKE_VER="$(jm_cmd_version cmake --version)"
[[ -n "${CMAKE_VER}" ]] || die "缺少 cmake(需要 >= ${JM_CMAKE_MIN})"
jm_ver_ge "${CMAKE_VER}" "${JM_CMAKE_MIN}" || \
    die "cmake 版本过低: ${CMAKE_VER}(需要 >= ${JM_CMAKE_MIN})"
BT_VER=""
if [[ -n "${SDK}" && -d "${SDK}/build-tools" ]]; then
    if [[ "${JM_BUILD_TOOLS}" == "auto" ]]; then
        BT_VER="$(ls -1 "${SDK}/build-tools" 2>/dev/null \
            | sort -t. -k1,1n -k2,2n -k3,3n | tail -n1)"
    else
        BT_VER="${JM_BUILD_TOOLS}"
    fi
    [[ -d "${SDK}/build-tools/${BT_VER}" ]] || \
        warn "build-tools ${BT_VER} 未安装（sdkmanager --install \"build-tools;${BT_VER}\"）"
fi

[[ -n "${NDK}" ]] || { printf '\033[1;31m[error]\033[0m 找不到 Android NDK\n' >&2; jm_ndk_hint "${SDK}"; exit 1; }
[[ -d "${NDK}" ]] || die "NDK 目录不存在: ${NDK}"
[[ -n "${NDK_VER}" ]] || NDK_VER="$(jm_ndk_version_of "${NDK}")"
# 16KB 页对齐是硬要求：r28 起默认对齐，r26/r27 编出的库仍会是 4KB
if ! jm_ndk_ge "${NDK_VER}" "${JM_NDK_MIN_MAJOR}.0.0"; then
    die "NDK 版本过低: ${NDK_VER}(路径 ${NDK})
       16KB 页对齐要求 NDK r${JM_NDK_MIN_MAJOR} 及以上(r28+ 默认按 16KB 对齐)。
       安装最新版: sdkmanager --install \"ndk\"
       或钉住一个已知版本: JM_NDK_VERSION=28.2.13676358 $0"
fi
[[ -n "${SDK}" ]] || warn "未设置 ANDROID_HOME，pyside6-android-deploy 可能找不到 SDK"
JOBS="$(jm_nproc)"

# 脚本卫生检查（CRLF/BOM/shebang）：踩过 `bad interpreter: No such file or directory`，
# 根因就是第一行末尾的 \r，和"环境没装 bash"看起来一模一样。
if [[ -f "${HERE}/tools/check_scripts.py" ]]; then
    if ! LINT_OUT="$("${PYTHON_BIN}" "${HERE}/tools/check_scripts.py" "${HERE}" 2>&1)"; then
        warn "脚本卫生检查未通过（CRLF/BOM/shebang），构建可能在其它机器上失败："
        printf '%s\n' "${LINT_OUT}" | sed 's/^/    /'
        warn "一键修复: ${PYTHON_BIN} tools/check_scripts.py ${HERE} --fix"
    fi
fi

log "构建入口: ${BASH_SOURCE[0]}"
log "目标架构: ${ABIS_STR}(一个 APK 只含一种 ABI，分别构建)"
log "输出目录: ${DIST_DIR}"
log "NDK:      ${NDK}(${NDK_VER})"
log "16KB 页:  $(jm_ndk_16k_note "${NDK_VER}")"
log "JDK:      ${JM_JDK}(Java ${JM_JDK_VER}；区间 ${JM_JDK_MIN}~${JM_JDK_MAX})"
log "cmake:    ${CMAKE_VER}(要求 >= ${JM_CMAKE_MIN})   build-tools: ${BT_VER:-未设置 JM_BUILD_TOOLS 且 SDK 缺失}"
log "平台版本: API ${JM_API_LEVEL} / minSdk ${JM_MIN_SDK}(见 tools/versions.env)"
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
# 逐个文件检查：ORT 会随版本增加/拆分头文件（1.29 起 c_api.h 新增
# #include "onnxruntime_error_code.h"），用"整目录存在就跳过"的写法会在升级
# ORT 后突然编译失败，而且报错点是 c_api.h 内部，看起来像 SDK 坏了。
ORT_HEADERS="onnxruntime_c_api.h onnxruntime_ep_c_api.h onnxruntime_error_code.h
onnxruntime_float16.h onnxruntime_session_options_config_keys.h
onnxruntime_cxx_api.h onnxruntime_cxx_inline.h"
_ort_missing=""
for name in ${ORT_HEADERS}; do
    [[ -s "${ORT_INC}/${name}" ]] && continue
    _ort_missing="${_ort_missing} ${name}"
done
if [[ -n "${_ort_missing}" ]]; then
    Step "获取 ONNX Runtime C 头文件(v${ORT_VERSION})"
    for name in ${_ort_missing}; do
        jm_download "https://raw.githubusercontent.com/microsoft/onnxruntime/v${ORT_VERSION}/include/onnxruntime/core/session/${name}" \
            "${ORT_INC}/${name}" \
            || { command rm -f "${ORT_INC}/${name}"; warn "下载 ${name} 失败(该版本可能没有这个头文件)"; }
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
# p4a 不在上面那三个包里：buildozer 是通过 `p4a` 命令调用它的。
# WSL 流程是 clone develop 分支再 pip install（见 tools/wsl_config_mirrors.sh）；
# Linux 主机上没预装时这里兜底装 PyPI 版，保证"干净机器也能起构建"。
# buildozer 以 root 运行时会交互式问 "Are you sure... [y/n]"，无人值守构建
# 拿不到 stdin 就 EOFError 崩掉。改它默认 spec 模板里的 warn_on_root（幂等）。
BUILDOZER_SPEC_TPL="$("${PYTHON_BIN}" -c 'import buildozer,os;print(os.path.join(os.path.dirname(buildozer.__file__),"default.spec"))' 2>/dev/null || true)"
if [[ -f "${BUILDOZER_SPEC_TPL}" ]] && grep -qE '^warn_on_root[[:space:]]*=[[:space:]]*1' "${BUILDOZER_SPEC_TPL}"; then
    jm_sed_i 's/^warn_on_root[[:space:]]*=[[:space:]]*1/warn_on_root = 0/' "${BUILDOZER_SPEC_TPL}"
    log "已关闭 buildozer 的 root 交互确认(模板 warn_on_root=0)"
fi
# 已经生成过的 buildozer.spec 也要改，否则"上一次失败的残留"会继续挡路
if [[ -f "${HERE}/buildozer.spec" ]] && grep -qE '^warn_on_root[[:space:]]*=[[:space:]]*1' "${HERE}/buildozer.spec"; then
    jm_sed_i 's/^warn_on_root[[:space:]]*=[[:space:]]*1/warn_on_root = 0/' "${HERE}/buildozer.spec"
    log "已关闭 buildozer 的 root 交互确认(现有 buildozer.spec)"
fi

if ! command -v p4a >/dev/null 2>&1; then
    warn "未检测到 p4a(python-for-android)，尝试 pip 安装"
    pip install -q python-for-android \
        || die "安装 python-for-android 失败；也可先 clone develop 分支再 pip install ./p4a"
fi

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
    # spec 必须放在工程根目录（= main.py 所在目录）：Qt deploy 工具把
    # config_file.parent 当作 project_dir，并把 deployment/ 与 .buildozer/ 都建在
    # project_dir 下，随后用 is_relative_to() 做安全校验。放进 .work/<abi>/ 会被
    # 判定成"要删除的目录在工程之外"而直接 RuntimeError。
    local SPEC="${HERE}/pysidedeploy.${abi}.spec"
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
            jm_download "${url}" "${AAR}" && { ok=1; break; }
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
            -DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON \
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
    cp "${SPEC}" "${ABI_WORK}/pysidedeploy.spec" 2>/dev/null || true   # 留一份按 ABI 存档
    "${PYTHON_BIN}" "${HERE}/tools/fill_deploy_spec.py" "${SPEC}" \
        --wheel-pyside "${PY_WHEEL}" --wheel-shiboken "${SHI_WHEEL}" \
        --arch "${ARCH_NAME}" \
        ${NDK:+--ndk-path "${NDK}"} ${SDK:+--sdk-path "${SDK}"} \
        || { Fail "fill_deploy_spec.py 写入失败(${abi})，详见上方输出"; return 1; }
    jm_sed_i "s|^mode[[:space:]]*=.*|mode = ${BUILD_TYPE}|" "${SPEC}" \
        || { Fail "设置 mode=${BUILD_TYPE} 失败"; return 1; }

    # ------------------------------------------------ 4.5 预置 Gradle 版本
    # JDK 25 只能跑 Gradle >= 9.1，而 p4a 模板自带的是 8.14.x；第一次 gradle 调用
    # 发生在 pyside6-android-deploy 内部，来不及"打完包再改"。所以这里先把
    # p4a 模板（site-packages）与已有 dist 里的 wrapper 一起改好，幂等、可重复执行。
    local SITE_PACKAGES P4A_MANAGED
    SITE_PACKAGES="$("${PYTHON_BIN}" -c 'import sysconfig;print(sysconfig.get_paths()["purelib"])' 2>/dev/null || true)"
    P4A_MANAGED="$(jm_norm_path "${JM_P4A_SRC:-${HERE}/.p4a-src}")"

    # ---- p4a recipe 下载地址镜像化（幂等）----
    # p4a 会把自己复制到 .buildozer/android/platform/ 下，**下载用的是那份副本**。
    # 只改 venv 没用：实测构建仍从 github.com 直连（502/超时），表现就是
    # "卡在下载 openssl / sqlite3 / python3"，进度条停在 90% 一动不动。
    Step "[${abi}] 镜像化 p4a recipe 下载地址"
    if [[ -n "${SITE_PACKAGES}" && -d "${SITE_PACKAGES}/pythonforandroid/recipes" ]]; then
        bash "${HERE}/tools/patch_p4a_urls.sh" "${SITE_PACKAGES}" \
            || warn "镜像化 venv 里的 p4a recipe 失败（下载可能很慢）"
    fi
    if [[ -d "${HERE}/.buildozer/android/platform/python-for-android/pythonforandroid/recipes" ]]; then
        bash "${HERE}/tools/patch_p4a_urls.sh" "${HERE}/.buildozer/android/platform/python-for-android" \
            || warn "镜像化 .buildozer 里的 p4a recipe 失败（下载可能很慢）"
    fi
    # aria2c 多线程下载（幂等本地补丁；JM_USE_ARIA2=0 可关）
    for _p4a_root in "${SITE_PACKAGES}" "${HERE}/.buildozer/android/platform/python-for-android" "${P4A_MANAGED}"; do
        if [[ -f "${_p4a_root}/pythonforandroid/recipe.py" ]]; then
            "${PYTHON_BIN}" "${HERE}/tools/patch_p4a_downloader.py" \
                "${_p4a_root}/pythonforandroid/recipe.py" | sed 's/^/    /' \
                || warn "aria2 下载补丁失败: ${_p4a_root}"
        fi
    done

    # ---- 用受管 p4a 源码树（关键修复）----
    # buildozer 每次 android debug 都会对它 clone 的 p4a 做 git clean/checkout，
    # 打在 .buildozer 副本里的镜像/aria2 补丁会被还原（实测 21:46 改写 109 个、
    # 随后下载仍走 github 直连）。而 .buildozer 一旦被删/重建，buildozer 还会
    # 重新 git clone，又是一份全新未打补丁的树。
    # 改用 p4a.source_dir 指向一棵我们自己管理的树：buildozer 检测到它会完全
    # 跳过 git 管理（只检查目录存在），补丁从此稳定存活。
    Step "[${abi}] 预置受管 p4a 源码树"
    if [[ ! -d "${P4A_MANAGED}/pythonforandroid" ]]; then
        if [[ -d "${HERE}/.buildozer/android/platform/python-for-android/pythonforandroid" ]]; then
            cp -a "${HERE}/.buildozer/android/platform/python-for-android" "${P4A_MANAGED}" \
                || { Fail "复制 p4a 源码树到 ${P4A_MANAGED} 失败"; return 1; }
            log "已从 .buildozer 副本复制受管 p4a 树"
        else
            git clone -b develop --single-branch \
                "${JM_GH_MIRROR_PREFIX}https://github.com/kivy/python-for-android.git" \
                "${P4A_MANAGED}" || { Fail "clone p4a 失败（可用 JM_P4A_SRC 指向现成源码树）"; return 1; }
        fi
    fi
    bash "${HERE}/tools/patch_p4a_urls.sh" "${P4A_MANAGED}" >/dev/null 2>&1 \
        || warn "受管 p4a 树镜像化失败"
    # 把 p4a.source_dir 写进 spec 的 [app] 段（幂等）
    python3 - "${SPEC}" "${P4A_MANAGED}" <<'PY'
import pathlib, sys
spec, src = pathlib.Path(sys.argv[1]), sys.argv[2]
lines = spec.read_text(encoding="utf-8").splitlines()
key = "p4a.source_dir = "
if not any(line.startswith(key) for line in lines):
    idx = lines.index("[app]") if "[app]" in lines else 0
    lines.insert(idx + 1, key + src)
    spec.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("[JM] buildozer.spec 已指向受管 p4a 树:", src)
PY

    if [[ -n "${JM_GRADLE_VERSION}" ]]; then
        Step "[${abi}] 预置 Gradle wrapper -> ${JM_GRADLE_VERSION}"
        # 三个来源都要覆盖：
        #   1) venv 里的 p4a（site-packages）
        #   2) .buildozer 里那份 p4a clone 的 **bootstrap 模板** —— dist 的 wrapper
        #      就是从它生成的，漏了它，新 dist 永远是模板里的旧版本
        #   3) 已存在的 dist（增量修复）
        local _groots=("${SITE_PACKAGES}" "${HERE}/.buildozer/android/platform/python-for-android" "${ABI_WORK}")
        for _root in "${_groots[@]}"; do
            [[ -n "${_root}" && -d "${_root}" ]] || continue
            "${PYTHON_BIN}" "${HERE}/tools/gradle_wrapper.py" --search "${_root}" \
                --min "${JM_GRADLE_MIN}" --set "${JM_GRADLE_VERSION}" \
                | sed 's/^/    /' || warn "预置 Gradle 失败: ${_root}"
        done
    fi

    # ------------------------------------------------ 5. 打包
    cd "${HERE}" || { Fail "cd ${HERE} 失败"; return 1; }
    Step "[${abi}] pyside6-android-deploy 打包(首次会下载/编译 python-for-android，耗时较长)"
    : > "${MARKER}" || { Fail "创建时间基准文件失败: ${MARKER}"; return 1; }
    # buildozer 在 root 下会交互确认；它的 init 阶段还没有 spec 可读，env 覆盖无效，
    # 只能喂有限行 stdin（不用 yes：它退出时的 SIGPIPE 会在 pipefail 下污染退出码）。
    printf 'y\ny\ny\n' | pyside6-android-deploy --config-file "${SPEC}" --keep-deployment-files --force \
        || { Fail "pyside6-android-deploy 失败(${abi})；常见原因：${abi} 的 Qt wheel 缺失/版本不匹配、NDK/SDK 路径错、python-for-android 编译错误。完整日志见 ${ABI_LOG_CUR}
       若报的是工具链/NDK 相关错误(装的是 NDK ${NDK_VER})，多半是 p4a 还没跟上这个 NDK 版本：
       用 JM_NDK_VERSION=28.2.13676358 $0 --abi ${abi} 换到 p4a 已适配的版本再试(r28 起默认 16KB 对齐)"; return 1; }

    # ------------------------------------------------ 6. 打补丁(minSdk/方向/local_libs/版本号)
    Step "[${abi}] 钉 minSdk/屏幕方向/原生库清单(pin_min_sdk.sh)"
    ABI="${abi}" bash "${HERE}/tools/pin_min_sdk.sh" \
        || { Fail "pin_min_sdk.sh 失败(${abi})：不补丁的话 APK 会缺 local_libs/minSdk，装上也起不来"; return 1; }
    # 让 APK 内部版本号与产物命名一致(buildozer.spec 的 app.version -> versionName/versionCode)
    if [[ -f "${HERE}/buildozer.spec" ]]; then
        if grep -qE '^version[[:space:]]*=' "${HERE}/buildozer.spec"; then
            jm_sed_i "s|^version[[:space:]]*=.*|version = ${APP_VERSION}|" "${HERE}/buildozer.spec"
        else
            printf 'version = %s\n' "${APP_VERSION}" >> "${HERE}/buildozer.spec"
        fi
        log "buildozer.spec version = ${APP_VERSION}"
    fi

    # ------------------------------------------------ 7. 重新打包(让补丁生效)
    if [[ "${REPACK:-1}" == "1" ]]; then
        Step "[${abi}] 应用补丁后重新打包"
        printf 'y\ny\ny\n' | pyside6-android-deploy --config-file "${SPEC}" --keep-deployment-files --force \
            || { Fail "第二次打包失败(${abi})，完整日志见 ${ABI_LOG_CUR}"; return 1; }
    fi

    # ------------------------------------------------ 7.5 Gradle wrapper 版本
    # Gradle 版本不在本仓库里，而在 p4a 生成的 dist 中，每次 --init 都会被重建。
    # 这里只做"检查 + 可选改写"：8.x -> 9.x 是跨大版本（会移除已弃用 API，
    # 本构建的日志里 Gradle 自己就打了 incompatible with Gradle 9.0），
    # 所以默认不强行跳大版本，只在显式给 JM_GRADLE_VERSION 时改写（下次构建生效）。
    Step "[${abi}] Gradle wrapper 版本检查"
    if [[ -n "${JM_GRADLE_VERSION}" ]]; then
        "${PYTHON_BIN}" "${HERE}/tools/gradle_wrapper.py" --search "${ABI_WORK}" \
            --min "${JM_GRADLE_MIN}" --set "${JM_GRADLE_VERSION}" \
            || warn "gradle-wrapper 改写失败或仍低于 ${JM_GRADLE_MIN}（见上）"
    else
        "${PYTHON_BIN}" "${HERE}/tools/gradle_wrapper.py" --search "${ABI_WORK}" \
            --min "${JM_GRADLE_MIN}" \
            || warn "Gradle 版本低于安全下限 ${JM_GRADLE_MIN}（8.14.6/9.8.1 起修掉 3 个 high 级公告）。
       要升级: JM_GRADLE_VERSION=${JM_GRADLE_MIN} $0 --abi ${abi}（同大版本，只需下载新分发包）"
    fi

    # ------------------------------------------------ 8. 收集产物 + 校验架构
    Step "[${abi}] 收集产物 -> ${DIST_DIR}"
    local EXT="apk"
    [[ "${BUILD_TYPE}" == "release" ]] && EXT="aab"
    # 只收本次打包新产出的(MARKER 在打包前创建)，多个时取 mtime 最新的
    local best="" best_ts=0 f ts
    while IFS= read -r f; do
        [[ -n "${f}" ]] || continue
        ts=$(jm_stat_mtime "${f}")
        if [[ "${ts}" -ge "${best_ts}" ]]; then best="${f}"; best_ts="${ts}"; fi
    done <<EOF
$(find "${HERE}" -maxdepth 8 -name "*.${EXT}" -newer "${MARKER}" -not -path '*/.venv/*' -not -path "${DIST_DIR}/*" 2>/dev/null)
EOF
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

    # 16KB 页门禁：在产物级判定，和上面的加载清单/QNN 清单同一层。
    # 只看 p_align < 16384 的库(Google check_elf_alignment.sh 口径)，
    # Hexagon skel / 非 ELF 数据包会自动跳过。真跑在 16KB 设备上是否正常
    # 还要靠 tools/check_16kb_device.sh 实测，这里拦的是"编错了"。
    Step "[${abi}] 16KB 页对齐门禁"
    if ! "${PYTHON_BIN}" "${HERE}/tools/check_elf_page_align.py" "${best}" --abi "${abi}"; then
        if [[ "${ALLOW_UNALIGNED:-0}" == "1" ]]; then
            warn "ALLOW_UNALIGNED=1，放行未对齐的包(16KB 设备上会退回系统兼容模式)"
        else
            Fail "有原生库未按 16KB 对齐(清单见上)。NDK r28+ 重编通常即可修复；
       若不是由本脚本编出的库(libc++_shared/openssl 等 recipe 产物)，检查是否走了旧 NDK。
       确需临时放行: ALLOW_UNALIGNED=1 $0 --abi ${abi}"
            return 1
        fi
    fi

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
            # 把日志末尾直接打到终端：失败原因常常只有几行，藏在几 MB 的日志里
            # 会让人以为"卡住了"，其实是早就报错了
            printf '\033[1;31m[error]\033[0m 最后 15 行日志:\n' >&2
            tail -n 15 "${ABI_LOG}" 2>/dev/null | tr '\r' '\n' | tail -n 15 | sed 's/^/    /' >&2
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
