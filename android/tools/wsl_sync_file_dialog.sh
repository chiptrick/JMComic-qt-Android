#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 同步"应用内文件选择器"改动的文件到 WSL 构建树，并做 py_compile 语法检查
# 用法: wsl -u root -e bash -lc '$JM_WORK/src/android/tools/wsl_sync_file_dialog.sh'
set -uo pipefail
W="${WORK:-"$JM_WORK"}"
REPO="${REPO:-"$JM_REPO"}"
SRC="$W/src"
PY="$W/venv311/bin/python3"
[ -x "$PY" ] || PY="$W/venv311/bin/python"

FILES=(
    src/tools/mobile_file_dialog.py
    src/view/tool/local_read_view.py
    src/view/tool/waifu2x_tool_view.py
    src/view/setting/setting_view.py
    src/view/download/download_dir_view.py
    src/view/nas/nas_add_view.py
    src/view/tool/batch_sr_tool_view.py
    src/view/read/read_view.py
    android/tools/host_test_file_dialog.py
)

failed=0
for f in "${FILES[@]}"; do
    mkdir -p "$SRC/$(dirname "$f")"
    if cp "$REPO/$f" "$SRC/$f"; then
        printf 'sync  %s\n' "$f"
    else
        printf 'FAIL  cp %s\n' "$f"
        failed=$((failed + 1))
    fi
done

echo
echo "===== py_compile (python 3.11，目标版本) ====="
cd "$SRC" || exit 1
if "$PY" -m py_compile "${FILES[@]}"; then
    echo "[ok] py_compile 通过"
else
    echo "[FAIL] py_compile 失败"
    failed=$((failed + 1))
fi

echo
echo "结果: 失败 $failed 项"
[ "$failed" -eq 0 ]
