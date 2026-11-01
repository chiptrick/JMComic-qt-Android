#!/usr/bin/env bash
# android/tools/resolve_host.sh —— 宿主平台抽象层
#
# 目的：让 android/ 下的脚本在 Linux / WSL / macOS 上行为一致，
# 不再隐含依赖某个平台的命令方言或路径写法。**不设置 shell 选项**，可安全 source。
#
# 为什么需要它（都是实际会炸的点）：
#   * `sed -i` 在 GNU 与 BSD 上参数不同（BSD 必须 `sed -i ''`）—— build_android.sh
#     头注释写着支持 macOS，但 14 处 sed -i 在 macOS 上会当场失败。
#   * `nproc` 只有 GNU coreutils 有；macOS 要 `sysctl -n hw.ncpu`。
#   * `sha256sum` 只有 GNU 有；macOS 是 `shasum -a 256`。
#   * `stat -c %Y` / `stat -f %m`、`readlink -f` 同样分平台。
#   * WSL 里如果 `ANDROID_HOME=D:\Android_SDK`（Windows 风格路径 + 反斜杠），
#     后续所有 `[[ -d ... ]]` 都会判假，报出来的却是"NDK 目录不存在"。
#
# 用法：`. tools/resolve_host.sh` 之后直接用 jm_* 函数。

# ---------------------------------------------------------------- 基础
jm_have() { command -v "$1" >/dev/null 2>&1; }

# 返回 linux | wsl | darwin | msys | other
jm_host_os() {
    local s
    s="$(uname -s 2>/dev/null || echo unknown)"
    case "$s" in
        Linux)
            # WSL2 的 uname 也是 Linux，靠内核版本串区分
            if [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then
                printf 'wsl'
            elif [ -n "${WSL_DISTRO_NAME:-}" ]; then
                printf 'wsl'
            else
                printf 'linux'
            fi ;;
        Darwin) printf 'darwin' ;;
        MINGW*|MSYS*|CYGWIN*) printf 'msys' ;;
        *) printf 'other' ;;
    esac
}

# 便于在日志里打印"我们现在到底在哪个平台"
jm_host_desc() {
    printf '%s %s' "$(jm_host_os)" "$(uname -r 2>/dev/null || echo '?')"
}

# 并行度：nproc / sysctl / getconf 三档回落
jm_nproc() {
    if jm_have nproc; then
        nproc 2>/dev/null && return 0
    fi
    if jm_have sysctl; then
        sysctl -n hw.ncpu 2>/dev/null && return 0
    fi
    if jm_have getconf; then
        getconf _NPROCESSORS_ONLN 2>/dev/null && return 0
    fi
    printf '4'
}

# ---------------------------------------------------------------- 文件/校验
# 修改时间（epoch 秒）：GNU 用 -c %Y，BSD 用 -f %m
jm_stat_mtime() {
    local f="$1"
    stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null || echo 0
}

# sha256：sha256sum -> shasum -a 256 -> openssl dgst
jm_sha256() {
    local f="$1"
    if jm_have sha256sum; then
        sha256sum "$f" | cut -d' ' -f1
    elif jm_have shasum; then
        shasum -a 256 "$f" | cut -d' ' -f1
    elif jm_have openssl; then
        openssl dgst -sha256 "$f" | awk '{print $NF}'
    else
        return 1
    fi
}

# 绝对路径（readlink -f 在 macOS 不存在）
jm_realpath() {
    local p="$1"
    if jm_have readlink && readlink -f "$p" >/dev/null 2>&1; then
        readlink -f "$p"
    elif jm_have python3; then
        python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$p"
    else
        printf '%s' "$p"
    fi
}

# 就地替换：把 `sed -i ...` 换成 `jm_sed_i ...`（其余参数原样传）
# 用法：jm_sed_i -E 's|a|b|' file / jm_sed_i 's|a|b|' file
JM_SED_BSD=""
jm_sed_i() {
    if [ -z "${JM_SED_BSD}" ]; then
        if sed --version >/dev/null 2>&1; then JM_SED_BSD=0; else JM_SED_BSD=1; fi
    fi
    if [ "${JM_SED_BSD}" = "1" ]; then
        sed -i '' "$@"
    else
        sed -i "$@"
    fi
}

# ---------------------------------------------------------------- 路径
# 归一化：去 CR、反斜杠转正斜杠、WSL 下把 C:/x 转成 /mnt/c/x
# 用途：环境变量里传进来的 SDK/NDK/JDK 路径可能是 Windows 写法。
jm_norm_path() {
    local p="${1:-}"
    p="${p%$'\r'}"
    p="${p//\\//}"
    if [ "$(jm_host_os)" = "wsl" ] && [[ "$p" =~ ^[A-Za-z]:/ ]]; then
        local drive
        drive="$(printf '%s' "${p:0:1}" | tr 'A-Z' 'a-z')"
        p="/mnt/${drive}/${p:3}"
    fi
    # 去掉尾部的 /（根目录除外）
    [ "${#p}" -gt 1 ] && p="${p%/}"
    printf '%s' "$p"
}

