#!/usr/bin/env bash
# 弄清 Python 运行时/site-packages 打包在 APK 的哪里
set -uo pipefail
APK=/path/to/JMComic-qt/android/JMComic-0.1-arm64-v8a-debug.apk
PY=/root/jmcomic-build/venv311/bin/python
"$PY" - "$APK" <<'PYEOF'
import io, sys, tarfile, zipfile
z = zipfile.ZipFile(sys.argv[1])
print("=== assets/ 全部条目 ===")
for i in z.infolist():
    if i.filename.startswith("assets/"):
        print("   %-46s %8.2f MB" % (i.filename, i.file_size / 1024 / 1024))
print()
print("=== APK 内含 jmcomic / PIL / PySide6 字样的条目(前 20) ===")
hits = [i.filename for i in z.infolist()
        if any(k in i.filename for k in ("jmcomic", "PIL", "PySide6", "python_bundle", "stdlib"))]
for h in hits[:20]:
    print("   ", h)
print("   合计:", len(hits))
print()
# 若存在 python 运行时归档，列出其内部顶层目录
for cand in ("assets/python_bundle.tar", "assets/stdlib.zip", "assets/private.tar"):
    try:
        data = z.read(cand)
    except KeyError:
        continue
    print("=== %s 内容顶层 ===" % cand)
    try:
        if cand.endswith(".tar"):
            tf = tarfile.open(fileobj=io.BytesIO(data))
            names = tf.getnames()
        else:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        tops = sorted({n.split("/")[0] for n in names})
        print("   条目 %d, 顶层: %s" % (len(names), tops[:20]))
        for mod in ("jmcomic", "PIL", "PySide6", "commonx", "curl_cffi"):
            print("      %-10s %s" % (mod, any(mod in n for n in names)))
    except Exception as es:
        print("   读取失败:", es)
PYEOF
echo
echo "=== dists 里的 _python_bundle 是否非空 ==="
du -sh /root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic/_python_bundle__arm64-v8a 2>/dev/null
ls /root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic/_python_bundle__arm64-v8a 2>/dev/null | head -8
