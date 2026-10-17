# sr_qnn 模型导出工具链（31 个 ONNX 的复现管线）

这个目录记录 `android/sr_qnn/models/` 里 **31 个 ONNX**（9 waifu2x + 17 Real-CUGAN
+ 5 Real-ESRGAN）是怎么从官方权重一步步做出来的。脚本原本跑在 WSL 构建环境
（`/root/jmcomic-build/`，见 `android/tools/env.sh` 的 `JM_WORK`）里，路径按当时
的环境写死；换机器时改脚本顶部的路径常量即可，逻辑不变。

模型文件本身（约 218MB）按 `.gitignore` 规则**不入库**，由构建流程从工作区同步
进 APK（`wsl_build_apk.sh` → `patch_buildozer_spec.py --models`）。

## 环境

WSL Ubuntu + `/root/jmcomic-build/venv311`（Python 3.11）：

```
pip install torch --index-url https://download.pytorch.org/whl/cpu   # 2.14.1+cpu
pip install onnx onnxsim onnxruntime safetensors ncnn
```

## 目录约定（WSL 侧）

| 路径 | 内容 |
| --- | --- |
| `models_src/src/` | 官方架构代码：`upcunet_v3.py`（Real-CUGAN）、`rrdbnet_arch.py` / `srvgg_arch.py`（Real-ESRGAN）、basicsr stub（`arch_util.py` 同目录思路，registry 直通） |
| `models_src/se_weights/` | Real-CUGAN SE 官方权重 11 个（up2x/up3x/up4x × no-denoise/conservative/denoise1x/denoise2x/denoise3x） |
| `models_src/pro_weights/` | Real-CUGAN PRO 权重 6 个（up2x/up3x × no-denoise/conservative/denoise3x），由 ncnn 转换而来 |
| `models_src/esrgan_weights/` | Real-ESRGAN：`anime_6B.pth` + `x4plus.safetensors` + `animevideo_v3.safetensors`（HF 版） |
| `models_src/ncnn_wasm/` | nihui/realcugan-ncnn-vulkan 的 6 个 PRO ncnn param/bin（pro 权重的中间来源） |
| `models_src/*.onnx` | waifu2x cunet 的 9 个 HF 动态 shape onnx（noise0-3 + art scale2x） |
| `models_out/{waifu2x,cugan,esrgan}/` | 最终产物（静态化 + QNN 友好化后） |
| `models_out/{waifu2x,cugan,esrgan}_raw_bak/` | simplify 前的原始导出备份 |
| `models_out/{cugan,esrgan}_ref/` | torch wrapper 的参考输出 npy（对账用） |

权重来源：
- waifu2x：HF `deepghs/waifu2x_onnx`（镜像 Library-Mutsumi/waifu2x_onnx）的
  `cunet/art/noise{0..3}[_scale2x].onnx`
- Real-CUGAN SE：官方 updated_weights（bilibili/Real-CUGAN）
- Real-CUGAN PRO：`nihui/realcugan-ncnn-vulkan` 的 `models-pro/`（ncnn 格式），
  用 `ncnn2torch_final.py` 转成 PyTorch state_dict；up3x 的 conservative /
  no-denoise 两个是后补下载的（`dl_pro3x.sh`）
- Real-ESRGAN：`xinntao/Real-ESRGAN` release 的 `RealESRGAN_x4plus_anime_6B.pth`；
  x4plus 与 animevideo_v3 用 HF 的 safetensors 版（**TF 布局**，见下）

## 管线

### 1. waifu2x（9 个）

HF 动态 shape onnx → 静态化 → 重命名 → 噪声档位验证：

```bash
# 静态化(与 android/tools/simplify_models.py 同一套逻辑)
python android/tools/simplify_models.py <hf onnx 目录> --tile 192 --write
# 重命名到 models.txt 规范名(scale2x -> waifu2x_cunet_up2x.onnx 等)
bash models_stage/rename_waifu2x.sh
# 噪声档位矩阵验证身份：干净图加 4 档高斯噪声，art/noise0 应单调降、
# noise3 在高 σ 下应显著优于 art
python models_stage/waifu2x_verify.py
```

cunet 内部有 crop，固定输入 192 时 **2x 实际输出 312、1x 输出 136**（不是 384/192），
引擎靠探针实测这个值， models.txt 的倍数列仍写原生倍数。

### 2. Real-CUGAN（17 个）

