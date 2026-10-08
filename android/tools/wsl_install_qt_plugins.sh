#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 把 APK 缺失的 Qt 插件补进 libs/arm64-v8a
#
# 背景：pyside6-android-deploy 只在 [android] plugins 里显式列出时才把插件放进 APK 的
# lib/<abi>/。我们的 pysidedeploy.spec 里 plugins 是空的，结果整个 APK 只有一个
# platforms 插件。真机实测的后果：
#   * 缺 imageformats/qsvg   -> 主题 QSS 里 65 处 svg 图标全部空白，
#                               设置页 checkbox/radio 的"交互框"直接看不见
#   * 缺 imageformats/qjpeg|qgif|qwebp -> 漫画图/GIF 验证码都解不出来
#   * 缺 sqldrivers/qsqlite  -> QtSql 全部 "Driver not loaded"，下载/历史/收藏库失效
#   * 缺 iconengines/qsvgicon -> QIcon 里的 svg 为空白
#
# 插件文件名规则 libplugins_<类别>_<名字>_<abi>.so，放进 APK 的 lib/<abi>/ 之后
# Qt 的 Android 插件加载器会自动扫描到(platforms 插件证明该机制有效)。
set -uo pipefail
WORK="${WORK:-"$JM_WORK"}"
ANDROID="$WORK/src/android"
LIBDIR="$ANDROID/libs/arm64-v8a"
VPY="$WORK/venv311/bin/python"
# p4a 从 wheel 解出来的插件目录(作为 wheel 不可用时的备用来源)
INSTALLS="$ANDROID/.buildozer/android/platform/build-arm64-v8a/build/python-installs/JMComic/arm64-v8a/PySide6/Qt/plugins"

# 需要的插件。刻意不含：
#   styles/qandroidstyle —— 会改变既有控件外观，收益不明确，不冒险
#   tls/*               —— 本项目 HTTPS 走 python 的 ssl，QtNetwork 只用于单实例(Android 已禁用)
PLUGINS="imageformats/qjpeg imageformats/qgif imageformats/qwebp imageformats/qsvg imageformats/qico iconengines/qsvgicon sqldrivers/qsqlite"

WHEEL=$(ls "$ANDROID/wheels/"pyside6-*-android_aarch64.whl 2>/dev/null | head -1)
mkdir -p "$LIBDIR"
echo "wheel:  ${WHEEL:-<无>}"
echo "installs: $INSTALLS"
echo "目标:   $LIBDIR"

"$VPY" - "$WHEEL" "$LIBDIR" "$INSTALLS" $PLUGINS <<'PY'
import os, sys, zipfile, shutil
wheel, libdir, installs = sys.argv[1], sys.argv[2], sys.argv[3]
wanted = sys.argv[4:]
names = []
if wheel and os.path.exists(wheel):
    names = zipfile.ZipFile(wheel).namelist()
ok, bad = 0, []
for spec in wanted:
    cat, name = spec.split("/", 1)
    src = local = None
    # 1) wheel 里找 libplugins_<cat>_<name>_*.so
    for n in names:
        if ("/plugins/%s/" % cat) in n and n.endswith(".so") \
                and os.path.basename(n).startswith("libplugins_%s_%s_" % (cat, name)):
            src = n
            break
    if src is None:  # 放宽：类别 + 名字子串
        for n in names:
            if ("/plugins/%s/" % cat) in n and n.endswith(".so") and name in os.path.basename(n):
                src = n
                break
    # 2) 备用：已解包的 python-installs
    folder = os.path.join(installs, cat)
    if src is None and os.path.isdir(folder):
        for f in sorted(os.listdir(folder)):
            if f.endswith(".so") and name in f:
                local = os.path.join(folder, f)
                break
    if src is None and local is None:
        bad.append(spec)
        print("  [MISS] %s" % spec)
        continue
    if src is not None:
        base = os.path.basename(src)
        dst = os.path.join(libdir, base)
        with zipfile.ZipFile(wheel).open(src) as f, open(dst, "wb") as out:
            out.write(f.read())
    else:
        base = os.path.basename(local)
        dst = os.path.join(libdir, base)
        shutil.copy2(local, dst)
    print("  [ok] %-26s -> %-52s %d bytes" % (spec, base, os.path.getsize(dst)))
    ok += 1
print("已安装 %d/%d 个 Qt 插件" % (ok, len(wanted)))
if bad:
    print("缺失(APK 里对应功能仍会失效): %s" % ", ".join(bad))
    sys.exit(3)
PY
rc=$?
echo "=== libs/arm64-v8a 里的 Qt 插件 ==="
ls -l "$LIBDIR" 2>/dev/null | grep libplugins || echo "(无)"
exit $rc
