#!/usr/bin/env bash
# 最终校验：minSdk / targetSdk、private.tar 内容(应用源码+垫片)、APK 大小与签名
set -uo pipefail
APK=/path/to/JMComic-qt/android/JMComic-0.1-arm64-v8a-debug.apk
SDK=/root/jmcomic-build/android-sdk
BT=$(ls -d "$SDK"/build-tools/* 2>/dev/null | sort -V | tail -1)
PY=/root/jmcomic-build/venv311/bin/python

echo "=== APK: $(du -h "$APK" | cut -f1) ==="
echo
echo "=== aapt badging(sdk 相关) ==="
"$BT/aapt2" dump badging "$APK" 2>/dev/null | grep -E "sdkVersion|targetSdkVersion|uses-permission|package:" | head -12

echo
echo "=== private.tar 里的应用源码与垫片 ==="
"$PY" - "$APK" <<'PYEOF'
import io, sys, tarfile, zipfile
z = zipfile.ZipFile(sys.argv[1])
data = z.read("assets/private.tar")
tf = tarfile.open(fileobj=io.BytesIO(data))
names = tf.getnames()
print("private.tar 条目数:", len(names))
def has(sub):
    return any(sub in n for n in names)
checks = {
    "app_src/main.py": has("main.py"),
    "app_src/start.py": has("start.py"),
    "应用源码 tools/mobile_ui.py": has("mobile_ui.py"),
    "应用源码 view/main/main_view.py": has("main_view.py"),
    "curl_cffi 垫片": has("shims/curl_cffi"),
    "android/main.py": has("main.py"),
    "site-packages/jmcomic": has("jmcomic"),
    "site-packages/PIL": has("/PIL/") or has("PIL"),
    "site-packages/PySide6": has("PySide6"),
    "site-packages/curl_cffi": has("curl_cffi"),
}
for k, v in checks.items():
    print("   %-32s %s" % (k, "✓" if v else "✗"))
# 打印顶层结构
tops = sorted({n.split("/")[0] for n in names})
print("顶层:", tops[:12])
PYEOF

echo
echo "=== 签名校验 ==="
"$BT/apksigner" verify --print-certs "$APK" 2>&1 | head -6

echo
echo "=== 仓库 android/ 目录 ==="
ls -sh /path/to/JMComic-qt/android/*.apk 2>/dev/null
ls /path/to/JMComic-qt/android/build_logs/ 2>/dev/null
