#!/usr/bin/env bash
# android/tools/resolve_jdk.sh —— JDK 发现 / 版本区间校验（与 resolve_ndk.sh 同一套路）
#
# 为什么不能直接用 `java`：
#   p4a → buildozer → Gradle 这条链对"构建 JVM"的版本有硬约束。Gradle 8.14.x 支持
#   运行在 Java 17~24；系统默认 java 一旦被换成 25/27，构建会在 Groovy 初始化阶段
#   直接抛 "Unsupported class file major version 71"，报错位置和真实原因毫无关系。
#   而且本机 `java -version` 已经是 27，属于"随时会踩"的状态。
#
# 选择顺序：
#   1. JM_JDK=<目录>            显式指定（不满足区间直接报错，不做静默替换）
#   2. JAVA_HOME                系统设置，落在区间内才采用；不在区间则告警后继续找
#   3. JM_JDK_VERSION=<版本>    按版本号在候选里挑
#   4. 扫描常见安装位置，取**区间内版本最高**的一个
# 区间：JM_JDK_MIN ~ JM_JDK_MAX（默认 17~24，定义在 tools/versions.env）
#
# 用法：
#   . tools/resolve_jdk.sh && jm_resolve_jdk       # 设置 JM_JDK / JM_JDK_VER
#   . tools/resolve_jdk.sh && jm_apply_jdk         # 额外导出 JAVA_HOME + PATH
#   bash tools/resolve_jdk.sh --check              # 打印结论（构建脚本的环境检查用）
#   JM_JDK=/usr/lib/jvm/java-17-openjdk-amd64 bash tools/resolve_jdk.sh --check

_jm_jdk_self="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# 单独运行时也要吃到集中配置里的区间（build_android.sh 会先 source versions.env，
# 但 `bash tools/resolve_jdk.sh --check` 是独立进程，不 source 就会用旧默认值）
if [ -f "${_jm_jdk_self}/versions.env" ]; then
    # shellcheck source=versions.env
    . "${_jm_jdk_self}/versions.env"
fi
# 版本区间兜底：versions.env 缺失时仍给出合理默认
: "${JM_JDK_MIN:=17}"
: "${JM_JDK_MAX:=25}"

