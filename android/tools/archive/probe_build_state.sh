#!/usr/bin/env bash
# 构建到底跑没跑完、跑了几轮、产出的 APK 各是什么时间
set -u
echo "== 还在跑吗 =="
ps -eo pid,etime,cmd | grep -E "wsl_build_apk|pythonforandroid|buildozer" | grep -v grep | head -5
echo "== detached_build.log 的关键节点 =="
grep -nE "=====|packaging done|Android package|BUILD|阶段|FAILED|Traceback" /root/jmcomic-build/logs/detached_build.log | tail -30
echo "== log 尾部 =="
tail -5 /root/jmcomic-build/logs/detached_build.log
echo "== 产出 APK =="
find /root/jmcomic-build/src/android -name "*.apk" -printf "%T@ %TY-%Tm-%Td %TH:%TM  %s  %p\n" 2>/dev/null | sort -n | tail -6
echo "== Windows 侧 APK =="
ls -la /path/to/JMComic-qt/android/*.apk
