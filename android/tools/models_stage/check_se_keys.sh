#!/bin/bash
# Inspect SE pth key structures and match against upcunet_v3 classes
source /root/jmcomic-build/venv311/bin/activate
python3 - << 'PYEOF'
import sys, torch
sys.path.insert(0, "/root/jmcomic-build/models_src/src")
import upcunet_v3
print("classes:", [n for n in dir(upcunet_v3) if n.startswith("UpCunet")])

import glob, os
for p in sorted(glob.glob("/root/jmcomic-build/models_src/se_weights/*.pth")):
    name = os.path.basename(p)
    sd = torch.load(p, map_location="cpu", weights_only=False)
    if isinstance(sd, dict) and "params_ema" in sd: sd = sd["params_ema"]
    if isinstance(sd, dict) and "params" in sd and not any(k.startswith("unet") or k.startswith("conv") for k in sd):
        sd = sd["params"]
    keys = list(sd.keys())
    print(f"\n{name}: {len(keys)} keys")
    print("  first:", keys[:3])
    print("  last :", keys[-3:])
    # 提取结构签名
    shapes = {k: tuple(v.shape) for k, v in sd.items()}
    print("  conv_bottom:", shapes.get("unet1.conv_bottom.weight"), shapes.get("unet2.conv_bottom.weight"))
PYEOF
