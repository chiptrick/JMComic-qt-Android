#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 让 buildozer 支持 android.add_libs_x86_64（幂等，重复执行无副作用）
#
# 背景
# ----
# buildozer 1.6.0 的 targets/android.py 里有一张固定的 add_libs 映射表：
#     ('android.add_libs_armeabi', 'armeabi'),
#     ('android.add_libs_armeabi_v7a', 'armeabi-v7a'),
#     ('android.add_libs_arm64_v8a', 'arm64-v8a'),
#     ('android.add_libs_x86', 'x86'),
#     ('android.add_libs_mips', 'mips')
# **没有 x86_64**。于是 android.add_libs_x86_64 写了也不会被读，dist/libs/x86_64
# 里不会出现我们的 .so —— APK 装上后 libsr_qnn.so / libonnxruntime.so 全缺，
# 超分后端直接"不可用"，而且日志里没有任何报错（静默丢库）。
#
# 为什么不改成 p4a recipe：buildozer 的这次拷贝发生在 build_package() 里，每次
# 打包都执行；而 recipe 有"已构建"标记，改了 libs 目录未必会重跑，容易出现
# "改了没生效，还以为是别的 bug"。改这张表是在同一位置补一行，行为可预期。
#
# 不改 arm64 的既有行为：只是往列表末尾加一项，arm64 构建走的还是原来那行。
set -uo pipefail
VPY="${JM_VPY:?}"
TARGET=$("$VPY" - <<'PY' 2>/dev/null
import os
import buildozer
print(os.path.join(os.path.dirname(buildozer.__file__), "targets", "android.py"))
PY
) || { echo "[error] 找不到已安装的 buildozer（先跑 wsl_build_apk.sh 的依赖安装）"; exit 1; }
[ -f "$TARGET" ] || { echo "[error] buildozer target 不存在: $TARGET"; exit 1; }
echo "buildozer target: $TARGET"

"$VPY" - "$TARGET" <<'PY'
import py_compile
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fp:
    src = fp.read()

if "android.add_libs_x86_64" in src:
    print("  = 已经支持 android.add_libs_x86_64，跳过")
    sys.exit(0)

anchor = "                ('android.add_libs_arm64_v8a', 'arm64-v8a'),"
if anchor not in src:
    print("  [error] 没找到 arm64-v8a 那一行，buildozer 版本结构变了，需人工检查")
    sys.exit(1)

added = anchor + "\n                ('android.add_libs_x86_64', 'x86_64'),"
src = src.replace(anchor, added, 1)

if not path.endswith(".orig") and not __import__("os").path.exists(path + ".orig"):
    with open(path + ".orig", "w", encoding="utf-8") as fp:
        fp.write(open(path, "r", encoding="utf-8").read())

with open(path, "w", encoding="utf-8") as fp:
    fp.write(src)

try:
    py_compile.compile(path, doraise=True)
except py_compile.PyCompileError as es:
    print("  [error] 补丁后语法错误: %s" % es)
    sys.exit(1)
print("  + 已在 add_libs 映射表里补上 ('android.add_libs_x86_64', 'x86_64')")
PY
rc=$?
[ "$rc" = "0" ] || exit $rc

# 立刻验证一遍：新进程里 import 一遍 buildozer 并确认表里真的能读到
"$VPY" - <<'PY'
import inspect
import buildozer.targets.android as target
src = inspect.getsource(target)
ok = "'android.add_libs_x86_64', 'x86_64'" in src
print("  验证: x86_64 条目存在 =", ok)
raise SystemExit(0 if ok else 1)
PY
