#!/bin/bash
# Download the two missing PRO ncnn models from nihui/realcugan-ncnn-vulkan
set -e
cd /root/jmcomic-build/models_src/ncnn_wasm
BASE="https://raw.githubusercontent.com/nihui/realcugan-ncnn-vulkan/master/models/models-pro"
for m in up3x-conservative up3x-no-denoise; do
    echo "--- $m.param"
    curl -skL --max-time 120 -w "http=%{http_code} size=%{size_download}\n" -o "$m.param" "$BASE/$m.param"
    echo "--- $m.bin"
    curl -skL --max-time 300 -w "http=%{http_code} size=%{size_download}\n" -o "$m.bin" "$BASE/$m.bin"
done
echo "=== result ==="
ls -la up3x-*.param up3x-*.bin
md5sum up3x-*.bin
echo "=== param diff (up2x vs up3x graph) ==="
diff up3x-conservative.param up3x-denoise3x.param && echo "PARAM_IDENTICAL"
