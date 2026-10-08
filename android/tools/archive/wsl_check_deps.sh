#!/usr/bin/env bash
# 检查依赖包在 p4a 下的可打包性：依赖关系 / 是否纯 python / 是否有原生扩展
set -uo pipefail
PKGS="jmcomic commonX curl_cffi webdavclient3 pysmb smbprotocol natsort beautifulsoup4 lxml pillow pycryptodomex tqdm PySocks"
for p in $PKGS; do
    curl -sS -m 25 "https://pypi.org/pypi/$p/json" -o /tmp/p.json 2>/dev/null
    python3 - "$p" <<'EOF'
import json, sys
p = sys.argv[1]
try:
    d = json.load(open('/tmp/p.json'))
except Exception as e:
    print('%-16s 查询失败 %s' % (p, e)); raise SystemExit
info = d['info']
reqs = info.get('requires_dist') or []
urls = d.get('urls') or []
kinds = set()
for u in urls:
    if u['filename'].endswith('.whl'):
        kinds.add('whl')
    else:
        kinds.add('sdist')
base = [r for r in reqs if ';' not in r or 'extra ==' not in r]
print('%-16s v%-10s %-14s 依赖: %s' % (p, info['version'], ','.join(sorted(kinds)), '; '.join(base)[:150]))
EOF
done
