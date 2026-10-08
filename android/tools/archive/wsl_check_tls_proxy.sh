#!/usr/bin/env bash
# 判断 www.openssl.org/python.org 等是否被 TLS 中间人代理，以及镜像是否可用
set -uo pipefail
echo "=== DNS ==="
for h in www.openssl.org www.python.org sqlite.org download.savannah.gnu.org github.com ghproxy.net; do
    ip=$(getent hosts "$h" 2>/dev/null | awk '{print $1}' | head -1)
    printf '%-28s %s\n' "$h" "${ip:-未解析}"
done

echo
echo "=== 证书签发者(判断是否被代理) ==="
for h in www.openssl.org www.python.org; do
    echo "--- $h ---"
    timeout 20 openssl s_client -connect "$h:443" -servername "$h" </dev/null 2>/dev/null \
      | openssl x509 -noout -issuer -subject -dates 2>/dev/null || echo "  握手失败"
done

echo
echo "=== 系统 CA 目录里有没有代理 CA ==="
ls /usr/local/share/ca-certificates/ 2>/dev/null || echo "(无本地 CA)"
ls -la /etc/ssl/certs/ 2>/dev/null | head -5

echo
echo "=== 关键源码包镜像可用性(curl, 跟随跳转) ==="
check() { c=$(curl -sSL -m 25 -o /dev/null -w '%{http_code}' -r 0-2000 "$1" 2>/dev/null); [ -z "$c" ] && c=FAIL; printf '%-95s %s\n' "$(echo "$1" | cut -c1-95)" "$c"; }
check "https://www.python.org/ftp/python/3.11.13/Python-3.11.13.tgz"
check "https://mirrors.aliyun.com/python-release/source/Python-3.11.13.tgz"
check "https://www.sqlite.org/2024/sqlite-autoconf-3450100.tar.gz"
check "https://download.savannah.gnu.org/releases/freetype/freetype-2.13.2.tar.gz"
check "https://ghproxy.net/https://github.com/openssl/openssl/releases/download/openssl-3.3.1/openssl-3.3.1.tar.gz"
