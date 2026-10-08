#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 检查"Windows 仓库"与"WSL 构建树"是否一致
# 用途：确认 APK 里打进去的代码，就是仓库里当前这份(避免改了代码却拿旧包验证)
set -uo pipefail
W="${WORK:-"$JM_WORK"}"
REPO="${REPO:-"$JM_REPO"}"
SYNC="$W/src"
# 构建前会把 src/ 复制成 android/app_src/，所以两份都要看
APP="$SYNC/android/app_src"

FILES=(
    src/tools/mobile_ui.py
    src/tools/platform_mobile.py
    src/tools/sr_backend.py
    src/tools/tool.py
    src/tools/mobile_file_dialog.py
    src/task/task_qimage.py
    src/task/task_multi.py
    src/server/req.py
    src/server/server.py
    src/view/main/main_view.py
    src/view/read/read_view.py
    src/view/setting/setting_view.py
    src/view/user/login_proxy_new_widget.py
    src/view/tool/waifu2x_tool_view.py
    src/component/list/comic_list_widget.py
    src/component/widget/comic_item_widget.py
    android/main.py
    android/sr_qnn/__init__.py
    android/tools/patch_buildozer_spec.py
    android/shims/curl_cffi/__init__.py
    android/shims/curl_cffi/requests/__init__.py
)

same=0
diff=0
for f in "${FILES[@]}"; do
    a="$SYNC/$f"
    b="$REPO/$f"
    if [ ! -e "$a" ] || [ ! -e "$b" ]; then
        printf 'MISS  %-46s sync=%s repo=%s\n' "$f" "$([ -e "$a" ] && echo y || echo n)" \
            "$([ -e "$b" ] && echo y || echo n)"
        diff=$((diff + 1))
        continue
    fi
    if diff -q "$a" "$b" > /dev/null; then
        printf 'SAME  %s\n' "$f"
        same=$((same + 1))
    else
        printf 'DIFF  %s\n' "$f"
        diff "$a" "$b" | head -12 | sed 's/^/        /'
        diff=$((diff + 1))
    fi
done

echo
echo "仓库 vs 构建树: 相同 $same, 不同/缺失 $diff"
echo "app_src 是否已生成: $([ -d "$APP" ] && echo "是 ($(ls "$APP" | wc -l) 项)" || echo 否)"
for f in src/tools/mobile_ui.py src/tools/tool.py src/task/task_qimage.py \
         src/component/list/comic_list_widget.py; do
    if [ -d "$APP" ] && [ -f "$APP/${f#src/}" ]; then
        if diff -q "$APP/${f#src/}" "$REPO/$f" > /dev/null; then
            echo "app_src/${f#src/} 与仓库一致(APK 用的是这份)"
        else
            echo "!! app_src/${f#src/} 与仓库不一致 —— APK 里是旧代码"
        fi
    fi
done

# 光看 app_src 还不够：APK 里是**编译后的 .pyc**。踩过的坑：
# 构建还没结束就 collect，拿到的是上一版 APK(tool.pyc 里没有 SegmentationPictureQt)。
APK="${APK:-$REPO/android/JMComic-0.1-arm64-v8a-debug.apk}"
PY="${PY:-$W/venv311/bin/python3}"
if [ -f "$APK" ] && [ -x "$PY" ]; then
    echo
    echo "APK: $APK ($(stat -c %y "$APK" | cut -d. -f1), $(stat -c %s "$APK") 字节)"
    "$PY" - "$APK" <<'EOF'
import sys, tarfile, zipfile, io
apk = sys.argv[1]
# (private.tar 里的路径后缀, 该文件里必须出现的标记, 说明)
checks = [
    ("tools/tool.pyc", b"SegmentationPictureQt", "Qt 分割还原(tool.py)"),
    ("task/task_qimage.pyc", b"segQt", "Qt 分割计数(task_qimage.py)"),
    ("tools/mobile_ui.pyc", "图片分割自检".encode(), "图片分割自检(mobile_ui.py)"),
    ("tools/mobile_ui.pyc", b"ScheduleGridCoverSize", "首屏网格去抖重排(mobile_ui.py)"),
    ("component/list/comic_list_widget.pyc", b"ScheduleGridCoverSize",
     "加完封面就排重排(comic_list_widget.py)"),
]
try:
    with zipfile.ZipFile(apk) as z:
        with z.open("assets/private.tar") as f:
            data = f.read()
    members = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        for name in t.getnames():
            if name.endswith(".pyc"):
                members[name] = t.extractfile(name).read()
    for suffix, marker, label in checks:
        hits = [(n, b) for n, b in members.items() if n.endswith(suffix)]
        if not hits:
            print("  !! 找不到 {} —— APK 里没有 {} 的字节码".format(suffix, label))
            continue
        name, blob = hits[0]
        ok = marker in blob
        print("  {:<9} {:<44} {}".format("命中" if ok else "!! 旧代码", name,
                                         label if ok else label + " 缺失"))
except Exception as es:
    print("  校验 APK 内容失败: {}".format(es))
EOF
fi
[ "$diff" -eq 0 ]
