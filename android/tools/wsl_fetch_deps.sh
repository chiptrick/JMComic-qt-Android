#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 获取构建依赖：
#   - PySide6 / shiboken6 的 android_aarch64 wheel(cp311)
#   - onnxruntime-android-qnn AAR(含 libonnxruntime.so + QNN HTP 运行库)
#   - ONNX Runtime C 头文件(NuGet 包，GitHub 不可达) + linux-x64 动态库(用于宿主自测)
set -euo pipefail
WORK="${WORK:-"$JM_WORK"}"
SRC="$WORK/src"
ORT="${ORT:-1.23.2}"
LIBS="$SRC/android/libs/arm64-v8a"
WHEELS="$SRC/android/wheels"
ORTHDR="$WORK/ort"
mkdir -p "$WHEELS" "$LIBS" "$ORTHDR/include" "$ORTHDR/linux-x64" "$WORK/logs"
exec > >(tee -a "$WORK/logs/fetch_deps.log") 2>&1

QT_BASE=https://download.qt.io/official_releases/QtForPython/pyside6

echo "===== [$(date +%T)] 1. Qt for Python Android wheels ====="
LIST="$WORK/qt_list.html"
curl -sS -m 120 "$QT_BASE/" -o "$LIST"
pick() { # $1 = pyside6|shiboken6
    grep -oE "href=\"[^\"]*${1}[^\"]*android_aarch64\.whl\"" "$LIST" \
        | sed 's/href="//;s/"//' | sort -V | tail -1
}
PYSIDE_WHL=$(pick pyside6)
SHIBOKEN_WHL=$(pick shiboken6)
echo "PySide6  : $PYSIDE_WHL"
echo "shiboken6: $SHIBOKEN_WHL"
[ -n "$PYSIDE_WHL" ] || { echo "找不到 PySide6 android wheel"; exit 1; }
[ -n "$SHIBOKEN_WHL" ] || { echo "找不到 shiboken6 android wheel"; exit 1; }
for f in "$PYSIDE_WHL" "$SHIBOKEN_WHL"; do
    out="$WHEELS/$(basename "$f")"
    if [ ! -f "$out" ]; then
        echo "下载 $(basename "$f")"
        curl -sSL -o "$out" "$QT_BASE/$f"
    fi
    printf '  %-70s %s\n' "$(basename "$out")" "$(du -h "$out" | cut -f1)"
done

echo "===== [$(date +%T)] 2. onnxruntime-android-qnn AAR ====="
AAR="$WORK/tools/onnxruntime-android-qnn-$ORT.aar"
[ -f "$AAR" ] || curl -sSL -o "$AAR" \
  "https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android-qnn/$ORT/onnxruntime-android-qnn-$ORT.aar"
echo "AAR: $(du -h "$AAR" | cut -f1)"
rm -rf "$WORK/tools/aar" && mkdir -p "$WORK/tools/aar"
python3 -m zipfile -e "$AAR" "$WORK/tools/aar"
cp "$WORK/tools/aar/jni/arm64-v8a/"*.so "$LIBS/"
echo "arm64-v8a 原生库:"
ls -1sh "$LIBS"

echo "===== [$(date +%T)] 3. ONNX Runtime 头文件 + linux-x64 库(NuGet) ====="
NUPKG="$WORK/tools/microsoft.ml.onnxruntime.$ORT.nupkg"
[ -f "$NUPKG" ] || curl -sSL -o "$NUPKG" \
  "https://api.nuget.org/v3-flatcontainer/microsoft.ml.onnxruntime/$ORT/microsoft.ml.onnxruntime.$ORT.nupkg"
rm -rf "$WORK/tools/nupkg" && mkdir -p "$WORK/tools/nupkg"
python3 -m zipfile -e "$NUPKG" "$WORK/tools/nupkg"
cp "$WORK/tools/nupkg/build/native/include/"*.h "$ORTHDR/include/" 2>/dev/null || true
if [ -d "$WORK/tools/nupkg/runtimes/linux-x64/native" ]; then
    cp "$WORK/tools/nupkg/runtimes/linux-x64/native/"*.so* "$ORTHDR/linux-x64/" 2>/dev/null || true
fi
echo "头文件: $(ls "$ORTHDR/include" | wc -l) 个"
ls "$ORTHDR/include" | head
echo "linux-x64 动态库:"; ls -sh "$ORTHDR/linux-x64" 2>/dev/null || echo "  (无)"

echo "===== [$(date +%T)] 4. 试试能不能拿到 waifu2x onnx 模型 ====="
mkdir -p "$SRC/android/sr_qnn/models"
HF=https://hf-mirror.com
for repo in Library-Mutsumi/waifu2x_onnx; do
    code=$(curl -sS -m 20 -o /tmp/hf.json -w '%{http_code}' "$HF/api/models/$repo" || echo FAIL)
    echo "$repo -> $code"
    [ "$code" = "200" ] && python3 -c "
import json;d=json.load(open('/tmp/hf.json'))
print('files:', [f['rfilename'] for f in d.get('siblings',[])][:20])" || true
done

echo "===== [$(date +%T)] 完成 ====="
echo "PYSIDE_WHL=$WHEELS/$(basename "$PYSIDE_WHL")"
echo "SHIBOKEN_WHL=$WHEELS/$(basename "$SHIBOKEN_WHL")"
