#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 把 p4a 的 Gradle 堆上限从 2500m 提到 4096m
#
# 为什么必须改（0.39 打包时踩到）：
#   p4a 的 gradle.tmpl.properties 里写死
#       org.gradle.jvmargs=-Xmx2500m ... -XX:+HeapDumpOnOutOfMemoryError
#   :packageDebug 要把 200MB 的 assets/private.tar + ~500MB 原生库压进一个 APK，
#   2500m 不够用 -> Java OOM，表现是 Gradle 只报一句
#       Execution failed for task ':packageDebug'.
#       > A failure occurred while executing ... PackageAndroidArtifact$IncrementalSplitterRunnable
#   真正的证据是 dist 目录里同时出现一个 400MB 的 java_pid*.hprof
#   (HeapDumpOnOutOfMemoryError 生成的堆转储) —— 看到它就说明是 OOM，不是代码问题。
#   把上限提到 4096m 后同一步 21s 通过（宿主 WSL 内存 6GB，够用）。
#
# 为什么改模板而不是只改 dist：p4a 每次构建都按模板重新渲染 gradle.properties，
# 只改 dist 下次就被覆盖回去了。dist 里已有的那份也一并改，保证当前这轮就生效。
set -uo pipefail
WORK="${WORK:-"$JM_WORK"}"
ANDROID="$WORK/src/android"
OLD_XMX="${OLD_XMX:-2500m}"
NEW_XMX="${NEW_XMX:-4096m}"

echo "=== Gradle 堆上限: -Xmx$OLD_XMX -> -Xmx$NEW_XMX ==="
changed=0
# 1) 模板（决定以后每次生成的 gradle.properties）
for f in "$WORK"/p4a/pythonforandroid/bootstraps/*/build/templates/gradle.tmpl.properties; do
    [ -f "$f" ] || continue
    if grep -q "Xmx$OLD_XMX" "$f"; then
        sed -i "s/Xmx$OLD_XMX/Xmx$NEW_XMX/g" "$f"
        echo "  已改模板 ${f#$WORK/}"
        changed=$((changed + 1))
    fi
done
# 2) 已存在的 dist / venv 副本（本轮就会用到）
while IFS= read -r f; do
    if grep -q "Xmx$OLD_XMX" "$f"; then
        sed -i "s/Xmx$OLD_XMX/Xmx$NEW_XMX/g" "$f"
        echo "  已改副本 ${f#$WORK/}"
        changed=$((changed + 1))
    fi
done < <(find "$ANDROID/.buildozer" "$WORK/venv311" "$WORK/p4a" \
         -name 'gradle.properties' 2>/dev/null | sort -u)

echo "  改了 $changed 个文件"
# 顺手清掉上一次 OOM 留下的堆转储(400MB/个，堆几次就吃掉可观空间)
find "$ANDROID/.buildozer" -maxdepth 6 -name 'java_pid*.hprof' -print -delete 2>/dev/null | head -3

echo "--- 校验 ---"
bad=0
while IFS= read -r f; do
    if grep -q "Xmx$OLD_XMX" "$f"; then
        echo "  [FAIL] 仍是 $OLD_XMX: ${f#$WORK/}"
        bad=$((bad + 1))
    fi
done < <(find "$ANDROID/.buildozer" "$WORK/p4a" \
         -name 'gradle*.properties' 2>/dev/null | sort -u)
if [ "$bad" -gt 0 ]; then
    echo "[FAIL] 还有 $bad 个文件没改过来，:packageDebug 可能再次 OOM"
    exit 1
fi
echo "  [ok] 没有残留 -Xmx$OLD_XMX"
exit 0
