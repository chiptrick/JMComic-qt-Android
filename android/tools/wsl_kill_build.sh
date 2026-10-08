#!/usr/bin/env bash
# 停掉正在跑的 buildozer/p4a 构建
pkill -f 'buildozer android' 2>/dev/null || true
pkill -f pythonforandroid.toolchain 2>/dev/null || true
sleep 4
echo "--- 残留构建进程 ---"
ps -eo pid,etime,cmd 2>/dev/null | grep -E 'buildozer|pythonforandroid|gradle' | grep -v grep | head -5
echo "--- 检查结束 ---"
