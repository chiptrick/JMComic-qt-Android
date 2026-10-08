#!/usr/bin/env bash
# libxml2 下载证书失败：查 URL、试 certifi、试国内镜像
set -uo pipefail
WORK=/root/jmcomic-build
VPY="$WORK/venv311/bin/python"
echo "=== p4a libxml2 recipe 的 url ==="
grep -nE "version|url =|url=" "$WORK/p4a/pythonforandroid/recipes/libxml2/__init__.py" | head -8

echo
echo "=== curl 直接测(系统 CA) ==="
URL=$(grep -oE "url = .*" "$WORK/p4a/pythonforandroid/recipes/libxml2/__init__.py" | head -1 | sed "s/url = //;s/['\"]//g")
VER=$(grep -oE "version = .*" "$WORK/p4a/pythonforandroid/recipes/libxml2/__init__.py" | head -1 | sed 's/version = //;s/["'"'"']//g')
echo "version=$VER  url=$URL"
FULL=$(echo "$URL" | sed "s/{version}/$VER/g")
echo "full=$FULL"
curl -sSL -m 30 -o /dev/null -w 'curl(系统CA): %{http_code} %{size_download}\n' -r 0-2000 "$FULL" || echo "curl 失败"

echo
echo "=== venv python + 系统 CA ==="
"$VPY" - "$FULL" <<'EOF'
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=30) as r:
        print("python(系统CA): OK", r.status)
except Exception as e:
    print("python(系统CA) 失败:", e)
EOF

echo
echo "=== venv python + certifi ==="
"$VPY" -m pip install -q certifi 2>&1 | tail -1
CERTIFI=$("$VPY" -c "import certifi;print(certifi.where())")
echo "certifi: $CERTIFI"
SSL_CERT_FILE="$CERTIFI" "$VPY" - "$FULL" <<'EOF'
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=30) as r:
        print("python(certifi): OK", r.status)
except Exception as e:
    print("python(certifi) 失败:", e)
EOF

echo
echo "=== 国内镜像候选 ==="
for u in \
    "https://mirrors.aliyun.com/gnome/sources/libxml2/$VER/libxml2-$VER.tar.xz" \
    "https://mirrors.tuna.tsinghua.edu.cn/gnome/sources/libxml2/$VER/libxml2-$VER.tar.xz" \
    "https://mirrors.ustc.edu.cn/gnome/sources/libxml2/$VER/libxml2-$VER.tar.xz" \
    "https://download.gnome.org/sources/libxml2/$VER/libxml2-$VER.tar.xz" ; do
    c=$(curl -sSL -m 20 -o /dev/null -w '%{http_code} %{size_download}' -r 0-2000 "$u" 2>/dev/null)
    [ -z "$c" ] && c=FAIL
    printf '%-88s %s\n' "$u" "$c"
done
