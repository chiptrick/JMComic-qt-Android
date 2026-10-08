#!/usr/bin/env bash
# 统计 android/ 与 src/ 里出现的文件扩展名，对照 source.include_exts（默认只放行 py,png,jpg,kv,atlas,qml,js）
set -u
A=/root/jmcomic-build/src/android
S=/root/jmcomic-build/src/src

echo "=== android/ 下除 app_src/libs/wheels/.buildozer/bin 外的扩展名统计 ==="
find "$A" -type f \
    -not -path "*/app_src/*" -not -path "*/libs/*" -not -path "*/wheels/*" \
    -not -path "*/.buildozer/*" -not -path "*/bin/*" -not -path "*/.run/*" \
    -not -path "*/build_logs/*" -not -path "*/__pycache__/*" \
  | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -30

echo
echo "=== src/ 下(即 app_src)的扩展名统计 ==="
find "$S" -type f -not -path "*/__pycache__/*" -not -path "*/logs/*" \
  | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -30

echo
echo "=== include_exts 放行的扩展: py,png,jpg,kv,atlas,qml,js ==="
echo "--- src/ 里不在放行名单内的文件(前 40) ---"
find "$S" -type f -not -path "*/__pycache__/*" -not -path "*/logs/*" \
  | grep -v -E '\.(py|png|jpg|kv|atlas|qml|js)$' | head -40

echo
echo "=== android/ 里不在放行名单内的文件(前 40, 只看会进 private 的) ==="
find "$A" -type f \
    -not -path "*/app_src/*" -not -path "*/libs/*" -not -path "*/wheels/*" \
    -not -path "*/.buildozer/*" -not -path "*/bin/*" -not -path "*/.run/*" \
    -not -path "*/build_logs/*" -not -path "*/__pycache__/*" \
  | grep -v -E '\.(py|png|jpg|kv|atlas|qml|js)$' | head -40
