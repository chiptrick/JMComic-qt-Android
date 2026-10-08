#!/usr/bin/env bash
# 给 venv311 装齐跑冒烟测试所需的业务依赖(Python 3.11 = APK 的目标版本)
set -uo pipefail
WORK="${WORK:-/root/jmcomic-build}"
VPY="$WORK/venv311/bin/python"
export PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
export PIP_TRUSTED_HOST="pypi.tuna.tsinghua.edu.cn"

echo "=== 安装业务依赖 ==="
"$VPY" -m pip install -q \
    natsort beautifulsoup4 soupsieve pillow pycryptodome pysocks \
    webdavclient3 pysmb python-dateutil pyasn1 commonx pyyaml 2>&1 | tail -20
echo "rc=$?"

echo "=== 单独装 jmcomic(--no-deps，避免拉 curl_cffi 原生包) ==="
"$VPY" -m pip install -q --no-deps jmcomic 2>&1 | tail -10
echo "rc=$?"

echo "=== 复查 ==="
"$VPY" - <<'PY'
import importlib
mods = ["PySide6", "natsort", "bs4", "soupsieve", "tqdm", "PIL", "Crypto",
        "requests", "commonx", "jmcomic", "yaml", "socks", "webdav3", "smb",
        "dateutil", "certifi", "urllib3", "pyasn1"]
bad = []
for m in mods:
    try:
        importlib.import_module(m)
        print("   [ok]  " + m)
    except Exception as es:
        bad.append(m)
        print("   [MISS] %-12s %s" % (m, es))
print("缺失: %s" % (bad or "无"))
PY
