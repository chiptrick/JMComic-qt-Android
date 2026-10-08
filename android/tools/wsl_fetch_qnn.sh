#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 取高通 QNN 运行库：com.qualcomm.qti:qnn-runtime AAR(ORT 的 android-qnn AAR 依赖它)
# 产出: android/libs/arm64-v8a/libQnnHtp.so / libQnnSystem.so / libQnnHtpV*Stub.so / *Skel.so
set -euo pipefail
WORK="${WORK:-"$JM_WORK"}"
SRC="$WORK/src"
LIBS="$SRC/android/libs/arm64-v8a"
QNN_VER="${QNN_VER:-2.37.1}"
mkdir -p "$LIBS" "$WORK/tools" "$WORK/logs"
exec > >(tee -a "$WORK/logs/fetch_qnn.log") 2>&1

BASE="https://repo1.maven.org/maven2/com/qualcomm/qti/qnn-runtime/$QNN_VER"
AAR="$WORK/tools/qnn-runtime-$QNN_VER.aar"
echo "===== [$(date +%T)] 下载 qnn-runtime $QNN_VER ====="
[ -s "$AAR" ] || curl -sSL --retry 3 -o "$AAR" "$BASE/qnn-runtime-$QNN_VER.aar"
ls -sh "$AAR"
python3 - "$AAR" <<'EOF'
import sys, zipfile, collections
z = zipfile.ZipFile(sys.argv[1])
names = z.namelist()
print("总条目:", len(names))
print("顶层:", collections.Counter(n.split('/')[0] for n in names))
for n in names:
    if n.endswith(('.so', '.jar', '.xml')) and n.count('/') < 4:
        print("  ", n, z.getinfo(n).file_size)
EOF

echo "===== [$(date +%T)] 解包 arm64-v8a 运行库 ====="
rm -rf "$WORK/tools/qnnaar" && mkdir -p "$WORK/tools/qnnaar"
python3 -m zipfile -e "$AAR" "$WORK/tools/qnnaar"
for abi in arm64-v8a; do
    dir="$WORK/tools/qnnaar/jni/$abi"
    if [ -d "$dir" ]; then
        cp "$dir"/*.so "$LIBS/" 2>/dev/null || true
    fi
done
# 有些版本把库放在 runtime/ 或 libs/ 下
for extra in "$WORK/tools/qnnaar/jni"/*; do
    [ -d "$extra" ] || continue
    abi=$(basename "$extra")
    if [ "$abi" != "arm64-v8a" ] && [ -n "$(ls "$extra"/*.so 2>/dev/null)" ]; then
        echo "  (跳过非 arm64 ABI: $abi)"
    fi
done
echo "--- android/libs/arm64-v8a 内容 ---"
ls -1sh "$LIBS"
echo "===== [$(date +%T)] 完成 ====="
