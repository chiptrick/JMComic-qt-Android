#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 安装宿主工具链：PySide6-Essentials + shiboken6(本地 wheel) + buildozer/cython(镜像)
# 并从 Qt 镜像下载 android_aarch64 cp311 wheel
set -uo pipefail
WORK="$JM_WORK"
VPY="$WORK/venv-host/bin/python"
WHL="$WORK/tools/whl"
SRC="$WORK/src"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
mkdir -p "$WORK/logs" "$SRC/android/wheels"
exec > >(tee -a "$WORK/logs/install_toolchain.log") 2>&1

echo "===== [$(date +%T)] 安装 PySide6-Essentials / shiboken6(本地 wheel) ====="
$VPY -m pip install -q --no-index --find-links "$WHL" \
    "PySide6-Essentials==6.11.2" "shiboken6==6.11.2" 2>&1 | tail -3
$VPY -c "import PySide6; print('PySide6', PySide6.__version__)"
$VPY -m pip show shiboken6 2>/dev/null | head -3

echo "===== [$(date +%T)] 安装 deploy 依赖(buildozer / cython / 其他) ====="
$VPY -m pip install -q -i "$MIRROR" buildozer "cython<3" pexpect packaging 2>&1 | tail -3
ls "$WORK/venv-host/bin" | grep -iE "deploy|buildozer" || true

echo "===== [$(date +%T)] 检查部署工具自述(需要哪些额外包) ====="
cat "$WORK/venv-host/lib/python3.14/site-packages/PySide6/scripts/requirements-android.txt" 2>/dev/null || \
    find "$WORK/venv-host" -name "requirements-android.txt" -exec cat {} \;

echo "===== [$(date +%T)] 下载 Qt for Python Android wheels(cp311 aarch64) ====="
# 先用官方源列目录，再优先从国内镜像下载
LIST="$WORK/qt_list2.html"
curl -sS -m 120 https://download.qt.io/official_releases/QtForPython/pyside6/ -o "$LIST"
PYSIDE_NAME=$(grep -oE 'href="[^"]*pyside6[^"]*android_aarch64\.whl"' "$LIST" | sed 's/href="//;s/"//' | sort -V | tail -1)
SHI_NAME=$(grep -oE 'href="[^"]*shiboken6[^"]*android_aarch64\.whl"' "$LIST" | sed 's/href="//;s/"//' | sort -V | tail -1)
echo "PySide6  : $PYSIDE_NAME"
echo "shiboken6: $SHI_NAME"
[ -n "$PYSIDE_NAME" ] || { echo "未找到 PySide6 android wheel"; exit 1; }

for name in "$PYSIDE_NAME" "$SHI_NAME"; do
    [ -n "$name" ] || continue
    out="$SRC/android/wheels/$(basename "$name")"
    [ -s "$out" ] && { echo "已存在 $(basename "$out")"; continue; }
    ok=0
    for base in \
        "https://mirrors.tuna.tsinghua.edu.cn/qt/official_releases/QtForPython/pyside6" \
        "https://mirrors.ustc.edu.cn/qtproject/official_releases/QtForPython/pyside6" \
        "https://download.qt.io/official_releases/QtForPython/pyside6" ; do
        echo "尝试 $base/$name"
        if curl -sSL --retry 2 -m 900 -f -o "$out" "$base/$name"; then ok=1; break; fi
        rm -f "$out"
    done
    [ "$ok" = "1" ] || { echo "下载失败: $name"; exit 1; }
    ls -sh "$out"
done

echo "===== [$(date +%T)] 完成 ====="
ls -sh "$SRC/android/wheels/"
