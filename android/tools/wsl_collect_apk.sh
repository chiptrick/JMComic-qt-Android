#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# APK 产出后：校验 + 拷回 Windows 仓库
#   * 用 build-tools 的 aapt2/aapt 读包名/minSdk/targetSdk
#   * 列出 APK 里的原生库与 assets
#   * 拷贝 APK 与关键日志到 android/ 目录
set -uo pipefail
WORK="$JM_WORK"
SRC="$WORK/src"
ANDROID="$SRC/android"
SDK="$WORK/android-sdk"
WIN="$JM_REPO/android"
BT=$(ls -d "$SDK"/build-tools/* 2>/dev/null | sort -V | tail -1)
AAPT="$BT/aapt2"
[ -x "$AAPT" ] || AAPT="$BT/aapt"
PY="$JM_WORK/venv311/bin/python"

# 取**最新**的 APK：仓库里可能还留着上一次的产物(android/*.apk)，
# 用 find|head -1 会误取旧包，所以按修改时间排序
APK=$(ls -t "$ANDROID"/bin/*.apk "$ANDROID"/*.apk "$SRC"/*.apk 2>/dev/null | head -1)
if [ -z "$APK" ]; then
    echo "还没有 APK"
    exit 1
fi
echo "=== APK: $APK ($(du -h "$APK" | cut -f1), $(date -r "$APK" '+%F %T')) ==="
cp -f "$APK" "$WIN/" && echo "已拷回仓库: $WIN/$(basename "$APK")"

echo
echo "=== 包信息(aapt) ==="
if [ -x "$AAPT" ]; then
    "$AAPT" dump badging "$APK" 2>/dev/null | grep -E "^package|sdkVersion|targetSdkVersion|application-label|native-code" | head -10
else
    echo "(没有 aapt)"
fi

echo
echo "=== APK 内原生库(lib/arm64-v8a) ==="
"$PY" - "$APK" <<'EOF'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
libs = [i for i in z.infolist() if i.filename.startswith('lib/')]
print("原生库文件数:", len(libs))
key = ("libsr_qnn", "libonnxruntime", "libQnn", "libpyside6", "libshiboken", "libc++_shared")
for i in sorted(libs, key=lambda x: x.filename):
    if any(k in i.filename for k in key):
        print("   %-58s %8.2f MB" % (i.filename, i.file_size / 1024 / 1024))
tot = sum(i.file_size for i in libs) / 1024 / 1024
print("   ---- 原生库合计 %.1f MB" % tot)
assets = [i for i in z.infolist() if i.filename.startswith('assets/')]
print("assets 文件数:", len(assets))
for i in assets[:12]:
    print("   ", i.filename, "%.1f KB" % (i.file_size / 1024))
py = [i for i in z.infolist() if i.filename.endswith(('.py', '.pyc'))]
print("打包的 python 文件数:", len(py))
print("APK 总大小: %.1f MB" % (sum(i.file_size for i in z.infolist()) / 1024 / 1024))
# 关键模块是否在包里
for need in ("jincomic",):
    pass
for mod in ("jmcomic/__init__.py", "lxml/__init__.py", "PIL/__init__.py", "PySide6/__init__.py",
            "curl_cffi/__init__.py", "shims/curl_cffi/__init__.py"):
    hit = any(mod in i.filename for i in z.infolist())
    print("   %-34s %s" % (mod, "✓" if hit else "✗"))
EOF

echo
echo "=== 拷贝构建日志 ==="
mkdir -p "$WIN/build_logs"
for f in "$WORK/logs/build_apk.log" "$WORK/logs/buildozer_full.log" "$WORK/logs/detached_build.log"; do
    [ -f "$f" ] && cp -f "$f" "$WIN/build_logs/" && echo "  $f -> $WIN/build_logs/"
done
ls -sh "$WIN"/*.apk 2>/dev/null
