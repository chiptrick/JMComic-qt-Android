#!/usr/bin/env bash
# 多任务(Recents)取证：按 HOME 把应用切到后台之后，在 PC 上跑这一条命令
#
#   bash android/tools/check_recents.sh            # 默认查 org.jmcomic.jmcomic
#   bash android/tools/check_recents.sh <包名>
#
# 目的：区分"任务根本不在 recents 里"和"任务在、但快照没内容"这两种完全不同的病：
#   * 第 1/2 段有 Task{...#N A=<uid>:<包名>} 记录 → 任务在，问题在快照(渲染容器)
#   * 第 1/2 段完全没有                    → 任务被移除/被排除(清单或 ROM 行为)
#   * 第 2 段里 thumbnailStatus=DENYLISTED / hasValidSnapshot=false → 快照被拒/为空
#
# 注意：不能在应用还处于前台时跑——那时 recents 里还没有它的快照。
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
set -uo pipefail

ADB="${JM_ADB:-adb}"
PKG="${1:-org.jmcomic.jmcomic}"

echo "=== 设备 ==="
"$ADB" devices | sed -n '2p'

echo
echo "=== 1. Activity 栈里还有没有它的任务(后台时也应有一行 Task{...#N A=..:$PKG}) ==="
"$ADB" shell dumpsys activity activities 2>/dev/null \
    | grep -E "Task\{[0-9a-f]+ #[0-9]+ .*${PKG}|topResumedActivity|ResumedActivity" \
    | head -12

echo
echo "=== 2. recents 里的记录 + 快照状态(thumbnailStatus / hasValidSnapshot / reasonForFailure) ==="
"$ADB" shell dumpsys activity recents 2>/dev/null | grep -A 14 "$PKG" | head -40
echo "  (没有输出 = recents 里查不到这个包)"

echo
echo "=== 3. 有没有被标记成不进多任务 ==="
"$ADB" shell dumpsys activity activities 2>/dev/null \
    | grep -iE "excludeFromRecents|autoRemoveFromRecents|taskAffinity" | head -8
echo "  (空 = 没被排除)"

echo
echo "=== 4. 进程是否还活着(说明是'任务没了但进程还在'还是'整进程被杀') ==="
"$ADB" shell pidof "$PKG" || echo "  (进程不在了)"

echo
echo "=== 5. 渲染容器类型 / 前后台切换日志(0=SurfaceView 1=TextureView) ==="
"$ADB" logcat -d 2>/dev/null \
    | grep -iE "surface container type|appState:|QT_ANDROID_SURFACE_CONTAINER_TYPE" \
    | tail -15

echo
echo "=== 判读 ==="
echo "  1/2 段有记录 + 快照为空  → 渲染容器问题(本仓库 0.54 起默认切 TextureView)"
echo "  1/2 段都没记录           → 任务被移除/排除，查第 3 段与厂商 ROM 的后台策略"
echo "  第 4 段空                → 进程被杀，另查崩溃/被系统清理(logcat 里有 FATAL)"
