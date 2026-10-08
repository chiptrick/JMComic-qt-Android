#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 构建前核对：Android 版 libsr_qnn.so 是新的、Qt 插件齐全、模型在位
set -uo pipefail
W="$JM_WORK"
L="$W/src/android/libs/arm64-v8a"
NDK="$W/android-sdk/ndk/26.1.10909125"
TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin"

echo "=== libs/arm64-v8a ($(ls "$L" | wc -l) 个文件) ==="
ls -l --time-style=+%H:%M "$L" | awk 'NR>1 {printf "  %s  %10d  %s\n", $6, $5, $7}'

echo
echo "=== libsr_qnn.so 架构 ==="
"$TOOLCHAIN/llvm-readelf" -h "$L/libsr_qnn.so" 2>/dev/null | grep -E "Class|Machine|Type"
echo "导出符号数: $("$TOOLCHAIN/llvm-nm" -D --defined-only "$L/libsr_qnn.so" 2>/dev/null | grep -c ' T srq_')"
echo "版本串: $("$TOOLCHAIN/llvm-nm" -D --defined-only "$L/libsr_qnn.so" 2>/dev/null | grep -c kVersion) （符号数，仅参考）"

echo
echo "=== 关键依赖 ==="
"$TOOLCHAIN/llvm-readelf" -d "$L/libsr_qnn.so" 2>/dev/null | grep NEEDED

echo
echo "=== Qt 插件 ==="
ls "$L" | grep libplugins || echo "(无插件!)"

echo
echo "=== 模型 ==="
ls "$W/src/android/sr_qnn/models/" | head -12
echo "onnx 数量: $(ls "$W/src/android/sr_qnn/models/"*.onnx 2>/dev/null | wc -l)"
