#!/usr/bin/env bash
# 从 hf-mirror 下载 waifu2x(cunet) ONNX，固化成 NPU 需要的固定 shape，
# 放进仓库 android/sr_qnn/models/，并把 models.txt 映射改成真实 cunet 模型
set -uo pipefail
WORK=/root/jmcomic-build
WIN=/path/to/JMComic-qt
MODELS_SRC="$WORK/models_src"
OUT="$WIN/android/sr_qnn/models"
VPY="$WORK/venv-host/bin/python"
REPO="deepghs/waifu2x_onnx"
TAG="20250502"
BASE="https://hf-mirror.com/$REPO/resolve/main/$TAG/onnx_models/cunet/art"
TILE="${TILE:-192}"
mkdir -p "$MODELS_SRC" "$OUT"
exec > >(tee -a "$WORK/logs/prepare_models.log") 2>&1

echo "===== [$(date +%T)] 1. 下载 cunet ONNX ====="
# 源文件 -> 目标文件名:倍数:降噪
MAP=(
  "noise3_scale2x.onnx:waifu2x_cunet_up2x_denoise3.onnx:2:3"
  "noise2_scale2x.onnx:waifu2x_cunet_up2x_denoise2.onnx:2:2"
  "noise1_scale2x.onnx:waifu2x_cunet_up2x_denoise1.onnx:2:1"
  "noise0_scale2x.onnx:waifu2x_cunet_up2x_denoise0.onnx:2:0"
  "scale2x.onnx:waifu2x_cunet_up2x.onnx:2:0"
  "noise3.onnx:waifu2x_cunet_up1x_denoise3.onnx:1:3"
  "noise2.onnx:waifu2x_cunet_up1x_denoise2.onnx:1:2"
  "noise1.onnx:waifu2x_cunet_up1x_denoise1.onnx:1:1"
  "noise0.onnx:waifu2x_cunet_up1x_denoise0.onnx:1:0"
)
ok=0
for item in "${MAP[@]}"; do
    IFS=':' read -r src dst scale noise <<< "$item"
    raw="$MODELS_SRC/$src"
    if [ ! -s "$raw" ]; then
        curl -sSL --retry 3 -m 600 -o "$raw" "$BASE/$src" || { echo "  下载失败 $src"; continue; }
    fi
    printf '  %-28s %s\n' "$src" "$(du -h "$raw" | cut -f1)"
    ok=$((ok + 1))
done
echo "已下载 $ok 个源模型"

echo
echo "===== [$(date +%T)] 2. 固化 shape 并校验(--tile $TILE) ====="
for item in "${MAP[@]}"; do
    IFS=':' read -r src dst scale noise <<< "$item"
    raw="$MODELS_SRC/$src"
    [ -s "$raw" ] || continue
    echo "--- $src -> $dst (倍数 $scale)"
    # prepare_models.py 支持 --name/--scale；一次处理一个文件
    "$VPY" "$WIN/android/tools/prepare_models.py" --src "$raw" --out "$OUT" \
        --tile "$TILE" --scale "$scale" --name "$dst" 2>&1 | tail -4
done

echo
echo "===== [$(date +%T)] 3. 更新 models.txt(指向真实 cunet 模型) ====="
"$VPY" - "$OUT/models.txt" <<'PYEOF'
import pathlib, re, sys
path = pathlib.Path(sys.argv[1])
if not path.exists():
    print("models.txt 不存在:", path); raise SystemExit
# 应用里默认用 CUNET 做下载、ANIME 做看图；这里把三者都映射到真实 cunet 模型
mapping = {
    "WAIFU2X_CUNET_UP2X_DENOISE3X": ("waifu2x_cunet_up2x_denoise3.onnx", 2, 3),
    "WAIFU2X_CUNET_UP2X_DENOISE2X": ("waifu2x_cunet_up2x_denoise2.onnx", 2, 2),
    "WAIFU2X_CUNET_UP2X_DENOISE1X": ("waifu2x_cunet_up2x_denoise1.onnx", 2, 1),
    "WAIFU2X_CUNET_UP2X_DENOISE0X": ("waifu2x_cunet_up2x_denoise0.onnx", 2, 0),
    "WAIFU2X_CUNET_UP2X": ("waifu2x_cunet_up2x.onnx", 2, 0),
    "WAIFU2X_ANIME_UP2X_DENOISE3X": ("waifu2x_cunet_up2x_denoise3.onnx", 2, 3),
    "WAIFU2X_ANIME_UP2X_DENOISE2X": ("waifu2x_cunet_up2x_denoise2.onnx", 2, 2),
    "WAIFU2X_ANIME_UP2X_DENOISE1X": ("waifu2x_cunet_up2x_denoise1.onnx", 2, 1),
    "WAIFU2X_ANIME_UP2X_DENOISE0X": ("waifu2x_cunet_up2x_denoise0.onnx", 2, 0),
    "WAIFU2X_ANIME_UP2X": ("waifu2x_cunet_up2x.onnx", 2, 0),
    "WAIFU2X_PHOTO_UP2X_DENOISE3X": ("waifu2x_cunet_up2x_denoise3.onnx", 2, 3),
    "WAIFU2X_PHOTO_UP2X_DENOISE2X": ("waifu2x_cunet_up2x_denoise2.onnx", 2, 2),
    "WAIFU2X_PHOTO_UP2X_DENOISE1X": ("waifu2x_cunet_up2x_denoise1.onnx", 2, 1),
    "WAIFU2X_PHOTO_UP2X_DENOISE0X": ("waifu2x_cunet_up2x_denoise0.onnx", 2, 0),
    "WAIFU2X_PHOTO_UP2X": ("waifu2x_cunet_up2x.onnx", 2, 0),
    "WAIFU2X_CUNET_UP1X_DENOISE3X": ("waifu2x_cunet_up1x_denoise3.onnx", 1, 3),
    "WAIFU2X_CUNET_UP1X_DENOISE2X": ("waifu2x_cunet_up1x_denoise2.onnx", 1, 2),
    "WAIFU2X_CUNET_UP1X_DENOISE1X": ("waifu2x_cunet_up1x_denoise1.onnx", 1, 1),
    "WAIFU2X_CUNET_UP1X_DENOISE0X": ("waifu2x_cunet_up1x_denoise0.onnx", 1, 0),
}
lines = path.read_text(encoding="utf-8").splitlines()
out, changed = [], 0
for line in lines:
    s = line.strip()
    if not s or s.startswith("#"):
        out.append(line); continue
    parts = s.split()
    name = parts[0]
    if name in mapping:
        f, sc, dn = mapping[name]
        out.append("%-34s %-34s %d  %d  %d" % (name, f, sc, dn, int(parts[4]) if len(parts) > 4 else 192))
        changed += 1
    else:
        out.append(line)
path.write_text("\n".join(out) + "\n", encoding="utf-8")
print("models.txt 更新条目:", changed)
PYEOF

echo
echo "===== [$(date +%T)] 4. 结果 ====="
ls -sh "$OUT"/*.onnx 2>/dev/null | head -12
echo "onnx 文件数: $(ls "$OUT"/*.onnx 2>/dev/null | wc -l)"
