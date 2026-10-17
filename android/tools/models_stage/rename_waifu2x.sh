#!/bin/bash
# 重命名 9 个 waifu2x onnx 到 models.txt 规范名并静态化
set -e
SRC=/root/jmcomic-build/models_src
OUT=/root/jmcomic-build/models_out/waifu2x
RAW_BAK=/root/jmcomic-build/models_out/waifu2x_raw_bak
PY=/root/jmcomic-build/venv311/bin/python
mkdir -p $OUT $RAW_BAK

cd $SRC
cp scale2x.onnx            $OUT/waifu2x_cunet_up2x.onnx
cp noise0_scale2x.onnx      $OUT/waifu2x_cunet_up2x_denoise0.onnx
cp noise1_scale2x.onnx      $OUT/waifu2x_cunet_up2x_denoise1.onnx
cp noise2_scale2x.onnx      $OUT/waifu2x_cunet_up2x_denoise2.onnx
cp noise3_scale2x.onnx      $OUT/waifu2x_cunet_up2x_denoise3.onnx
cp noise0.onnx              $OUT/waifu2x_cunet_up1x_denoise0.onnx
cp noise1.onnx              $OUT/waifu2x_cunet_up1x_denoise1.onnx
cp noise2.onnx              $OUT/waifu2x_cunet_up1x_denoise2.onnx
cp noise3.onnx              $OUT/waifu2x_cunet_up1x_denoise3.onnx
echo "=== copied 9 files ==="
ls -la $OUT/

# 先看原模型信息（输入输出名/opset）
$PY - << 'PYEOF'
import onnx, glob, os
for p in sorted(glob.glob("/root/jmcomic-build/models_out/waifu2x/*.onnx")):
    m = onnx.load(p)
    ins = [(i.name, [d.dim_value or d.dim_param for d in i.type.tensor_type.shape.dim]) for i in m.graph.input]
    outs = [(o.name, [d.dim_value or d.dim_param for d in o.type.tensor_type.shape.dim]) for o in m.graph.output]
    print(os.path.basename(p), "opset", [(op.domain or "ai.onnx", op.version) for op in m.opset_import])
    print("   in:", ins, "out:", outs)
PYEOF
