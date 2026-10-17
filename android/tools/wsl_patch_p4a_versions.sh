#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 把 p4a 的 recipe 版本切到"迁移 CPython 3.14 + 官方 curl_cffi android wheel"所需：
#
#   python3 / hostpython3  3.11.13 -> 3.14.8
#       curl_cffi 0.16.3 的 cp314 wheel 里 curl_cffi/_wrapper.abi3.so 是
#       `NEEDED libpython3.14.so`；Qt 6.12.0 的 abi3 android wheel 的
#       libshiboken6.abi3.so 同样是 `NEEDED libpython3.14.so` —— 两边都绑死
#       目标 CPython 大版本，所以整个 app 只能迁到 3.14。
#   cffi  2.0.0 -> 2.1.1
#       curl_cffi 运行时 `import _cffi_backend`；cffi 2.0.0 不支持 3.14，
#       2.1.1 才声明 3.14/3.15(classifiers)。
#
# 只改 recipe 的 version 属性(url 都是 {version} 占位)，patch 列表不变；
# 幂等：已经是目标值就不再动。可用 JM_PY_VERSION / JM_CFFI_VERSION 覆盖。
set -uo pipefail
PY_VERSION="${JM_PY_VERSION:-3.14.8}"
CFFI_VERSION="${JM_CFFI_VERSION:-2.1.1}"
R="$JM_WORK/p4a/pythonforandroid/recipes"

SetVer() {
    local file="$1" want="$2" label="$3"
    if [ ! -f "$file" ]; then
        echo "[FAIL] 缺少 $file"
        return 1
    fi
    local cur
    cur=$(grep -E "^    version = " "$file" | head -1 | sed "s/^    version = '\(.*\)'.*/\1/")
    if [ "$cur" = "$want" ]; then
        echo "  = $label 已是 $want"
    else
        sed -i "s/^    version = '.*'/    version = '$want'/" "$file"
        echo "  ~ $label: $cur -> $want"
    fi
}

echo "== p4a recipe 版本(目标 CPython $PY_VERSION / cffi $CFFI_VERSION) =="
SetVer "$R/python3/__init__.py" "$PY_VERSION" "python3" || exit 1
SetVer "$R/hostpython3/__init__.py" "$PY_VERSION" "hostpython3" || exit 1
SetVer "$R/cffi/__init__.py" "$CFFI_VERSION" "cffi" || exit 1

echo
echo "--- 核对 ---"
grep -HnE "^    version = " "$R/python3/__init__.py" "$R/hostpython3/__init__.py" "$R/cffi/__init__.py"
