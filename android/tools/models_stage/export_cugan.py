#!/usr/bin/env python3
"""Real-CUGAN ONNX 导出（SE 11 + PRO 6 = 17 个模型）

- 固定输入 1x3x192x192 float [0,1]（与引擎约定一致）
- 输出 1x3x(T*scale)x(T*scale) float [0,1]
- 复刻官方 upcunet_v3.py tile_mode=0 前向：
    2x: reflect pad 18 -> unet1 -> unet2(alpha=1) -> crop20 -> add -> (pro变换)
    3x: reflect pad 14 -> ... 同上
    4x: reflect pad 19 -> ... -> conv_final -> crop1 -> PixelShuffle2 -> +nearest4x(x00) -> (pro变换)
- pro: 输入 x*0.7+0.15, 输出 (y-0.15)/0.7; se: 恒等
- 输出不做 round/clamp（引擎侧负责 uint8 量化）
"""
import os, sys, collections
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, "/root/jmcomic-build/models_src/src")
from upcunet_v3 import UpCunet2x, UpCunet3x, UpCunet4x

TILE = 192
SE_DIR = "/root/jmcomic-build/models_src/se_weights"
PRO_DIR = "/root/jmcomic-build/models_src/pro_weights"
OUT_DIR = "/root/jmcomic-build/models_out/cugan"

# (pth 文件, 类, scale, pro, 输出文件名)
JOBS = [
    # ---- SE 11 ----
    ("up2x-latest-no-denoise.pth",   UpCunet2x, 2, False, "realcugan_se_up2x.onnx"),
    ("up2x-latest-conservative.pth", UpCunet2x, 2, False, "realcugan_se_up2x_conservative.onnx"),
    ("up2x-latest-denoise1x.pth",    UpCunet2x, 2, False, "realcugan_se_up2x_denoise1.onnx"),
    ("up2x-latest-denoise2x.pth",    UpCunet2x, 2, False, "realcugan_se_up2x_denoise2.onnx"),
    ("up2x-latest-denoise3x.pth",    UpCunet2x, 2, False, "realcugan_se_up2x_denoise3.onnx"),
    ("up3x-latest-no-denoise.pth",   UpCunet3x, 3, False, "realcugan_se_up3x.onnx"),
    ("up3x-latest-conservative.pth", UpCunet3x, 3, False, "realcugan_se_up3x_conservative.onnx"),
    ("up3x-latest-denoise3x.pth",    UpCunet3x, 3, False, "realcugan_se_up3x_denoise3.onnx"),
    ("up4x-latest-no-denoise.pth",   UpCunet4x, 4, False, "realcugan_se_up4x.onnx"),
    ("up4x-latest-conservative.pth", UpCunet4x, 4, False, "realcugan_se_up4x_conservative.onnx"),
    ("up4x-latest-denoise3x.pth",    UpCunet4x, 4, False, "realcugan_se_up4x_denoise3.onnx"),
    # ---- PRO 6 ----
    ("up2x-no-denoise.pth",          UpCunet2x, 2, True,  "realcugan_pro_up2x.onnx"),
    ("up2x-conservative.pth",        UpCunet2x, 2, True,  "realcugan_pro_up2x_conservative.onnx"),
    ("up2x-denoise3x.pth",           UpCunet2x, 2, True,  "realcugan_pro_up2x_denoise3.onnx"),
    ("up3x-no-denoise.pth",          UpCunet3x, 3, True,  "realcugan_pro_up3x.onnx"),
    ("up3x-conservative.pth",        UpCunet3x, 3, True,  "realcugan_pro_up3x_conservative.onnx"),
    ("up3x-denoise3x.pth",           UpCunet3x, 3, True,  "realcugan_pro_up3x_denoise3.onnx"),
]


class CuganOnnx(nn.Module):
    """固定 192 输入的 tile_mode=0 前向（官方数学，无 round/clamp）"""

    def __init__(self, base, scale, pro):
        super().__init__()
        self.base = base
        self.scale = scale
        self.pro = pro

    def forward(self, x):  # x: 1x3x192x192 [0,1]
        t = x * 0.7 + 0.15 if self.pro else x
        if self.scale == 2:
            t = F.pad(t, (18, 18, 18, 18), "reflect")
            u = self.base.unet1.forward(t)
            x0 = self.base.unet2.forward(u, 1)
            u = F.pad(u, (-20, -20, -20, -20))
            y = torch.add(x0, u)
        elif self.scale == 3:
            t = F.pad(t, (14, 14, 14, 14), "reflect")
            u = self.base.unet1.forward(t)
            x0 = self.base.unet2.forward(u, 1)
            u = F.pad(u, (-20, -20, -20, -20))
            y = torch.add(x0, u)
        else:  # 4
            t0 = t  # pad 前的归一化输入（官方 x00）
            t = F.pad(t, (19, 19, 19, 19), "reflect")
            u = self.base.unet1.forward(t)
            x0 = self.base.unet2.forward(u, 1)
            u = F.pad(u, (-20, -20, -20, -20))
            y = torch.add(x0, u)
            y = self.base.conv_final(y)
            y = F.pad(y, (-1, -1, -1, -1))
            y = self.base.ps(y)
            y = y + F.interpolate(t0, scale_factor=4, mode="nearest")
        if self.pro:
            return (y - 0.15) / 0.7
        return y


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    dummy = torch.rand(1, 3, TILE, TILE, dtype=torch.float32)
    for pth_name, cls, scale, pro, out_name in JOBS:
        if only and out_name not in only:
            continue
        src = os.path.join(PRO_DIR if pro else SE_DIR, pth_name)
        out_path = os.path.join(OUT_DIR, out_name)
        print(f"=== {out_name} (from {pth_name}, scale={scale}, pro={pro}) ===")
        base = cls()
        sd = torch.load(src, map_location="cpu", weights_only=False)
        if isinstance(sd, dict) and "params_ema" in sd:
            sd = sd["params_ema"]
        base.load_state_dict(sd, strict=True)
        base.eval()
        wrapper = CuganOnnx(base, scale, pro)
        wrapper.eval()
        with torch.no_grad():
            ref = wrapper(dummy).numpy()
        torch.onnx.export(
            wrapper, (dummy,), out_path,
            opset_version=17, input_names=["x"], output_names=["y"],
            dynamic_axes=None, dynamo=False,
        )
        print(f"  exported: {os.path.getsize(out_path)/1e6:.2f} MB, ref out {ref.shape}")


if __name__ == "__main__":
    main()
