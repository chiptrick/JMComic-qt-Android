#!/usr/bin/env bash
# 看 buildozer 的真实进度（detached_build.log 在 buildozer 阶段是缓冲的）
set -uo pipefail
L=/root/jmcomic-build/logs/buildozer_full.log
W=/root/jmcomic-build
B="$W/src/android/.buildozer/android/platform/build-arm64-v8a"

echo "buildozer_full.log 行数: $(wc -l < "$L" 2>/dev/null || echo 0)"
echo
echo "=== 当前正在编译的 recipe(最近出现的 [INFO] 目标) ==="
grep -oE 'Building (hostpython3|python3|openssl|libffi|freetype|sqlite3|[A-Za-z0-9_]+)' "$L" 2>/dev/null | tail -6
echo
echo "=== 其他进度标记 ==="
grep -E 'Downloading|Unpacking|Configure|Installing|Building|\[INFO\]' "$L" 2>/dev/null | tail -14 | cut -c1-160
echo
echo "=== other_builds 已完成的 recipe ==="
ls "$B/build/other_builds" 2>/dev/null | sed 's/^/  /' || echo "  (还是空)"
echo
echo "=== dists 内容 ==="
ls "$B/dists/JMComic" 2>/dev/null | sed 's/^/  /' || echo "  (空)"
echo
echo "=== 最后 25 行原始输出 ==="
tail -25 "$L" 2>/dev/null | cut -c1-170
