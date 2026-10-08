#!/usr/bin/env bash
# 用 python+certifi 下载 hf-mirror 的模型(它跳转到另一个主机，curl 验不过证书)
set -uo pipefail
WORK=/root/jmcomic-build
WIN=/path/to/JMComic-qt
VPY="$WORK/venv-host/bin/python"
MODELS_SRC="$WORK/models_src"
OUT="$WIN/android/sr_qnn/models"
REPO="deepghs/waifu2x_onnx"
TAG="20250502"
BASE="https://hf-mirror.com/$REPO/resolve/main/$TAG/onnx_models/cunet/art"
TILE="${TILE:-192}"
mkdir -p "$MODELS_SRC" "$OUT"
exec > >(tee -a "$WORK/logs/prepare_models2.log") 2>&1

FILES=(noise3_scale2x.onnx noise2_scale2x.onnx noise1_scale2x.onnx noise0_scale2x.onnx
       scale2x.onnx noise3.onnx noise2.onnx noise1.onnx noise0.onnx)

echo "===== [$(date +%T)] 1. python 下载(带 certifi) ====="
"$VPY" - "$BASE" "$MODELS_SRC" "${FILES[@]}" <<'PYEOF'
import os, ssl, sys, urllib.request
base, dest = sys.argv[1], sys.argv[2]
files = sys.argv[3:]
try:
    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
except Exception:
    ctx = ssl.create_default_context()
os.makedirs(dest, exist_ok=True)
for name in files:
    path = os.path.join(dest, name)
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        print("  已有", name, os.path.getsize(path) // 1024, "KB")
        continue
    url = f"{base}/{name}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "jmcomic-build"})
        with urllib.request.urlopen(req, timeout=300, context=ctx) as r, open(path, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        print("  下载", name, os.path.getsize(path) // 1024, "KB")
    except Exception as es:
        print("  失败", name, str(es)[:120])
        if os.path.exists(path):
            os.remove(path)
PYEOF

echo
echo "===== [$(date +%T)] 2. 兜底: curl -k 重试失败项 ====="
for f in "${FILES[@]}"; do
    p="$MODELS_SRC/$f"
    if [ ! -s "$p" ]; then
        echo "  curl -k $f"
        curl -sSLk --retry 2 -m 600 -o "$p" "$BASE/$f" && [ -s "$p" ] && echo "    ok $(du -h "$p" | cut -f1)" || rm -f "$p"
    fi
done
ls -sh "$MODELS_SRC" 2>/dev/null | head -12

echo
echo "===== [$(date +%T)] 3. 固化 shape(--tile $TILE) ====="
declare -A MAP=(
  [noise3_scale2x.onnx]="waifu2x_cunet_up2x_denoise3.onnx:2"
  [noise2_scale2x.onnx]="waifu2x_cunet_up2x_denoise2.onnx:2"
  [noise1_scale2x.onnx]="waifu2x_cunet_up2x_denoise1.onnx:2"
  [noise0_scale2x.onnx]="waifu2x_cunet_up2x_denoise0.onnx:2"
  [scale2x.onnx]="waifu2x_cunet_up2x.onnx:2"
  [noise3.onnx]="waifu2x_cunet_up1x_denoise3.onnx:1"
  [noise2.onnx]="waifu2x_cunet_up1x_denoise2.onnx:1"
  [noise1.onnx]="waifu2x_cunet_up1x_denoise1.onnx:1"
  [noise0.onnx]="waifu2x_cunet_up1x_denoise0.onnx:1"
)
for src in "${!MAP[@]}"; do
    raw="$MODELS_SRC/$src"
    [ -s "$raw" ] || continue
    dst="${MAP[$src]%:*}"; scale="${MAP[$src]##*:}"
    echo "--- $src -> $dst (倍数 $scale)"
    "$VPY" "$WIN/android/tools/prepare_models.py" --src "$raw" --out "$OUT" \
        --tile "$TILE" --scale "$scale" --name "$dst" --verify 2>&1 | tail -5
done

echo
echo "===== [$(date +%T)] 4. 结果 ====="
ls -sh "$OUT"/*.onnx 2>/dev/null
echo "onnx 文件数: $(ls "$OUT"/*.onnx 2>/dev/null | wc -l)"
