#!/usr/bin/env bash
# 探测 GitHub 可达性、本机代理端口、GitHub 镜像
set -uo pipefail
echo "=== GitHub 各域名 ==="
for u in https://github.com https://api.github.com https://raw.githubusercontent.com \
         https://codeload.github.com https://objects.githubusercontent.com \
         https://github.com/kivy/python-for-android/archive/refs/heads/develop.tar.gz ; do
    c=$(curl -sS -m 12 -o /dev/null -w '%{http_code}' -r 0-200 "$u" 2>/dev/null)
    [ -z "$c" ] && c=FAIL
    printf '%-72s %s\n' "$u" "$c"
done
echo
echo "=== DNS 解析 ==="
getent hosts github.com raw.githubusercontent.com 2>/dev/null || echo "getent 无结果"
python3 -c "import socket
for h in ('github.com','raw.githubusercontent.com','codeload.github.com'):
    try: print(h, socket.gethostbyname(h))
    except Exception as e: print(h, 'FAIL', e)"
echo
echo "=== 本机常见代理端口 ==="
for p in 7890 7891 7897 10809 10808 1080 8080 8888 20171 33210; do
    if timeout 2 bash -c "echo > /dev/tcp/127.0.0.1/$p" 2>/dev/null; then
        echo "127.0.0.1:$p OPEN"
    fi
done
echo "(宿主 Windows 的代理在 WSL 里通常要用 <windows-ip>:port，见下)"
ip route | grep default
cat /etc/resolv.conf | grep nameserver
echo
echo "=== GitHub 镜像可用性 ==="
for u in https://ghproxy.net/https://github.com/kivy/python-for-android/archive/refs/heads/develop.tar.gz \
         https://gh-proxy.com/https://github.com/kivy/python-for-android/archive/refs/heads/develop.tar.gz \
         https://ghfast.top/https://github.com/kivy/python-for-android/archive/refs/heads/develop.tar.gz \
         https://gitee.com/mirrors/python-for-android \
         https://kkgithub.com/kivy/python-for-android ; do
    c=$(curl -sSL -m 15 -o /dev/null -w '%{http_code}' -r 0-200 "$u" 2>/dev/null)
    [ -z "$c" ] && c=FAIL
    printf '%-100s %s\n' "$(echo "$u" | cut -c1-100)" "$c"
done
