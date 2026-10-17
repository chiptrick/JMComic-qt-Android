#!/usr/bin/env bash
# 预置 p4a 原生源码包到 storage packages（文件 + .mark- 即视为已下载，p4a 会跳过联网）
# 背景：ghproxy 下 openssl(16.9MB) 只有 ~240KB/s，冷构建光下载就卡住。
# 用法: bash wsl_seed_native_pkgs.sh
set -uo pipefail
PKG=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/packages

Get() {
    local recipe="$1" name="$2" min="$3"; shift 3
    local dir="$PKG/$recipe" out="$PKG/$recipe/$name"
    mkdir -p "$dir"
    # 完整性校验(不只看大小)：被 kill 的构建会留下截断 tar.gz，大小够但解不开，
    # p4a 到 unpack 阶段才炸(unexpected EOF)。这里先自己 `tar -t` / `unzip -t` 验一遍。
    Valid() {
        [ -s "$1" ] && [ "$(stat -c %s "$1")" -ge "$min" ] || return 1
        case "$1" in
            *.zip) unzip -tqq "$1" >/dev/null 2>&1 ;;
            *)     tar -tzf "$1" >/dev/null 2>&1 ;;
        esac
    }
    if Valid "$out"; then
        echo "  = $recipe/$name 已存在且完整 ($(stat -c %s "$out") 字节)"
        touch "$dir/.mark-$name"
        return 0
    fi
    [ -e "$out" ] && { echo "  ! $recipe/$name 不完整($(stat -c %s "$out" 2>/dev/null || echo 0) 字节)，重下"; rm -f "$out"; }
    local base
    for base in "$@"; do
        for try in 1 2; do
            echo "  > $base$name (第 $try 次)"
            curl -fsSL --connect-timeout 15 --max-time 900 -o "$out" "$base$name" || { rm -f "$out"; continue; }
            if Valid "$out"; then
                touch "$dir/.mark-$name"
                echo "  [ok] $recipe/$name $(stat -c %s "$out") 字节(解压校验通过)"
                return 0
            fi
            echo "  ! 不完整，删掉重试"; rm -f "$out"
        done
    done
    echo "  [FAIL] $recipe/$name"
    return 1
}

echo "== 预置 p4a 原生源码包 -> $PKG =="
bad=0
Get openssl openssl-3.3.1.tar.gz 10000000 \
    "https://mirrors.huaweicloud.com/openssl/source/" \
    "https://ghproxy.net/https://github.com/openssl/openssl/releases/download/openssl-3.3.1/" || bad=$((bad+1))
Get libffi v3.4.2.tar.gz 500000 \
    "https://ghproxy.net/https://github.com/libffi/libffi/archive/" || bad=$((bad+1))
Get sqlite3 version-3.50.4.tar.gz 1000000 \
    "https://ghproxy.net/https://github.com/sqlite/sqlite/archive/refs/tags/" || bad=$((bad+1))
Get png v1.6.37.zip 500000 \
    "https://ghproxy.net/https://github.com/glennrp/libpng/archive/" || bad=$((bad+1))
Get jpeg 2.0.1.tar.gz 500000 \
    "https://ghproxy.net/https://github.com/libjpeg-turbo/libjpeg-turbo/archive/" || bad=$((bad+1))
Get freetype freetype-2.14.1.tar.gz 1000000 \
    "https://download-mirror.savannah.gnu.org/releases/freetype/" \
    "https://download.savannah.gnu.org/releases/freetype/" || bad=$((bad+1))

echo
echo "== 结果(缺 $bad 个) =="
ls -la "$PKG"/openssl "$PKG"/libffi "$PKG"/sqlite3 "$PKG"/png "$PKG"/jpeg "$PKG"/freetype 2>/dev/null | grep -E "tar.gz|zip"
exit $bad
