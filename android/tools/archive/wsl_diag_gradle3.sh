#!/usr/bin/env bash
# 看这次失败是不是还是 gradle 下载/PKIX，以及 JAVA_TOOL_OPTIONS 是否传给了 gradle 子进程
set -uo pipefail
L=/root/jmcomic-build/logs/detached_build.log
echo "=== 失败相关 ==="
grep -nE "gradlew failed|PKIX|ValidatorException|trustStore|FAILURE:|What went wrong" "$L" | tail -8 | cut -c1-190
echo
echo "=== 日志里是否出现 JAVA_TOOL_OPTIONS ==="
grep -c 'JAVA_TOOL_OPTIONS' "$L"
grep -m2 'JAVA_TOOL_OPTIONS' "$L" | cut -c1-160
echo
echo "=== gradle 目录与 dists ==="
du -sh /root/.gradle 2>/dev/null
ls -la /root/.gradle/wrapper/dists 2>/dev/null | head -5
echo
echo "=== 日志最后 12 行 ==="
tail -c 1500 "$L" | tr '\r' '\n' | grep -vE '^\s*$' | tail -12 | cut -c1-170
