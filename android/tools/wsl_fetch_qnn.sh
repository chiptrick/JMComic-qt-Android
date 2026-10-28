#!/usr/bin/env bash
# 取高通 QNN 运行库：com.qualcomm.qti:qnn-runtime AAR(ORT 的 android-qnn AAR 依赖它)
#
# 产出 libs/arm64-v8a/ 下这批库(ORT 的 QNN EP 运行时按需 dlopen)：
#   libQnnHtp.so           backend_path 指的库(QnnInterface_getProviders)
#   libQnnSystem.so        QNN 系统接口(ORT 按 backend_path 的目录部分去找)
#   libQnnHtpV*Stub.so     CPU 侧与 DSP 通信的桩，按设备 HTP 架构选一个
#   libQnnHtpV*Skel.so     DSP 侧执行体(ELF32/Hexagon，由 ADSP 加载)
#   libQnnHtpPrepare.so / libQnnGpu.so / libQnnDsp*.so   可选(默认一并带上)
#
# 为什么要单独一个脚本：android/libs/ 被 .gitignore 与 tools/wsl_sync.sh 同时排除，
# 不会跟着仓库走。**没有本步骤就没有 NPU**，而构建脚本只做校验(见 qnn_guard.sh)。
#
# 用法：
#   bash android/tools/wsl_fetch_qnn.sh                      # 写 $JM_WORK/src/android/libs/arm64-v8a
#   bash android/tools/wsl_fetch_qnn.sh --libs-dir DIR       # 写指定目录(仓库直构时用)
#   QNN_VER=2.44.0 bash android/tools/wsl_fetch_qnn.sh --force   # 换版本 / 强制重下
#   bash android/tools/wsl_fetch_qnn.sh --verify-only        # 只校验，不下载
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QNN_VER="${QNN_VER:-2.42.0}"
FORCE=0
VERIFY_ONLY=0
# 默认目标：WSL 构建树(历史行为)；给了 --libs-dir 就用给的
LIBS="${LIBS_DIR:-$JM_WORK/src/android/libs/arm64-v8a}"
# 下载缓存/日志目录：优先用 $WORK/$JM_WORK(WSL 里是 ext4)，不可写就退到仓库内
# 的 android/.work(gitignore 里有)，这样在裸 Linux/macOS 上直构也能跑。
CACHE_ROOT="${WORK:-${JM_WORK:-}}"
if [ -z "$CACHE_ROOT" ] || ! mkdir -p "$CACHE_ROOT" 2>/dev/null; then
    CACHE_ROOT="$(cd "$HERE/.." && pwd)/.work"
    mkdir -p "$CACHE_ROOT" 2>/dev/null || true
fi
WORK="$CACHE_ROOT"

while [ $# -gt 0 ]; do
    case "$1" in
        --libs-dir=*) LIBS="${1#--libs-dir=}" ;;
        --libs-dir)   LIBS="${2:-}"; shift ;;
        --version=*)  QNN_VER="${1#--version=}" ;;
        --version)    QNN_VER="${2:-}"; shift ;;
        --force)      FORCE=1 ;;
        --verify-only) VERIFY_ONLY=1 ;;
        -h|--help)
            sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "未知参数: $1(见 --help)" >&2; exit 2 ;;
    esac
    shift
done
[ -n "$LIBS" ] || { echo "[error] --libs-dir 不能为空" >&2; exit 2; }

PY="${PYTHON_BIN:-python3}"
MANIFEST="$HERE/qnn_manifest.py"
VERIFY=("$PY" "$MANIFEST" verify --libs-dir "$LIBS" --abi arm64-v8a)

mkdir -p "$LIBS"
if [ "$VERIFY_ONLY" = "1" ]; then
    "${VERIFY[@]}"
    exit $?
fi

mkdir -p "$WORK/tools" "$WORK/logs"
exec > >(tee -a "$WORK/logs/fetch_qnn.log") 2>&1

BASE="https://repo1.maven.org/maven2/com/qualcomm/qti/qnn-runtime/$QNN_VER"
AAR="$WORK/tools/qnn-runtime-$QNN_VER.aar"
echo "===== [$(date +%T)] 下载 qnn-runtime $QNN_VER ====="
echo "目标目录: $LIBS"
if [ "$FORCE" = "1" ]; then
    rm -f "$AAR"
fi
[ -s "$AAR" ] || curl -sSL --retry 3 -o "$AAR" "$BASE/qnn-runtime-$QNN_VER.aar" \
    || { echo "[error] 下载失败: $BASE/qnn-runtime-$QNN_VER.aar(检查 QNN_VER 或网络)" >&2; exit 1; }
ls -sh "$AAR"

# AAR 里 .so 的落点是 jni/<abi>/（个别版本在 libs/ 或根下），先看一眼再解
"$PY" - "$AAR" <<'EOF'
import sys, zipfile, collections
z = zipfile.ZipFile(sys.argv[1])
names = z.namelist()
print("总条目:", len(names))
print("顶层:", dict(collections.Counter(n.split('/')[0] for n in names)))
so = [n for n in names if n.endswith('.so')]
print("含 .so 的目录:", sorted({n.rsplit('/', 1)[0] for n in so}) or "<无>")
EOF

echo "===== [$(date +%T)] 解包 arm64-v8a 运行库 ====="
rm -rf "$WORK/tools/qnnaar" && mkdir -p "$WORK/tools/qnnaar"
"$PY" -m zipfile -e "$AAR" "$WORK/tools/qnnaar"

# 兼容三种落点：jni/<abi>/、libs/<abi>/、<abi>/
COPIED=0
for rel in "jni/arm64-v8a" "libs/arm64-v8a" "arm64-v8a"; do
    dir="$WORK/tools/qnnaar/$rel"
    [ -d "$dir" ] || continue
    # 用 find 而不是 ls：glob 不匹配时 ls 返回非 0，配合 pipefail 会让整个脚本
    # 在这一步无声退出(踩过一次：库明明解开了，脚本却 "失败")。
    n=$(find "$dir" -maxdepth 1 -name '*.so' 2>/dev/null | wc -l | tr -d ' ')
    [ "$n" -gt 0 ] || continue
    cp -f "$dir"/*.so "$LIBS/" || { echo "[error] 拷贝失败: $dir -> $LIBS" >&2; exit 1; }
    echo "  从 $rel 拷入 $n 个 .so"
    COPIED=$((COPIED + n))
done
if [ "$COPIED" = "0" ]; then
    echo "[error] AAR 里没找到任何 .so(版本/打包结构变了？上方已列出实际目录)" >&2
    exit 1
fi
# 记下版本，便于事后核对"这个包是用哪版 QNN 打的"
printf '%s\n' "$QNN_VER" > "$LIBS/.qnn-version"

# 架构与配对校验：Stub 缺 Skel、x86_64 混入、文件被截断，都在这里拦住
echo "===== [$(date +%T)] 校验 ====="
if ! "${VERIFY[@]}"; then
    echo "[error] QNN 库校验未通过，见上方 [致命] 项" >&2
    exit 1
fi
echo "===== [$(date +%T)] 完成 ====="
