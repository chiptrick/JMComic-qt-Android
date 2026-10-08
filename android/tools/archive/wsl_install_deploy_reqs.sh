#!/usr/bin/env bash
# 安装 pyside6-android-deploy 自述的 android 依赖(pkginfo/tqdm 等)
set -uo pipefail
WORK=/root/jmcomic-build
VPY="$WORK/venv-host/bin/python"
REQ=$(find "$WORK/venv-host" -name "requirements-android.txt" | head -1)
echo "requirements: $REQ"
[ -n "$REQ" ] && cat "$REQ"
$VPY -m pip install -q -r "$REQ" 2>&1 | tail -3
$VPY -c "import pkginfo, tqdm; print('pkginfo/tqdm OK')"
# 顺手把 buildozer/p4a 常用依赖也补齐
$VPY -m pip install -q sh pexpect packaging virtualenv appdirs jinja2 toml filetype requests six colorama 2>&1 | tail -2
$VPY -c "import sh, pexpect, jinja2; print('buildozer deps OK')"
