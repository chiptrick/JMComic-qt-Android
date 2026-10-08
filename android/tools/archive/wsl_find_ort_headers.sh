#!/usr/bin/env bash
# 找 onnxruntime C API 头文件的可达来源(raw.githubusercontent 不可达)
set -uo pipefail
ORT=1.23.2

echo "=== A) NuGet Microsoft.ML.OnnxRuntime ($ORT) ==="
curl -sSL -o /tmp/ort.nupkg -w 'http:%{http_code} size:%{size_download}\n' \
  "https://api.nuget.org/v3-flatcontainer/microsoft.ml.onnxruntime/$ORT/microsoft.ml.onnxruntime.$ORT.nupkg"
python3 - <<'EOF'
import zipfile, os
p='/tmp/ort.nupkg'
if os.path.exists(p) and os.path.getsize(p) > 10000:
    z=zipfile.ZipFile(p)
    hs=[n for n in z.namelist() if n.endswith('.h')]
    print('nupkg headers:', len(hs))
    for h in hs[:25]: print('   ', h)
else:
    print('nupkg 下载失败/过小')
EOF

echo "=== B) PyPI onnxruntime wheel 内容 ==="
curl -sSL -o /tmp/ort.whl -w 'http:%{http_code} size:%{size_download}\n' \
  "$(curl -sS https://pypi.org/pypi/onnxruntime/$ORT/json | python3 -c "import sys,json;d=json.load(sys.stdin);print([u['url'] for u in d['urls'] if 'manylinux' in u['filename'] and 'x86_64' in u['filename']][0])" 2>/dev/null || echo https://pypi.org/simple/onnxruntime/)"
python3 - <<'EOF'
import zipfile, os
p='/tmp/ort.whl'
if os.path.exists(p) and os.path.getsize(p) > 10000:
    try:
        z=zipfile.ZipFile(p)
        hs=[n for n in z.namelist() if n.endswith('.h')]
        print('wheel headers:', len(hs))
        for h in hs[:20]: print('   ', h)
    except Exception as e:
        print('whl 解压失败(可能不是 zip):', e)
else:
    print('wheel 下载失败/过小')
EOF

echo "=== C) 模型来源可达性 ==="
for url in https://huggingface.co https://hf-mirror.com https://modelscope.cn; do
  code=$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null) || code=FAIL
  printf '%-25s %s\n' "$url" "$code"
done

echo "=== D) Maven: onnxruntime-android-qnn AAR 是否存在 ==="
curl -sS -m 20 -o /dev/null -w 'aar:%{http_code} size:%{size_download}\n' -r 0-500 \
  "https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android-qnn/$ORT/onnxruntime-android-qnn-$ORT.aar"
