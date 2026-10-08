#!/usr/bin/env bash
# 诊断 conda 通道可达性与 micromamba 安装进度
echo "=== conda 通道 ==="
for u in https://conda.anaconda.org/conda-forge/noarch/repodata.json \
         https://repo.anaconda.com/pkgs/main/linux-64/repodata.json \
         https://micro.mamba.pm/api/micromamba/linux-64/latest; do
    c=$(curl -sS -m 12 -o /dev/null -w '%{http_code}' -r 0-200 "$u" 2>/dev/null)
    [ -z "$c" ] && c=FAIL
    echo "$u -> $c"
done
echo "=== 文件情况 ==="
ls -la /root/jmcomic-build/tools/ 2>/dev/null
echo "=== mamba 目录 ==="
ls -la /root/jmcomic-build/mamba 2>/dev/null | head -5
echo "=== 日志尾部 ==="
tail -8 /root/jmcomic-build/logs/setup_base2.log 2>/dev/null
echo "=== 进程 ==="
ps -eo pid,etimes,cmd | grep -E "micromamba|curl|tar" | grep -v grep | head -5
