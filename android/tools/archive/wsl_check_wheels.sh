#!/usr/bin/env bash
# 确认 PySide6 Android wheel 的可用版本/CPython 版本，以及 sudo 与 APT 可用性
echo "=== sudo ==="
sudo -n true 2>/dev/null && echo "sudo: passwordless OK" || echo "sudo: NEED PASSWORD (or not installed)"
echo "=== apt ==="
command -v apt-get >/dev/null && echo "apt-get: ok" || echo "apt-get: MISSING"
echo "=== qt pyside6 android wheels (目录列表) ==="
curl -sS -m 30 https://download.qt.io/official_releases/QtForPython/pyside6/ | grep -oE 'href="[^"]+"' | sed 's/href="//;s/"//' | tail -25
echo "=== 查最新几个版本里的 android wheel ==="
for ver in $(curl -sS -m 30 https://download.qt.io/official_releases/QtForPython/pyside6/ | grep -oE 'href="[0-9]+\.[0-9]+\.[0-9]+/"' | sed 's/href="//;s|/"||' | sort -V | tail -6); do
    echo "--- $ver ---"
    curl -sS -m 30 "https://download.qt.io/official_releases/QtForPython/pyside6/$ver/" 2>/dev/null \
        | grep -oE 'href="[^"]*android[^"]*"' | sed 's/href="//;s/"//' | head -6
done
echo "=== 其他下载源可达性(github codeload / objects) ==="
for url in https://codeload.github.com/microsoft/onnxruntime/tar.gz/refs/tags/v1.23.2 \
           https://github.com/microsoft/onnxruntime/archive/refs/tags/v1.23.2.tar.gz \
           https://files.pythonhosted.org/ ; do
    code=$(curl -sS -m 15 -o /dev/null -w '%{http_code}' -r 0-100 "$url" 2>/dev/null) || code=FAIL
    printf '%-80s %s\n' "$url" "$code"
done
