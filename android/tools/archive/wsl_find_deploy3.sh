#!/usr/bin/env bash
# 检查 PySide6-Essentials wheel 是否包含 pyside6-android-deploy
set -euo pipefail
WORK=/root/jmcomic-build
VPY="$WORK/venv-host/bin/python"
exec > >(tee -a "$WORK/logs/find_deploy3.log") 2>&1

echo "===== [$(date +%T)] 下载 PySide6-Essentials 6.11.2 (linux x86_64) ====="
$VPY -m pip download --no-deps --only-binary=:all: -d "$WORK/tools/whl" PySide6-Essentials==6.11.2 2>&1 | tail -2
ls -sh "$WORK/tools/whl"

python3 - <<'EOF'
import glob, zipfile
for path in sorted(glob.glob('/root/jmcomic-build/tools/whl/PySide6_Essentials*.whl')):
    z = zipfile.ZipFile(path)
    names = z.namelist()
    print('==', path.split('/')[-1], 'files:', len(names))
    hits = [n for n in names if 'deploy' in n.lower() or 'android' in n.lower()]
    print('deploy/android 相关文件:', len(hits))
    for h in hits[:40]:
        print('   ', h)
    for n in names:
        if n.endswith('entry_points.txt'):
            print('--- 入口点:', n)
            print(z.read(n).decode('utf-8', 'ignore'))
        if n.endswith('WHEEL'):
            print('--- WHEEL:', z.read(n).decode('utf-8', 'ignore'))
EOF
