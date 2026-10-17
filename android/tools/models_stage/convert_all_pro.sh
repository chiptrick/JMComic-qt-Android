#!/bin/bash
# Convert all 6 PRO ncnn models to torch pth, verify torch vs ncnn consistency
set -e
cd /root/jmcomic-build/models_src/ncnn_wasm
PY=/root/jmcomic-build/venv311/bin/python
OUT=/root/jmcomic-build/models_src/pro_weights
mkdir -p $OUT

for m in up2x-conservative up2x-denoise3x up2x-no-denoise up3x-conservative up3x-denoise3x up3x-no-denoise; do
    echo "=== convert $m ==="
    $PY ncnn2torch_final.py $m.param $m.bin $OUT/$m.pth ${m:2:1}
done
echo "=== all pth ==="
ls -la $OUT/
