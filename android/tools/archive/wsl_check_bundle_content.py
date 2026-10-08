#!/usr/bin/env python3
"""确认 APK 里 python bundle 的 site-packages 含应用所需依赖"""
import io
import tarfile
import zipfile

APK = "/path/to/JMComic-qt/android/JMComic-0.1-arm64-v8a-debug.apk"
z = zipfile.ZipFile(APK)
tf = tarfile.open(fileobj=io.BytesIO(z.read("lib/arm64-v8a/libpybundle.so")))
names = tf.getnames()
site = [n for n in names if "site-packages/" in n]
mods = [n for n in names if "/modules/" in n]
print("site-packages 条目:", len(site), " modules 条目:", len(mods))
checks = ("jmcomic", "PIL", "PySide6", "commonx", "curl_cffi", "bs4", "natsort", "tqdm",
          "requests", "pyasn1", "socks", "yaml", "shims", "mobile_ui")
for m in checks:
    hit = any((n.startswith("_python_bundle/site-packages/" + m)
               or ("/" + m + "/") in n) for n in names)
    print("   %-12s %s" % (m, "✓" if hit else "✗"))
print("--- site-packages 前 10 ---")
for n in site[:10]:
    print("   ", n)
