#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 本地回归：Android 冒烟测试(offscreen，不联网) + 接口一致性 + 解密链 + 图片管线 + 文件选择器
# python 选择：优先 venv314(与 APK 目标 CPython 3.14 同大版本，见 tools/wsl_setup_venv314.sh)，
# 退回 venv311(构建工具链 venv，仍可用但覆盖不到 3.14 语义)
set -uo pipefail
WORK="${WORK:-"$JM_WORK"}"
REPO="${REPO:-"$JM_REPO"}"
PY="$WORK/venv314/bin/python"
[ -x "$PY" ] || PY="$WORK/venv311/bin/python"
[ -x "$PY" ] || PY="$WORK/venv-host/bin/python"
[ -x "$PY" ] || PY=$(command -v python3)

echo "python: $($PY --version) ($(command -v "$PY"))"
cd "$REPO"

echo
echo "===== 1. 语法编译(目标版本语法) ====="
"$PY" -m py_compile \
    src/tools/platform_mobile.py \
    src/tools/mobile_ui.py \
    src/tools/mobile_ui_base.py \
    src/tools/mobile_ui_hooks.py \
    src/tools/mobile_ui_window.py \
    src/tools/mobile_ui_drawer.py \
    src/tools/mobile_ui_layout.py \
    src/tools/mobile_ui_reader.py \
    src/tools/mobile_ui_grid.py \
    src/tools/mobile_ui_touch.py \
    src/tools/mobile_ui_diag.py \
    src/tools/mobile_file_dialog.py \
    src/tools/saf_bridge.py \
    src/component/widget/comic_item_widget.py \
    src/component/list/comic_list_widget.py \
    src/component/label/msg_label.py \
    src/task/task_qimage.py \
    src/task/task_multi.py \
    src/tools/tool.py \
    src/view/main/main_view.py \
    src/view/tool/local_read_view.py \
    src/view/tool/waifu2x_tool_view.py \
    src/view/download/download_item.py \
    src/view/download/download_dir_view.py \
    src/view/setting/setting_view.py \
    src/view/read/read_view.py \
    android/main.py \
    android/sr_qnn/__init__.py \
    android/shims/curl_cffi/__init__.py \
    android/shims/curl_cffi/requests/__init__.py \
    android/tools/patch_buildozer_spec.py \
    android/tools/patch_android_manifest.py \
    android/tools/smoke_test_android.py \
    android/tools/host_test_crypto_android.py \
    android/tools/host_test_image_pipeline.py \
    android/tools/host_test_file_dialog.py \
    android/tools/host_test_saf_bridge.py \
    android/tools/host_test_net_fallback.py \
    && echo "[ok] 语法编译通过" || echo "[FAIL] 语法编译失败"

run() {
    # $1=名字 $2=脚本
    echo
    echo "===== $1 ====="
    QT_QPA_PLATFORM=offscreen "$PY" "$2"
    local rc=$?
    echo "$1 退出码=$rc"
    return $rc
}

run "2. Android 竖屏冒烟测试" android/tools/smoke_test_android.py
smoke=$?
run "3. C/Python 接口一致性" android/tools/check_interfaces.py
iface=$?
run "4. 真机 AES 不可用问题回归(p4a 的 android 包)" android/tools/host_test_crypto_android.py
crypto=$?
run "5. 图片解密管线回归(拼图/QImage 线程/超时)" android/tools/host_test_image_pipeline.py
image=$?
run "6. 应用内文件选择器回归" android/tools/host_test_file_dialog.py
picker=$?
run "7. HTTP/3、ECH 失败降级回归" android/tools/host_test_net_fallback.py
netfb=$?
run "8. SAF 桥信箱协议回归" android/tools/host_test_saf_bridge.py
saf=$?

echo
echo "结果: smoke=$smoke interfaces=$iface crypto=$crypto image=$image picker=$picker netfb=$netfb saf=$saf"
[ "$smoke" -eq 0 ] && [ "$iface" -eq 0 ] && [ "$crypto" -eq 0 ] && [ "$image" -eq 0 ] \
    && [ "$picker" -eq 0 ] && [ "$netfb" -eq 0 ] && [ "$saf" -eq 0 ]
