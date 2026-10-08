#!/usr/bin/env bash
# 看 APK 里 private.tar(应用私有数据)中装的 tool.py / tool.pyc 是哪一版
set -u
PY=/root/jmcomic-build/venv311/bin/python3
APK=/path/to/JMComic-qt/android/JMComic-0.1-arm64-v8a-debug.apk
echo "APK: $(ls -la "$APK" | awk '{print $5, $6, $7, $8}')"
TMP=/tmp/apkprobe
rm -rf "$TMP"; mkdir -p "$TMP"
cd "$TMP"
unzip -o -q "$APK" "assets/*" 2>/dev/null
echo "== assets 项 =="
ls -la assets/ | head -20
echo "== private.tar 内容(应用源码) =="
if [ -f assets/private.tar ]; then
  "$PY" - <<'EOF'
import tarfile
t = tarfile.open("/tmp/apkprobe/assets/private.tar")
names = [n for n in t.getnames() if ("tool.py" in n or "mobile_ui" in n or "task_qimage" in n)]
for n in names[:20]:
    print("  ", n)
for n in names:
    if n.endswith("tools/tool.py") or n.endswith("tools/tool.pyc") or n.endswith("task/task_qimage.py"):
        f = t.extractfile(n)
        data = f.read()
        print("  {}: {} bytes, SegmentationPictureQt={} Qt分割={}".format(
            n, len(data), data.count(b"SegmentationPictureQt"), data.count("Qt分割".encode())))
EOF
else
  echo "no private.tar"
fi
echo "== app_src 的编译产物 =="
ls -la /root/jmcomic-build/src/android/.buildozer/android/app/app_src/tools/tool.py* 2>/dev/null
ls -la /root/jmcomic-build/src/android/.buildozer/android/app/app_src/tools/__pycache__/tool* 2>/dev/null | head