```bash
# (仅 pro) 补下载 up3x-conservative / up3x-no-denoise 的 ncnn 权重
bash models_stage/dl_pro3x.sh
# ncnn param/bin -> PyTorch pth(ncnn bin 的 weight 带 0x01306B47 tag 的 fp16,
# bias 是无 tag 的 fp32; 逐层与 torch 前向对账 166.4~175.1 dB)
python models_stage/ncnn2torch_final.py
bash models_stage/convert_all_pro.sh
bash models_stage/verify_all_pro.sh

# 导出 17 个 onnx(固定 1x3x192x192 输入)
python models_stage/export_cugan.py
# torch wrapper 参考输出(固定输入: 正弦渐变+条纹+噪声, rng(11))
python models_stage/gen_ref.py
# 静态化 + QNN 友好化 + 与参考对账
python models_stage/simplify_generic.py models_out/cugan --ref-dir models_out/cugan_ref --write
```

导出复刻官方 `upcunet_v3.py` 的 tile_mode=0 前向，按倍数分：

| 倍数 | 前向 |
| --- | --- |
| 2x | reflect pad 18 → unet1 → unet2(alpha=1) → crop 20 → add |
| 3x | reflect pad **14**（不是 18）→ 同上 |
| 4x | reflect pad 19 → 同上 → conv_final → crop1 → PixelShuffle(2) → **+ nearest(x00)**（x00 = pad 前的输入） |

pro 与 se 的差别只是前后缀：pro 输入 `x*0.7+0.15`、输出 `(y-0.15)/0.7`；se 恒等。
导出 wrapper 把变换包进 onnx，产出与官方行为一致（torchΔ ≤ 3.5e-5）。

### 3. Real-ESRGAN（5 个）

```bash
python models_stage/export_esrgan.py
python models_stage/esrgan_gen_ref.py
python models_stage/simplify_generic.py models_out/esrgan --ref-dir models_out/esrgan_ref --write
python models_stage/check_esrgan.py        # 元数据/输出边长核对
bash models_stage/verify_anime6b.sh        # anime_6B.pth 与 RRDBNet 对账
```

- `x4plus` / `x4plus_anime`：RRDBNet 原生 4x → 768
- `animevideo_v3`：SRVGGNetCompact(upscale=4) + **末端双线性**缩到目标倍数
  （up4x→768、up3x→576、up2x→384）——它本来就是"4x 网络输出再缩放"的结构
- HF 的 safetensors 是 **TF 布局**：4D 权重若 `shape[2] != shape[3]` 则为
  `[out,kh,kw,in]`（PyTorch 合法布局恒有 kh==kw），加载时要 `permute(0,3,1,2)`
- `PRelu` 在 ONNX 里是**大写 R**（QNN 白名单写错大小写会误报"非 QNN 算子"）

### 4. 部署 + 对账

```bash
# 从 models_out 部署到仓库 models/，并核对 models.txt 的 41 条引用零缺失
bash models_stage/fix_deploy.sh
```

## 踩坑记录（都是实际踩过的）

1. **4x 导出的 `F.interpolate` 必须用 pad 前保存的 `t0`**（192→768）；用 pad 后的
   t（230）会算出 920，尺寸对不上。
2. **Git Bash 的 MSYS 路径转换**：`wsl -u root -- bash -c '...'` 的单引号里如果含
   `/mnt/...`、`/root/...` 子串，可能被转换成 Windows 路径导致变量变空、文件误落
   到 WSL 根目录。可靠做法：`MSYS_NO_PATHCONV=1 wsl -u root -- bash -c '...'`，
   或把脚本写到 Windows 侧再 cp 进 WSL 执行。
3. **basicsr stub** 要提供 `register()` / `register_module` / `get()` 三个入口，
   rrdbnet_arch.py 用的是 `@ARCH_REGISTRY.register()`。
4. ncnn bin 格式：weight = `[4B tag 0x01306B47][fp16 alignSize(2ws,4)]`，
   bias = `[fp32 4×out 无 tag]`。
5. CUGAN pro/se 架构完全同一，别为 pro 单独写一套前向。

## 与引擎的接口约定

- 输入 `1x3x192x192` float [0,1]，输出 float [0,1]；**onnx 内不做 round/clamp**，
  由引擎侧 ×255、+0.5、clamp 到 uint8
- 输出边长不一定是 `tile × 倍数`（cunet 收缩；animevideo_v3 是 4x 网络缩放出来的），
  引擎用全 0 输入探针实测，见 `sr_qnn.cpp` 的 ProbeOutput
- models.txt 最后一列是**固定输入边长**（全部 192），不是输出边长
