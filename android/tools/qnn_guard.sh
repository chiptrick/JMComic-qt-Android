#!/usr/bin/env bash
# QNN 运行库闸门：打包前确认 libs/<abi> 里真的有 NPU 运行库，没有就（可选）自动补
#
# 为什么要有这道闸：patch_buildozer_spec.py 的 add_libs 是**按目录 glob** 生成的，
# libs/<abi> 里没有 libQnn*.so 时它只是少写几条 —— buildozer 全程成功，APK 里就是
# 没有 NPU 运行库。装到真机上 QNN EP 起不来，超分静默退回 CPU(单块 0.4s、整页数十秒)，
# 界面只提示"超分未使用 NPU"。历史事故就是这样：日志里一个 error 都没有。
#
# 用法：
#   bash android/tools/qnn_guard.sh --android android --abi arm64-v8a
#   bash android/tools/qnn_guard.sh --android android --abi arm64-v8a --auto-fetch 0
#
# 环境变量：
#   JM_QNN=0        显式声明"这个 arm64 包不要 NPU"(跳过校验，用于排障对照包)
#   QNN_AUTO_FETCH  1(默认)=缺库时自动跑 wsl_fetch_qnn.sh；0=只报错不动网
#   QNN_VER         传给 wsl_fetch_qnn.sh 的 QNN 版本
#
# 退出码：0 通过(或该 ABI 不需要 QNN)；1 缺库且无法补齐
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID="$(cd "$HERE/.." && pwd)"
ABI="${JM_ABI:-arm64-v8a}"
AUTO_FETCH="${QNN_AUTO_FETCH:-1}"

while [ $# -gt 0 ]; do
    case "$1" in
        --android) ANDROID="${2:-}"; shift ;;
        --android=*) ANDROID="${1#--android=}" ;;
        --abi) ABI="${2:-}"; shift ;;
        --abi=*) ABI="${1#--abi=}" ;;
        --auto-fetch) AUTO_FETCH="${2:-1}"; shift ;;
        --auto-fetch=*) AUTO_FETCH="${1#--auto-fetch=}" ;;
        -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "[qnn-guard] 未知参数: $1" >&2; exit 2 ;;
    esac
    shift
done

log()  { printf '\033[1;36m[qnn-guard]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[qnn-guard]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[qnn-guard]\033[0m %s\n' "$*" >&2; }

LIBS="$ANDROID/libs/$ABI"
MANIFEST="$HERE/qnn_manifest.py"
PY="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"

# ---- 该 ABI 需不需要 QNN ----
case "$ABI" in
    arm64*) ;;
    *) log "$ABI 没有 NPU(NPU 只在 arm64 真机上)，跳过 QNN 校验"; exit 0 ;;
esac
if [ "${JM_QNN:-1}" = "0" ]; then
    warn "JM_QNN=0：显式跳过 QNN 校验。产物将只有 CPU EP(超分慢，仅用于对照/排障)"
    exit 0
fi
[ -n "$PY" ] || { err "找不到 python3，无法校验 QNN 库"; exit 1; }
[ -f "$MANIFEST" ] || { err "缺少 $MANIFEST(脚本被移动了？)"; exit 1; }

verify() { "$PY" "$MANIFEST" verify --libs-dir "$LIBS" --abi "$ABI"; }

if verify; then
    VER=$([ -f "$LIBS/.qnn-version" ] && cat "$LIBS/.qnn-version" || echo "未知")
    log "QNN 运行库就绪(libs/$ABI, qnn-runtime $VER)"
    exit 0
fi

# ---- 缺库：尝试自动补齐 ----
if [ "$AUTO_FETCH" != "1" ]; then
    err "libs/$ABI 缺 QNN 运行库，且 QNN_AUTO_FETCH=0(不自动下载)。"
    err "手动补：bash android/tools/wsl_fetch_qnn.sh --libs-dir $LIBS"
    exit 1
fi
warn "libs/$ABI 缺 QNN 运行库，自动补齐(一次性 ~60MB 下载，之后走缓存)"
if ! QNN_VER="${QNN_VER:-2.42.0}" bash "$HERE/wsl_fetch_qnn.sh" --libs-dir "$LIBS"; then
    err "自动补齐失败。手动执行排查："
    err "  bash android/tools/wsl_fetch_qnn.sh --libs-dir $LIBS"
    exit 1
fi
if ! verify; then
    err "补齐后校验仍失败，拒绝继续打包(NPU 会在真机上静默失效)"
    exit 1
fi
log "QNN 运行库已补齐并校验通过: libs/$ABI"
exit 0
