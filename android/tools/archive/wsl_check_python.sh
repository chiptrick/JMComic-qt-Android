#!/usr/bin/env bash
# 探测可用的宿主 Python 与 PySide6 宿主 wheel、部署工具包名
echo "=== apt 里的 python 版本 ==="
apt-cache policy python3 python3.11 python3.12 python3.13 python3.14 python3.11-venv python3.13-venv 2>/dev/null \
  | grep -E "^python3|Candidate" | head -30
echo
echo "=== PyPI: PySide6 6.11.2 有哪些 linux wheel(cp 版本) ==="
curl -sS -m 40 https://pypi.org/pypi/PySide6/6.11.2/json -o /tmp/pyside.json
python3 - <<'EOF'
import json
d = json.load(open('/tmp/pyside.json'))
names = [u['filename'] for u in d['urls']]
print('全部 wheel 数:', len(names))
for n in sorted(names):
    print('  ', n)
EOF
echo
echo "=== PyPI: 部署工具包是否存在 ==="
for pkg in pyside6-android-deploy pyside6-deploy PySide6-Essentials buildozer; do
    code=$(curl -sS -m 20 -o /tmp/pkg.json -w '%{http_code}' "https://pypi.org/pypi/$pkg/json")
    ver=$(python3 -c "import json;d=json.load(open('/tmp/pkg.json'));print(d['info']['version'], '| requires:', (d['info'].get('requires_dist') or [])[:3])" 2>/dev/null)
    printf '%-24s %s %s\n' "$pkg" "$code" "$ver"
done
echo
echo "=== 死进程清理 ==="
pkill -f "micromamba" 2>/dev/null; pkill -f "mm.tar.bz2" 2>/dev/null; echo done
