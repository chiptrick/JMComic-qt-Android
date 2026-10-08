#!/usr/bin/env bash
# 诊断/备选：为宿主 Python 3.11 找一条可达且快的路
set -uo pipefail
WORK=/root/jmcomic-build
echo "=== 当前 uv 进程与缓存 ==="
ps -eo pid,etimes,cmd | grep -E "uv |python-build" | grep -v grep | head -5
du -sh "$WORK/pythons" 2>/dev/null; ls -la "$WORK/pythons" 2>/dev/null | head -5
du -sh "$HOME/.cache/uv" 2>/dev/null

echo
echo "=== 候选源可达性 ==="
check() { c=$(curl -sSL -m 15 -o /dev/null -w '%{http_code}' -r 0-500 "$1" 2>/dev/null); [ -z "$c" ] && c=FAIL; printf '%-95s %s\n' "$(echo "$1" | cut -c1-95)" "$c"; }
check "https://ghproxy.net/https://github.com/astral-sh/python-build-standalone/releases/download/20250918/cpython-3.11.13+20250918-x86_64-unknown-linux-gnu-install_only.tar.gz"
check "https://mirrors.tuna.tsinghua.edu.cn/github-release/astral-sh/python-build-standalone/"
check "https://mirrors.ustc.edu.cn/github-release/astral-sh/python-build-standalone/"
check "https://www.python.org/ftp/python/3.11.13/Python-3.11.13.tgz"
check "https://mirrors.aliyun.com/python-release/source/Python-3.11.13.tgz"
check "https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa"
check "https://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu/dists/noble/Release"

echo
echo "=== TSINGHUA github-release 目录(找 python-build-standalone) ==="
curl -sS -m 25 "https://mirrors.tuna.tsinghua.edu.cn/github-release/astral-sh/python-build-standalone/" 2>/dev/null | grep -oE 'href="[^"]+"' | head -10
echo "--- 该镜像下最新版本目录 ---"
curl -sS -m 25 "https://mirrors.tuna.tsinghua.edu.cn/github-release/astral-sh/python-build-standalone/LatestRelease/" 2>/dev/null | grep -oE 'href="[^"]+"' | head -15