# 目录 -> 主版本号（17 / 21 / 24），取不到输出空
jm_jdk_version_of() {
    local dir="${1%/}" ver=""
    if [ -f "$dir/release" ]; then
        ver="$(sed -n 's/^JAVA_VERSION="\([^"]*\)".*/\1/p' "$dir/release" 2>/dev/null | head -n1)"
    fi
    if [ -z "$ver" ] && [ -x "$dir/bin/java" ]; then
        ver="$("$dir/bin/java" -version 2>&1 | head -n1 | sed -n 's/.*"\([^"]*\)".*/\1/p')"
    fi
    [ -n "$ver" ] || ver="$(basename "$dir" | grep -oE '[0-9]+(\.[0-9]+)*' | head -n1)"
    printf '%s' "${ver%%.*}"
}

# Java 可执行文件在 Windows 上带 .exe（env.sh 用它拼 PATH 时不涉及，但提示信息里有）
jm_java_bin() { printf '%s/bin/java' "$1"; }

# 候选目录 -> "主版本<TAB>路径"
# 只收完整 JDK（有 javac）：JRE 目录跑不了 Gradle 的 Java 编译任务，混进来只会制造噪音。
jm_jdk_list() {
    local dir ver
    {
        [ -n "${JM_JDK:-}" ] && printf '%s\n' "$JM_JDK"
        [ -n "${JAVA_HOME:-}" ] && printf '%s\n' "$JAVA_HOME"
        [ -n "${JM_WORK:-}" ] && printf '%s\n' "$JM_WORK"/jdk*
        [ -n "${HOME:-}" ] && printf '%s\n' "$HOME"/jdk* "$HOME"/.jdks/* "$HOME"/.sdkman/candidates/java/*
        # 构建根目录下的 tools/jdk*（手工解压的 Temurin 就放这里），
        # 以及仓库自带的 tools/jdk*：都不需要用户 export JM_JDK
        printf '%s\n' "$(dirname "${_jm_jdk_self}/../..")"/tools/jdk*
        printf '%s\n' "${_jm_jdk_self}/../.."/tools/jdk*
        printf '%s\n' /usr/lib/jvm/* /usr/java/* /opt/java/* /opt/*jdk* /usr/local/*jdk*
        # Windows / MSYS 上常见的手工解压位置（D:\jdk-21.0.13+9 这种）
        printf '%s\n' /[a-z]/jdk* "/c/Program Files/Java"/* "/c/Program Files/Eclipse Adoptium"/*
        printf '%s\n' /Library/Java/JavaVirtualMachines/*/Contents/Home
    } 2>/dev/null | while IFS= read -r dir; do
        [ -n "$dir" ] || continue
        case "$(basename "$dir")" in jre*|jre-*|jdk-*-jre) continue ;; esac
        [ -x "$dir/bin/java" ] || continue
        # 有 javac 才算 JDK；macOS 的 JavaVirtualMachines 下也是 Contents/Home/bin/javac
        [ -x "$dir/bin/javac" ] || [ -x "$dir/bin/javac.exe" ] || continue
        ver="$(jm_jdk_version_of "$dir")"
        [ -n "$ver" ] || continue
        [ "$ver" -ge 8 ] 2>/dev/null || continue
        printf '%s\t%s\n' "$ver" "$dir"
    done | sort -u
}

# 主版本是否落在 [MIN, MAX]
jm_jdk_in_range() {
    local major="$1"
    [ -n "$major" ] || return 1
    [ "$major" -ge "$JM_JDK_MIN" ] 2>/dev/null || return 1
    [ "$major" -le "$JM_JDK_MAX" ] 2>/dev/null || return 1
    return 0
}

# 解析并写 JM_JDK / JM_JDK_VER；找不到输出空串
jm_resolve_jdk() {
    local pin="${JM_JDK_VERSION:-}" explicit="${JM_JDK:-}"
    local cand major best="" best_major=0
    # 先把入参存进 local 再清空输出变量，否则会把"用户显式指定的 JM_JDK"抹掉
    JM_JDK=""; JM_JDK_VER=""

    # 1) 显式 JM_JDK：不做静默替换（越界就报错，而不是悄悄换成别的 JDK 去构建）
    if [ -n "$explicit" ] && [ -x "$explicit/bin/java" ]; then
        major="$(jm_jdk_version_of "$explicit")"
        if jm_jdk_in_range "$major"; then
            JM_JDK="$explicit"; JM_JDK_VER="$major"
            printf '%s' "$JM_JDK"; return 0
        fi
        printf 'JM_JDK=%s 是 Java %s，超出允许区间 %s~%s（Gradle 8.14 跑不了这个 JVM）\n' \
            "$explicit" "$major" "$JM_JDK_MIN" "$JM_JDK_MAX" >&2
        return 1
    fi

    # 2/3/4) 其余来源统一过一遍候选表
    while IFS="$(printf '\t')" read -r major cand; do
        [ -n "${cand:-}" ] || continue
        jm_jdk_in_range "$major" || continue
        if [ -n "$pin" ]; then
            [ "$major" = "${pin%%.*}" ] || continue
        fi
        if [ "$major" -gt "$best_major" ] 2>/dev/null; then
            best_major="$major"; best="$cand"
        fi
    done <<EOF
$(jm_jdk_list)
EOF

    if [ -n "$best" ]; then
        JM_JDK="$best"; JM_JDK_VER="$best_major"
        printf '%s' "$best"
    fi
    return 0
}

# 导出给下游（Gradle / apksigner / keytool / buildozer 都认 JAVA_HOME）
jm_apply_jdk() {
    [ -n "${JM_JDK:-}" ] || jm_resolve_jdk >/dev/null
    [ -n "${JM_JDK:-}" ] || return 1
    export JAVA_HOME="$JM_JDK"
    export PATH="$JAVA_HOME/bin:$PATH"
    return 0
}

jm_jdk_hint() {
    local all
    all="$(jm_jdk_list | cut -f1 | sort -n -u | tr '\n' ' ')"
    {
        printf '  候选 JDK（主版本）: %s\n' "${all:-无}"
        printf '  允许区间: %s ~ %s（由 tools/versions.env 的 JM_JDK_MIN/MAX 决定）\n' "$JM_JDK_MIN" "$JM_JDK_MAX"
        printf '  * 高于上限说明 Gradle 还不支持那个 JVM（Java 25 需 Gradle 9.1+，27 需 9.8+）\n'
        printf '  * 指定: JM_JDK=/path/to/jdk  或  JM_JDK_VERSION=21\n'
        printf '  * 安装: apt install openjdk-17-jdk / sdkman install java 21-tem\n'
    } >&2
}

# ------------------------------------------------------------------ 命令行
_jm_jdk_main() {
    local mode="check"
    while [ $# -gt 0 ]; do
        case "$1" in
            --path)    mode="path" ;;
            --version) mode="version" ;;
            --check)   mode="check" ;;
            -h|--help) sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
            *) printf '未知参数: %s\n' "$1" >&2; return 2 ;;
        esac
        shift
    done

    jm_resolve_jdk >/dev/null
    if [ -z "${JM_JDK:-}" ]; then
        printf '找不到落在允许区间内的 JDK\n' >&2
        jm_jdk_hint
        return 2
    fi

    case "$mode" in
        path)    printf '%s\n' "$JM_JDK" ;;
        version) printf '%s\n' "$JM_JDK_VER" ;;
        check)
            printf 'JDK:  %s\n' "$JM_JDK"
            printf '版本: %s（允许 %s~%s）\n' "$JM_JDK_VER" "$JM_JDK_MIN" "$JM_JDK_MAX"
            if [ -n "${JAVA_HOME:-}" ] && [ "${JM_JDK}" != "${JAVA_HOME}" ]; then
                printf '[WARN] JAVA_HOME=%s 不可用（超区间或不存在），已改用上面的 JDK\n' "$JAVA_HOME"
            fi
            printf '[OK]  JDK 满足 Gradle 的运行要求\n'
            ;;
    esac
    return 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    _jm_jdk_main "$@"
fi
