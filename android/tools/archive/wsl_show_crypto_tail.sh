#!/usr/bin/env bash
# 取出 pycryptodome 失败链的完整尾部(最终异常那几行)
set -uo pipefail
ADB=adb
PKG=org.jmcomic.jmcomic
S=DEVICE_SERIAL_HERE
LOG=$("$ADB" -s "$S" shell "run-as $PKG sh -c 'ls -t files/state/jmcomic-qt/logs/*.log | head -1'" | tr -d '\r')
echo "日志: $LOG"
"$ADB" -s "$S" shell "run-as $PKG cat $LOG" \
  | tr -d '\r' \
  | grep -n -A 30 '_raw_api.py", line 173' \
  | head -70
