#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 把已编译产物搬出 .buildozer，避免被 pyside6-android-deploy --init 的 cleanup() 清掉
# (cleanup() 里有 shutil.rmtree(project_dir/.buildozer)，一次冷构建要 30 分钟)
# 用 mv 而不是 cp：同一文件系统上是瞬时的
set -uo pipefail
W="${WORK:-"$JM_WORK"}"
B="$W/src/android/.buildozer/android/platform/build-arm64-v8a"
K="$W/keep"
mkdir -p "$K"
moved=0
for sub in build packages dists; do
    if [ -e "$B/$sub" ] && [ ! -e "$K/$sub" ]; then
        mv "$B/$sub" "$K/$sub"
        printf '  已移出 %-10s %s\n' "$sub" "$(du -sh "$K/$sub" 2>/dev/null | cut -f1)"
        moved=$((moved + 1))
    elif [ -e "$K/$sub" ]; then
        printf '  %-10s 已在 keep 里，跳过\n' "$sub"
    else
        printf '  %-10s 不存在，跳过\n' "$sub"
    fi
done
echo "移出 $moved 项 -> $K"
