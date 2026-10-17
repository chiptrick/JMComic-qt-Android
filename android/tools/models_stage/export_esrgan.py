#!/usr/bin/env python3
"""Real-ESRGAN ONNX 导出（5 个模型）

- 固定输入 1x3x192x192 float [0,1]，输出 [0,1]（引擎约定）
- x4plus / x4plus_anime: RRDBNet 原生 4x -> 768
- animevideo_v3: SRVGGNetCompact(upscale=4) + 末端双线性缩放
    up4x: 768; up3x: 768*0.75=576; up2x: 768*0.5=384
"""
import os, sys
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, "/root/jmcomic-build/models_src/src")
from rrdbnet_arch import RRDBNet
from srvgg_arch import SRVGGNetCompact

TILE = 192
W_DIR = "/root/jmcomic-build/models_src/esrgan_weights"
OUT_DIR = "/root/jmcomic-build/models_out/esrgan"


class RrdbOnnx(nn.Module):
    def __init__(self, num_block):
        super().__init__()
        self.net = RRDBNet(3, 3, scale=4, num_feat=64, num_block=num_block, num_grow_ch=32)

    def forward(self, x):
        return self.net(x)


class SrvggOnnx(nn.Module):
    """animevideo_v3 4x 网络 + 末端双线性缩放到目标倍数"""

    def __init__(self, out_scale):
        super().__init__()
        self.net = SRVGGNetCompact(num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=16,
                                   upscale=4, act_type="prelu")
        self.factor = out_scale / 4.0

    def forward(self, x):
        y = self.net(x)
        if self.factor != 1.0:
            y = F.interpolate(y, scale_factor=self.factor, mode="bilinear", align_corners=False)
        return y


def load_st(path):
    from safetensors.torch import load_file
    sd = load_file(path)
    out = {}
    for k, v in sd.items():
        t = v.float()
        # HF 的 animevideo_v3.safetensors 是 TF 布局 [out, kh, kw, in]（PyTorch 合法布局恒有 kh==kw）
        if t.dim() == 4 and t.shape[2] != t.shape[3]:
            t = t.permute(0, 3, 1, 2).contiguous()
        out[k] = t
    return out


def load_pth(path):
    sd = torch.load(path, map_location="cpu", weights_only=False)
    if isinstance(sd, dict) and "params_ema" in sd:
        sd = sd["params_ema"]
    if isinstance(sd, dict) and "params" in sd and not any("conv_first" in k or "body.0" in k for k in sd):
        sd = sd["params"]
    return {k: v.float() for k, v in sd.items()}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    dummy = torch.rand(1, 3, TILE, TILE, dtype=torch.float32)
    jobs = [
        ("x4plus.safetensors", "st", RrdbOnnx(23), "realesrgan_x4plus_up4x.onnx"),
        ("anime_6B.pth", "pth", RrdbOnnx(6), "realesrgan_x4plus_anime_up4x.onnx"),
        ("animevideo_v3.safetensors", "st", SrvggOnnx(4), "realesrgan_animevideo_v3_up4x.onnx"),
        ("animevideo_v3.safetensors", "st", SrvggOnnx(3), "realesrgan_animevideo_v3_up3x.onnx"),
        ("animevideo_v3.safetensors", "st", SrvggOnnx(2), "realesrgan_animevideo_v3_up2x.onnx"),
    ]
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    for wname, kind, wrapper, out_name in jobs:
        if only and out_name not in only:
            continue
        out_path = os.path.join(OUT_DIR, out_name)
        print(f"=== {out_name} (from {wname}) ===")
        sd = load_st(os.path.join(W_DIR, wname)) if kind == "st" else load_pth(os.path.join(W_DIR, wname))
        net = wrapper.net if isinstance(wrapper, RrdbOnnx) else wrapper.net
        missing, unexpected = net.load_state_dict(sd, strict=False)
        # load_state_dict(strict=False) 返回 missing/unexpected；必须为空才是同一结构
        assert not missing and not unexpected, f"missing={missing[:3]} unexpected={unexpected[:3]}"
        wrapper.eval()
        with torch.no_grad():
            ref = wrapper(dummy).numpy()
        torch.onnx.export(
            wrapper, (dummy,), out_path,
            opset_version=17, input_names=["x"], output_names=["y"],
            dynamic_axes=None, dynamo=False,
        )
        print(f"  exported: {os.path.getsize(out_path)/1e6:.2f} MB, ref out {ref.shape} range [{ref.min():.3f}, {ref.max():.3f}]")


if __name__ == "__main__":
    main()
