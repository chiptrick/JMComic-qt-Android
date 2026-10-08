#!/usr/bin/env bash
# 真实 wheel 下载测速：从各镜像取一个 ~15MB wheel 的直链，限时 20s 看速度
set -uo pipefail
test_mirror() {
    name="$1"; base="$2"
    # 从一个体积适中的包(numpy)里取 wheel 直链
    url=$(curl -sSL -m 20 "$base/numpy/" 2>/dev/null \
          | grep -oE 'https?://[^"#]+numpy-2\.[0-9]+\.[0-9]+-cp311-cp311-manylinux[^"#]*x86_64\.whl' \
          | head -1)
    if [ -z "$url" ]; then
        url=$(curl -sSL -m 20 "$base/numpy/" 2>/dev/null | grep -oE 'https?://[^"#]+\.whl' | tail -1)
    fi
    if [ -z "$url" ]; then echo "$name: 未取到直链"; return; fi
    got=$(curl -sSL -m 20 -o /dev/null -w '%{size_download}' "$url" 2>/dev/null)
    speed=$(( got / 1024 / 20 ))
    printf '%-40s %10d bytes in ~20s  = %6d KB/s   (%s)\n' "$name" "$got" "$speed" "$(echo "$url" | cut -c1-60)"
}
echo "=== 真实 wheel 下载测速(20s 上限) ==="
test_mirror "清华 TUNA"  "https://pypi.tuna.tsinghua.edu.cn/simple"
test_mirror "阿里云"     "https://mirrors.aliyun.com/pypi/simple"
test_mirror "中科大"     "https://mirrors.ustc.edu.cn/pypi/simple"
test_mirror "PyPI 官方"  "https://pypi.org/simple"
echo
echo "=== 当前 Essentials 下载进度 ==="
ls -sh /root/jmcomic-build/tools/whl/pyside6_essentials*.whl 2>/dev/null