# 把路径转成"给 Windows 侧工具用"的形式（.ps1 / adb.exe 场景用得到）
jm_win_path() {
    local p="$1"
    case "$(jm_host_os)" in
        wsl)
            if [[ "$p" =~ ^/mnt/([a-z])/(.*)$ ]]; then
                printf '%s:/%s' "$(printf '%s' "${BASH_REMATCH[1]}" | tr 'a-z' 'A-Z')" "${BASH_REMATCH[2]}"
            else
                printf '%s' "$p"
            fi ;;
        msys)
            if jm_have cygpath; then cygpath -w "$p"; else printf '%s' "$p"; fi ;;
        *) printf '%s' "$p" ;;
    esac
}

# ---------------------------------------------------------------- 版本比较
# "3.20.1" >= "3.20" ；只比较数字段，够用即可（不引入 sort -V，macOS 没有）
jm_ver_ge() {
    local a="$1" b="$2"
    [ "$(printf '%s\n%s\n' "$a" "$b" | sort -t. -k1,1n -k2,2n -k3,3n | tail -n1)" = "$a" ]
}

# 取命令的版本号（cmake --version 之类），取不到返回空
jm_cmd_version() {
    "$@" 2>/dev/null | head -n1 | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -n1
}

# ---------------------------------------------------------------- SDK 包查询
# 从 `sdkmanager --list` 里取某个前缀的最高版本，输出完整包名（如 build-tools;36.0.0）
# 查不到就输出空串，让调用方决定回退策略（离线/无网络时不该让脚本直接死）。
jm_sdk_latest_pkg() {
    local sdkmanager="$1" prefix="$2" ver
    [ -x "$sdkmanager" ] || return 0
    ver="$("$sdkmanager" --list 2>/dev/null | tr -d '\r' \
        | awk -v p="$prefix" '$1 ~ "^"p"$" || $1 ~ "^"p";" { print $1 }' \
        | sed "s|^${prefix}||" | grep -E '^[0-9]+(\.[0-9]+)*$' \
        | sort -t. -k1,1n -k2,2n -k3,3n | tail -n1)"
    [ -n "$ver" ] && printf '%s%s' "$prefix" "$ver"
}

# ---------------------------------------------------------------- 下载
# GitHub 镜像：github.com / raw.githubusercontent.com 一律走 JM_GH_MIRROR_PREFIX
# （已是镜像的、codeload 的不动）。非 GitHub 的 URL 原样返回。
jm_mirror_url() {
    local u="$1"
    case "$u" in
        *gh-proxy.com/*|*ghfast.top/*|*ghproxy.net/*|*codeload.github.com/*)
            printf '%s' "$u" ;;
        https://github.com/*|https://raw.githubusercontent.com/*)
            printf '%s%s' "${JM_GH_MIRROR_PREFIX%/}/" "$u" ;;
        *) printf '%s' "$u" ;;
    esac
}

# 统一下载入口：aria2c 多线程优先（-x/-s 并发、断点续传、自动重试），
# aria2 不可用或下载失败时回落 curl。
# 用法: jm_download <url> <输出文件路径>
jm_download() {
    local url out dir name rc
    url="$(jm_mirror_url "$1")"
    out="$2"
    dir="$(dirname "$out")"; name="$(basename "$out")"
    mkdir -p "$dir" 2>/dev/null

    if jm_have aria2c; then
        aria2c -x "${JM_ARIA2_CONN:-16}" -s "${JM_ARIA2_CONN:-16}" -k 1M \
            --file-allocation=none --allow-overwrite=true \
            --auto-file-renaming=false --max-tries=5 --retry-wait=3 \
            --console-log-level=warn --summary-interval=0 \
            --connect-timeout=20 --timeout=60 \
            -d "$dir" -o "$name" "$url" >/dev/null 2>&1
        rc=$?
        if [ $rc -eq 0 ] && [ -s "$out" ]; then
            return 0
        fi
        # 半截文件/control 文件都清掉，回落 curl 从头下
        command rm -f "$out" "$out.aria2" 2>/dev/null
    fi
    curl -fsSL --retry 3 --connect-timeout 20 -o "$out" "$url"
}

# 检查一组命令是否都在，缺哪个报哪个（错误信息里带上平台，方便判断）
jm_require_cmds() {
    local missing="" c
    for c in "$@"; do
        jm_have "$c" || missing="${missing} ${c}"
    done
    if [ -n "$missing" ]; then
        printf '缺少命令:%s（当前平台: %s）\n' "$missing" "$(jm_host_desc)" >&2
        return 1
    fi
    return 0
}

# ------------------------------------------------------------------ 命令行入口
# 迁移到新主机时先跑这个，比"构建失败再回头看"省事
_jm_host_main() {
    case "${1:-}" in
        -h|--help) sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
    esac
    printf '平台:   %s\n' "$(jm_host_desc)"
    printf '并行度: %s\n' "$(jm_nproc)"
    if sed --version >/dev/null 2>&1; then
        printf 'sed:    GNU（sed -i 可直接用；脚本仍统一走 jm_sed_i）\n'
    else
        printf 'sed:    BSD（jm_sed_i 会自动补 -i 的空参数）\n'
    fi
    printf 'sha256: %s\n' "$(jm_sha256 /dev/null 2>/dev/null || printf '不可用')"
    printf '路径归一化: D:\\Android_SDK\\ndk -> %s\n' "$(jm_norm_path 'D:\Android_SDK\ndk')"
    printf '缺失命令: %s\n' "$(for c in unzip curl zip java; do jm_have "$c" || printf '%s ' "$c"; done)"
    return 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    _jm_host_main "$@"
fi
