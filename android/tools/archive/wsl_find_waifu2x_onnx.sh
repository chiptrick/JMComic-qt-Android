#!/usr/bin/env bash
# 从 hf-mirror 找 waifu2x ONNX 模型（HuggingFace 主站不可达，镜像可用）
set -uo pipefail
HF=https://hf-mirror.com
PY=/root/jmcomic-build/venv311/bin/python

echo "=== 候选仓库的模型文件列表 ==="
for repo in Library-Mutsumi/waifu2x_onnx deepghs/waifu2x_onnx onnx-community/waifu2x \
            skbhadra/CartoonGAN thebiglaskowski/waifu2x-onnx; do
    code=$(curl -sS -m 25 -o /tmp/hf_$$.json -w '%{http_code}' "$HF/api/models/$repo" 2>/dev/null)
    echo "--- $repo (http=$code)"
    if [ "$code" = "200" ]; then
        "$PY" - /tmp/hf_$$.json <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
sib = [f["rfilename"] for f in d.get("siblings", [])]
onnx = [s for s in sib if s.endswith(".onnx")]
print("    文件数:", len(sib), " onnx:", len(onnx))
for s in onnx[:15]:
    print("      ", s)
if not onnx:
    for s in sib[:10]:
        print("      ", s)
EOF
    fi
done

echo
echo "=== 直接试搜 HuggingFace 镜像的模型搜索接口 ==="
curl -sS -m 25 "$HF/api/models?search=waifu2x&limit=20" -o /tmp/hfsearch.json 2>/dev/null
"$PY" - /tmp/hfsearch.json <<'EOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    for m in d[:20]:
        print(" ", m.get("modelId") or m.get("id"), "| downloads:", m.get("downloads"))
except Exception as es:
    print("搜索失败:", es)
EOF
