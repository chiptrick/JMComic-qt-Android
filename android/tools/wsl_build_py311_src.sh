#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 编译安装 CPython 3.11(宿主) —— pyside6-android-deploy/buildozer 要求 <=3.11
# 源码走阿里云镜像，依赖用 apt
set -uo pipefail
WORK="$JM_WORK"
PYVER="${PYVER:-3.11.13}"
PREFIX="$WORK/py311"
VENV311="$WORK/venv311"
mkdir -p "$WORK/logs"
exec > >(tee -a "$WORK/logs/build_py311.log") 2>&1

echo "===== [$(date +%T)] 安装编译依赖 ====="
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq --no-install-recommends \
    libffi-dev libbz2-dev liblzma-dev libreadline-dev libsqlite3-dev libncurses-dev \
    uuid-dev tk-dev >/dev/null
echo "ok"

echo "===== [$(date +%T)] 下载 CPython $PYVER 源码 ====="
cd "$WORK"
if [ ! -f "Python-$PYVER.tgz" ]; then
    for base in "https://mirrors.aliyun.com/python-release/source" "https://www.python.org/ftp/python/$PYVER"; do
        echo "尝试 $base"
        curl -sSL --retry 2 -m 900 -o "Python-$PYVER.tgz" "$base/Python-$PYVER.tgz" && [ -s "Python-$PYVER.tgz" ] && break
        rm -f "Python-$PYVER.tgz"
    done
fi
ls -sh "Python-$PYVER.tgz" || { echo "源码下载失败"; exit 1; }
rm -rf "Python-$PYVER" && tar -xzf "Python-$PYVER.tgz"

echo "===== [$(date +%T)] configure + make(-j$(nproc)) ====="
cd "Python-$PYVER"
./configure --prefix="$PREFIX" --with-ensurepip=install --enable-optimizations=no >/dev/null 2>&1 || \
    ./configure --prefix="$PREFIX" --with-ensurepip=install >/dev/null
make -j"$(nproc)" >/dev/null 2>&1 || { echo "make 失败"; exit 1; }
make install >/dev/null 2>&1 || { echo "make install 失败"; exit 1; }
"$PREFIX/bin/python3.11" --version
"$PREFIX/bin/python3.11" -c "import ssl, sqlite3, zlib, bz2, lzma, ctypes; print('stdlib(ssl/sqlite3/ctypes) OK')"

echo "===== [$(date +%T)] 建 venv311 并装工具链 ====="
rm -rf "$VENV311"
"$PREFIX/bin/python3.11" -m venv "$VENV311"
VPY="$VENV311/bin/python"
"$VPY" -m pip install -q --upgrade pip 2>&1 | tail -2
"$VPY" -m pip install -q \
    "PySide6-Essentials==6.11.2" "shiboken6==6.11.2" \
    buildozer "cython<3" pkginfo tqdm "packaging==24.1" \
    sh pexpect jinja2 toml virtualenv appdirs filetype requests six colorama 2>&1 | tail -5
"$VPY" -c "import PySide6, pkginfo, tqdm, sh; print('PySide6', PySide6.__version__, '| deps OK')"
ls "$VENV311/bin" | grep -i deploy
"$VENV311/bin/pyside6-android-deploy" --help 2>&1 | head -4
echo "===== [$(date +%T)] 完成 VENV311=$VENV311 ====="
