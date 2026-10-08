#!/usr/bin/env bash
# 看 jmcomic 到底要从 curl_cffi 拿哪些名字
set -uo pipefail
D=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/build/python-installs/JMComic/arm64-v8a/jmcomic
echo "=== jm_async_client.py 前 30 行 ==="
sed -n '1,30p' "$D/jm_async_client.py"
echo
echo "=== 该目录下所有 curl_cffi import ==="
grep -rn 'curl_cffi' "$D" | head -20
echo
echo "=== jm_async_downloader.py 里的 curl_cffi ==="
grep -n 'curl_cffi' "$D/jm_async_downloader.py" 2>/dev/null || echo "(无)"
echo
echo "=== 这些文件里用到的 curl_cffi 名字 ==="
grep -rhoE 'from curl_cffi[^ ]* import [^#]*' "$D" | sort -u
grep -rhoE 'curl_cffi\.[A-Za-z_.]+' "$D" | sort -u
