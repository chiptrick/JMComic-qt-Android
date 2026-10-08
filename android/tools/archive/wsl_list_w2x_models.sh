#!/usr/bin/env bash
# 列出 hf-mirror 上 waifu2x_onnx 仓库里我们需要的模型路径 + 构建状态
set -uo pipefail
HF=https://hf-mirror.com
PY=/root/jmcomic-build/venv311/bin/python
curl -sS -m 40 "$HF/api/models/deepghs/waifu2x_onnx" -o /tmp/w2x.json
echo "=== 我们关心的模型路径 ==="
"$PY" - /tmp/w2x.json <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
sib = [f["rfilename"] for f in d.get("siblings", [])]
want = [s for s in sib if s.endswith(".onnx") and any(
    k in s for k in ("upconv_7", "cunet")) and any(k in s for k in ("/art/", "/photo/"))]
print("匹配数:", len(want))
for s in sorted(want):
    print("  ", s)
# 顶层目录结构
import collections
tops = collections.Counter("/".join(s.split("/")[:2]) for s in sib)
print("--- 顶层结构 ---")
for k, v in list(tops.items())[:12]:
    print("  %-40s %d" % (k, v))
EOF
echo
echo "=== 构建状态 ==="
bash /path/to/JMComic-qt/android/tools/wsl_build_status.sh 2>/dev/null | head -6
ls /root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/build/libs_collections/JMComic/arm64-v8a 2>/dev/null | tr '\n' ' '
