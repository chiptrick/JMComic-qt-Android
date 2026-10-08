#!/usr/bin/env bash
# openssl 源码包的可用镜像(原站证书链在此环境验不过)
set -uo pipefail
V=3.3.1
test_url() {
    local u="$1"
    local out
    out=$(curl -sSL -m 25 -o /dev/null -w '%{http_code} %{size_download}' -r 0-2000 "$u" 2>/dev/null)
    [ -z "$out" ] && out=FAIL
    printf '%-100s %s\n' "$u" "$out"
}
echo "=== 候选源 ==="
test_url "https://www.openssl.org/source/openssl-$V.tar.gz"
test_url "https://mirrors.aliyun.com/openssl/source/openssl-$V.tar.gz"
test_url "https://mirrors.tuna.tsinghua.edu.cn/openssl/source/openssl-$V.tar.gz"
test_url "https://mirrors.ustc.edu.cn/openssl/source/openssl-$V.tar.gz"
test_url "https://mirrors.cloud.tencent.com/openssl/source/openssl-$V.tar.gz"
test_url "https://ghproxy.net/https://github.com/openssl/openssl/releases/download/openssl-$V/openssl-$V.tar.gz"
test_url "https://github.com/openssl/openssl/releases/download/openssl-$V/openssl-$V.tar.gz"
test_url "https://www.openssl.org/source/old/$V/openssl-$V.tar.gz"

echo
echo "=== p4a openssl recipe 期望的 md5/url ==="
sed -n '1,20p' /root/jmcomic-build/p4a/pythonforandroid/recipes/openssl/__init__.py

echo
echo "=== p4a download_if_necessary 逻辑(是否校验 md5) ==="
sed -n '405,470p' /root/jmcomic-build/p4a/pythonforandroid/recipe.py
