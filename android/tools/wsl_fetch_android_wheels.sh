#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 下载并校验目标 ABI 需要的 android wheel（JM_ABI=arm64-v8a|x86_64）
#
#   * Qt 6.12.0 PySide6 / shiboken6（cp310-abi3，实际 NEEDED libpython3.14.so）
#       真机   -> pyside6-6.12.0-6.12.0-cp310-abi3-android_aarch64.whl
#       模拟器 -> pyside6-6.12.0-6.12.0-cp310-abi3-android_x86_64.whl
#   * curl_cffi 0.16.3 cp314（官方只发 arm64-v8a；x86_64 上没有，改用
#     android/shims/curl_cffi 纯 python 垫片，见 patch_buildozer_spec.py）
#
# 幂等 + 防残片：sha256 不匹配就删掉重下（踩过的坑：86MB 下载中断留下半截文件，
# 下次被当成"已存在"跳过，构建时 unzip 才发现坏了）。
# arm64 的两个 wheel 有上游公布的 sha256；x86_64 没有公布值，改为"下载后核对
# .so 的 NEEDED 必须是 libpython3.14.so"来兜底（同版本 Qt 的 ABI 契约）。
# 可用 JM_WHEEL_DIR 覆盖存放目录（默认 $JM_WORK/src/android/wheels）。
set -uo pipefail
DIR="${JM_WHEEL_DIR:-$JM_WORK/src/android/wheels}"
TAG="${JM_WHEEL_TAG:?需要 env.sh 提供的 JM_WHEEL_TAG}"
QT_VER="${QT_VER:-6.12.0}"
mkdir -p "$DIR"
cd "$DIR" || exit 1

Fetch() {
    local name="$1" want="$2"; shift 2
    local got
    # 切换 ABI 后另一个架构的 wheel 被归档在 archive/ 里；先取回，别重复下 90MB
    if [ ! -s "$name" ] && [ -s "archive/$name" ]; then
        mv -f "archive/$name" "$name"
        echo "  <- 从 archive/ 取回 $name"
    fi
    if [ -s "$name" ]; then
        got=$(sha256sum "$name" | cut -d' ' -f1)
        # want 为空(x86_64 没有上游公布的 sha256)时，至少要确认是完整 zip：
        # 下载被中断留下的半截文件也"存在"，只看 -s 会把它当成品。
        if [ -z "$want" ] && ! "$JM_VPY" -c "import sys,zipfile; sys.exit(0 if zipfile.ZipFile(sys.argv[1]).testzip() is None else 1)" "$name" 2>/dev/null; then
            echo "  ! $name 不是完整 zip(残片)，删除重下"
            rm -f "$name"
        elif [ -z "$want" ] || [ "$got" = "$want" ]; then
            echo "  = $name 已存在（sha256 $got）"
            return 0
        fi
        if [ -s "$name" ]; then
            echo "  ! $name 已存在但 sha256 不匹配(可能是残片)，删除重下: $got"
            rm -f "$name"
        fi
    fi
    for base in "$@"; do
        for try in 1 2 3; do
            echo "  > $base$name (第 $try 次)"
            # --speed-limit/--speed-time：镜像站经常"连得上但只有十几 KB/s"
            # （jaist 实测 12KB/s，86MB 要下 2 小时），低于 200KB/s 持续 20 秒就换下一个。
            curl -fL --retry 2 --connect-timeout 20 --max-time 1200 \
                --speed-limit 200000 --speed-time 20 -o "$name" "$base$name" || {
                rm -f "$name"; sleep 3; continue
            }
            got=$(sha256sum "$name" | cut -d' ' -f1)
            if [ -z "$want" ]; then
                # 没有预期 sha256 时，以"zip 结构完整"作为下载成功的判据
                if "$JM_VPY" -c "import sys,zipfile; sys.exit(0 if zipfile.ZipFile(sys.argv[1]).testzip() is None else 1)" "$name" 2>/dev/null; then
                    echo "  [ok] $name $(stat -c %s "$name") 字节 sha256=$got"
                    return 0
                fi
                echo "  ! zip 不完整(下载被截断)，删除重试"
                rm -f "$name"
                continue
            fi
            if [ "$got" = "$want" ]; then
                echo "  [ok] $name $(stat -c %s "$name") 字节 sha256=$got"
                return 0
            fi
            echo "  ! sha256 不匹配，删除: $got"
            rm -f "$name"
        done
    done
    echo "[FAIL] 所有镜像都拿不到 $name"
    return 1
}

QT_PYSIDE="https://download.qt.io/official_releases/QtForPython/pyside6/"
QT_SHIBO="https://download.qt.io/official_releases/QtForPython/shiboken6/"
PYPI="https://files.pythonhosted.org/packages/"

PYSIDE_WHEEL="pyside6-${QT_VER}-${QT_VER}-cp310-abi3-${TAG}.whl"
SHIBO_WHEEL="shiboken6-${QT_VER}-${QT_VER}-cp310-abi3-${TAG}.whl"

