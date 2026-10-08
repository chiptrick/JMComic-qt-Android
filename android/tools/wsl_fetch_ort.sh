#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 获取 ONNX Runtime：android-qnn AAR + NuGet 头文件/linux 库
set -euo pipefail
WORK="$JM_WORK"
SRC="$WORK/src"
ORT="${ORT:-1.23.2}"
LIBS="$SRC/android/libs/arm64-v8a"
ORTHDR="$WORK/ort"
mkdir -p "$LIBS" "$ORTHDR/include" "$ORTHDR/linux-x64" "$WORK/logs" "$WORK/tools"
exec > >(tee -a "$WORK/logs/fetch_ort.log") 2>&1

echo "===== [$(date +%T)] onnxruntime-android-qnn AAR $ORT ====="
AAR="$WORK/tools/onnxruntime-android-qnn-$ORT.aar"
[ -s "$AAR" ] || curl -sSL --retry 3 -o "$AAR" \
  "https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android-qnn/$ORT/onnxruntime-android-qnn-$ORT.aar"
ls -sh "$AAR"
rm -rf "$WORK/tools/aar" && mkdir -p "$WORK/tools/aar"
python3 -m zipfile -e "$AAR" "$WORK/tools/aar"
cp "$WORK/tools/aar/jni/arm64-v8a/"*.so "$LIBS/"
echo "android 原生库:"; ls -1sh "$LIBS"

echo "===== [$(date +%T)] NuGet 头文件 + linux 库 $ORT ====="
NUPKG="$WORK/tools/microsoft.ml.onnxruntime.$ORT.nupkg"
[ -s "$NUPKG" ] || curl -sSL --retry 3 -o "$NUPKG" \
  "https://api.nuget.org/v3-flatcontainer/microsoft.ml.onnxruntime/$ORT/microsoft.ml.onnxruntime.$ORT.nupkg"
ls -sh "$NUPKG"
rm -rf "$WORK/tools/nupkg" && mkdir -p "$WORK/tools/nupkg"
python3 -m zipfile -e "$NUPKG" "$WORK/tools/nupkg"
cp "$WORK/tools/nupkg/build/native/include/"*.h "$ORTHDR/include/"
if [ -d "$WORK/tools/nupkg/runtimes/linux-x64/native" ]; then
    cp "$WORK/tools/nupkg/runtimes/linux-x64/native/"*.so* "$ORTHDR/linux-x64/" 2>/dev/null || true
fi
if [ -e "$ORTHDR/linux-x64/libonnxruntime.so.1.23.2" ] && [ ! -e "$ORTHDR/linux-x64/libonnxruntime.so" ]; then
    ln -sf libonnxruntime.so.1.23.2 "$ORTHDR/linux-x64/libonnxruntime.so"
fi
echo "头文件: $(ls "$ORTHDR/include" | wc -l)"; ls "$ORTHDR/include" | head -5
echo "linux 库:"; ls -sh "$ORTHDR/linux-x64" 2>/dev/null | head -5

echo "===== [$(date +%T)] 完成 ====="
