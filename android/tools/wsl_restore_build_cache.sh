#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 把 wsl_save_build_cache.sh 移出的已编译产物搬回 .buildozer
# 必须在 pyside6-android-deploy --init 之后、buildozer 之前执行
set -uo pipefail
W="${WORK:-"$JM_WORK"}"
B="$W/src/android/.buildozer/android/platform/build-arm64-v8a"
K="$W/keep"
if [ ! -d "$K" ]; then
    echo "(没有 $K，跳过恢复)"
    exit 0
fi
mkdir -p "$B"
for sub in build packages dists; do
    if [ -e "$K/$sub" ]; then
        rm -rf "$B/$sub"
        mv "$K/$sub" "$B/$sub"
        printf '  已恢复 %-10s %s\n' "$sub" "$(du -sh "$B/$sub" 2>/dev/null | cut -f1)"
    fi
done
echo "--- 恢复后的状态 ---"
echo "other_builds: $(ls "$B/build/other_builds" 2>/dev/null | wc -l) 个 recipe"
echo "python-installs: $(ls "$B/build/python-installs" 2>/dev/null | wc -l) 个"
echo "dists: $(ls "$B/dists" 2>/dev/null | tr '\n' ' ')"
