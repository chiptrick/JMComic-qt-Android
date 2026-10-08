#!/usr/bin/env bash
# 把 pyside6-android-deploy 生成的工程钉到 Android 14(API 34) 并加入 NPU 模型资产
#
# pyside6-android-deploy 会自己生成 buildozer.spec 与 AndroidManifest.xml，
# 它没有暴露 minSdk / 屏幕方向 / 资产目录这些配置项，所以这里在生成之后打补丁。
#
# 用法(先跑一次 pyside6-android-deploy --keep-deployment-files，再执行本脚本；
# build_android.sh 会自动调用它)：
#     ./tools/pin_min_sdk.sh
#     API=35 MINAPI=34 ORIENTATION=portrait ./tools/pin_min_sdk.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API="${API:-34}"
MINAPI="${MINAPI:-34}"
ORIENTATION="${ORIENTATION:-fullUser}"   # fullUser=跟随系统旋转锁定(默认)，portrait=强制竖屏
MODEL_DIR="${HERE}/sr_qnn/models"

log()  { printf '\033[1;32m[pin]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }

SetKey() {
    local file="$1" key="$2" value="$3"
    if grep -qE "^[#[:space:]]*${key}[[:space:]]*=" "$file"; then
        sed -i -E "s|^[#[:space:]]*${key}[[:space:]]*=.*|${key} = ${value}|" "$file"
    else
        printf '%s = %s\n' "${key}" "${value}" >> "$file"
    fi
}

# --------------------------------------------------------------- buildozer.spec
mapfile -t SPECS < <(find "${HERE}" -name buildozer.spec -not -path '*/.venv/*' 2>/dev/null || true)
if [[ ${#SPECS[@]} -eq 0 ]]; then
    warn "没有找到 buildozer.spec，先执行一次 pyside6-android-deploy --keep-deployment-files"
else
    for spec in "${SPECS[@]}"; do
        log "打补丁: ${spec}"
        SetKey "${spec}" "android.api" "${API}"
        SetKey "${spec}" "android.minapi" "${MINAPI}"
        SetKey "${spec}" "android.archs" "arm64-v8a"
        SetKey "${spec}" "android.accept_sdk_license" "True"
        SetKey "${spec}" "android.private_storage" "True"
        # 应用外部私有目录(下载目录要用，Android 10+ 无需权限)
        SetKey "${spec}" "android.allow_backup" "False"
        if compgen -G "${MODEL_DIR}/*.onnx" >/dev/null; then
            SetKey "${spec}" "android.add_assets" "${MODEL_DIR}:models"
            log "  已加入模型资产: ${MODEL_DIR} -> assets/models"
        else
            warn "  sr_qnn/models 没有 onnx，跳过 add_assets(用 adb push 推送模型)"
        fi
        # 确保原生库打进 APK
        SetKey "${spec}" "android.local_libs" \
            "libsr_qnn.so,libonnxruntime.so,libQnnHtp.so,libQnnSystem.so,libQnnHtpPrepare.so,libQnnHtpV68Stub.so,libQnnHtpV69Stub.so,libQnnHtpV73Stub.so,libQnnHtpV75Stub.so"
        SetKey "${spec}" "android.no_compile_pyo" "False"
    done
fi

# ----------------------------------------------------------- AndroidManifest.xml
mapfile -t MANIFESTS < <(find "${HERE}" -name AndroidManifest.xml -not -path '*/.venv/*' 2>/dev/null || true)
for manifest in "${MANIFESTS[@]:-}"; do
    [[ -n "${manifest}" ]] || continue
    log "打补丁: ${manifest}"
    if grep -q 'android:screenOrientation' "${manifest}"; then
        sed -i -E "s|android:screenOrientation=\"[^\"]*\"|android:screenOrientation=\"${ORIENTATION}\"|" "${manifest}"
    else
        sed -i -E "0,/<activity/s|(<activity )|\1android:screenOrientation=\"${ORIENTATION}\" |" "${manifest}"
    fi
    if ! grep -q 'android.permission.INTERNET' "${manifest}"; then
        sed -i -E "0,/<application/s|(<manifest[^>]*>)|\1\n    <uses-permission android:name=\"android.permission.INTERNET\" />|" "${manifest}"
    fi
done

log "完成：API=${API}, minSdk=${MINAPI}, 屏幕方向=${ORIENTATION}"
log "重新执行 pyside6-android-deploy 即可让补丁生效"
