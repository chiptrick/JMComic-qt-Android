#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 修正版：micromamba + Python3.11 + 仓库副本(可重复执行)
set -euo pipefail
WORK="${WORK:-"$JM_WORK"}"
SRC="${SRC:-"$JM_REPO"}"
mkdir -p "$WORK/logs" "$WORK/tools"
exec > >(tee -a "$WORK/logs/setup_base2.log") 2>&1

echo "===== [$(date +%T)] micromamba ====="
if [ ! -x "$WORK/tools/micromamba" ]; then
    curl -sSL -o "$WORK/tools/mm.tar.bz2" https://micro.mamba.pm/api/micromamba/linux-64/latest
    rm -rf "$WORK/tools/mm" && mkdir -p "$WORK/tools/mm"
    tar -xjf "$WORK/tools/mm.tar.bz2" -C "$WORK/tools/mm"
    found=$(find "$WORK/tools/mm" -type f -name micromamba | head -1)
    echo "解包得到: $found"
    install -m 0755 "$found" "$WORK/tools/micromamba"
fi
"$WORK/tools/micromamba" --version

export MAMBA_ROOT_PREFIX="$WORK/mamba"
PY311="$MAMBA_ROOT_PREFIX/envs/py311/bin/python"
if [ ! -x "$PY311" ]; then
    echo "创建 python 3.11 环境(conda-forge)"
    "$WORK/tools/micromamba" create -y -q -p "$MAMBA_ROOT_PREFIX/envs/py311" \
        -c conda-forge python=3.11 "pip>=24" setuptools wheel
fi
echo "python: $($PY311 --version)"
$PY311 -m pip install -q --upgrade pip

echo "===== [$(date +%T)] 复制仓库到 ext4 ====="
mkdir -p "$WORK/src"
rsync -a --delete \
    --exclude '.git' --exclude '.vs' --exclude 'build_out' --exclude 'logs' \
    --exclude '__pycache__' --exclude 'android/.venv' --exclude 'android/app_src' \
    --exclude 'android/libs' --exclude 'android/.work' --exclude 'android/wheels' \
    "$SRC/" "$WORK/src/"
echo "仓库副本大小: $(du -sh "$WORK/src" | cut -f1)"
ls "$WORK/src"

echo "===== [$(date +%T)] 完成 ====="
echo "PY311=$PY311"
echo "WORK=$WORK"
