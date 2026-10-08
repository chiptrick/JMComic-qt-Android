#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 把 p4a Qt bootstrap 里硬编码的 PYTHONOPTIMIZE=2 改成 1
#
# 为什么必须改（这是"登录报错、首页也报错"的真正根因，第二层）：
#   pythonforandroid/bootstraps/qt/.../PythonActivity.java 在 onCreate 里写死了
#       setEnvironmentVariable("PYTHONOPTIMIZE", "2");
#   于是 sys.flags.optimize == 2，而 pycryptodome 在 optimize==2 时会**主动**放弃
#   cffi 后端（它认为 -OO 下 pycparser 坏掉），回落到 ctypes 后端；而 ctypes 后端在
#   Android 上根本不可用：
#       ctypes.pythonapi.PyObject_GetBuffer
#       -> AttributeError: undefined symbol: PyObject_GetBuffer
#   因为 libpython 是被 RTLD_LOCAL 载入的，dlopen(NULL) 看不到 Python C API 符号。
#   结果 Crypto.Cipher.AES 永远不可用，禁漫所有接口响应（全是 AES 密文）都解不开。
#
# 为什么用 1 而不是 0：
#   -O(1) 同样会去掉 assert（和原来 -OO 行为一致，193 个 assert 不会突然生效），
#   但**保留 docstring**，cffi/pycparser 因此可用。
#   实测（venv311, cffi 2.0.0 + pycparser 2.14，与 APK 里完全相同的版本）：
#       python -OO -> backend=ctypes   (真机就是这条，ctypes 在 Android 上必炸)
#       python -O  -> backend=cffi     (AES 往返正常)
#   stdlib.zip 用的是 legacy 命名(module.pyc)，不受 optimize 变化影响。
set -uo pipefail
WORK="${WORK:-"$JM_WORK"}"
ANDROID="$WORK/src/android"

echo "=== 修改 p4a bootstraps 里的 PYTHONOPTIMIZE ==="
# 只改 qt bootstrap 就够，但把 sdl2/webview 等一起改掉更省事(反正这个项目只用 qt)
mapfile -t FILES < <(find \
    "$WORK/venv311/lib" "$WORK/p4a" "$ANDROID/.buildozer" \
    -name 'PythonActivity.java' -path '*org/kivy/android*' 2>/dev/null | sort -u)

if [ "${#FILES[@]}" -eq 0 ]; then
    echo "[FAIL] 一个 PythonActivity.java 都没找到 —— 补丁没生效，接口解密仍然会失败"
    exit 1
fi

changed=0
for f in "${FILES[@]}"; do
    before=$(grep -c 'PYTHONOPTIMIZE", "2"' "$f" 2>/dev/null || true)
    if [ "${before:-0}" -gt 0 ]; then
        sed -i 's/PYTHONOPTIMIZE", "2"/PYTHONOPTIMIZE", "1"/g' "$f"
        changed=$((changed + 1))
        printf '  已改 %s\n' "${f#$WORK/}"
    fi
done

echo "  改了 $changed 个文件(共 ${#FILES[@]} 个候选)"
echo "--- 校验 ---"
bad=0
for f in "${FILES[@]}"; do
    if grep -q 'PYTHONOPTIMIZE", "2"' "$f" 2>/dev/null; then
        printf '  [FAIL] 仍然是 2: %s\n' "${f#$WORK/}"
        bad=$((bad + 1))
    fi
done
if [ "$bad" -gt 0 ]; then
    echo "[FAIL] 还有 $bad 个文件没改过来"
    exit 1
fi
echo "  [ok] 所有副本都是 PYTHONOPTIMIZE=1"
# dist 里那份是 Gradle 真正编译的；它必须存在且已改
DISTJAVA=$(find "$ANDROID/.buildozer" -path '*dists/*/src/main/java/org/kivy/android/PythonActivity.java' 2>/dev/null | head -1)
if [ -n "$DISTJAVA" ]; then
    if grep -q 'PYTHONOPTIMIZE", "1"' "$DISTJAVA"; then
        echo "  [ok] dist 里那份也已改: ${DISTJAVA#$WORK/}"
    else
        echo "  [FAIL] dist 里那份没改，APK 里还会是 optimize=2"
        exit 1
    fi
else
    echo "  (还没有 dist 副本，本次会由 p4a 从已改过的 bootstrap 重新拷贝)"
fi
exit 0
