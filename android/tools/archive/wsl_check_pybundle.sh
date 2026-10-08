#!/usr/bin/env bash
# 核对 libpybundle.so(python 运行时的 tar) 是否生成并进入 APK
set -uo pipefail
D=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic
APK=/path/to/JMComic-qt/android/JMComic-0.1-arm64-v8a-debug.apk
PY=/root/jmcomic-build/venv311/bin/python

echo "=== 磁盘上的 libs/arm64-v8a ==="
ls -sh "$D/libs/arm64-v8a" 2>/dev/null | head -12
echo "libpybundle 存在? $(ls -sh "$D/libs/arm64-v8a/libpybundle.so" 2>/dev/null || echo 否)"

echo
echo "=== APK 的 lib/arm64-v8a 里是否有 libpybundle.so ==="
"$PY" - "$APK" <<'PYEOF'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
for i in z.infolist():
    if i.filename.startswith("lib/") and ("pybundle" in i.filename or "python" in i.filename.lower()):
        print("   %-46s 压缩后 %7.2f MB  原始 %7.2f MB" % (
            i.filename, i.compress_size / 1024 / 1024, i.file_size / 1024 / 1024))
print("lib/ 条目总数:", len([i for i in z.infolist() if i.filename.startswith('lib/')]))
PYEOF
