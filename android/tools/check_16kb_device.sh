#!/usr/bin/env bash
# android/tools/check_16kb_device.sh —— 在真机/模拟器上验收 16KB 页兼容性
#
# 静态门禁(tools/check_elf_page_align.py)只能证明"库编对了"，证明不了
# "在这台 16KB 设备上真的跑得起来"。这个脚本补上后半段，且把结论落成
# 可复述的几条输出(设备页大小 / 兼容模式状态 / 应用是否被塞进兼容模式)。
#
# 用法：
#   bash tools/check_16kb_device.sh                       # 只看设备页大小
#   bash tools/check_16kb_device.sh --pkg org.jmcomic.jmcomic
#   bash tools/check_16kb_device.sh --pkg org.jmcomic.jmcomic --launch
#   JM_ABI=x86_64 bash tools/check_16kb_device.sh --pkg ...   # 模拟器
#   bash tools/check_16kb_device.sh --fatal on            # 打开严格模式(需 root/userdebug)
#   bash tools/check_16kb_device.sh --fatal off
#
# 16KB 设备从哪来：
#   * Pixel 8/8a/9/9a 及以上：开发者选项 "Boot with 16KB page size"(会清数据一次)
#   * Android Studio 的 16KB 系统镜像 AVD
#   * Android 17 起的部分新机型默认就是 16KB
#
# 退出码: 0 设备是 16KB 且(指定了 --pkg 时)应用没被标记为兼容模式
#         1 设备不是 16KB(无法验收) / 2 环境问题
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
set -uo pipefail

PKG=""
LAUNCH=0
FATAL=""
ACTIVITY="org.kivy.android.PythonActivity"

while [ $# -gt 0 ]; do
    case "$1" in
        --pkg)    PKG="${2:-}"; shift ;;
        --pkg=*)  PKG="${1#--pkg=}" ;;
        --activity)   ACTIVITY="${2:-}"; shift ;;
        --activity=*) ACTIVITY="${1#--activity=}" ;;
        --launch) LAUNCH=1 ;;
        --fatal)  FATAL="${2:-on}"; shift ;;
        --fatal=*) FATAL="${1#--fatal=}" ;;
        -h|--help) sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "未知参数: $1" >&2; exit 2 ;;
    esac
    shift
done

[ -x "$JM_ADB" ] || { echo "[FAIL] 找不到 adb: $JM_ADB" >&2; exit 2; }
adbs() {
    if [ -n "${JM_SERIAL:-}" ]; then "$JM_ADB" -s "$JM_SERIAL" "$@"; else "$JM_ADB" "$@"; fi
}
if [ -z "${JM_SERIAL:-}" ]; then
    echo "[FAIL] 没有已授权的设备(adb devices)。插上设备并允许调试后重试。" >&2
    exit 2
fi

echo "设备: $(adbs shell getprop ro.product.model 2>/dev/null | tr -d '\r')  " \
     "Android $(adbs shell getprop ro.build.version.release 2>/dev/null | tr -d '\r')  " \
     "ABI $(adbs shell getprop ro.product.cpu.abi 2>/dev/null | tr -d '\r')"
echo "串号: $JM_SERIAL"

PAGE_SIZE="$(adbs shell getconf PAGE_SIZE 2>/dev/null | tr -d '\r')"
if [ -z "$PAGE_SIZE" ]; then
    echo "[WARN] getconf PAGE_SIZE 取不到，退回到 kernel 命令行判断"
    PAGE_SIZE="$(adbs shell 'grep -o "page_size=[0-9]*" /proc/cmdline' 2>/dev/null | tr -d '\r' | cut -d= -f2)"
fi
echo "页大小: ${PAGE_SIZE:-未知} 字节"

COMPAT_LINKER="$(adbs shell getprop bionic.linker.16kb.app_compat.enabled 2>/dev/null | tr -d '\r')"
COMPAT_PM="$(adbs shell getprop pm.16kb.app_compat.disabled 2>/dev/null | tr -d '\r')"
echo "兼容开关: bionic.linker.16kb.app_compat.enabled=${COMPAT_LINKER:-<默认>}" \
     " pm.16kb.app_compat.disabled=${COMPAT_PM:-<默认>}"

