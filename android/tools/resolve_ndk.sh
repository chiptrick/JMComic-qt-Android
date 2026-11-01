#!/usr/bin/env bash
# android/tools/resolve_ndk.sh —— Android NDK 发现/选择（全仓库唯一入口）
#
# 为什么要有这个文件
# ------------------------------------------------------------------
# 以前 8 个脚本各自写死 `$SDK/ndk/26.1.10909125`，换一次 NDK 就要改 8 处，
# 而且 NDK 版本直接决定 16KB 页兼容性：
#   r27 及更早：默认按 4KB 对齐，必须显式加 -Wl,-z,max-page-size=16384
#   r28 及以上：默认就按 16KB 对齐（Google 官方口径）
# 所以"用哪个 NDK"不是环境细节，而是产物属性。集中到本文件后：
#   * 默认永远选本机装好的最高版本 —— 以后出新 NDK 不用改任何脚本
#   * 需要回退时用 JM_NDK_VERSION=<版本> 钉住，同样不用改脚本
#
# 选择顺序（先命中先用）
# ------------------------------------------------------------------
#   1. JM_NDK / ANDROID_NDK_HOME / ANDROID_NDK_ROOT / ANDROID_NDK  显式路径
#   2. JM_NDK_VERSION=<版本>        -> $SDK/ndk/<版本>
#   3. $SDK/ndk/* 中版本号最高者    -> 默认行为（新增 NDK 自动跟进）
#   4. $SDK/ndk-bundle              -> 老式布局兜底
#
# 用法
# ------------------------------------------------------------------
#   # a) 被 source（推荐，函数可用）
#   . "$(dirname "$0")/resolve_ndk.sh"
#   jm_resolve_ndk "$SDK" >/dev/null      # 之后 JM_NDK / JM_NDK_VER 可用
#
#   # b) 命令行
#   bash tools/resolve_ndk.sh --sdk "$SDK"            # 打印 NDK 路径
#   bash tools/resolve_ndk.sh --sdk "$SDK" --version  # 打印版本号 30.0.16248370
#   bash tools/resolve_ndk.sh --sdk "$SDK" --check    # 打印路径 + 16KB 结论
#   bash tools/resolve_ndk.sh --sdk "$SDK" --check --min 28
#
# 约定：本文件不设置 shell 选项（不 set -e/-u/pipefail），不产生全局副作用，
#       只定义函数 + JM_NDK/JM_NDK_VER 两个变量，避免影响 source 它的调用方。

# 16KB 页支持的最低 NDK 主版本（r28 起默认对齐；r27 需手动加链接参数）
JM_NDK_MIN_MAJOR="${JM_NDK_MIN_MAJOR:-28}"

# 从 source.properties 读真实版本号；读不到就退回目录名（如 30.0.16248370）
jm_ndk_version_of() {
    local dir="${1%/}" ver=""
    if [ -f "$dir/source.properties" ]; then
        ver="$(sed -n 's/^Pkg\.Revision[[:space:]]*=[[:space:]]*//p' "$dir/source.properties" \
               | head -n1 | tr -d '[:space:]')"
    fi
    [ -n "$ver" ] || ver="$(basename "$dir")"
    printf '%s' "$ver"
}

# 版本号 -> 定宽可排序键（1.2.3 -> 0000100002000003），避免依赖 sort -V
# （macOS 自带 BSD sort 不支持 -V，这条路径要能跑在 Darwin 上）
jm_ndk_key() {
    printf '%s' "$1" | awk -F. '{printf "%05d%05d%05d%05d", $1+0, $2+0, $3+0, $4+0}'
}

