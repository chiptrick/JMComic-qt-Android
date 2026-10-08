#!/usr/bin/env bash
# 探明 sqlite3 recipe 的 URL，并从可用的镜像快速预置
set -uo pipefail
WORK=/root/jmcomic-build
P4A=$WORK/p4a
R="$P4A/pythonforandroid/recipes/sqlite3/__init__.py"
echo "=== sqlite3 recipe ==="
grep -nE "version = |url = |md5sum|sha256sum" "$R" | head -5
VER=$(grep -oE "version\s*=\s*['\"][^'\"]+['\"]" "$R" | head -1 | sed "s/version\s*=\s*//;s/['\"]//g")
URL=$(grep -oE "url\s*=\s*['\"][^'\"]+['\"]" "$R" | head -1 | sed "s/url\s*=\s*//;s/['\"]//g")
URL=$(echo "$URL" | sed "s/{version}/$VER/g")
echo "version=$VER"
echo "url=$URL"
echo "期望缓存文件名: $(basename "$URL")"

echo
echo "=== 候选镜像可达性 ==="
for u in \
  "https://ghproxy.net/https://github.com/sqlite/sqlite/archive/refs/tags/version-$VER.tar.gz" \
  "https://ghproxy.net/https://github.com/sqlite/sqlite/archive/version-$VER.tar.gz" \
  "https://mirrors.tuna.tsinghua.edu.cn/sqlite/2025/sqlite-autoconf-3500400.tar.gz" \
  "https://www.sqlite.org/2025/sqlite-autoconf-3500400.tar.gz" ; do
    c=$(curl -sSL -m 25 -o /dev/null -w '%{http_code} %{size_download}' -r 0-2000 "$u" 2>/dev/null)
    [ -z "$c" ] && c=FAIL
    printf '%-100s %s\n' "$u" "$c"
done

echo
echo "=== 用 ghproxy 的 GitHub 归档预置 ==="
GHURL="https://ghproxy.net/https://github.com/sqlite/sqlite/archive/refs/tags/version-$VER.tar.gz"
TMP="/tmp/sqlite3-$VER.tar.gz"
curl -sSL --retry 3 -m 900 -o "$TMP" "$GHURL" && echo "下载完成: $(du -h "$TMP" | cut -f1)" || echo "下载失败"
if [ -s "$TMP" ]; then
    fname=$(basename "$URL")
    for store in "$WORK/src/android/.buildozer/android/platform/build-arm64-v8a/packages" \
                 "$WORK/.buildozer/android/platform/build-arm64-v8a/packages"; do
        mkdir -p "$store/sqlite3"
        rm -f "$store/sqlite3/$fname" "$store/sqlite3/.mark-$fname"
        cp -f "$TMP" "$store/sqlite3/$fname"
        touch "$store/sqlite3/.mark-$fname"
        echo "  -> $store/sqlite3/$fname"
    done
fi
