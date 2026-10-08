#!/usr/bin/env bash
# 看 venv-host / venv311 里装了哪些业务依赖，判断冒烟测试缺什么
set -u
for V in venv-host venv311; do
    P="/root/jmcomic-build/$V/bin/python"
    [ -x "$P" ] || { echo "--- $V: 不存在"; continue; }
    echo "--- $V ($($P --version 2>&1))"
    "$P" - <<'PY'
import importlib
mods = ["PySide6", "natsort", "bs4", "soupsieve", "tqdm", "PIL", "Crypto",
        "requests", "commonx", "jmcomic", "yaml", "lxml", "curl_cffi", "socks",
        "webdav3", "smb", "dateutil", "certifi", "urllib3", "pyasn1"]
for m in mods:
    try:
        importlib.import_module(m)
        print("   [ok]  " + m)
    except Exception as es:
        print("   [MISS] %-12s %s" % (m, type(es).__name__))
PY
done
