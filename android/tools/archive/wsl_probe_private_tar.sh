#!/usr/bin/env bash
# 确认模型为什么没进 private.tar：看 buildozer.spec 的 source.include_exts / exclude
set -u
A=/root/jmcomic-build/src/android
echo "=== source.* 相关配置 ==="
grep -n -E '^source\.' "$A/buildozer.spec" 2>/dev/null

echo
echo "=== .buildozer/android/app 里实际有什么 ==="
ls -la "$A/.buildozer/android/app/" 2>/dev/null | head -30
echo "--- sr_qnn 下 ---"
ls -la "$A/.buildozer/android/app/sr_qnn/" 2>/dev/null

echo
echo "=== APK 内 private.tar 条目里找 onnx / sr_qnn ==="
APK=$(ls "$A"/bin/*.apk 2>/dev/null | head -1)
echo "APK=$APK"
if [ -n "$APK" ]; then
    TMP=$(mktemp -d)
    cd "$TMP"
    python3 - "$APK" <<'PY'
import sys, zipfile, tarfile, io
apk = sys.argv[1]
z = zipfile.ZipFile(apk)
name = "assets/private.tar"
print("private.tar size:", z.getinfo(name).file_size)
data = z.read(name)
tf = tarfile.open(fileobj=io.BytesIO(data))
names = tf.getnames()
print("total entries:", len(names))
onnx = [n for n in names if n.endswith(".onnx")]
print("onnx entries:", len(onnx))
for n in names[:60]:
    print("   ", n)
PY
    cd /
    rm -rf "$TMP"
fi
