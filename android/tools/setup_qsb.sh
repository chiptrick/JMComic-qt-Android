#!/usr/bin/env bash
# 给 PySide6 轮子补上 qsb（Qt Shader Baker），并烘焙 .qsb 着色器
#
# 背景
# ----
# PySide6 的 Linux 轮子**只带运行时库**，不带 Qt 工具（没有 PySide6/Qt/bin）；
# 而 pyside6-qsb 只是个包装器：
#
#   PySide6/scripts/pyside_tool.py:  qt_tool_wrapper("qsb", ...)  ->  执行 PySide6/qsb
#
# 轮子里没有 PySide6/qsb，于是 pyside6-qsb 直接 FileNotFoundError。
# 同时轮子也没有 libQt6ShaderTools（qsb 唯一的非 Core/Gui 依赖）。
#
# 这个脚本做两件事（都不需要 root）：
#   1) 用 apt-get download 把 qsb 所在包 + ShaderTools 运行时库拉到本地解包，
#      装进 venv 的 site-packages/PySide6（qsb.real + qsb shim + Qt/lib 里的 .so）
#   2) 调用 pyside6-qsb 把 src/component/widget/shaders/*.{vert,frag} 烘成 .qsb
#
# 用法（在 WSL 里）：
#   bash android/tools/setup_qsb.sh                 # 安装工具链 + 烘焙
#   bash android/tools/setup_qsb.sh --skip-install  # 只烘焙
#
# 备注：qsb 6.10.2 的二进制配 PySide6 的 Qt 6.12 运行时可用（qsb 生成的容器版本
# 向后兼容，QShader 6.12 能读）。要在目标机上确认，用
#   android/tools/host_test_gpu_layer.py
# 它会检查 .qsb 里是否有 Vulkan 需要的 SpirvShader。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${JM_VENV:-$HOME/jmcomic-build/venv311}"
SP="$VENV/lib/python3.11/site-packages/PySide6"
WORK="${JM_QSB_WORK:-$HOME/qsbpkg}"
SKIP_INSTALL=0
[ "${1:-}" = "--skip-install" ] && SKIP_INSTALL=1

echo "== venv: $VENV"
[ -d "$SP" ] || { echo "[FATAL] 找不到 PySide6: $SP"; exit 1; }

if [ "$SKIP_INSTALL" = "0" ]; then
    if [ -x "$SP/qsb.real" ]; then
        echo "== qsb 已安装，跳过下载"
    else
        echo "== 1/3 下载 qsb 所在包（apt-get download，无需 root）"
        mkdir -p "$WORK"
        cd "$WORK"
        # qt6-shader-baker: /usr/lib/qt6/bin/qsb
        # libqt6shadertools6: libQt6ShaderTools.so.6（qsb 唯一缺失的依赖）
        apt-get download qt6-shader-baker libqt6shadertools6

        echo "== 2/3 解包并装进 PySide6"
        rm -rf "$WORK/root"
        mkdir -p "$WORK/root"
        for f in "$WORK"/*.deb; do dpkg-deb -x "$f" "$WORK/root"; done

        QSB="$(find "$WORK/root" -type f -name qsb | head -1)"
        LIB="$(find "$WORK/root" -name 'libQt6ShaderTools.so.6.*' | head -1)"
        [ -n "$QSB" ] && [ -n "$LIB" ] || { echo "[FATAL] 解包后没找到 qsb / ShaderTools"; exit 1; }

        # 运行时库放 Qt/lib（和 PySide6 其它 Qt 库同目录）
        cp -f "$LIB" "$SP/Qt/lib/$(basename "$LIB")"
        ln -sf "$(basename "$LIB")" "$SP/Qt/lib/libQt6ShaderTools.so.6"

        # 真正的二进制 + shim（shim 只补 LD_LIBRARY_PATH，因为 qt_tool_wrapper
        # 直接 exec PySide6/qsb，不会帮它找库）
        cp -f "$QSB" "$SP/qsb.real"
        chmod +x "$SP/qsb.real"
        cat > "$SP/qsb" <<'SH'
#!/bin/sh
# pyside6-qsb -> PySide6/qsb.real，补齐 Qt ShaderTools 的库搜索路径
d=$(dirname "$0")
LD_LIBRARY_PATH="$d/Qt/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" exec "$d/qsb.real" "$@"
SH
        chmod +x "$SP/qsb"
        echo "   $("$VENV/bin/pyside6-qsb" --version)"
    fi
fi

echo "== 3/3 烘焙着色器"
SHADERS="$REPO/src/component/widget/shaders"
cd "$SHADERS"
for src in *.vert *.frag; do
    [ -f "$src" ] || continue
    out="$src.qsb"
    # --glsl 除了给 OpenGL 回退用，也决定了 qsb 是否顺带算出 SPIR-V；
    # Vulkan 只认 SpirvShader，缺了就是"能建管线但画不出来"。
    "$VENV/bin/pyside6-qsb" "$src" -o "$out" --glsl "100 es,120,150" --hlsl 50 --msl 12
    echo "   $src -> $out ($(stat -c %s "$out") 字节)"
done

echo "== 校验（QShader 能否解析 + 是否含 SpirvShader）"
cd "$REPO/src"
QT_QPA_PLATFORM=offscreen "$VENV/bin/python3" "$REPO/android/tools/host_test_gpu_layer.py" | tail -6