# 上游公布的 sha256（只有 arm64 有；x86_64 传空串 -> 只做 NEEDED 校验）
PYSIDE_SHA=""
SHIBO_SHA=""
if [ "$TAG" = "android_aarch64" ] && [ "$QT_VER" = "6.12.0" ]; then
    PYSIDE_SHA="2cb8352ae6cd091c9f5e11d7bc4ba3bf54088548f63cd804adfdffe5c97c5eb2"
    SHIBO_SHA="dc5dc4ca86c88327575a9d338c678a8f81f859a25a4dc0e6a539e465ab881660"
fi

echo "== 目标 ABI=$JM_ABI  平台标签=$TAG  存放目录=$DIR =="
Fetch "$PYSIDE_WHEEL" "$PYSIDE_SHA" \
      "https://mirrors.tuna.tsinghua.edu.cn/qt/official_releases/QtForPython/pyside6/" \
      "https://mirrors.ustc.edu.cn/qtproject/official_releases/QtForPython/pyside6/" \
      "https://mirror.sjtu.edu.cn/qt/official_releases/QtForPython/pyside6/" \
      "https://ftp.fau.de/qtproject/official_releases/QtForPython/pyside6/" \
      "https://mirror.accum.se/mirror/qt.io/qtproject/official_releases/QtForPython/pyside6/" \
      "https://ftp.jaist.ac.jp/pub/qtproject/official_releases/QtForPython/pyside6/" \
      "$QT_PYSIDE" || exit 1

Fetch "$SHIBO_WHEEL" "$SHIBO_SHA" \
      "https://mirrors.tuna.tsinghua.edu.cn/qt/official_releases/QtForPython/shiboken6/" \
      "https://mirrors.ustc.edu.cn/qtproject/official_releases/QtForPython/shiboken6/" \
      "https://mirror.sjtu.edu.cn/qt/official_releases/QtForPython/shiboken6/" \
      "https://ftp.fau.de/qtproject/official_releases/QtForPython/shiboken6/" \
      "https://mirror.accum.se/mirror/qt.io/qtproject/official_releases/QtForPython/shiboken6/" \
      "https://ftp.jaist.ac.jp/pub/qtproject/official_releases/QtForPython/shiboken6/" \
      "$QT_SHIBO" || exit 1

if [ "$JM_ABI" = "arm64-v8a" ]; then
    Fetch "curl_cffi-0.16.3-cp314-cp314-android_24_arm64_v8a.whl" \
          "0c8b70191dc88ea770a5c39d7e213bff1606e248c13566777e6527f0d8cf96ec" \
          "${PYPI}fb/f4/3dedff1a31c93a9b18acaa346e23832c29bc18075138e90e9af795188e5e/" || exit 1
else
    echo "  · x86_64 没有官方 curl_cffi android wheel -> 使用 android/shims 纯 python 垫片"
fi

echo
echo "=== 核对 .so 的 NEEDED(必须是 libpython3.14.so) ==="
# 只看关键库：整个 wheel 有几百个 .so，逐个 readelf 会把日志刷成几万行，
# 而这几个就能证明"这个 wheel 是给目标 CPython 3.14 编的"。
NDKBIN="$JM_WORK/android-sdk/ndk/26.1.10909125/toolchains/llvm/prebuilt/linux-x86_64/bin"
PY="$JM_VPY"
for w in "$DIR/$PYSIDE_WHEEL" "$DIR/$SHIBO_WHEEL"; do
    echo "--- $(basename "$w") ---"
    tmp=$(mktemp -d)
    "$PY" -c "
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
keys = ('libpyside6.abi3.so', 'pyside6/libshiboken6.abi3.so',
        'libQt6Core_', '_wrapper.abi3.so')
for n in z.namelist():
    if n.endswith('.so') and any(k in n for k in keys):
        z.extract(n, sys.argv[2])
        print('   ', n)
" "$w" "$tmp"
    for s in $(find "$tmp" -name "*.so" | head -6); do
        echo "      NEEDED: $("$NDKBIN/llvm-readelf" -d "$s" | grep NEEDED | sed 's/.*\[\(.*\)\]/\1/' | tr '\n' ' ')"
    done
    rm -rf "$tmp"
done

echo
echo "=== 归档其它平台的 wheel ==="
# wsl_build_apk.sh 用 `ls wheels/pyside6-*-<TAG>.whl` 选 wheel，但同一目录里同时存在
# arm64 / x86_64 两套时，任何按字母序的 glob 都可能选错；把非当前 ABI 的移进 archive/
# （不删，切换 ABI 时再用 mv 换回来即可）。
mkdir -p "$DIR/archive"
for old in "$DIR"/pyside6-*.whl "$DIR"/shiboken6-*.whl; do
    [ -f "$old" ] || continue
    case "$(basename "$old")" in
        "$PYSIDE_WHEEL"|"$SHIBO_WHEEL") ;;
        *) mv -f "$old" "$DIR/archive/"
           echo "  归档 $(basename "$old")" ;;
    esac
done

echo
echo "=== 目录 ==="
ls -la "$DIR"
