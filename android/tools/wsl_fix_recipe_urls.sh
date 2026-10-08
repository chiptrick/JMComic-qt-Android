#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 修正 p4a recipe：下载地址(可达性) + Python 版本(必须与 PySide6 android wheel 的
# cp311 对齐，否则打进 APK 的 CPython 3.14 无法加载 cp311 的 PySide6 扩展)
# 可重复执行(幂等)
set -uo pipefail
P4A="${P4A:-"$JM_WORK/p4a"}"
GH="https://ghproxy.net/https://github.com"
RECIPES="$P4A/pythonforandroid/recipes"
PYVER="${PYVER:-3.11.13}"

echo "== 1) 修复被重复加了 ghproxy 前缀的 URL =="
fixed=0
while IFS= read -r file; do
    if grep -q 'ghproxy.net/https://ghproxy.net/' "$file"; then
        sed -i 's|ghproxy\.net/https://ghproxy\.net/|ghproxy.net/|g' "$file"
        fixed=$((fixed + 1))
    fi
done < <(find "$RECIPES" -name '*.py')
echo "  修复 $fixed 个文件"

echo "== 2) 给未加前缀的 GitHub 直链加 ghproxy(幂等) =="
# 用 python 精确处理：只替换前面不是 ghproxy.net/ 的 github.com
python3 - "$RECIPES" "$GH" <<'EOF'
import os, re, sys
recipes, gh = sys.argv[1], sys.argv[2]
pattern = re.compile(r'(?<!ghproxy\.net/)https://github\.com/')
count = 0
for root, _, files in os.walk(recipes):
    for name in files:
        if not name.endswith('.py'):
            continue
        path = os.path.join(root, name)
        text = open(path, encoding='utf-8').read()
        new = pattern.sub(gh + '/', text)
        if new != text:
            open(path, 'w', encoding='utf-8').write(new)
            count += 1
print('  改写 %d 个 recipe 的 GitHub 直链' % count)
EOF

echo "== 3) openssl 换到 GitHub release(openssl.org 证书链 python 验不过) =="
f="$RECIPES/openssl/__init__.py"
if [ -f "$f" ] && grep -q "www.openssl.org" "$f"; then
    sed -i "s|https://www.openssl.org/source/openssl-{version}.tar.gz|$GH/openssl/openssl/releases/download/openssl-{version}/openssl-{version}.tar.gz|g" "$f"
fi
grep -oE "url = .*" "$f" | head -1

echo "== 4) python3 / hostpython3 固定为 $PYVER(对齐 cp311 wheel) =="
for r in python3 hostpython3; do
    f="$RECIPES/$r/__init__.py"
    [ -f "$f" ] || continue
    python3 - "$f" "$PYVER" "$GH" <<'EOF'
import re, sys
path, pyver, gh = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path, encoding='utf-8').read()
text = re.sub(r"(\n\s*version\s*=\s*)['\"][0-9]+\.[0-9]+\.[0-9]+['\"]",
              lambda m: m.group(1) + "'" + pyver + "'", text, count=1)
url = gh + "/python/cpython/archive/refs/tags/v{version}.tar.gz"
text = re.sub(r"(\n\s*url\s*=\s*)['\"][^'\"]*['\"]",
              lambda m: m.group(1) + "'" + url + "'", text, count=1)
open(path, 'w', encoding='utf-8').write(text)
print('  %s -> version=%s' % (path.split('/')[-2], pyver))
EOF
done
echo "--- 校验 ---"
grep -nE "version = |url = " "$RECIPES/python3/__init__.py" | head -2
grep -nE "version = |url = " "$RECIPES/hostpython3/__init__.py" | head -2

echo "== 5) 验证关键 URL 用 python urllib 可下载 =="
VPY="$JM_WORK/venv311/bin/python"
if [ -x "$VPY" ]; then
    CERTIFI=$("$VPY" -c "import certifi;print(certifi.where())" 2>/dev/null || echo "")
    [ -n "$CERTIFI" ] && export SSL_CERT_FILE="$CERTIFI"
    "$VPY" - <<EOF
import urllib.request
urls = {
    "cpython-$PYVER": "$GH/python/cpython/archive/refs/tags/v$PYVER.tar.gz",
    "openssl": "$GH/openssl/openssl/releases/download/openssl-3.3.1/openssl-3.3.1.tar.gz",
    "libffi": "$GH/libffi/libffi/archive/v3.4.2.tar.gz",
}
for name, url in urls.items():
    try:
        req = urllib.request.Request(url, headers={"Range": "bytes=0-100"})
        with urllib.request.urlopen(req, timeout=30) as r:
            print("  ok  ", name, r.status)
    except Exception as es:
        print("  FAIL", name, str(es)[:110])
EOF
fi
