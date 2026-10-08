#!/usr/bin/env bash
# 补齐 p4a recipe 编译所需的前置工具(autotools 等)，然后重启脱离式构建
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive
echo "== 安装 autotools/构建前置 =="
apt-get install -y -qq --no-install-recommends \
    autoconf automake libtool libtool-bin gettext autopoint pkg-config m4 flex bison \
    gperf texinfo help2man >/dev/null
for c in autoreconf automake libtoolize autopoint pkg-config m4 flex bison; do
    printf '%-12s %s\n' "$c" "$(command -v "$c" || echo MISSING)"
done

echo
echo "== 重启脱离式构建 =="
bash /path/to/JMComic-qt/android/tools/wsl_start_detached_build.sh
