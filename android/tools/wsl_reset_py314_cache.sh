#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# CPython 3.14 迁移的一次性冷启动：清掉所有 3.11 时代的编译缓存
#
# 背景(见 android/README.md §3.10)：目标 Python 从 3.11.13 整机迁到 3.14.8 后，
# p4a/buildozer 的已编译产物全是绑死 libpython3.11 的，一个都不能复用：
#   * $JM_WORK/keep                 —— wsl_save_build_cache.sh 移出的 build/packages/dists
#   * src/android/.buildozer        —— 当前构建树的编译产物 + 下载缓存(packages)
#   * $JM_WORK/.buildozer           —— 旧 storage 的编译产物
# packages/ 里"与 Python 版本无关"的源码包(openssl/libffi/png 等)会被
# wsl_seed_from_old_storage.sh 复制回来，所以这里整目录删掉不心疼；
# CPython 3.14.8 源码包由 $JM_WORK/Python-3.14.8.tgz 兜底(见 seed 脚本)。
#
# 幂等：目录不存在就跳过。**执行后下一次构建是全量冷构建(约数小时)**，
# 仅在切换目标 Python 大版本时跑一次。
set -uo pipefail
W="${WORK:-"$JM_WORK"}"

echo "== 清 3.11 编译缓存(目标 Python 3.14 冷构建) =="
for d in \
    "$W/keep" \
    "$W/src/android/.buildozer" \
    "$W/.buildozer"
do
    if [ -e "$d" ]; then
        du -sh "$d" 2>/dev/null
        rm -rf "$d"
        echo "  已删 $d"
    else
        echo "  (不存在，跳过) $d"
    fi
done

echo
echo "== p4a recipe 版本核对(应为 3.14.8 / cffi 2.1.1) =="
R="$W/p4a/pythonforandroid/recipes"
grep -HnE "^    version = " \
    "$R/python3/__init__.py" "$R/hostpython3/__init__.py" "$R/cffi/__init__.py" \
    2>/dev/null || echo "  (recipe 未改版本？先跑 wsl_patch_p4a_versions.sh)"

echo
echo "== CPython 3.14.8 源码包兜底 =="
if [ -s "$W/Python-3.14.8.tgz" ]; then
    echo "  [ok] $W/Python-3.14.8.tgz ($(stat -c %s "$W/Python-3.14.8.tgz") 字节)"
else
    echo "  [缺] 没有 $W/Python-3.14.8.tgz —— p4a 走 ghproxy 下载容易断流，"
    echo "       建议从 https://www.python.org/ftp/python/3.14.8/ 放一份过来"
fi
echo "完成。下次 wsl_build_apk.sh 即全量冷构建。"
