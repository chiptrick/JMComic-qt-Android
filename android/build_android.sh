#!/usr/bin/env bash
# JMComic Android 打包脚本
#
# 要求(宿主机必须是 Linux 或 macOS；pyside6-android-deploy 目前不支持 Windows 主机)：
#   * Python 3.11/3.12 + venv
#   * JDK 17
#   * Android SDK(platform-tools, platforms;android-34, build-tools;35.0.0)
#   * Android NDK r26d (26.1.10909125)
#   * 已下载 PySide6 / shiboken6 的 android_aarch64 wheel
#        qtpip download PySide6   --android --arch aarch64
#        qtpip download shiboken6 --android --arch aarch64
#
# 用法：
#   export ANDROID_HOME=$HOME/Android/Sdk
#   export ANDROID_NDK_HOME=$HOME/Android/Sdk/ndk/26.1.10909125
#   ./build_android.sh                # 全流程：原生库 + 模型检查 + 打包 APK
#   SKIP_NATIVE=1 ./build_android.sh  # 只重新打包(原生库已经编好)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"

# ------------------------------------------------------------------ 可调参数
ORT_VERSION="${ORT_VERSION:-1.23.2}"           # onnxruntime-android-qnn 版本
ANDROID_PLATFORM="${ANDROID_PLATFORM:-android-34}"  # 最低 Android 14
ABI="${ABI:-arm64-v8a}"
BUILD_TYPE="${BUILD_TYPE:-debug}"              # debug -> apk, release -> aab
PYTHON_BIN="${PYTHON_BIN:-python3}"
NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-}}"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
WHEEL_DIR="${HERE}/wheels"
LIBS_DIR="${HERE}/libs/${ABI}"
WORK_DIR="${HERE}/.work"

