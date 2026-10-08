#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 以非 root 用户(JM_USER，默认 uid=1000)再跑一次文件选择器回归测试。
#
# 为什么需要它：root(euid 0)会无视权限位，chmod 000 对 root 无效，
# 所以"真权限位"那条分支只有在普通用户下才算真正跑到。
# (主测试 host_test_file_dialog.py 里那部分用"让 os.scandir 抛 PermissionError"来
#  等价模拟真机上的权限墙，root 下也会跑；本脚本是额外的确认。)
#
# /root 是 0700：普通用户连解释器都执行不了。venv 里的 python3 只是指向
# "$JM_WORK/py311/bin/python3.11" 的**符号链接**，复制 venv 搬不走它，
# 所以这里用一个 wrapper 脚本（#!/bin/sh exec 真实解释器）代替 python3，
# 真正的进程镜像由 root 打开，之后再降权执行。
#
# 用法: wsl -u root -e bash -lc 'bash <repo>/android/tools/wsl_run_file_dialog_asuser.sh'
set -uo pipefail
REPO="${REPO:-"$JM_REPO"}"
REAL_PY="${REAL_PY:-"$JM_WORK/venv311/bin/python3"}"
USER_NAME="${USER_NAME:-${JM_USER}}"
WORK="${WORK:-/tmp/jmfd_asuser}"

rm -rf "$WORK"
mkdir -p "$WORK/android/tools"
cp -r "$REPO/src" "$WORK/src"
cp "$REPO/android/tools/host_test_file_dialog.py" "$WORK/android/tools/"

# wrapper：普通用户执行它，它 exec 真实 venv 解释器。
# 注意解释器路径要在**降权之后**才解析，所以用 `python3 -c` 把 exec 放到 wq159 进程里
# (由 root 先 fork 再 setuid，内核会在降权后的权限下解析那个 /root 路径 —— 会失败)，
# 因此改成：直接复制一份**真实解释器二进制**到 /tmp，再把 venv 的脚本路径指过去。
REAL_BIN="$(readlink -f "$REAL_PY")"
cp "$REAL_BIN" "$WORK/python3"
chmod 755 "$WORK/python3"

# PySide6 等 site-packages 是 venv 里的，先把 venv 复制出来
cp -a "$(dirname "$(dirname "$REAL_PY")")" "$WORK/venv311"
# pyvenv.cfg 的 home= 指向基础解释器的 bin 目录；它的 prefix 是上一级(py311)，
# 所以要从 prefix 那一级整棵复制到 /tmp，再把 home= 指过去。
BASE_BIN="$(sed -n 's/^home *= *//p' "$WORK/venv311/pyvenv.cfg" | head -1)"
BASE_PREFIX="$(dirname "$BASE_BIN")"
if [ -n "$BASE_BIN" ] && [ -d "$BASE_PREFIX" ]; then
    mkdir -p "$WORK/base$(dirname "$BASE_PREFIX")"
    cp -a "$BASE_PREFIX" "$WORK/base$BASE_PREFIX"
    sed -i "s#^home *= *.*#home = $WORK/base$BASE_BIN#" "$WORK/venv311/pyvenv.cfg"
fi
cat > "$WORK/py" <<EOF
#!/bin/sh
# PYTHONHOME 必须重新指到 /tmp 下的那份基础解释器：
# 解释器二进制里编死的 prefix 是 /root/...，普通用户读不到。
# 设了 PYTHONHOME 就找不到 venv 的 site-packages 了，所以显式加进 PYTHONPATH。
PYTHONHOME="$WORK/base$BASE_PREFIX" \\
PYTHONPATH="$WORK/venv311/lib/python3.11/site-packages" \\
    exec "$WORK/python3" "\$@"
EOF
chmod 755 "$WORK/py"
chmod -R a+rX "$WORK"

runuser -u "$USER_NAME" -- sh -c "cd '$WORK' && QT_QPA_PLATFORM=offscreen ./py android/tools/host_test_file_dialog.py" > "$WORK/out.log" 2>&1
code=$?
grep -v -e 'propagateSizeHints' -e 'support raise' "$WORK/out.log"
echo "非 root($USER_NAME) 退出码=$code"
exit "$code"
