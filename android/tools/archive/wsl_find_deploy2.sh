#!/usr/bin/env bash
# 1) 装 pip/venv  2) 找 pyside6-android-deploy 到底在哪个 wheel 里
set -euo pipefail
WORK=/root/jmcomic-build
export DEBIAN_FRONTEND=noninteractive
exec > >(tee -a "$WORK/logs/find_deploy.log") 2>&1

echo "===== [$(date +%T)] 安装 pip / venv ====="
apt-get install -y -qq --no-install-recommends python3-pip python3-venv python3-full >/dev/null
python3 -m pip --version

echo "===== [$(date +%T)] 宿主 venv(python3.14, PySide6 是 cp310-abi3 可用) ====="
if [ ! -x "$WORK/venv-host/bin/python" ]; then
    python3 -m venv "$WORK/venv-host"
fi
VPY="$WORK/venv-host/bin/python"
$VPY -m pip install -q --upgrade pip
$VPY --version

echo "===== [$(date +%T)] 检查 shiboken6 / PySide6 wheel 里是否带部署工具 ====="
mkdir -p "$WORK/tools/whl"
$VPY -m pip download --no-deps --only-binary=:all: -d "$WORK/tools/whl" shiboken6==6.11.2 2>&1 | tail -2
ls -sh "$WORK/tools/whl"
python3 - <<'EOF'
import glob, zipfile
for path in sorted(glob.glob('/root/jmcomic-build/tools/whl/*.whl')):
    z = zipfile.ZipFile(path)
    names = z.namelist()
    hits = [n for n in names if 'deploy' in n.lower() or 'android' in n.lower()]
    print('==', path.split('/')[-1], 'files:', len(names))
    for h in hits[:30]:
        print('   ', h)
    for meta in ('entry_points.txt',):
        for n in names:
            if n.endswith(meta):
                print('   ---', n)
                print(z.read(n).decode('utf-8', 'ignore')[:1200])
EOF
