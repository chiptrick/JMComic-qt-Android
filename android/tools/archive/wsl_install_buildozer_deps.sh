#!/usr/bin/env bash
# 预装 buildozer 自己的依赖(它会执行 pip install --user，在 venv 里会失败)
set -uo pipefail
VPY=/root/jmcomic-build/venv311/bin/python
"$VPY" -m pip install -q appdirs "colorama>=0.3.3" jinja2 "sh>=2,<3" meson ninja build \
    toml packaging setuptools "wheel~=0.43.0" 2>&1 | tail -3
"$VPY" - <<'EOF'
mods = ["appdirs", "colorama", "jinja2", "sh", "mesonbuild", "ninja", "build", "toml",
        "packaging", "wheel"]
import importlib
for m in mods:
    try:
        importlib.import_module(m)
        print("ok  ", m)
    except Exception as es:
        print("FAIL", m, es)
EOF
