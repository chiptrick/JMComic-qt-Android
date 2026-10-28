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
ABI="${ABI:-arm64-v8a}"                    # arm64-v8a(真机) / x86_64(模拟器)
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

DelKey() {
    local file="$1" key="$2"
    sed -i -E "/^[#[:space:]]*${key}[[:space:]]*=/d" "$file"
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
        SetKey "${spec}" "android.archs" "${ABI}"
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
        # 原生库清单：buildozer **只认** android.add_libs_<abi>（targets/android.py
        # 里那张固定映射表），而 android.local_libs 不是 buildozer/p4a 认识任何一个键
        # (grep 整个包都没有这个字符串) —— 写它只会给人"已经配好"的错觉。
        # 历史事故：arm64 的 NPU 库缺失时，日志里只看到 local_libs 里赫然列着
        # libQnnHtp.so，实际包里一个都没有。现在改成按目录**实际内容**生成，
        # 目录里没有的库不会出现在清单里，也就不会盖住问题。
        libs_dir="${HERE}/libs/${ABI}"
        add_libs=""
        if [ -d "$libs_dir" ]; then
            add_libs="$(python3 "${HERE}/tools/qnn_manifest.py" list \
                --libs-dir "$libs_dir" --prefix "libs/${ABI}" 2>/dev/null || true)"
        fi
        if [ -n "$add_libs" ]; then
            SetKey "$spec" "android.add_libs_$(printf '%s' "${ABI}" | tr '-' '_')" "$add_libs"
            log "  add_libs_$(printf '%s' "${ABI}" | tr '-' '_'): $(printf '%s' "$add_libs" | tr ',' '\n' | wc -l | tr -d ' ') 个 .so"
        else
            warn "  libs/${ABI} 里没有 .so，跳过 add_libs(超分/原生库都不会进包)"
        fi
        # 另一架构的 add_libs 整行删掉：留着它，buildozer 会去读一个本 ABI 不存在的
        # 目录，日志里全是空 file_matches，真缺库时反而看不出问题在哪。
        for other in arm64_v8a x86_64; do
            [ "$other" = "$(printf '%s' "${ABI}" | tr '-' '_')" ] && continue
            DelKey "$spec" "android.add_libs_${other}"
        done
        DelKey "$spec" "android.local_libs"
        SetKey "$spec" "android.no_compile_pyo" "False"
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

# --------------------------------------------------------------- QNN 体检
# 这里只做提示：真正的硬闸门在打包前(tools/qnn_guard.sh)与打包后
# (qnn_manifest.py verify-apk)。放这里是为了让"手工跑一次 pin_min_sdk.sh"
# 也能立刻看到 libs 目录到底缺什么。
if [[ "${ABI}" == arm64* ]]; then
    python3 "${HERE}/tools/qnn_manifest.py" verify --libs-dir "${HERE}/libs/${ABI}" || \
        warn "libs/${ABI} 的 QNN 运行库不合规：真机上超分会退回 CPU。补齐命令：
       bash android/tools/wsl_fetch_qnn.sh --libs-dir ${HERE}/libs/${ABI}"
fi

log "完成：API=${API}, minSdk=${MINAPI}, 屏幕方向=${ORIENTATION}"
log "重新执行 pyside6-android-deploy 即可让补丁生效"