log() { printf '\033[1;32m[build]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn ]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------------ 环境检查
[[ "$(uname -s)" == "Linux" || "$(uname -s)" == "Darwin" ]] || \
    die "pyside6-android-deploy 只支持 Linux/macOS 主机(Windows 请用 WSL2 或 WSL+Docker)"
[[ -n "${NDK}" ]] || die "请设置 ANDROID_NDK_HOME 指向 NDK r26d"
[[ -d "${NDK}" ]] || die "NDK 目录不存在: ${NDK}"
[[ -n "${SDK}" ]] || warn "未设置 ANDROID_HOME，pyside6-android-deploy 可能找不到 SDK"
command -v cmake >/dev/null || die "缺少 cmake(>=3.20)"

# ------------------------------------------------------------------ 1. 业务源码
log "同步业务源码 -> android/app_src"
rm -rf "${HERE}/app_src"
mkdir -p "${HERE}/app_src"
cp -r "${ROOT}/src/." "${HERE}/app_src/"
# 去掉开发机的缓存与日志
find "${HERE}/app_src" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "${HERE}/app_src/logs"

# ------------------------------------------------------------------ 2. ONNX Runtime + QNN 运行库
mkdir -p "${LIBS_DIR}" "${WORK_DIR}"
AAR="${WORK_DIR}/onnxruntime-android-qnn-${ORT_VERSION}.aar"
if [[ ! -f "${AAR}" ]]; then
    log "下载 onnxruntime-android-qnn ${ORT_VERSION}"
    curl -fL -o "${AAR}" \
        "https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android-qnn/${ORT_VERSION}/onnxruntime-android-qnn-${ORT_VERSION}.aar"
fi
log "解包 AAR -> ${LIBS_DIR}"
rm -rf "${WORK_DIR}/aar" && mkdir -p "${WORK_DIR}/aar"
unzip -q -o "${AAR}" -d "${WORK_DIR}/aar"
cp "${WORK_DIR}/aar/jni/${ABI}/"*.so "${LIBS_DIR}/"
ls -1 "${LIBS_DIR}" | sed 's/^/    /'

# ------------------------------------------------------------------ 3. ONNX Runtime 头文件
ORT_INC="${WORK_DIR}/onnxruntime-include"
if [[ ! -f "${ORT_INC}/onnxruntime_c_api.h" ]]; then
    log "获取 ONNX Runtime C 头文件(v${ORT_VERSION})"
    mkdir -p "${ORT_INC}"
    for name in onnxruntime_c_api.h onnxruntime_ep_c_api.h onnxruntime_float16.h \
                onnxruntime_session_options_config_keys.h onnxruntime_cxx_api.h; do
        curl -fL -o "${ORT_INC}/${name}" \
            "https://raw.githubusercontent.com/microsoft/onnxruntime/v${ORT_VERSION}/include/onnxruntime/core/session/${name}" \
            || warn "下载 ${name} 失败(可能该版本没有这个头文件)"
    done
fi

# ------------------------------------------------------------------ 4. libsr_qnn.so
if [[ "${SKIP_NATIVE:-0}" != "1" ]]; then
    log "编译 libsr_qnn.so (${ABI})"
    BUILD="${HERE}/sr_qnn/cpp/build-${ABI}"
    cmake -S "${HERE}/sr_qnn/cpp" -B "${BUILD}" \
        -DCMAKE_TOOLCHAIN_FILE="${NDK}/build/cmake/android.toolchain.cmake" \
        -DANDROID_ABI="${ABI}" \
        -DANDROID_PLATFORM="${ANDROID_PLATFORM}" \
        -DONNXRUNTIME_INCLUDE_DIR="${ORT_INC}" \
        -DONNXRUNTIME_LIB_DIR="${LIBS_DIR}" \
        -DCMAKE_BUILD_TYPE=Release
    cmake --build "${BUILD}" -j"$(nproc)"
    cp "${BUILD}/libsr_qnn.so" "${LIBS_DIR}/"
    log "原生库就绪: ${LIBS_DIR}/libsr_qnn.so"
else
    warn "SKIP_NATIVE=1，跳过原生库编译"
fi

# ------------------------------------------------------------------ 5. 模型检查
MODEL_DIR="${HERE}/sr_qnn/models"
MODEL_COUNT=$(find "${MODEL_DIR}" -maxdepth 1 -name '*.onnx' | wc -l | tr -d ' ')
if [[ "${MODEL_COUNT}" == "0" ]]; then
    warn "sr_qnn/models 下还没有 onnx 模型，超分功能会在手机上禁用。"
    warn "请先运行: python android/tools/prepare_models.py --src <waifu2x onnx 目录> --tile 192 --verify"
else
    log "发现 ${MODEL_COUNT} 个模型文件"
fi

# ------------------------------------------------------------------ 6. 依赖
log "准备 python 依赖(pyside6-android-deploy + buildozer)"
if [[ ! -d "${HERE}/.venv" ]]; then
    "${PYTHON_BIN}" -m venv "${HERE}/.venv"
fi
# shellcheck disable=SC1091
source "${HERE}/.venv/bin/activate"
pip install -q --upgrade pip
pip install -q pyside6-android-deploy buildozer cython
if ! compgen -G "${WHEEL_DIR}/*.whl" >/dev/null; then
    warn "wheels 目录为空，尝试用 qtpip 下载 android aarch64 wheel"
    mkdir -p "${WHEEL_DIR}"
    (cd "${WHEEL_DIR}" && qtpip download PySide6 --android --arch aarch64 || true)
    (cd "${WHEEL_DIR}" && qtpip download shiboken6 --android --arch aarch64 || true)
fi
PY_WHEEL=$(ls "${WHEEL_DIR}"/PySide6-*-android_aarch64.whl 2>/dev/null | head -n1 || true)
SHI_WHEEL=$(ls "${WHEEL_DIR}"/shiboken6-*-android_aarch64.whl 2>/dev/null | head -n1 || true)
[[ -n "${PY_WHEEL}" ]] || die "缺少 PySide6 android_aarch64 wheel，请放到 ${WHEEL_DIR}/"
[[ -n "${SHI_WHEEL}" ]] || die "缺少 shiboken6 android_aarch64 wheel，请放到 ${WHEEL_DIR}/"
log "PySide6 wheel: $(basename "${PY_WHEEL}")"

# ------------------------------------------------------------------ 7. 打包
log "生成部署配置(写入实际 wheel 路径)"
SPEC="${HERE}/pysidedeploy.spec"
sed -e "s|^wheel_pyside = .*|wheel_pyside = ${PY_WHEEL}|" \
    -e "s|^wheel_shiboken = .*|wheel_shiboken = ${SHI_WHEEL}|" \
    -e "s|^mode = .*|mode = ${BUILD_TYPE}|" \
    "${SPEC}" > "${WORK_DIR}/pysidedeploy.spec"
[[ -n "${SDK}" ]] && {
    sed -i "s|^sdk_path = .*|sdk_path = ${SDK}|" "${WORK_DIR}/pysidedeploy.spec"
    sed -i "s|^ndk_path = .*|ndk_path = ${NDK}|" "${WORK_DIR}/pysidedeploy.spec"
}

cd "${HERE}"
log "调用 pyside6-android-deploy(首次会下载/编译 python-for-android，耗时较长)"
pyside6-android-deploy --config-file "${WORK_DIR}/pysidedeploy.spec" \
    --keep-deployment-files --force || die "打包失败，查看上方日志"

# 打补丁把工程钉到 Android 14 (API 34) + 加入模型资产，然后(可选)再打一次包
log "钉 minSdk/屏幕方向/模型资产"
bash "${HERE}/tools/pin_min_sdk.sh" || warn "pin_min_sdk.sh 执行失败，请手动检查 buildozer.spec"
REPACK="${REPACK:-1}"
if [[ "${REPACK}" == "1" ]]; then
    log "应用补丁后重新打包"
    pyside6-android-deploy --config-file "${WORK_DIR}/pysidedeploy.spec" \
        --keep-deployment-files --force || die "第二次打包失败"
fi

# ------------------------------------------------------------------ 8. 结果
APK=$(find "${HERE}" -maxdepth 3 -name '*.apk' -newer "${SPEC}" | head -n1 || true)
AAB=$(find "${HERE}" -maxdepth 3 -name '*.aab' -newer "${SPEC}" | head -n1 || true)
log "打包完成"
[[ -n "${APK}" ]] && log "APK: ${APK}"
[[ -n "${AAB}" ]] && log "AAB: ${AAB}"

cat <<EOF

下一步：
  1) 安装到手机
       adb install -r ${APK:-<你的.apk>}
  2) 推送模型(如果模型没有打进 APK)
       adb push ${MODEL_DIR}/. /sdcard/Android/data/com.tonquer.jmcomic/files/waifu2x-models/
       # 包名以 buildozer.spec 里的 package.name/domain 为准
  3) 查看日志
       adb logcat | grep -i -E "python|sr_qnn|Qt"

原生库清单(务必和 buildozer.local_libs 一致):
$(ls -1 "${LIBS_DIR}" | sed 's/^/    /')
EOF
