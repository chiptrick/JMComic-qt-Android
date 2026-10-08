#!/usr/bin/env bash
# 测国内镜像速度，并从镜像下载 PySide6-Essentials，检查部署工具入口点
set -uo pipefail
WORK=/root/jmcomic-build
exec > >(tee -a "$WORK/logs/mirror.log") 2>&1
VER=6.11.2
NAME="pyside6_essentials-$VER-cp310-abi3-manylinux_2_34_x86_64.whl"

echo "===== [$(date +%T)] 镜像测速(各拉 2MB 计时) ====="
for base in \
    "https://pypi.tuna.tsinghua.edu.cn/simple" \
    "https://mirrors.aliyun.com/pypi/simple" \
    "https://mirrors.ustc.edu.cn/pypi/simple" \
    "https://pypi.org/simple" ; do
    url="$base/pyside6-essentials/"
    start=$(date +%s%N)
    got=$(curl -sSL -m 25 -o /dev/null -w '%{size_download}' -r 0-2000000 "$url" 2>/dev/null)
    end=$(date +%s%N)
    ms=$(( (end - start) / 1000000 ))
    kbps=$(( got / 1024 / (ms / 1000 + 1) ))
    printf '%-48s %8s bytes %6s ms %6s KB/s\n' "$base" "$got" "$ms" "$kbps"
done

echo
echo "===== [$(date +%T)] 从最快镜像取 wheel URL ====="
for base in "https://pypi.tuna.tsinghua.edu.cn/simple" "https://mirrors.aliyun.com/pypi/simple"; do
    curl -sSL -m 30 "$base/pyside6-essentials/" -o /tmp/simple.html 2>/dev/null
    URL=$(grep -oE 'https?://[^"#]+'"$NAME" /tmp/simple.html | head -1)
    [ -n "$URL" ] && { echo "mirror=$base"; echo "URL=$URL"; break; }
done
[ -n "${URL:-}" ] || { echo "镜像未找到 wheel"; exit 1; }

echo "===== [$(date +%T)] 下载 ====="
OUT="$WORK/tools/whl/$NAME"
time curl -sSL --retry 3 -C - -o "$OUT" "$URL"
ls -sh "$OUT"

echo "===== [$(date +%T)] 检查内容 ====="
python3 - "$OUT" <<'EOF'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
names = z.namelist()
print('文件总数:', len(names))
hits = [n for n in names if 'deploy' in n.lower() or 'android' in n.lower()]
print('deploy/android 相关:', len(hits))
for h in hits[:50]:
    print('   ', h)
for n in names:
    if n.endswith('entry_points.txt'):
        print('--- 入口点:', n)
        print(z.read(n).decode('utf-8', 'ignore'))
EOF
echo "===== [$(date +%T)] 完成 ====="
