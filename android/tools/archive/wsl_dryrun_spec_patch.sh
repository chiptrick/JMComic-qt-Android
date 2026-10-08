#!/usr/bin/env bash
# 干跑 patch_buildozer_spec.py：在 buildozer.spec 的副本上打补丁，检查关键行
# 临时目录里放一个 libs 软链，这样相对路径的解析方式与真实构建完全一致
set -uo pipefail
WORK="${WORK:-/root/jmcomic-build}"
A="$WORK/src/android"
VPY="$WORK/venv311/bin/python"
SRC="$A/buildozer.spec"
TMP=$(mktemp -d)
cp "$SRC" "$TMP/buildozer.spec" || { echo "没有 $SRC，先跑一次 --init"; exit 1; }
ln -sfn "$A/libs" "$TMP/libs"

echo "=== 打补丁前 ==="
grep -E '^(source\.include_exts|android\.add_assets)' "$TMP/buildozer.spec" || true

"$VPY" "$A/tools/patch_buildozer_spec.py" "$TMP/buildozer.spec" \
    --recipes "" --libs "libs/arm64-v8a" --models "$A/sr_qnn/models" 2>&1 | tail -20

echo
echo "=== 打补丁后 ==="
grep -E '^(source\.include_exts|android\.add_assets|android\.minapi|android\.api)' "$TMP/buildozer.spec" || true

echo
echo "=== add_libs 总数 / 其中 Qt 插件数 ==="
LIBS=$(grep -E '^android\.add_libs_arm64_v8a' "$TMP/buildozer.spec" | cut -d= -f2-)
echo "$LIBS" | tr ',' '\n' | sed '/^$/d' | wc -l
echo "$LIBS" | tr ',' '\n' | grep plugins || echo "(没有插件!)"

echo
echo "=== include_exts 是否含 onnx ==="
grep -E '^source\.include_exts' "$TMP/buildozer.spec" | grep -q onnx \
    && echo "[ok] include_exts 已放行 onnx" || echo "[FAIL] include_exts 仍不含 onnx"

echo
echo "=== android.add_assets 必须整行消失(空值会让 p4a 打包时 FileExistsError) ==="
if grep -qE '^android\.add_assets' "$TMP/buildozer.spec"; then
    echo "[FAIL] android.add_assets 仍然存在:"
    grep -nE '^android\.add_assets' "$TMP/buildozer.spec"
else
    echo "[ok] android.add_assets 已整行删除"
fi

echo
echo "=== 按补丁后的 include_exts 模拟 p4a 过滤 models/ ==="
"$VPY" - "$TMP/buildozer.spec" "$A/sr_qnn/models" <<'PY'
import os, sys
spec, mdir = sys.argv[1], sys.argv[2]
exts = set()
for line in open(spec, encoding="utf-8"):
    if line.startswith("source.include_exts"):
        exts = {e.strip().lower() for e in line.split("=", 1)[1].split(",") if e.strip()}
kept, dropped = [], []
for name in sorted(os.listdir(mdir)):
    ext = name.rsplit(".", 1)[-1].lower()
    (kept if ext in exts else dropped).append(name)
print("  include_exts =", sorted(exts))
print("  会保留 %d 个:" % len(kept), kept)
print("  被丢弃 %d 个:" % len(dropped), dropped)
assert "models.txt" in kept, "models.txt 必须随包(否则 srq_init 读不到模型表)"
assert len([n for n in kept if n.endswith(".onnx")]) == 9, "9 个 onnx 必须全部随包"
print("  [ok] 9 个 onnx + models.txt 都会进入 private.tar")
PY
rm -rf "$TMP"
