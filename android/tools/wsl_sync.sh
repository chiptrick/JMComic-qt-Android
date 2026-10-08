#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 把 Windows 侧仓库同步到 WSL 的构建目录(ext4，避免 /mnt/c 慢)
# 保留 WSL 侧已下载/已编译的产物：android/libs、android/wheels
set -euo pipefail
WORK="${WORK:-"$JM_WORK"}"
WIN="${WIN:-"$JM_REPO"}"
mkdir -p "$WORK/src"
rsync -a --delete \
    --exclude '.git/' --exclude '.vs/' --exclude 'build_out/' --exclude 'logs/' \
    --exclude '__pycache__/' --exclude '*.pyc' \
    --exclude 'src/data/*.db' --exclude 'src/logs/' \
    --exclude 'android/app_src/' --exclude 'android/.work/' --exclude 'android/.venv/' \
    --exclude 'android/.buildozer/' --exclude 'android/bin/' \
    --exclude 'android/buildozer.spec' \
    --exclude 'android/libs/' --exclude 'android/wheels/' \
    --exclude 'android/*.apk' --exclude 'android/build_logs/' \
    --exclude 'android/deployment/' \
    "$WIN/" "$WORK/src/"
echo "同步完成 -> $WORK/src"
echo "sr_qnn/cpp: $(ls "$WORK/src/android/sr_qnn/cpp" 2>/dev/null | tr '\n' ' ')"
echo "tools 数量: $(ls "$WORK/src/android/tools" 2>/dev/null | wc -l)"
echo "recipes: $(ls "$WORK/src/android/recipes" 2>/dev/null | tr '\n' ' ')"
echo "libs: $(ls "$WORK/src/android/libs/arm64-v8a" 2>/dev/null | wc -l) 个 .so"
