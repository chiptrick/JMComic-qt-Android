#!/usr/bin/env bash
# 最后两项硬证据：AndroidManifest 里的 minSdkVersion；pillow(PIL) 是否打进包
set -uo pipefail
APK=/path/to/JMComic-qt/android/JMComic-0.1-arm64-v8a-debug.apk
SDK=/root/jmcomic-build/android-sdk
BT=$(ls -d "$SDK"/build-tools/* 2>/dev/null | sort -V | tail -1)
PY=/root/jmcomic-build/venv311/bin/python

echo "=== manifest minSdkVersion ==="
"$BT/aapt2" dump xmltree --file AndroidManifest.xml "$APK" 2>/dev/null | grep -iE "minSdkVersion|targetSdkVersion" | head -4

echo
echo "=== pillow / site-packages 关键项 ==="
"$PY" - "$APK" <<'PYEOF'
import io, sys, tarfile, zipfile
z = zipfile.ZipFile(sys.argv[1])
tf = tarfile.open(fileobj=io.BytesIO(z.read("assets/private.tar")))
names = tf.getnames()
site = [n for n in names if n.startswith("site-packages/")]
print("site-packages 条目数:", len(site))
tops = sorted({n.split("/")[1] for n in site if n.count("/") >= 1})
print("site-packages 顶层:", tops[:40])
for mod in ("PIL", "jmcomic", "PySide6", "commonx", "curl_cffi", "bs4", "natsort", "tqdm",
            "requests", "pyasn1", "smb", "webdav3", "yaml", "Cryptodome", "socks"):
    hit = any(mod in n for n in site)
    print("   %-12s %s" % (mod, "✓" if hit else "✗"))
PYEOF
