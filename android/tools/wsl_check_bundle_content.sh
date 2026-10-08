#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 解出 APK 里的 libpybundle.so(其实是 tar)，确认 Python 运行时包含应用所需依赖
set -uo pipefail
APK="$JM_REPO/android/JMComic-0.1-arm64-v8a-debug.apk"
PY="$JM_WORK/venv311/bin/python"
"$PY" - "$APK" <<'PYEOF'
import io, sys, tarfile, zipfile
z = zipfile.ZipFile(sys.argv[1])
data = z.read("lib/arm64-v8a/libpybundle.so")
print("libpybundle.so 大小: %.1f MB" % (len(data) / 1024 / 1024))
tf = tarfile.open(fileobj=io.BytesIO(data))
names = tf.getnames()
print("条目数:", len(names))
tops = sorted({n.split("/")[0] for n in names})
print("顶层:", tops)
# 找 stdlib.zip / site-packages
inner = [n for n in names if n.endswith(".zip")]
print("内层 zip:", inner[:4])
for inner_zip in inner:
    try:
        f = tf.extractfile(inner_zip)
        iz = zipfile.ZipFile(io.BytesIO(f.read()))
        innames = iz.namelist()
        print("  %s: %d 条目" % (inner_zip, len(innames)))
        for mod in ("jmcomic", "PIL", "PySide6", "commonx", "curl_cffi", "bs4", "natsort",
                    "tqdm", "requests", "pyasn1", "smb", "webdav3", "yaml", "socks",
                    "shims", "mobile_ui", "sr_qnn", "onsite"):
            hit = any(("/" + mod + "/") in ("/" + n) or n.startswith(mod) for n in innames)
            print("      %-12s %s" % (mod, "✓" if hit else "✗"))
        break
    except Exception as es:
        print("  读取失败:", es)
PYEOF
