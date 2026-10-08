#!/usr/bin/env bash
# 取出 buildozer 调用的完整 p4a apk 命令，并核对 .buildozer/android/app 里是否是最新源码
set -uo pipefail
W=/root/jmcomic-build
A="$W/src/android"
T=/tmp/bz4.txt
tr '\r' '\n' < "$W/logs/buildozer_full.log" > "$T"

echo "=== 完整 p4a apk 命令 ==="
grep -nE "^# Run '.*pythonforandroid.toolchain apk" "$T" | tail -1 | sed 's/^[0-9]*://' | fold -w 200

echo
echo "=== 关键参数(拆开看) ==="
CMD=$(grep -E "^# Run '.*pythonforandroid.toolchain apk" "$T" | tail -1 | sed "s/^# Run '//; s/'$//")
echo "$CMD" | tr ' ' '\n' | grep -E '^--' | sed 's/^/  /'

echo
echo "=== .buildozer/android/app 是否包含最新改动 ==="
APP="$A/.buildozer/android/app"
for pair in \
    "app_src/tools/mobile_ui.py:_DrawerScrim" \
    "app_src/server/req.py:import urllib.request" \
    "app_src/server/server.py:import urllib.request" \
    "app_src/view/user/login_proxy_new_widget.py:import urllib.request" \
    "app_src/tools/platform_mobile.py:GetNativeLibDirs" \
    "shims/curl_cffi/requests/__init__.py:_GetCurlOpt" \
    "sr_qnn/__init__.py:_PreloadLibs" \
    "main.py:DumpDiagnostics" ; do
    f="${pair%%:*}"; pat="${pair##*:}"
    if [ -f "$APP/$f" ]; then
        n=$(grep -c "$pat" "$APP/$f" 2>/dev/null || echo 0)
        if [ "$n" -gt 0 ]; then printf '  [ok]   %-52s 命中 %s\n' "$f" "$n"
        else printf '  [陈旧] %-52s 未找到 "%s"\n' "$f" "$pat"; fi
    else
        printf '  [缺失] %s\n' "$f"
    fi
done

echo
echo "=== private app 目录里的模型 ==="
ls "$APP/sr_qnn/models/" 2>/dev/null | head -12 || echo "  (没有 models 目录!)"
echo "onnx 数量: $(ls "$APP/sr_qnn/models/"*.onnx 2>/dev/null | wc -l)"
