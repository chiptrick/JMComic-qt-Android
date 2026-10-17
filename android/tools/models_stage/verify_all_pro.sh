#!/bin/bash
# torch(转换权重) vs ncnn(官方加载) 数值一致性 —— 全部 6 个 PRO 模型
source /root/jmcomic-build/venv311/bin/activate
cd /root/jmcomic-build/models_src/ncnn_wasm
python3 - << 'PYEOF'
import sys, numpy as np, torch
sys.path.insert(0, "/root/jmcomic-build/models_src/src")
import ncnn
from PIL import Image
from upcunet_v3 import UpCunet2x, UpCunet3x

def psnr(a, b):
    a = a.astype(np.float64); b = b.astype(np.float64)
    mse = ((a - b) ** 2).mean()
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)

ori = np.asarray(Image.open("/root/jmcomic-build/demos/ori.jpg").convert("RGB")).astype(np.float32)
h0, w0 = ori.shape[:2]

MODELS = [
    ("up2x-conservative", 2, UpCunet2x),
    ("up2x-denoise3x", 2, UpCunet2x),
    ("up2x-no-denoise", 2, UpCunet2x),
    ("up3x-conservative", 3, UpCunet3x),
    ("up3x-denoise3x", 3, UpCunet3x),
    ("up3x-no-denoise", 3, UpCunet3x),
]

for name, scale, cls in MODELS:
    net = ncnn.Net()
    net.opt.use_vulkan_compute = False
    net.opt.num_threads = 8
    net.load_param(f"{name}.param")
    net.load_model(f"{name}.bin")
    x = ori * (0.7 / 255.0) + 0.15
    ph = ((h0 - 1) // 2 + 1) * 2; pw = ((w0 - 1) // 2 + 1) * 2
    xp = np.pad(x, ((18, 18 + ph - h0), (18, 18 + pw - w0), (0, 0)), mode="reflect")
    H, W = xp.shape[:2]
    m = ncnn.Mat(W, H, 3)
    m.numpy()[:] = np.transpose(xp, (2, 0, 1))
    ex = net.create_extractor()
    ex.input("in0", m)
    ret, out = ex.extract("out0")
    ncnn_out = out.numpy()

    model = cls()
    sd = torch.load(f"/root/jmcomic-build/models_src/pro_weights/{name}.pth", weights_only=False)
    model.load_state_dict(sd, strict=True)
    model.eval()
    with torch.no_grad():
        t = torch.from_numpy(np.transpose(ori, (2, 0, 1))).unsqueeze(0) * (0.7 / 255.0) + 0.15
        n, c, hh, ww = t.shape
        phh = ((hh - 1) // 2 + 1) * 2; pww = ((ww - 1) // 2 + 1) * 2
        tt = torch.nn.functional.pad(t, (18, 18 + pww - ww, 18, 18 + phh - hh), 'reflect')
        u1 = model.unet1.forward(tt)
        u2 = model.unet2.forward(u1, 1)
        u1c = torch.nn.functional.pad(u1, (-20, -20, -20, -20))
        raw = torch.add(u2, u1c)
        raw = raw[:, :, :hh * scale, :ww * scale]
    torch_out = raw.squeeze(0).numpy()

    ncnn_c = ncnn_out[:, :torch_out.shape[1], :torch_out.shape[2]]
    if ncnn_c.shape == torch_out.shape:
        d = np.abs(ncnn_c.astype(np.float64) - torch_out.astype(np.float64))
        print(f"{name}: max abs diff = {d.max():.6f}, PSNR(torch vs ncnn) = {psnr(torch_out, ncnn_c):.1f} dB")
    else:
        print(f"{name}: SHAPE MISMATCH ncnn {ncnn_c.shape} torch {torch_out.shape}")
PYEOF
