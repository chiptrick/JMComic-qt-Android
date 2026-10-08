#!/usr/bin/env bash
# 检查 /etc/hosts 屏蔽 + 宿主(网关)代理端口 + 镜像上的 git 克隆
set -uo pipefail
echo "=== /etc/hosts ==="
cat /etc/hosts
echo
echo "=== raw.githubusercontent.com 真实可用性(跟随跳转) ==="
curl -sSL -m 15 -o /dev/null -w 'raw README: %{http_code}\n' \
  https://raw.githubusercontent.com/microsoft/onnxruntime/main/README.md
echo
GW=$(ip route | awk '/default/ {print $3; exit}')
echo "=== 网关 $GW 上的代理端口 ==="
for p in 7890 7891 7897 10809 10808 1080 8080 8888 20171 33210 2080; do
    if timeout 2 bash -c "echo > /dev/tcp/$GW/$p" 2>/dev/null; then echo "$GW:$p OPEN"; fi
done
command -v nc >/dev/null && echo "(nc 可用)" || true
echo
echo "=== 通过镜像 git 克隆 p4a(验证 insteadOf 方案可行) ==="
export GIT_TERMINAL_PROMPT=0
timeout 120 git ls-remote https://ghproxy.net/https://github.com/kivy/python-for-android.git develop 2>&1 | head -3
echo "--- git ls-remote 直连 github ---"
timeout 30 git ls-remote https://github.com/kivy/python-for-android.git develop 2>&1 | head -3
