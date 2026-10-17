#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 下载并校验"迁移 CPython 3.14 + 原生 curl_cffi"所需的三个 android wheel：
#   * Qt 6.12.0 PySide6 / shiboken6(cp310-abi3，实际 NEEDED libpython3.14.so)
#   * curl_cffi 0.16.3 cp314(官方 android_24_arm64_v8a，静态编入 BoringSSL +
#     ngtcp2/nghttp3(HTTP/3) + ECH)
#
# 幂等 + 防残片：sha256 不匹配就删掉重下(踩过的坑：86MB 下载中断留下半截文件，
# 下次被当成"已存在"跳过，构建时 unzip 才发现坏了)。
# 可用 JM_WHEEL_DIR 覆盖存放目录(默认 $JM_WORK/src/android/wheels)。
set -uo pipefail
DIR="${JM_WHEEL_DIR:-$JM_WORK/src/android/wheels}"
mkdir -p "$DIR"
cd "$DIR" || exit 1

Fetch() {
    local name="$1" want="$2"; shift 2
    local got
    if [ -s "$name" ]; then
        got=$(sha256sum "$name" | cut -d' ' -f1)
        if [ "$got" = "$want" ]; then
            echo "  = $name 已存在且校验通过"
            return 0
        fi
        echo "  ! $name 已存在但 sha256 不匹配(可能是残片)，删除重下: $got"
        rm -f "$name"
    fi
    for base in "$@"; do
        for try in 1 2 3; do
            echo "  > $base$name (第 $try 次)"
            curl -fL --retry 2 --connect-timeout 20 --max-time 1800 -o "$name" "$base$name" || {
                rm -f "$name"; sleep 3; continue
            }
            got=$(sha256sum "$name" | cut -d' ' -f1)
            if [ "$got" = "$want" ]; then
                echo "  [ok] $name $(stat -c %s "$name") 字节"
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

echo "== 下载 android wheel 到 $DIR =="
# Qt 6.12.0 abi3：cp310-abi3 标签但 .so 绑定 libpython3.14.so(Qt 用 3.14 构建 android 包)
Fetch "pyside6-6.12.0-6.12.0-cp310-abi3-android_aarch64.whl" \
      "2cb8352ae6cd091c9f5e11d7bc4ba3bf54088548f63cd804adfdffe5c97c5eb2" \
      "https://ftp.jaist.ac.jp/pub/qtproject/official_releases/QtForPython/pyside6/" \
      "https://mirror.accum.se/mirror/qt.io/qtproject/official_releases/QtForPython/pyside6/" \
      "https://ftp.fau.de/qtproject/official_releases/QtForPython/pyside6/" \
      "$QT_PYSIDE" || exit 1

Fetch "shiboken6-6.12.0-6.12.0-cp310-abi3-android_aarch64.whl" \
      "dc5dc4ca86c88327575a9d338c678a8f81f859a25a4dc0e6a539e465ab881660" \
      "https://ftp.jaist.ac.jp/pub/qtproject/official_releases/QtForPython/shiboken6/" \
      "https://mirror.accum.se/mirror/qt.io/qtproject/official_releases/QtForPython/shiboken6/" \
      "https://ftp.fau.de/qtproject/official_releases/QtForPython/shiboken6/" \
      "$QT_SHIBO" || exit 1

Fetch "curl_cffi-0.16.3-cp314-cp314-android_24_arm64_v8a.whl" \
      "0c8b70191dc88ea770a5c39d7e213bff1606e248c13566777e6527f0d8cf96ec" \
      "${PYPI}fb/f4/3dedff1a31c93a9b18acaa346e23832c29bc18075138e90e9af795188e5e/" || exit 1

echo
echo "=== 核对 .so 的 NEEDED(必须是 libpython3.14.so) ==="
NDKBIN="$JM_WORK/android-sdk/ndk/26.1.10909125/toolchains/llvm/prebuilt/linux-x86_64/bin"
PY="$JM_WORK/venv311/bin/python"
for w in "$DIR"/pyside6-6.12.0*.whl "$DIR"/shiboken6-6.12.0*.whl "$DIR"/curl_cffi-0.16.3*.whl; do
    echo "--- $(basename "$w") ---"
    tmp=$(mktemp -d)
    "$PY" -c "
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
for n in z.namelist():
    if n.endswith('.so'):
        z.extract(n, sys.argv[2])
        print('   ', n)
" "$w" "$tmp"
    for s in $(find "$tmp" -name "*.so"); do
        echo "      NEEDED: $("$NDKBIN/llvm-readelf" -d "$s" | grep NEEDED | sed 's/.*\[\(.*\)\]/\1/' | tr '\n' ' ')"
    done
    rm -rf "$tmp"
done

echo
echo "=== 归档旧版本 Qt wheel ==="
# wsl_build_apk.sh 用 `ls wheels/pyside6-*-android_aarch64.whl | head -1` 选 wheel，
# 字符串排序 6.11.2 < 6.12.0 —— 旧 wheel 留在目录里就会被继续选中(还是 cp311)。
# 移进 archive/ 子目录(不删)，保证目录里只有当前目标版本。
mkdir -p "$DIR/archive"
for old in "$DIR"/pyside6-*.whl "$DIR"/shiboken6-*.whl; do
    [ -f "$old" ] || continue
    case "$(basename "$old")" in
        pyside6-6.12.0-6.12.0-cp310-abi3-android_aarch64.whl|\
        shiboken6-6.12.0-6.12.0-cp310-abi3-android_aarch64.whl) ;;
        *) mv -f "$old" "$DIR/archive/"
           echo "  归档 $(basename "$old")" ;;
    esac
done

echo
echo "=== 目录 ==="
ls -la "$DIR"