case "$FATAL" in
    on|1|true)
        echo "-> 尝试打开严格模式(不兼容即 abort，用来暴露问题)"
        adbs root >/dev/null 2>&1 || true
        sleep 1
        adbs shell setprop bionic.linker.16kb.app_compat.enabled fatal 2>&1 | sed 's/^/   /'
        adbs shell setprop pm.16kb.app_compat.disabled true 2>&1 | sed 's/^/   /'
        COMPAT_LINKER="$(adbs shell getprop bionic.linker.16kb.app_compat.enabled 2>/dev/null | tr -d '\r')"
        echo "   现在: bionic.linker.16kb.app_compat.enabled=${COMPAT_LINKER:-<设置失败，需要 root/userdebug>}"
        ;;
    off|0|false)
        echo "-> 恢复默认兼容行为"
        adbs root >/dev/null 2>&1 || true
        sleep 1
        adbs shell setprop bionic.linker.16kb.app_compat.enabled false >/dev/null 2>&1 || true
        adbs shell setprop pm.16kb.app_compat.disabled false >/dev/null 2>&1 || true
        ;;
    "") ;;
    *) echo "未知 --fatal 取值: $FATAL" >&2; exit 2 ;;
esac

if [ "$PAGE_SIZE" != "16384" ]; then
    echo
    echo "[FAIL] 这台设备不是 16KB 页(PAGE_SIZE=${PAGE_SIZE:-未知})，无法做 16KB 验收。"
    echo "       Pixel 8/9 及以上：开发者选项 -> 开启 'Boot with 16KB page size'(会清数据)。"
    echo "       或改用 Android Studio 的 16KB 系统镜像 AVD。"
    exit 1
fi
echo "[OK]   设备运行在 16KB 页上，可以验收。"

[ -n "$PKG" ] || { echo; echo "未指定 --pkg，跳过应用侧检查。"; exit 0; }

echo
echo "=== 应用侧检查: $PKG ==="
if ! adbs shell pm list packages 2>/dev/null | tr -d '\r' | grep -qx "package:$PKG"; then
    echo "[FAIL] 设备上没有安装 $PKG"
    exit 2
fi

# 应用被 PackageManager 标记为兼容模式时，AppInfo 里会带 PAGE_SIZE_COMPAT 之类的 flag；
# 不同版本 dump 的措辞不完全一致，这里只做尽力匹配，匹配不到就提示看日志。
FLAGS="$(adbs shell dumpsys package "$PKG" 2>/dev/null | tr -d '\r' \
    | grep -iE "page_?size|pageSizeCompat|16kb" | head -5)"
if [ -n "$FLAGS" ]; then
    echo "$FLAGS" | sed 's/^/  /'
    if echo "$FLAGS" | grep -qi "compat"; then
        echo "[WARN] 应用被标记为 16KB 兼容模式 -> 说明包内仍有 4KB 对齐的库："
        echo "       先跑 python tools/check_elf_page_align.py dist/<apk> --abi $JM_ABI"
    else
        echo "[OK]   dumpsys 里没有兼容模式标记"
    fi
else
    echo "[INFO] dumpsys 未输出页大小相关字段(不同 ROM 措辞不同)，以启动日志为准。"
fi

if [ "$LAUNCH" = "1" ]; then
    echo
    echo "-> 冷启动并抓首启日志"
    adbs shell am force-stop "$PKG" >/dev/null 2>&1 || true
    adbs logcat -c >/dev/null 2>&1 || true
    adbs shell am start -n "${PKG}/${ACTIVITY}" 2>&1 | sed 's/^/   /'
    sleep 8
    echo "--- 兼容模式/加载失败相关日志 ---"
    adbs logcat -d 2>/dev/null | tr -d '\r' \
        | grep -iE "16 ?kb|page size|compat mode|UnsatisfiedLink|dlopen|abort message|FATAL" \
        | tail -20 | sed 's/^/   /'
    PID="$(adbs shell pidof "$PKG" 2>/dev/null | tr -d '\r')"
    if [ -n "$PID" ]; then
        echo "[OK]   进程存活 pid=$PID"
    else
        echo "[FAIL] 进程没起来(严格模式下大概率是某个 4KB 库被拒载)"
    fi
fi

cat <<'EOF'

验收清单(逐条做，别只看启动成功)：
  1. 冷启动 -> 首页出图；期间 logcat 无 "running in 16 KB backcompat mode" 警告
  2. 超分：开关打开跑一张图(QNN/HTP 与 CPU 两条后端各一次)
  3. 图片解码：webp/gif/长图各一张；翻页动画(QRhi 覆盖层)连续翻 30 页
  4. 下载 + 解密入库(SQLite)、历史记录、字体渲染
  5. --fatal on 后重复 1~4，全过才算"不依赖兼容模式"
EOF
