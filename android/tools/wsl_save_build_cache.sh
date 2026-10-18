#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 把已编译产物搬出 .buildozer，避免被 pyside6-android-deploy --init 的 cleanup() 清掉
# (cleanup() 里有 shutil.rmtree(project_dir/.buildozer)，一次冷构建要 30 分钟)
#
# 会保存**所有存在的 ABI 目录**，不只是当前 JM_ABI：
# 打 x86_64 包时 cleanup() 同样会删掉 build-arm64-v8a，反过来也一样。
# 每个 ABI 落到自己的 keep-<abi>/，两套缓存互不污染。
# 用 mv 而不是 cp：同一文件系统上是瞬时的。
set -uo pipefail
W="${WORK:-"$JM_WORK"}"
PLATFORM="$W/src/android/.buildozer/android/platform"
# 兼容旧布局：以前的缓存目录叫 keep/(只有 arm64)
if [ ! -e "$W/keep-arm64-v8a" ] && [ -d "$W/keep" ]; then
    mv "$W/keep" "$W/keep-arm64-v8a"
    echo "  旧缓存目录 keep/ -> keep-arm64-v8a"
fi
total=0
for abi in arm64-v8a x86_64; do
    B="$PLATFORM/build-$abi"
    K="$W/keep-$abi"
    [ -d "$B" ] || continue
    echo "== $abi =="
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
    total=$((total + moved))
done
[ "$total" -gt 0 ] || echo "(没有可保存的构建产物)"
