#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 本地回归：Android 冒烟测试(offscreen，不联网) + 接口一致性 + 解密链 + 图片管线 + 文件选择器
# 用 venv311(APK 的目标 python3.11)执行，不依赖真机
set -uo pipefail
WORK="${WORK:-"$JM_WORK"}"
REPO="${REPO:-"$JM_REPO"}"
PY="$WORK/venv311/bin/python"
[ -x "$PY" ] || PY="$WORK/venv-host/bin/python"
[ -x "$PY" ] || PY=$(command -v python3)

echo "python: $($PY --version)"
cd "$REPO"

echo
echo "===== 1. 语法编译(python3.11，目标版本) ====="
"$PY" -m py_compile \
    src/tools/platform_mobile.py \
    src/tools/mobile_ui.py \
    src/tools/mobile_file_dialog.py \
    src/component/widget/comic_item_widget.py \
    src/component/list/comic_list_widget.py \
    src/component/label/msg_label.py \
    src/task/task_qimage.py \
    src/task/task_multi.py \
    src/tools/tool.py \
    src/view/main/main_view.py \
    src/view/tool/local_read_view.py \
    src/view/tool/waifu2x_tool_view.py \
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
    && echo "[ok] py3.11 编译通过" || echo "[FAIL] py3.11 编译失败"

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

echo
echo "结果: smoke=$smoke interfaces=$iface crypto=$crypto image=$image picker=$picker"
[ "$smoke" -eq 0 ] && [ "$iface" -eq 0 ] && [ "$crypto" -eq 0 ] && [ "$image" -eq 0 ] && [ "$picker" -eq 0 ]
