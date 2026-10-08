#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 深度校验新 APK：包信息 / 原生库 / Qt 插件 / private.tar 里的模型
set -uo pipefail
WORK="$JM_WORK"
A="$WORK/src/android"
SDK="$WORK/android-sdk"
APK=$(ls -t "$A"/bin/*.apk "$A"/*.apk 2>/dev/null | head -1)
BT=$(ls -d "$SDK"/build-tools/* 2>/dev/null | sort -V | tail -1)
AAPT="$BT/aapt2"; [ -x "$AAPT" ] || AAPT="$BT/aapt"

echo "=== APK: $APK ==="
ls -sh "$APK"
echo "修改时间: $(date -r "$APK" '+%F %T')"

echo
echo "=== 包信息 ==="
if [ -x "$AAPT" ]; then
    "$AAPT" dump badging "$APK" 2>/dev/null | grep -E "^package|sdkVersion|targetSdkVersion|native-code|application-label" | head -8
else
    echo "(没有 aapt)"
fi

echo
echo "=== 关键原生库与插件 ==="
python3 - "$APK" <<'PY'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
libs = {i.filename: i.file_size for i in z.infolist() if i.filename.startswith('lib/')}
print("  原生库总数:", len(libs))
need = ["libsr_qnn.so", "libonnxruntime.so",
        "libplugins_platforms_qtforandroid_arm64-v8a.so",
        "libplugins_imageformats_qsvg_arm64-v8a.so",
        "libplugins_imageformats_qjpeg_arm64-v8a.so",
        "libplugins_imageformats_qgif_arm64-v8a.so",
        "libplugins_imageformats_qwebp_arm64-v8a.so",
        "libplugins_sqldrivers_qsqlite_arm64-v8a.so",
        "libplugins_iconengines_qsvgicon_arm64-v8a.so",
        "libQnnHtp.so", "libQnnHtpV79Skel.so"]
bad = 0
for n in need:
    hit = [k for k in libs if k.endswith("/" + n)]
    if hit:
        print("  [ok]   %-52s %8.2f MB" % (n, libs[hit[0]] / 1024 / 1024))
    else:
        print("  [缺失] %s" % n); bad += 1
print("  缺失项:", bad)
PY

echo
echo "=== assets 内容 ==="
python3 - "$APK" <<'PY'
import sys, zipfile, tarfile, io
z = zipfile.ZipFile(sys.argv[1])
assets = [(i.filename, i.file_size) for i in z.infolist() if i.filename.startswith('assets/')]
for n, s in assets:
    print("  %-34s %10.1f KB" % (n, s / 1024))
name = "assets/private.tar"
if any(n == name for n, _ in assets):
    tf = tarfile.open(fileobj=io.BytesIO(z.read(name)))
    names = tf.getnames()
    onnx = [n for n in names if n.endswith('.onnx')]
    print("  private.tar 条目: %d, 其中 onnx: %d" % (len(names), len(onnx)))
    print("  models.txt:", any(n.endswith('models.txt') for n in names))
    for n in sorted(onnx)[:3]:
        print("     ", n)
    print("  app_src 条目:", len([n for n in names if n.startswith('app_src/')]))
    print("  shims 条目:", len([n for n in names if n.startswith('shims/')]))
PY

echo
echo "=== 签名 ==="
"$BT"/apksigner verify --print-certs "$APK" 2>/dev/null | head -4 || echo "(apksigner 不可用)"
