#!/bin/bash
source /root/jmcomic-build/venv311/bin/activate
python3 - << 'PYEOF'
import sys, types
bs = types.ModuleType("basicsr")
bs_utils = types.ModuleType("basicsr.utils")
bs_reg = types.ModuleType("basicsr.utils.registry")
class _Reg:
    def register(self, cls=None, **kw):
        def deco(c):
            return c
        if cls is not None:
            return cls
        return deco
bs_reg.ARCH_REGISTRY = _Reg()
bs.utils = bs_utils
bs_utils.registry = bs_reg
sys.modules["basicsr"] = bs
sys.modules["basicsr.utils"] = bs_utils
sys.modules["basicsr.utils.registry"] = bs_reg

import numpy as np, torch
sys.path.insert(0, "/root/jmcomic-build/models_src/src")
from PIL import Image
from rrdbnet_arch import RRDBNet

def psnr(a, b):
    a = a.astype(np.float64); b = b.astype(np.float64)
    mse = ((a - b) ** 2).mean()
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)

ori = np.asarray(Image.open("/root/jmcomic-build/demos/ori.jpg").convert("RGB")).astype(np.float32)
ref = np.asarray(Image.open("/root/jmcomic-build/demos/bc_anime6b.png").convert("RGB"))

model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=6, num_grow_ch=32, scale=4)
sd = torch.load("/root/jmcomic-build/models_src/esrgan_weights/anime_6B.pth", weights_only=False)
if "params_ema" in sd: sd = sd["params_ema"]
elif "params" in sd: sd = sd["params"]
sd = {k.replace("module.", ""): v for k, v in sd.items()}
model.load_state_dict(sd, strict=True)
model.eval()
with torch.no_grad():
    t = torch.from_numpy(np.transpose(ori, (2, 0, 1))).unsqueeze(0) / 255.0
    out = model(t)
y = np.clip(np.round(out.squeeze(0).numpy() * 255.0), 0, 255).astype(np.uint8)
y = np.transpose(y, (1, 2, 0))
print("4x out:", y.shape)
img = Image.fromarray(y)
for resample, name in [(Image.LANCZOS, "LANCZOS"), (Image.BICUBIC, "BICUBIC"), (Image.BILINEAR, "BILINEAR"), (Image.BOX, "BOX"), (Image.NEAREST, "NEAREST")]:
    d = np.asarray(img.resize((ref.shape[1], ref.shape[0]), resample)).astype(np.float64)
    print(f"anime_6B 4x->2x ({name}) vs official: PSNR = {psnr(d, ref.astype(np.float64)):.2f} dB")
PYEOF
