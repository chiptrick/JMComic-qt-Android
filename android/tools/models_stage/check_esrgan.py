import torch, sys, os
# anime_6B.pth 身份确认
p = "/root/jmcomic-build/models_src/esrgan_weights/anime_6B.pth"
sd = torch.load(p, map_location="cpu", weights_only=False)
if isinstance(sd, dict) and "params_ema" in sd: sd = sd["params_ema"]
if isinstance(sd, dict) and "params" in sd and not any("body" in k for k in sd): sd = sd["params"]
keys = list(sd.keys())
print("anime_6B.pth keys:", len(keys))
print("  first:", keys[:2])
print("  has conv_first:", any("conv_first" in k for k in keys), "| has body.0:", any("body.0" in k for k in keys))
nb = len(set(k.split(".")[1] for k in keys if k.startswith("body.") and "rdb" not in k.split(".")[1] and k.split(".")[1].isdigit()))
print("  body blocks:", nb)
# safetensors 可用性
try:
    import safetensors
    print("safetensors OK", safetensors.__version__)
except ImportError as e:
    print("safetensors MISSING:", e)
