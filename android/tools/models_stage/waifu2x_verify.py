#!/usr/bin/env python3
"""waifu2x 9 个 onnx 身份验证：噪声档位匹配矩阵

对干净 crop 加 4 档高斯噪声，分别过 noise0-3 的 up2x / up1x 模型，
与干净 crop 对比 PSNR。正确身份应呈现对角线：noiseN 对 sigma≈N*8 噪声最优。
另外验证 up1x 输出确实小于输入(crop 边界)，up2x 输出 = 2x-72。
"""
import numpy as np
import onnxruntime as ort
from PIL import Image

DIR = "/root/jmcomic-build/models_out/waifu2x"
ori = np.asarray(Image.open("/root/jmcomic-build/demos/ori.jpg").convert("RGB")).astype(np.float32)
# ori 是 179x179，reflect pad 到 192x192
crop = np.pad(ori, ((0, 192 - ori.shape[0]), (0, 192 - ori.shape[1]), (0, 0)), mode="reflect")
h, w = crop.shape[:2]
assert (h, w) == (192, 192)
clean01 = crop / 255.0

def run(path, x):
    so = ort.SessionOptions(); so.log_severity_level = 3
    sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
    out = sess.run(None, {"x": x})[0]
    return out

def psnr(a, b):
    a = a.astype(np.float64); b = b.astype(np.float64)
    mse = ((a - b) ** 2).mean()
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)

print("clean crop:", clean01.shape, "range", clean01.min(), clean01.max())
print()
print("=== up2x 系列（输出应为 312x312，即 192*2-72） ===")
sigmas = [5, 15, 25, 35]
# 参考: 干净 crop 放大 2x 后 crop 到 312（双线性）
ref = np.asarray(Image.fromarray(crop.astype(np.uint8)).resize((384, 384), Image.BILINEAR))
ref312 = ref[36:348, 36:348]  # 312x312 中心

results = {}
for n in range(4):
    path = f"{DIR}/waifu2x_cunet_up2x_denoise{n}.onnx" if n else f"{DIR}/waifu2x_cunet_up2x.onnx"
    row = []
    for s in sigmas:
        rng = np.random.default_rng(42)
        noisy = np.clip(clean01 + rng.normal(0, s / 255.0, clean01.shape), 0, 1).astype(np.float32)
        out = run(path, noisy.transpose(2, 0, 1)[None])[0]
        out = np.clip(out.transpose(1, 2, 0) * 255.0, 0, 255)
        # PSNR vs 干净参考（312 域）
        if out.shape[:2] == (312, 312):
            row.append(psnr(out, ref312))
        else:
            row.append(float("nan"))
    results[n] = row
    print(f"noise{n}: " + "  ".join(f"σ={s}:{v:5.2f}dB" for s, v in zip(sigmas, row)))

print()
print("=== up1x 系列（输出应为 136x136） ===")
for n in range(4):
    path = f"{DIR}/waifu2x_cunet_up1x_denoise{n}.onnx"
    row = []
    for s in sigmas:
        rng = np.random.default_rng(42)
        noisy = np.clip(clean01 + rng.normal(0, s / 255.0, clean01.shape), 0, 1).astype(np.float32)
        out = run(path, noisy.transpose(2, 0, 1)[None])[0]
        out = np.clip(out.transpose(1, 2, 0) * 255.0, 0, 255)
        if out.shape[:2] == (136, 136):
            # 参考: 干净 crop crop 到 136 中心
            ref136 = crop[28:164, 28:164]
            row.append(psnr(out, ref136))
        else:
            row.append(float("nan"))
    print(f"noise{n}: " + "  ".join(f"σ={s}:{v:5.2f}dB" for s, v in zip(sigmas, row)))

print()
print("=== 对角线检验（up2x） ===")
ok = True
for i, n in enumerate(range(4)):
    row = results[n]
    best = int(np.nanargmax(row))
    if best != i:
        ok = False
    print(f"  noise{n}: 最优 σ={sigmas[best]}（期望 {sigmas[i]}）{'✓' if best == i else '✗'}")
print("对角线" + ("成立 ✓" if ok else "不成立 ✗"))
