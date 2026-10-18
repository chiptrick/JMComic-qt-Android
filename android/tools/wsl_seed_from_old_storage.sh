#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 把已下载的源码包灌进当前 storage 的 packages 目录，让 p4a 跳过联网下载
#
# 背景：ghproxy 镜像在下载 CPython 3.11.13(27MB) 时会中途断流
# (http.client.IncompleteRead)，导致 hostpython3/python3 recipe 失败。
# 上一个会话的产物还留在另一处 storage 目录里，直接复用最稳妥。
#
# 用法: bash wsl_seed_from_old_storage.sh
set -uo pipefail
# .mark-* 是隐藏文件，dotglob 才能被 * 匹配到(p4a 正是靠它判断"已下载完成")
shopt -s dotglob
W="${WORK:-"$JM_WORK"}"
ABI="${JM_ABI:-arm64-v8a}"
DST="$W/src/android/.buildozer/android/platform/build-$ABI/packages"
# 源码包(CPython/openssl/libffi/sqlite)与架构无关，可以直接复用 arm64 目录里已经
# 下好的那份 —— x86_64 第一次构建不用再赌 ghproxy 的 27MB 断流。
# 候选三处：当前 storage、被 save 移出去的 keep-arm64-v8a、(旧布局的).buildozer
OLD=""
if [ "$ABI" != "arm64-v8a" ]; then
    for cand in \
        "$W/src/android/.buildozer/android/platform/build-arm64-v8a/packages" \
        "$W/keep-arm64-v8a/packages" \
        "$W/.buildozer/android/platform/build-arm64-v8a/packages" ; do
        if [ -d "$cand" ]; then OLD="$cand"; break; fi
    done
else
    OLD="$W/.buildozer/android/platform/build-arm64-v8a/packages"
fi
echo "源码包来源: ${OLD:-<没有>}"
# CPython 3.14.8(目标 Python 整机迁移 3.14，见 tools/wsl_patch_p4a_versions.sh)
LOCAL_PY="$W/Python-3.14.8.tgz"
PY_TAG="v3.14.8.tar.gz"

# p4a 会用到的包(源码包与 Python 版本无关的可以复用旧 storage)
PKGS="hostpython3 python3 openssl libffi sqlite3 png jpeg freetype Pillow lxml pycryptodome"

mkdir -p "$DST"
echo "=== 从旧 storage 复制 ==="
echo "源: $OLD"
copied=0
if [ -d "$OLD" ]; then
    for d in "$OLD"/*/; do
        name=$(basename "$d")
        mkdir -p "$DST/$name"
        for f in "$d"*; do
            [ -f "$f" ] || continue
            cp -f "$f" "$DST/$name/" && copied=$((copied + 1))
        done
    done
    echo "复制了 $copied 个文件"
else
    echo "(旧 storage 不存在，跳过)"
fi

# 3.11 时代的 CPython 源码包对 3.14 构建没用(文件名不同不会被命中)，
# 留着只会混淆，清掉。
for pkg in hostpython3 python3; do
    if [ -e "$DST/$pkg/v3.11.13.tar.gz" ] || [ -e "$DST/$pkg/.mark-v3.11.13.tar.gz" ]; then
        rm -f "$DST/$pkg/v3.11.13.tar.gz" "$DST/$pkg/.mark-v3.11.13.tar.gz"
        echo "已清掉 $pkg/v3.11.13.tar.gz(3.11 时代残留)"
    fi
done

echo
echo "=== 兜底：本地 CPython-3.14.8 源码包 ==="
if [ -f "$LOCAL_PY" ]; then
    for pkg in hostpython3 python3; do
        mkdir -p "$DST/$pkg"
        # p4a 期望的文件名是 v3.14.8.tar.gz(ghproxy 上的 tag 包名)
        if [ ! -s "$DST/$pkg/$PY_TAG" ] || \
           [ "$(stat -c%s "$DST/$pkg/$PY_TAG" 2>/dev/null || echo 0)" -lt 20000000 ]; then
            cp -f "$LOCAL_PY" "$DST/$pkg/$PY_TAG"
            touch "$DST/$pkg/.mark-$PY_TAG"
            echo "  已用本地源码包补齐 $pkg/$PY_TAG"
        fi
    done
else
    echo "  (没有 $LOCAL_PY —— 建议从 python.org 下载后放到该路径，"
    echo "   否则 p4a 走 ghproxy 下载 27MB 容易中途断流)"
fi

echo
echo "=== 校验(非 mark 文件必须有同名 .mark- 才算下载完成) ==="
bad=0
for pkg in $PKGS; do
    dir="$DST/$pkg"
    if [ ! -d "$dir" ]; then
        printf '  [缺失] %-14s 目录不存在\n' "$pkg"
        bad=$((bad + 1))
        continue
    fi
    for f in "$dir"/*; do
        base=$(basename "$f")
        case "$base" in .mark-*) continue ;; esac
        size=$(stat -c%s "$f" 2>/dev/null || echo 0)
        if [ -f "$dir/.mark-$base" ]; then
            printf '  [ok]   %-14s %-28s %10d bytes\n' "$pkg" "$base" "$size"
        else
            printf '  [缺mark] %-12s %-28s %10d bytes (会被重新下载)\n' "$pkg" "$base" "$size"
            bad=$((bad + 1))
        fi
    done
done
echo
echo "有问题的条目: $bad"
[ "$bad" -eq 0 ]
