#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 获取 ONNX Runtime 的 Android 原生库 + NuGet 头文件/linux 库
#
# ABI 差异（JM_ABI）：
#   arm64-v8a -> onnxruntime-android-qnn AAR（自带 QNN EP，配合 QNN HTP 跑 NPU）
#   x86_64    -> onnxruntime-android      AAR（普通版；-qnn 那个 AAR 里只有 arm64-v8a，
#                而且 x86_64 模拟器本来就没有高通 NPU，QNN EP 没有意义）
# 头文件与 linux 库两份 ABI 共用（都在 $WORK/ort），x86_64 只多拷一份 lib。
set -euo pipefail
WORK="$JM_WORK"
SRC="$WORK/src"
ORT="${ORT:-1.29.0}"
LIBS="$SRC/android/libs/${JM_ABI}"
ORTHDR="$WORK/ort"
VARIANT="onnxruntime-android-qnn"
[ "$JM_QNN" = "1" ] || VARIANT="onnxruntime-android"
MIRRORS=(
    "https://maven.aliyun.com/repository/central/com/microsoft/onnxruntime"
    "https://repo1.maven.org/maven2/com/microsoft/onnxruntime"
)
mkdir -p "$LIBS" "$ORTHDR/include" "$ORTHDR/linux-x64" "$WORK/logs" "$WORK/tools"
exec > >(tee -a "$WORK/logs/fetch_ort.log") 2>&1

echo "===== [$(date +%T)] $VARIANT AAR $ORT (abi=$JM_ABI) ====="
AAR="$WORK/tools/${VARIANT}-${ORT}.aar"
if [ ! -s "$AAR" ]; then
    for base in "${MIRRORS[@]}"; do
        url="$base/$VARIANT/$ORT/$VARIANT-$ORT.aar"
        echo "  > $url"
        curl -fL --retry 3 --connect-timeout 20 --max-time 900 -o "$AAR" "$url" && break
        rm -f "$AAR"
    done
fi
[ -s "$AAR" ] || { echo "[FATAL] 下载 $VARIANT 失败"; exit 1; }
ls -sh "$AAR"
rm -rf "$WORK/tools/aar" && mkdir -p "$WORK/tools/aar"
"$JM_VPY" -m zipfile -e "$AAR" "$WORK/tools/aar" 2>/dev/null || python3 -m zipfile -e "$AAR" "$WORK/tools/aar"
if [ ! -d "$WORK/tools/aar/jni/$JM_ABI" ]; then
    echo "[FATAL] $VARIANT AAR 里没有 jni/$JM_ABI（现有：$(ls "$WORK/tools/aar/jni" 2>/dev/null | tr '\n' ' ')）"
    exit 1
fi
cp "$WORK/tools/aar/jni/$JM_ABI/"*.so "$LIBS/"
echo "android 原生库($JM_ABI):"; ls -1sh "$LIBS"/*.so

echo "===== [$(date +%T)] 校验 ABI 是否真的匹配 ====="
READELF="$JM_NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"
for so in "$LIBS"/libonnxruntime.so; do
    [ -f "$so" ] || continue
    echo "--- $so"
    "$READELF" -h "$so" | grep -E "Class|Machine" || true
done

echo "===== [$(date +%T)] NuGet 头文件 + linux 库 $ORT ====="
NUPKG="$WORK/tools/microsoft.ml.onnxruntime.$ORT.nupkg"
if [ ! -s "$NUPKG" ]; then
    curl -sSL --retry 3 -o "$NUPKG" \
      "https://api.nuget.org/v3-flatcontainer/microsoft.ml.onnxruntime/$ORT/microsoft.ml.onnxruntime.$ORT.nupkg" || true
fi
if [ -s "$NUPKG" ]; then
    ls -sh "$NUPKG"
    rm -rf "$WORK/tools/nupkg" && mkdir -p "$WORK/tools/nupkg"
    python3 -m zipfile -e "$NUPKG" "$WORK/tools/nupkg"
    cp "$WORK/tools/nupkg/build/native/include/"*.h "$ORTHDR/include/"
    if [ -d "$WORK/tools/nupkg/runtimes/linux-x64/native" ]; then
        cp "$WORK/tools/nupkg/runtimes/linux-x64/native/"*.so* "$ORTHDR/linux-x64/" 2>/dev/null || true
    fi
else
    echo "[warn] 拿不到 NuGet 包（头文件/宿主库可能已存在，继续）"
fi
if [ -e "$ORTHDR/linux-x64/libonnxruntime.so.1.23.2" ] && [ ! -e "$ORTHDR/linux-x64/libonnxruntime.so" ]; then
    ln -sf libonnxruntime.so.1.23.2 "$ORTHDR/linux-x64/libonnxruntime.so"
fi
echo "头文件: $(ls "$ORTHDR/include" 2>/dev/null | wc -l)"; ls "$ORTHDR/include" 2>/dev/null | head -5
echo "linux 库:"; ls -sh "$ORTHDR/linux-x64" 2>/dev/null | head -5

echo "===== [$(date +%T)] 完成 ====="
