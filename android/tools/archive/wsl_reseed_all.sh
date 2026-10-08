#!/usr/bin/env bash
# 停掉所有构建进程 -> 补齐所有包的源码缓存(文件+marker) -> 校验
set -uo pipefail
WORK=/root/jmcomic-build
P4A=$WORK/p4a
STORES=(
  "$WORK/src/android/.buildozer/android/platform/build-arm64-v8a/packages"
  "$WORK/.buildozer/android/platform/build-arm64-v8a/packages"
)
mkdir -p "$WORK/logs"
exec > >(tee -a "$WORK/logs/reseed.log") 2>&1

echo "===== [$(date +%T)] 停掉构建进程 ====="
pkill -f pythonforandroid.toolchain 2>/dev/null || true
pkill -f 'buildozer android' 2>/dev/null || true
sleep 4
ps -eo pid,cmd | grep -E 'pythonforandroid|buildozer' | grep -v grep | head -3
echo "(以上为空表示已全部退出)"

echo
echo "===== [$(date +%T)] 用 recipe 自己的 URL(curl)补齐缺 marker 的包 ====="
RECIPES="$P4A/pythonforandroid/recipes"
while IFS= read -r f; do
    url=$(grep -oE "url\s*=\s*['\"][^'\"]+['\"]" "$f" | head -1 | sed "s/url\s*=\s*//;s/['\"]//g")
    ver=$(grep -oE "version\s*=\s*['\"][^'\"]+['\"]" "$f" | head -1 | sed "s/version\s*=\s*//;s/['\"]//g")
    [ -n "$url" ] || continue
    case "$url" in *'{version}'*) [ -n "$ver" ] || continue ;; esac
    full=$(echo "$url" | sed "s/{version}/$ver/g")
    recipe=$(basename "$(dirname "$f")")
    fname=$(basename "$full")
    # 只处理"目标 build 目录里缺文件或缺少 marker"的包
    need=0
    for store in "${STORES[@]}"; do
        if [ ! -s "$store/$recipe/$fname" ] || [ ! -f "$store/$recipe/.mark-$fname" ]; then
            need=1
        fi
    done
    [ "$need" = "1" ] || continue
    # 只补我们依赖清单里用得到的包，避免全量下载
    case " python3 hostpython3 openssl libffi libxml2 libxslt png jpeg freetype sqlite3 Pillow lxml pycryptodome " in
        *" $recipe "*) ;;
        *) continue ;;
    esac
    echo "-- $recipe: 需要补齐($fname)"
    tmp="/tmp/reseed_${recipe}_${fname}"
    if [ ! -s "$tmp" ] || [ "$(stat -c%s "$tmp" 2>/dev/null || echo 0)" -lt 10000 ]; then
        curl -sSL --retry 3 -m 1800 -o "$tmp" "$full" || { echo "   下载失败: $full"; continue; }
    fi
    echo "   $(du -h "$tmp" | cut -f1)"
    for store in "${STORES[@]}"; do
        mkdir -p "$store/$recipe"
        cp -f "$tmp" "$store/$recipe/$fname"
        touch "$store/$recipe/.mark-$fname"
    done
done < <(find "$RECIPES" -maxdepth 2 -name '__init__.py')

echo
echo "===== [$(date +%T)] 目标 build 目录缓存校验 ====="
for store in "${STORES[@]}"; do
    echo "--- $store"
    for d in "$store"/*/; do
        [ -d "$d" ] || continue
        n=$(basename "$d")
        case " python3 hostpython3 openssl libffi libxml2 libxslt png jpeg freetype sqlite3 Pillow lxml pycryptodome " in
            *" $n "*) ;;
            *) continue ;;
        esac
        f=$(find "$d" -maxdepth 1 -type f ! -name '.mark-*' | head -1)
        m=""
        [ -n "$f" ] && m=$(find "$d" -maxdepth 1 -name ".mark-$(basename "$f")" | head -1)
        printf '  %-14s %-30s %s\n' "$n" "$(basename "${f:-无}")" "$([ -n "$m" ] && echo 'marker OK' || echo 'marker 缺失')"
    done
done
