#!/usr/bin/env bash
# 定位 pyside6-android-deploy 的获取位置
echo "=== PyPI simple 索引探测(候选包名) ==="
for name in pyside6-deploy pyside6-android-deploy pyside6-deploy-tool pyside6-tools \
            pysidedeploy qt-deploy pyside6-deployer shiboken6 pyside6-essentials; do
    code=$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "https://pypi.org/simple/$name/")
    printf '%-26s %s\n' "$name" "$code"
done
echo
echo "=== download.qt.io/QtForPython 目录 ==="
curl -sS -m 30 https://download.qt.io/official_releases/QtForPython/ | grep -oE 'href="[^"]+"' | sed 's/href="//;s/"//' | head -30
echo
echo "=== 是否有 deploy 相关 wheel ==="
for d in pyside6 shiboken6; do
    echo "--- $d ---"
    curl -sS -m 30 "https://download.qt.io/official_releases/QtForPython/$d/" 2>/dev/null \
      | grep -oiE 'href="[^"]*(deploy|tool)[^"]*"' | sed 's/href="//;s/"//' | sort -V | tail -8
done
echo
echo "=== 系统 python3.14 是否有 pip ==="
python3 -m pip --version 2>&1 | head -2
echo "=== python-for-android 是否在 PyPI ==="
curl -sS -m 15 -o /dev/null -w 'python-for-android: %{http_code}\n' https://pypi.org/simple/python-for-android/
