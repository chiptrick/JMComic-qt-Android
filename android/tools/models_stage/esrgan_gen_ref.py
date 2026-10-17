#!/usr/bin/env python3
"""ESRGAN torch 参考输出（与 simplify_generic.TestInput 一致的固定输入）"""
import os, sys
import numpy as np
import torch

sys.path.insert(0, "/root/jmcomic-build/models_src/src")
sys.path.insert(0, "/root/jmcomic-build")
from export_esrgan import RrdbOnnx, SrvggOnnx, load_st, load_pth, W_DIR, TILE

REF_DIR = "/root/jmcomic-build/models_out/esrgan_ref"
os.makedirs(REF_DIR, exist_ok=True)

gridY, gridX = np.mgrid[0:TILE, 0:TILE]
x = np.zeros((1, 3, TILE, TILE), dtype=np.float32)
x[0, 0] = 0.9 + 0.1 * np.sin(gridX / 7.0)
x[0, 1] = 0.9 + 0.1 * np.cos(gridY / 9.0)
x[0, 2] = 0.95
x[0, :, ::13, :] = 0.05
x[0, :, :, ::17] = 0.05
rng = np.random.default_rng(11)
feed = np.clip(x + rng.normal(0, 0.01, x.shape), 0, 1).astype(np.float32)

jobs = [
    ("x4plus.safetensors", "st", RrdbOnnx(23), "realesrgan_x4plus_up4x.onnx"),
    ("anime_6B.pth", "pth", RrdbOnnx(6), "realesrgan_x4plus_anime_up4x.onnx"),
    ("animevideo_v3.safetensors", "st", SrvggOnnx(4), "realesrgan_animevideo_v3_up4x.onnx"),
    ("animevideo_v3.safetensors", "st", SrvggOnnx(3), "realesrgan_animevideo_v3_up3x.onnx"),
    ("animevideo_v3.safetensors", "st", SrvggOnnx(2), "realesrgan_animevideo_v3_up2x.onnx"),
]
for wname, kind, wrapper, out_name in jobs:
    sd = load_st(os.path.join(W_DIR, wname)) if kind == "st" else load_pth(os.path.join(W_DIR, wname))
    missing, unexpected = wrapper.net.load_state_dict(sd, strict=False)
    assert not missing and not unexpected, f"missing={missing[:3]} unexpected={unexpected[:3]}"
    wrapper.eval()
    with torch.no_grad():
        out = wrapper(torch.from_numpy(feed)).numpy()
    np.save(os.path.join(REF_DIR, os.path.splitext(out_name)[0] + ".npy"), out)
    print(f"{out_name}: ref {out.shape} range [{out.min():.3f}, {out.max():.3f}]")
