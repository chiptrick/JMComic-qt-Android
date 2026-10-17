#!/usr/bin/env python3
"""为 CUGAN onnx 生成 torch wrapper 参考输出（与 simplify_generic.TestInput 一致的固定输入）"""
import os, sys
import numpy as np
import torch

sys.path.insert(0, "/root/jmcomic-build/models_src/src")
from export_cugan import JOBS, CuganOnnx, TILE
from upcunet_v3 import UpCunet2x, UpCunet3x, UpCunet4x

REF_DIR = "/root/jmcomic-build/models_out/cugan_ref"
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

only = sys.argv[1:] if len(sys.argv) > 1 else None
for pth_name, cls, scale, pro, out_name in JOBS:
    if only and out_name not in only:
        continue
    from export_cugan import SE_DIR, PRO_DIR
    src = os.path.join(PRO_DIR if pro else SE_DIR, pth_name)
    base = cls()
    sd = torch.load(src, map_location="cpu", weights_only=False)
    if isinstance(sd, dict) and "params_ema" in sd:
        sd = sd["params_ema"]
    base.load_state_dict(sd, strict=True)
    base.eval()
    wrapper = CuganOnnx(base, scale, pro)
    wrapper.eval()
    with torch.no_grad():
        out = wrapper(torch.from_numpy(feed)).numpy()
    np.save(os.path.join(REF_DIR, os.path.splitext(out_name)[0] + ".npy"), out)
    print(f"{out_name}: ref {out.shape} range [{out.min():.3f}, {out.max():.3f}]")
