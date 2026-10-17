#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 建 venv314(宿主 CPython 3.14) —— 3.14 迁移后 wsl_run_smoke.sh 优先用它跑回归，
# 让"语法编译 + 冒烟"覆盖目标 Python 的真实语义(3.11 的 venv 覆盖不到 3.14 移除项)。
#
# * 用系统 python3.14(Ubuntu 26.04 自带；没有就 apt 装 python3.14-venv)
# * PySide6 用 6.12.0(cp310-abi3, linux x86_64)—— 与 APK 里的 android wheel 同版本，
#   桌面/宿主回归跟 APK 的 Qt 大版本对齐(旧 venv311 是 6.11.2,仅构建工具链继续用)
# * buildozer 仍然只在 venv311 里跑(它要求宿主 <=3.11)，venv314 只做回归
set -uo pipefail
W="${WORK:-"$JM_WORK"}"
VENV="$W/venv314"
MIRROR="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
mkdir -p "$W/logs"
exec > >(tee -a "$W/logs/setup_venv314.log") 2>&1

SYS314=$(command -v python3.14 || true)
[ -n "$SYS314" ] || {
    echo "缺 python3.14，尝试 apt 安装"
    export DEBIAN_FRONTEND=noninteractive
    apt-get install -y -qq --no-install-recommends python3.14 python3.14-venv || {
        echo "[FAIL] apt 装不上 python3.14(Ubuntu 26.04 应自带)"; exit 1; }
    SYS314=$(command -v python3.14)
}
echo "系统 python: $SYS314 ($($SYS314 --version))"

echo "===== 建 venv314 ====="
rm -rf "$VENV"
"$SYS314" -m venv "$VENV"
PY="$VENV/bin/python"
"$PY" -m pip install -q --upgrade pip -i "$MIRROR" 2>&1 | tail -2

echo "===== 安装 PySide6 6.12.0(abi3) + 回归依赖 ====="
# PySide6-Essentials 6.12.0 的 linux wheel 是 cp310-abi3，pip 在 3.14 上可直接装
"$PY" -m pip install -q -i "$MIRROR" \
    "PySide6-Essentials==6.12.0" "shiboken6==6.12.0" \
    pillow pycryptodome requests "cython<3" 2>&1 | tail -3
"$PY" -c "import PySide6, shiboken6; print('PySide6', PySide6.__version__, 'OK')"

echo "===== 完成 VENV314=$VENV ====="
"$PY" --version
echo "用法: bash android/tools/wsl_run_smoke.sh(自动优先选 venv314)"
