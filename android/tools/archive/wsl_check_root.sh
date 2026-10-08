#!/usr/bin/env bash
# 1) 是否能以 root 运行(apt 安装前置) 2) Qt Android wheel 命名/版本 3) 备用下载源
echo "=== id ==="; id
echo "=== apt-get as $(id -un) ==="; command -v apt-get && echo "apt-get ok"
echo
echo "=== qt android wheels (根目录全量 grep) ==="
curl -sS -m 60 https://download.qt.io/official_releases/QtForPython/pyside6/ -o /tmp/qtroot.html
grep -oE 'href="[^"]*android[^"]*"' /tmp/qtroot.html | sed 's/href="//;s/"//' | sort -V | tail -20
echo "--- 版本子目录 ---"
grep -oE 'href="[0-9]+\.[0-9]+\.[0-9]+/"' /tmp/qtroot.html | sed 's/href="//;s|/"||' | sort -V | tail -8
echo "--- 是否有 PySide6-6.10 目录及其中 android wheel ---"
for ver in 6.8.0 6.9.0 6.10.0 6.10.1; do
    n=$(curl -sS -m 30 "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-$ver/" 2>/dev/null | grep -c 'android' || true)
    echo "PySide6-$ver: android 文件数=$n"
    curl -sS -m 30 "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-$ver/" 2>/dev/null | grep -oE 'href="[^"]*android[^"]*"' | sed 's/href="//;s/"//' | head -4
done
echo
echo "=== 备用源可达性(ORT 头文件 / 便携 JDK / conda) ==="
for url in https://cdn.jsdelivr.net/gh/microsoft/onnxruntime@v1.23.2/include/onnxruntime/core/session/onnxruntime_c_api.h \
           https://api.nuget.org/v3/index.json \
           https://api.adoptium.net/v3/info/available_releases \
           https://micro.mamba.pm/api/micromamba/linux-64/latest \
           https://repo.anaconda.com/pkgs/main/linux-64/repodata.json ; do
    code=$(curl -sSL -m 20 -o /dev/null -w '%{http_code}' -r 0-200 "$url" 2>/dev/null) || code=FAIL
    printf '%-95s %s\n' "$(echo "$url" | cut -c1-95)" "$code"
done
