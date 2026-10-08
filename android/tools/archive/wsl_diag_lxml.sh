#!/usr/bin/env bash
# 诊断 lxml recipe 的静态依赖要求
set -uo pipefail
P4A=/root/jmcomic-build/p4a
B=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a
echo "=== p4a lxml recipe ==="
cat "$P4A/pythonforandroid/recipes/lxml/__init__.py"
echo
echo "=== lxml setupinfo.py 关键部分(280-300) ==="
sed -n '275,300p' "$B/build/other_builds/lxml/arm64-v8a__ndk_target_34/lxml/setupinfo.py" 2>/dev/null
echo
echo "=== 相关环境变量线索 ==="
grep -nE "STATIC_DEPS|static_library_dirs|STATIC_LIBRARY_DIRS|LIBRARY_DIRS|xml2-config|XML2_CONFIG" \
  "$B/build/other_builds/lxml/arm64-v8a__ndk_target_34/lxml/setupinfo.py" 2>/dev/null | head -14
echo
echo "=== libxml2/libxslt 是否已构建出静态库 ==="
find "$B/build/other_builds/libxml2" "$B/build/other_builds/libxslt" -name '*.a' 2>/dev/null | head -6
find "$B/build/other_builds/libxml2" -name 'xml2-config' 2>/dev/null | head -2
