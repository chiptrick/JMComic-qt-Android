#!/usr/bin/env bash
# 用 curl 直接下载 PySide6-Essentials wheel(避开 pip 解析/缓存)并检查部署工具
set -uo pipefail
WORK=/root/jmcomic-build
exec > >(tee -a "$WORK/logs/essentials.log") 2>&1
VER=6.11.2
echo "===== [$(date +%T)] 解析 wheel URL ====="
curl -sS -m 60 "https://pypi.org/pypi/PySide6-Essentials/$VER/json" -o /tmp/ess.json
URL=$(python3 -c "
import json
d=json.load(open('/tmp/ess.json'))
for u in d['urls']:
    if 'manylinux' in u['filename'] and 'x86_64' in u['filename']:
        print(u['url']); break
")
echo "URL=$URL"
NAME=$(basename "$URL")
OUT="$WORK/tools/whl/$NAME"
if [ ! -s "$OUT" ]; then
    echo "===== [$(date +%T)] 下载 $NAME ====="
    curl -L --retry 3 --retry-delay 5 -m 1800 -C - -o "$OUT" "$URL"
fi
ls -sh "$OUT"
echo "===== [$(date +%T)] 检查内容 ====="
python3 - "$OUT" <<'EOF'
import sys, zipfile
path = sys.argv[1]
z = zipfile.ZipFile(path)
names = z.namelist()
print('文件总数:', len(names))
hits = [n for n in names if 'deploy' in n.lower() or 'android' in n.lower()]
print('deploy/android 相关:', len(hits))
for h in hits[:40]:
    print('   ', h)
for n in names:
    if n.endswith('entry_points.txt'):
        print('--- 入口点', n)
        print(z.read(n).decode('utf-8', 'ignore'))
    if n.endswith('WHEEL'):
        print('--- WHEEL tag:', z.read(n).decode('utf-8', 'ignore').replace('\n', ' | '))
EOF
echo "===== [$(date +%T)] 完成 ====="
