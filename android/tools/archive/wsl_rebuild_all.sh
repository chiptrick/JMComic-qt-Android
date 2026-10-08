#!/usr/bin/env bash
# 一条链：重编原生库(含宿主测试) -> 重打 APK
# 用于改了 sr_qnn.cpp 之后一次性产出新包
set -uo pipefail
T=/path/to/JMComic-qt/android/tools
echo "===== [$(date +%T)] A. 原生库 ====="
bash "$T/wsl_build_native.sh"
echo "===== [$(date +%T)] A 结束, 开始 APK ====="
bash "$T/wsl_build_apk.sh"
echo "===== [$(date +%T)] 全部结束 ====="
