#!/usr/bin/env bash
# 1) 从 shiboken6 目录下载 android wheel  2) 打印部署工具 android 实现的要点
set -uo pipefail
WORK=/root/jmcomic-build
SRC="$WORK/src"
exec > >(tee -a "$WORK/logs/tool_inspect.log") 2>&1

echo "===== [$(date +%T)] shiboken6 android wheel ====="
LIST="$WORK/shiboken_list.html"
curl -sS -m 60 https://download.qt.io/official_releases/QtForPython/shiboken6/ -o "$LIST"
NAME=$(grep -oE 'href="[^"]*android_aarch64\.whl"' "$LIST" | sed 's/href="//;s/"//' | sort -V | tail -1)
echo "最新: $NAME"
grep -oE 'href="[^"]*android_aarch64\.whl"' "$LIST" | sed 's/href="//;s/"//' | sort -V | tail -5
if [ -n "$NAME" ]; then
    OUT="$SRC/android/wheels/$(basename "$NAME")"
    if [ ! -s "$OUT" ]; then
        for base in \
            "https://mirrors.tuna.tsinghua.edu.cn/qt/official_releases/QtForPython/shiboken6" \
            "https://mirrors.ustc.edu.cn/qtproject/official_releases/QtForPython/shiboken6" \
            "https://download.qt.io/official_releases/QtForPython/shiboken6"; do
            echo "尝试 $base"
            curl -sSL -f --retry 2 -m 600 -o "$OUT" "$base/$NAME" && break
            rm -f "$OUT"
        done
    fi
    ls -sh "$OUT" 2>/dev/null || echo "下载失败"
fi
ls -sh "$SRC/android/wheels/"

echo
echo "===== [$(date +%T)] 部署工具 android 实现要点 ====="
SP="$WORK/venv-host/lib/python3.14/site-packages/PySide6/scripts"
ls "$SP"
echo "--- android_helper.py 关键函数 ---"
grep -nE "^def |^class |buildozer|local_libs|wheel|android.api|minapi|requirements|ARCH|ndk|sdk" "$SP/deploy_lib/android/android_helper.py" | head -60
echo
echo "--- android_config.py ---"
sed -n '1,80p' "$SP/deploy_lib/android/android_config.py"
echo
echo "--- buildozer.py 关键点 ---"
grep -nE "local_libs|android.api|minapi|requirements|def |ARCH|bootstrap" "$SP/deploy_lib/android/buildozer.py" | head -40
