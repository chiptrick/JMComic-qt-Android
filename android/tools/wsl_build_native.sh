#!/usr/bin/env bash
# 编译 libsr_qnn.so（ABI 由 JM_ABI 决定：arm64-v8a / x86_64）：
#   A) Android $JM_ABI(NDK) -> android/libs/$JM_ABI/
#   B) 宿主 x86_64 Linux -> 用 host_test_sr_qnn.py 验证引擎逻辑(不依赖 NPU)
#
# x86_64 说明：模拟器没有高通 NPU，libs/x86_64 里也不会放 libQnn*.so。引擎的 QNN 是
# 运行期 dlopen 的(见 sr_qnn.cpp)，找不到就回落到 ONNX Runtime CPU EP —— 同一个源
# 码两种 ABI 都能编，不需要 #ifdef。
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
WORK="${WORK:-$JM_WORK}"
SRC="$WORK/src"
SDK="$WORK/android-sdk"
NDK="$SDK/ndk/26.1.10909125"
ORT="$WORK/ort"
ABI="${JM_ABI:-arm64-v8a}"
LIBS="$SRC/android/libs/$ABI"
BUILD="$WORK/build-android-$ABI"
# 用 venv311(目标 Python 版本，wheel 齐全)跑宿主测试；onnx/numpy 在 3.14 上未必有 wheel
VPY="$WORK/venv311/bin/python"
[ -x "$VPY" ] || VPY="$WORK/venv-host/bin/python"
MIRROR="${MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"
ORT_VER="${ORT_VER:-1.29.0}"
mkdir -p "$WORK/logs" "$LIBS"
exec > >(tee -a "$WORK/logs/build_native.log") 2>&1

echo "===== [$(date +%T)] 0. 同步仓库到 WSL (ABI=$ABI) ====="
bash "$JM_REPO/android/tools/wsl_sync.sh"

echo "===== [$(date +%T)] 准备宿主 python 依赖 ====="
$VPY -m pip install -q -i "$MIRROR" onnx numpy 2>&1 | tail -3
$VPY -c "import PySide6, onnx, numpy; print('PySide6', PySide6.__version__, '| onnx', onnx.__version__, '| numpy', numpy.__version__)"

echo "===== [$(date +%T)] 确认 ORT 头文件 / 库 ====="
ls "$ORT/include/onnxruntime_c_api.h" || { echo "缺少 ORT 头文件，先跑 wsl_fetch_ort.sh"; exit 1; }
if [ ! -e "$ORT/linux-x64/libonnxruntime.so" ]; then
    echo "从 PyPI wheel 提取 linux 版 libonnxruntime.so"
    $VPY -m pip download -q --no-deps -i "$MIRROR" -d "$WORK/tools/ortwhl" "onnxruntime==$ORT_VER"
    python3 - "$WORK" <<'EOF'
import glob, os, sys, zipfile, shutil
work = sys.argv[1]
dest = os.path.join(work, "ort/linux-x64")
os.makedirs(dest, exist_ok=True)
found = None
for whl in glob.glob(os.path.join(work, "tools/ortwhl/*.whl")):
    z = zipfile.ZipFile(whl)
    for n in z.namelist():
        if n.endswith("libonnxruntime.so.1.23.2") or n.endswith("libonnxruntime.so"):
            with z.open(n) as src, open(os.path.join(dest, "libonnxruntime.so"), "wb") as out:
                shutil.copyfileobj(src, out)
            found = n
            break
    if found:
        break
print("提取:", found)
EOF
fi
ls -sh "$ORT/linux-x64" || true

echo "===== [$(date +%T)] A) Android $ABI 构建 ====="
if [ ! -f "$LIBS/libonnxruntime.so" ]; then
    echo "[error] 缺少 $LIBS/libonnxruntime.so —— 先跑: JM_ABI=$ABI bash android/tools/wsl_fetch_ort.sh"
    exit 1
fi
cmake -S "$SRC/android/sr_qnn/cpp" -B "$BUILD" \
    -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI="$ABI" -DANDROID_PLATFORM=android-34 \
    -DONNXRUNTIME_INCLUDE_DIR="$ORT/include" \
    -DONNXRUNTIME_LIB_DIR="$LIBS" \
    -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -8
cmake --build "$BUILD" -j"$(nproc)" 2>&1 | tail -25
cp "$BUILD/libsr_qnn.so" "$LIBS/libsr_qnn.so"
# 独立进程入口：命名成 lib*.so 才会随 buildozer 打进 APK(extractNativeLibs 后
# 位于 nativeLibraryDir，允许 exec)。它的用途见 sr_qnn_proc.cpp 头注释。
cp "$BUILD/sr_qnn_proc" "$LIBS/libsr_qnn_proc.so"
chmod +x "$LIBS/libsr_qnn_proc.so"
TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin"
echo "--- 产物校验 ---"
ls -sh "$LIBS/libsr_qnn.so" "$LIBS/libsr_qnn_proc.so"
"$TOOLCHAIN/llvm-readelf" -h "$LIBS/libsr_qnn.so" | grep -E "Class|Machine|Type"
"$TOOLCHAIN/llvm-readelf" -h "$LIBS/libsr_qnn_proc.so" | grep -E "Class|Machine|Type"
echo "导出符号数: $("$TOOLCHAIN/llvm-nm" -D --defined-only "$LIBS/libsr_qnn.so" | grep -c ' T srq_')"
"$TOOLCHAIN/llvm-readelf" -d "$LIBS/libsr_qnn.so" | grep NEEDED || true
echo "sr_qnn_proc NEEDED: $("$TOOLCHAIN/llvm-readelf" -d "$LIBS/libsr_qnn_proc.so" | grep -c NEEDED) 项"

echo "===== [$(date +%T)] B) 宿主 x86_64 构建 ====="
cmake -S "$SRC/android/sr_qnn/cpp" -B "$WORK/build-host" \
    -DONNXRUNTIME_INCLUDE_DIR="$ORT/include" \
    -DONNXRUNTIME_LIB_DIR="$ORT/linux-x64" \
    -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -6
cmake --build "$WORK/build-host" -j"$(nproc)" 2>&1 | tail -25
ls -sh "$WORK/build-host/libsr_qnn.so"

if [ "${SKIP_HOST_TEST:-0}" = "1" ]; then
    echo "===== [$(date +%T)] 跳过宿主功能测试(SKIP_HOST_TEST=1) ====="
    exit 0
fi

echo "===== [$(date +%T)] C) 宿主功能测试(分块拼接/缩放/编码/任务 API) ====="
# NuGet 里的 libonnxruntime.so 的 SONAME 是 libonnxruntime.so.1，补一个软链给动态链接器
ln -sf libonnxruntime.so "$ORT/linux-x64/libonnxruntime.so.1"
export JM_SR_QNN_LIB="$WORK/build-host/libsr_qnn.so"
export LD_LIBRARY_PATH="$ORT/linux-x64:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$SRC/android:$SRC/src"
"$VPY" "$SRC/android/tools/host_test_sr_qnn.py" 2>&1 | tail -45
echo "host_test exit=$?"
echo "===== [$(date +%T)] 完成 ====="
