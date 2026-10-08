#!/usr/bin/env bash
# 用 pip + 国内镜像下载 PySide6-Essentials / shiboken6，并打印速度与内容检查
set -uo pipefail
WORK=/root/jmcomic-build
VPY="$WORK/venv-host/bin/python"
exec > >(tee -a "$WORK/logs/pip_mirror.log") 2>&1

echo "===== [$(date +%T)] 上一次下载结果 ====="
ls -sh "$WORK/tools/whl/" 2>/dev/null
tail -5 /root/mirror.out 2>/dev/null

echo "===== [$(date +%T)] 用清华镜像 pip 下载(带进度) ====="
time "$VPY" -m pip download --no-deps -d "$WORK/tools/whl" \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    PySide6-Essentials==6.11.2 2>&1 | tail -6

echo "===== [$(date +%T)] 检查 wheel 内容 ====="
python3 - <<'EOF'
import glob, zipfile
for path in sorted(glob.glob('/root/jmcomic-build/tools/whl/pyside6_essentials*.whl')):
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        print(path, '打开失败(可能没下完):', e); continue
    names = z.namelist()
    print('==', path.split('/')[-1], 'files:', len(names))
    hits = [n for n in names if 'deploy' in n.lower() or 'android' in n.lower()]
    print('deploy/android:', len(hits))
    for h in hits[:40]:
        print('   ', h)
    for n in names:
        if n.endswith('entry_points.txt'):
            print('--- 入口点', n)
            print(z.read(n).decode('utf-8', 'ignore'))
EOF
echo "===== [$(date +%T)] 完成 ====="
