#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# WSL Ubuntu 构建环境：基础工具 + JDK17 + Python3.11(conda) + 仓库副本
# 需要 root 运行(apt 安装)。日志: ~/jmcomic-build/logs/setup_base.log
set -euo pipefail

WORK="${WORK:-"$JM_WORK"}"
SRC="${SRC:-"$JM_REPO"}"
mkdir -p "$WORK/logs" "$WORK/tools"
exec > >(tee -a "$WORK/logs/setup_base.log") 2>&1

echo "===== [$(date +%T)] 基础环境安装开始 ====="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    openjdk-17-jdk-headless build-essential cmake ninja-build unzip zip rsync wget curl \
    git file pkg-config libssl-dev zlib1g-dev ca-certificates xz-utils bzip2 locales
echo "jdk: $(java -version 2>&1 | head -1)"
echo "gcc: $(gcc --version | head -1)"
echo "cmake: $(cmake --version | head -1)"

echo "===== [$(date +%T)] 安装 micromamba + Python 3.11 ====="
# Qt 的 Android wheel 是 cp311，而 Ubuntu 26.04 只有 python3.14，所以用 conda 提供 3.11
if [ ! -x "$WORK/tools/micromamba" ]; then
    curl -sSL -o "$WORK/tools/mm.tar.bz2" https://micro.mamba.pm/api/micromamba/linux-64/latest
    mkdir -p "$WORK/tools/mm" && tar -xjf "$WORK/tools/mm.tar.bz2" -C "$WORK/tools/mm" --strip-components=1 bin/micromamba
    cp "$WORK/tools/mm/bin/micromamba" "$WORK/tools/micromamba" && chmod +x "$WORK/tools/micromamba"
fi
export MAMBA_ROOT_PREFIX="$WORK/mamba"
"$WORK/tools/micromamba" --version
if [ ! -x "$MAMBA_ROOT_PREFIX/envs/py311/bin/python" ]; then
    "$WORK/tools/micromamba" create -y -q -p "$MAMBA_ROOT_PREFIX/envs/py311" \
        -c conda-forge python=3.11 pip=24 setuptools wheel
fi
PY311="$MAMBA_ROOT_PREFIX/envs/py311/bin/python"
echo "python3.11: $($PY311 --version)"
$PY311 -m pip install -q --upgrade pip

echo "===== [$(date +%T)] 复制仓库到 ext4(避免 /mnt/c 慢与权限问题) ====="
mkdir -p "$WORK/src"
rsync -a --delete \
    --exclude '.git' --exclude '.vs' --exclude 'build_out' --exclude 'logs' \
    --exclude '__pycache__' --exclude 'android/.venv' --exclude 'android/app_src' \
    --exclude 'android/libs' --exclude 'android/.work' --exclude 'android/wheels' \
    "$SRC/" "$WORK/src/"
echo "仓库副本: $(du -sh "$WORK/src" | cut -f1)"
ls "$WORK/src" | head

echo "===== [$(date +%T)] 基础环境完成 ====="
echo "WORK=$WORK"
echo "PY311=$PY311"
