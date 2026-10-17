#!/usr/bin/env python3
"""补测：up2x.onnx vs up2x_denoise0.onnx 应为同一模型（noise0 无降噪档）"""
import numpy as np
import onnxruntime as ort
from PIL import Image

DIR = "/root/jmcomic-build/models_out/waifu2x"
ori = np.asarray(Image.open("/root/jmcomic-build/demos/ori.jpg").convert("RGB")).astype(np.float32)
crop = np.pad(ori, ((0, 192 - ori.shape[0]), (0, 192 - ori.shape[1]), (0, 0)), mode="reflect")
x = (crop / 255.0).astype(np.float32).transpose(2, 0, 1)[None]

def run(path):
    so = ort.SessionOptions(); so.log_severity_level = 3
    sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
    return sess.run(None, {"x": x})[0]

a = run(f"{DIR}/waifu2x_cunet_up2x.onnx")
b = run(f"{DIR}/waifu2x_cunet_up2x_denoise0.onnx")
print("up2x.onnx          :", a.shape, f"range [{a.min():.4f}, {a.max():.4f}]")
print("up2x_denoise0.onnx :", b.shape, f"range [{b.min():.4f}, {b.max():.4f}]")
d = np.abs(a - b)
print(f"max|Δ| = {d.max():.6f}, mean = {d.mean():.8f}")
if d.max() < 1e-4:
    print("=> 同一模型 ✓（noise0 无降噪档位，两文件等价）")
else:
    print("=> 两文件不同！需要人工检查来源")