# 列出候选：每行 "排序键<TAB>版本<TAB>路径"
jm_ndk_list() {
    local sdk="${1:-}" dir ver
    [ -n "$sdk" ] || return 0
    for dir in "$sdk"/ndk/*/ "$sdk"/ndk-bundle/; do
        [ -d "$dir" ] || continue
        # 只认带 CMake 工具链的完整安装，跳过 .temp 之类的半成品目录
        [ -f "${dir%/}/build/cmake/android.toolchain.cmake" ] || continue
        ver="$(jm_ndk_version_of "$dir")"
        [ -n "$ver" ] || continue
        printf '%s\t%s\t%s\n' "$(jm_ndk_key "$ver")" "$ver" "${dir%/}"
    done
}

# 选版本号最高者；没有候选就输出空串（不报错，由调用方决定怎么提示）
jm_ndk_pick() {
    local sdk="${1:-}" best
    best="$(jm_ndk_list "$sdk" | sort -k1,1 | tail -n1)"
    [ -n "$best" ] || return 0
    printf '%s' "$best" | cut -f3
}

# ver1 >= ver2 ?
jm_ndk_ge() {
    local k1 k2
    k1="$(jm_ndk_key "$1")"; k2="$(jm_ndk_key "$2")"
    [[ "$k1" > "$k2" || "$k1" == "$k2" ]]
}

# 解析 NDK 并写 JM_NDK / JM_NDK_VER；同时把路径打到 stdout（便于 $(...) 取用）
jm_resolve_ndk() {
    local sdk="${1:-}" explicit pin path=""
    explicit="${JM_NDK:-${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-${ANDROID_NDK:-}}}}"
    pin="${JM_NDK_VERSION:-}"

    if [ -n "$explicit" ] && [ -d "$explicit" ]; then
        path="$explicit"                                # 1) 显式路径优先
    elif [ -n "$pin" ] && [ -d "$sdk/ndk/$pin" ]; then
        path="$sdk/ndk/$pin"                            # 2) 钉住版本
    elif [ -z "$pin" ]; then
        path="$(jm_ndk_pick "$sdk")"                    # 3) 默认：最新
    fi

    [ -n "$path" ] || return 0
    JM_NDK="${path%/}"
    JM_NDK_VER="$(jm_ndk_version_of "$JM_NDK")"
    printf '%s' "$JM_NDK"
    return 0
}

# 找不到 NDK 时的统一提示（各脚本 die 之前打出来，避免"只说要设环境变量"）
jm_ndk_hint() {
    local sdk="${1:-}"
    {
        printf '  已查找的位置:\n'
        printf '    $JM_NDK / $ANDROID_NDK_HOME / $ANDROID_NDK_ROOT / $ANDROID_NDK  (当前: %s)\n' \
            "${JM_NDK:-${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-${ANDROID_NDK:-<未设置>}}}}"
        printf '    %s/ndk/*            (当前候选: %s)\n' "${sdk:-<未设置 SDK>}" \
            "$(jm_ndk_list "$sdk" | cut -f2 | tr '\n' ' ')"
        if [ -n "${JM_NDK_VERSION:-}" ]; then
            printf '    $SDK/ndk/%s      (由 JM_NDK_VERSION 指定，但目录不存在)\n' "${JM_NDK_VERSION}"
        fi
        printf '  安装最新版: sdkmanager --install "ndk"\n'
        printf '  或指定版本: export JM_NDK_VERSION=28.2.13676358\n'
    } >&2
}

# 用当前选中的 NDK 编 16KB 对齐的库，需要额外做什么
jm_ndk_16k_note() {
    local ver="${1:-${JM_NDK_VER:-}}" major
    major="${ver%%.*}"
    if [ -z "$major" ]; then
        printf '未知 NDK 版本'
    elif jm_ndk_ge "$ver" "$JM_NDK_MIN_MAJOR.0.0"; then
        printf 'r28 及以上，默认按 16KB 对齐编译（无需额外链接参数）'
    elif jm_ndk_ge "$ver" "27.0.0"; then
        printf 'r27，需显式 -Wl,-z,max-page-size=16384（r28 起才默认）'
    else
        printf 'r26 及更早，recipes 编出的库仍是 4KB 对齐，不建议用于 16KB 目标'
    fi
}

# ------------------------------------------------------------------ 命令行入口
_jm_ndk_main() {
    local sdk="" mode="path" min="$JM_NDK_MIN_MAJOR.0.0"

    while [ $# -gt 0 ]; do
        case "$1" in
            --sdk=*)     sdk="${1#--sdk=}" ;;
            --sdk)       sdk="${2:-}"; shift ;;
            --version)   mode="version" ;;
            --check)     mode="check" ;;
            --min=*)     min="${1#--min=}" ;;
            --min)       min="${2:-}"; shift ;;
            -h|--help)   sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
            *)           printf '未知参数: %s\n' "$1" >&2; return 2 ;;
        esac
        shift
    done

    jm_resolve_ndk "$sdk" >/dev/null
    if [ -z "${JM_NDK:-}" ]; then
        printf '找不到可用的 Android NDK（SDK=%s）\n' "${sdk:-<未设置>}" >&2
        jm_ndk_hint "$sdk"
        return 2
    fi

    case "$mode" in
        path)    printf '%s\n' "$JM_NDK" ;;
        version) printf '%s\n' "$JM_NDK_VER" ;;
        check)
            printf 'NDK:  %s\n' "$JM_NDK"
            printf '版本: %s\n' "$JM_NDK_VER"
            printf '16KB: %s\n' "$(jm_ndk_16k_note "$JM_NDK_VER")"
            if ! jm_ndk_ge "$JM_NDK_VER" "$min"; then
                printf '[FAIL] 版本低于要求的 %s（需要 r28+ 才能默认产出 16KB 对齐库）\n' "$min" >&2
                return 1
            fi
            printf '[OK]  满足最低版本要求 %s\n' "$min"
            ;;
    esac
    return 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    _jm_ndk_main "$@"
fi
