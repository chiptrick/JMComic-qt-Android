#!/usr/bin/env bash
# 直接从清华镜像的 simple 索引解析 sdist 直链并放入 p4a 缓存
# (pip --no-binary 会尝试构建 lxml 等包而失败，所以这里绕开 pip)
set -uo pipefail
WORK=/root/jmcomic-build
P4A="${P4A:-$WORK/p4a}"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
STORES=(
  "$WORK/src/android/.buildozer/android/platform/build-arm64-v8a/packages"
  "$WORK/.buildozer/android/platform/build-arm64-v8a/packages"
)
RECIPES="$P4A/pythonforandroid/recipes"
exec > >(tee -a "$WORK/logs/seed_sources2.log") 2>&1

Seed() {  # $1=recipe $2=version $3=url(含 {version} 已替换) $4=pypi 包名
    local recipe="$1" ver="$2" full="$3" pkg="$4"
    local fname; fname=$(basename "$full")
    echo "== $recipe ($pkg==$ver) 期望文件名: $fname"
    # 从镜像 simple 页拿 sdist 直链
    local page="/tmp/simple_$pkg.html"
    curl -sSL -m 60 "$MIRROR/$pkg/" -o "$page" || { echo "  索引失败"; return 1; }
    # 镜像页里的链接是相对路径
    local link
    link=$(grep -oE 'href="[^"]*"' "$page" | sed 's/href="//;s/"//' \
           | grep -iE "(${pkg}|${recipe})[-_]$ver[-.].*\.(tar\.gz|zip|tar\.bz2)" \
           | grep -v '\.whl' | head -1)
    if [ -z "$link" ]; then
        echo "  索引里没找到 $ver 的 sdist"
        return 1
    fi
    case "$link" in
        http*) url="$link" ;;
        /*)    url="https://pypi.tuna.tsinghua.edu.cn$link" ;;
        *)     url="https://pypi.tuna.tsinghua.edu.cn/simple/$pkg/$link" ;;
    esac
    echo "  直链: $(echo "$url" | cut -c1-110)"
    local tmp="/tmp/${pkg}_$ver"
    if [ ! -s "$tmp" ]; then
        curl -sSL --retry 3 -o "$tmp" "$url" || { echo "  下载失败"; return 1; }
    fi
    echo "  大小: $(du -h "$tmp" | cut -f1)"
    for store in "${STORES[@]}"; do
        mkdir -p "$store/$recipe"
        rm -f "$store/$recipe/$fname" "$store/$recipe/.mark-$fname"
        cp -f "$tmp" "$store/$recipe/$fname"
        touch "$store/$recipe/.mark-$fname"
    done
    echo "  已放入缓存"
}

# Pillow: recipe 版本 11.3.0，URL 形如 .../{version}.tar.gz
PILLOW_VER=$(grep -oE "version\s*=\s*['\"][^'\"]+['\"]" "$RECIPES/Pillow/__init__.py" | head -1 | sed "s/version\s*=\s*//;s/['\"]//g")
PILLOW_URL=$(grep -oE "url\s*=\s*['\"][^'\"]+['\"]" "$RECIPES/Pillow/__init__.py" | head -1 | sed "s/url\s*=\s*//;s/['\"]//g")
PILLOW_URL=$(echo "$PILLOW_URL" | sed "s/{version}/$PILLOW_VER/g")
echo "Pillow recipe: version=$PILLOW_VER url=$(echo "$PILLOW_URL" | cut -c1-90)"
Seed "Pillow" "$PILLOW_VER" "$PILLOW_URL" "pillow"

# lxml: recipe 版本 4.8.0
LXML_VER=$(grep -oE "version\s*=\s*['\"][^'\"]+['\"]" "$RECIPES/lxml/__init__.py" | head -1 | sed "s/version\s*=\s*//;s/['\"]//g")
LXML_URL=$(grep -oE "url\s*=\s*['\"][^'\"]+['\"]" "$RECIPES/lxml/__init__.py" | head -1 | sed "s/url\s*=\s*//;s/['\"]//g")
LXML_URL=$(echo "$LXML_URL" | sed "s/{version}/$LXML_VER/g")
echo "lxml recipe: version=$LXML_VER url=$(echo "$LXML_URL" | cut -c1-90)"
Seed "lxml" "$LXML_VER" "$LXML_URL" "lxml"

# pycryptodome(如果 recipe 存在)
if [ -d "$RECIPES/pycryptodome" ]; then
    PC_VER=$(grep -oE "version\s*=\s*['\"][^'\"]+['\"]" "$RECIPES/pycryptodome/__init__.py" | head -1 | sed "s/version\s*=\s*//;s/['\"]//g")
    PC_URL=$(grep -oE "url\s*=\s*['\"][^'\"]+['\"]" "$RECIPES/pycryptodome/__init__.py" | head -1 | sed "s/url\s*=\s*//;s/['\"]//g")
    PC_URL=$(echo "$PC_URL" | sed "s/{version}/$PC_VER/g")
    echo "pycryptodome recipe: version=$PC_VER url=$(echo "$PC_URL" | cut -c1-90)"
    Seed "pycryptodome" "$PC_VER" "$PC_URL" "pycryptodome"
fi

echo
echo "=== 缓存校验(应有文件 + .mark) ==="
for store in "${STORES[@]}"; do
    for r in Pillow lxml pycryptodome; do
        d="$store/$r"
        [ -d "$d" ] || continue
        echo "--- $d"
        ls -1 "$d" | sed 's/^/    /'
    done
done
