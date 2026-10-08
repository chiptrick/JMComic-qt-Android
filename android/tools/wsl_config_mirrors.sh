#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 配置可达镜像 + 安装 buildozer/p4a 依赖 + 克隆 p4a(develop) 并改写 GitHub 域名
set -uo pipefail
WORK="$JM_WORK"
VPY="$WORK/venv-host/bin/python"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
GH="https://ghproxy.net/https://github.com"
mkdir -p "$WORK/logs"
exec > >(tee -a "$WORK/logs/buildenv.log") 2>&1

echo "===== [$(date +%T)] 1. pip 永久使用清华镜像 ====="
cat > /etc/pip.conf <<EOF
[global]
index-url = $MIRROR
extra-index-url = https://mirrors.aliyun.com/pypi/simple
trusted-host = pypi.tuna.tsinghua.edu.cn mirrors.aliyun.com
timeout = 60
EOF
cat /etc/pip.conf
$VPY -m pip config list 2>/dev/null | head -3

echo "===== [$(date +%T)] 2. git 走 ghproxy 镜像 ====="
git config --global url."$GH/".insteadOf "https://github.com/"
git config --global url."$GH/".insteadOf "git@github.com:"
git config --global --get-regexp 'url\.' || true

echo "===== [$(date +%T)] 3. 安装 buildozer / p4a 依赖 ====="
$VPY -m pip install -q -U pip setuptools wheel 2>&1 | tail -2
$VPY -m pip install -q buildozer "cython<3" sh pexpect packaging virtualenv appdirs \
    jinja2 toml filetype requests six colorama importlib-metadata psutil 2>&1 | tail -3
$VPY -m pip show buildozer 2>/dev/null | head -3

echo "===== [$(date +%T)] 4. 克隆 python-for-android(develop) ====="
if [ ! -d "$WORK/p4a/.git" ]; then
    rm -rf "$WORK/p4a"
    GIT_TERMINAL_PROMPT=0 git clone --depth 1 -b develop "$GH/kivy/python-for-android.git" "$WORK/p4a" 2>&1 | tail -3
fi
echo "p4a 版本: $(cd "$WORK/p4a" && git log -1 --format='%h %ad %s' --date=short 2>/dev/null)"
ls "$WORK/p4a" | head -8

echo "===== [$(date +%T)] 5. 把 p4a recipes 里的 GitHub 直链改写成镜像 ====="
# p4a 的 recipe 用 url = "https://github.com/..." 直接下载 tarball，这里统一加代理前缀
count=0
while IFS= read -r f; do
    if grep -q 'https://github.com/' "$f"; then
        sed -i "s|https://github.com/|$GH/|g" "$f"
        count=$((count + 1))
    fi
done < <(find "$WORK/p4a/pythonforandroid/recipes" -name '*.py')
echo "改写 recipe 数: $count"
grep -rl 'ghproxy.net' "$WORK/p4a/pythonforandroid/recipes" | wc -l
echo "--- 抽查 ---"
grep -h -m1 'url = ' "$WORK/p4a/pythonforandroid/recipes/libffi/__init__.py" 2>/dev/null
grep -h -m1 'url = ' "$WORK/p4a/pythonforandroid/recipes/openssl/__init__.py" 2>/dev/null

echo "===== [$(date +%T)] 6. 安装 p4a(本地源码) ====="
$VPY -m pip install -q "$WORK/p4a" 2>&1 | tail -5
$VPY -c "import pythonforandroid, sys; print('pythonforandroid', pythonforandroid.__file__)"
$VPY -m pip show python-for-android 2>/dev/null | head -3

echo "===== [$(date +%T)] 7. 验证镜像拉取 tarball 可用 ====="
curl -sSL -m 30 -o /dev/null -w 'libffi tarball: %{http_code} %{size_download}\n' -r 0-100000 \
  "$GH/libffi/libffi/archive/v3.4.4.tar.gz" || true
echo "===== [$(date +%T)] 完成 ====="
