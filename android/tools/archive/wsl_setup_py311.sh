#!/usr/bin/env bash
# 准备宿主 Python 3.11 环境(pyside6-android-deploy 要求 <=3.11)
# uv 本身从 PyPI 镜像装；CPython 解释器从 ghproxy 镜像的 python-build-standalone 取
set -uo pipefail
WORK=/root/jmcomic-build
VPY314="$WORK/venv-host/bin/python"
UV="$WORK/venv-host/bin/uv"
VENV311="$WORK/venv311"
mkdir -p "$WORK/logs"
exec > >(tee -a "$WORK/logs/py311.log") 2>&1

echo "===== [$(date +%T)] 安装 uv ====="
$VPY314 -m pip install -q uv 2>&1 | tail -2
$UV --version

echo "===== [$(date +%T)] 安装 CPython 3.11(走 ghproxy 镜像) ====="
export UV_PYTHON_INSTALL_MIRROR="https://ghproxy.net/https://github.com/astral-sh/python-build-standalone/releases/download"
export UV_PYTHON_INSTALL_DIR="$WORK/pythons"
$UV python install 3.11 2>&1 | tail -5
$UV python list 2>&1 | head -5

echo "===== [$(date +%T)] 建 venv311 ====="
rm -rf "$VENV311"
$UV venv --python 3.11 "$VENV311" 2>&1 | tail -3
VPY="$VENV311/bin/python"
"$VPY" --version || { echo "python3.11 不可用"; exit 1; }

echo "===== [$(date +%T)] 装依赖 ====="
"$VPY" -m ensurepip -q 2>/dev/null || true
"$VPY" -m pip install -q --upgrade pip 2>&1 | tail -2
"$VPY" -m pip install -q \
    "PySide6-Essentials==6.11.2" "shiboken6==6.11.2" \
    buildozer "cython<3" pkginfo tqdm "packaging==24.1" \
    sh pexpect jinja2 toml virtualenv appdirs filetype requests six colorama \
    python-for-android 2>&1 | tail -5
"$VPY" -c "import PySide6, pkginfo, tqdm, sh; print('PySide6', PySide6.__version__, '| deps OK')"

echo "===== [$(date +%T)] 校验部署工具 ====="
ls "$VENV311/bin" | grep -i deploy
"$VENV311/bin/pyside6-android-deploy" --help 2>&1 | head -5
echo "===== [$(date +%T)] 完成 ====="
