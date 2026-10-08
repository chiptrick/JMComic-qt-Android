#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 只跑宿主 sr_qnn 逻辑测试(不重新编译)，用已构建好的 build-host/libsr_qnn.so
# 用法: bash wsl_run_host_test.sh
set -uo pipefail
WORK="${WORK:-"$JM_WORK"}"
SRC="$WORK/src"
VPY="$WORK/venv311/bin/python"
[ -x "$VPY" ] || VPY="$WORK/venv-host/bin/python"
ORT="$WORK/ort/linux-x64"

[ -f "$WORK/build-host/libsr_qnn.so" ] || { echo "缺少 build-host/libsr_qnn.so，先跑 wsl_build_native.sh"; exit 1; }
ln -sf libonnxruntime.so "$ORT/libonnxruntime.so.1" 2>/dev/null || true

# 用仓库(Windows)侧的最新测试脚本
export JM_SR_QNN_LIB="$WORK/build-host/libsr_qnn.so"
export LD_LIBRARY_PATH="$ORT:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$SRC/android:$SRC/src"
echo "lib:  $JM_SR_QNN_LIB"
echo "ORT:  $ORT"
"$VPY" "$JM_REPO/android/tools/host_test_sr_qnn.py"
echo "host_test exit=$?"
