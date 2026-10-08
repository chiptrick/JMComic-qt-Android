#!/usr/bin/env bash
# 把 recipe 里指向 PyPI(files.pythonhosted.org) 的源码包，用国内镜像预先放进 p4a 缓存
# (PyPI 直连只有几 KB/s，几十 MB 的 sdist 会卡几小时)
#
# p4a 的下载缓存校验逻辑：packages/<recipe>/<basename(url)> 存在且
# .mark-<basename> 存在即跳过下载(recipe 未声明 md5 时不校验内容)
set -uo pipefail
WORK=/root/jmcomic-build
P4A="${P4A:-$WORK/p4a}"
VPY="$WORK/venv311/bin/python"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
# p4a 的 packages 目录随 storage-dir 变化，这里两个位置都放一份
STORES=(
  "$WORK/src/android/.buildozer/android/platform/build-arm64-v8a/packages"
  "$WORK/.buildozer/android/platform/build-arm64-v8a/packages"
)
RECIPES="$P4A/pythonforandroid/recipes"
SEED=/tmp/seed
mkdir -p "$SEED"
exec > >(tee -a "$WORK/logs/seed_sources.log") 2>&1

echo "===== [$(date +%T)] 找出走 PyPI 的 recipe ====="
targets=()
while IFS= read -r f; do
    url=$(grep -oE "url\s*=\s*['\"][^'\"]+['\"]" "$f" | head -1 | sed "s/url\s*=\s*//;s/['\"]//g")
    case "$url" in
        *files.pythonhosted.org*|*pypi.org*|*pypi.python.org*) ;;
        *) continue ;;
    esac
    ver=$(grep -oE "version\s*=\s*['\"][^'\"]+['\"]" "$f" | head -1 | sed "s/version\s*=\s*//;s/['\"]//g")
    recipe=$(basename "$(dirname "$f")")
    full=$(echo "$url" | sed "s/{version}/$ver/g")
    echo "  $recipe  version=$ver  $(basename "$full")"
    targets+=("$recipe|$ver|$full")
done < <(find "$RECIPES" -maxdepth 2 -name '__init__.py')

echo
echo "===== [$(date +%T)] 从镜像下载并放入缓存 ====="
for item in "${targets[@]:-}"; do
    [ -n "$item" ] || continue
    IFS='|' read -r recipe ver full <<< "$item"
    fname=$(basename "$full")
    need=0
    for store in "${STORES[@]}"; do
        if [ -f "$store/$recipe/$fname" ] && [ -f "$store/$recipe/.mark-$fname" ]; then
            continue
        fi
        need=1
    done
    if [ "$need" = "0" ]; then
        echo "  $recipe: 已有缓存"
        continue
    fi
    pkg=$(echo "$recipe" | tr '[:upper:]' '[:lower:]')
    rm -rf "$SEED/$recipe" && mkdir -p "$SEED/$recipe"
    echo "  $recipe: pip download $pkg==$ver (镜像)"
    if ! "$VPY" -m pip download -q --no-deps --no-binary :all: -i "$MIRROR" \
            -d "$SEED/$recipe" "$pkg==$ver" 2>&1 | tail -2; then
        echo "    [warn] 镜像下载失败，跳过(让 p4a 自己下)"
        continue
    fi
    got=$(find "$SEED/$recipe" -maxdepth 1 -type f \( -name '*.tar.gz' -o -name '*.zip' -o -name '*.tar.bz2' \) | head -1)
    if [ -z "$got" ]; then
        echo "    [warn] 镜像里没有 sdist"
        continue
    fi
    for store in "${STORES[@]}"; do
        mkdir -p "$store/$recipe"
        cp -f "$got" "$store/$recipe/$fname"
        touch "$store/$recipe/.mark-$fname"
    done
    echo "    -> $(du -h "$got" | cut -f1) 已放入缓存"
done

echo
echo "===== [$(date +%T)] 缓存现状 ====="
for store in "${STORES[@]}"; do
    [ -d "$store" ] || continue
    echo "--- $store ---"
    for d in "$store"/*/; do
        [ -d "$d" ] || continue
        printf '  %-14s %s\n' "$(basename "$d")" "$(ls "$d" 2>/dev/null | tr '\n' ' ' | cut -c1-100)"
    done
done
