# 超分模型(高通 NPU 用)

这个目录存放 `libsr_qnn.so` 使用的 **固定输入 shape** ONNX 模型，以及模型清单
`models.txt`。手机端默认从应用的 `waifu2x-models` 目录读取（`JM_SR_MODELS` 可覆盖）。

## 为什么必须固定 shape

高通 QNN Execution Provider 不支持动态 shape，模型输入必须是确定的
`1×3×T×T`（T 见 `models.txt` 最后一列，默认 192）。引擎会把原图切成 T×T 的块、
用边缘像素补齐后送 NPU，回读后按有效区域无缝拼接，因此块大小不匹配也不会出错，
只是会失去“按图片自适应块大小”的能力。

## 生成模型

```bash
# 1) 准备源 onnx(动态 shape 也行)，例如 HuggingFace 上的 waifu2x_onnx 转换版
# 2) 固化 shape 并校验
python android/tools/prepare_models.py --src D:/waifu2x_onnx --tile 192 --verify

# 3) 想要 HTP 上最快，再生成量化模型(QNN HTP 原生只吃量化模型)
python android/tools/prepare_models.py --src D:/waifu2x_onnx --tile 192 \
       --quantize --calib-dir D:/anime_pics

# 4) 生成结果在本目录(或 --out 指定目录)，文件名要和 models.txt 对上
```

把生成的 `*.onnx` 与 `models.txt` 一起：
* 打包进 APK：`android.add_assets = sr_qnn/models`（buildozer.spec），或
* 安装后推送：

```bash
adb push android/sr_qnn/models/. \
    /sdcard/Android/data/<包名>/files/waifu2x-models/
```

## 默认模型映射

| 应用里选的模型 | 实际使用的 onnx | 说明 |
| --- | --- | --- |
| `MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X`（默认看图/下载） | `waifu2x_cunet_up2x_denoise3.onnx` | 动漫风格 2x + 降噪 3 |
| `MODEL_WAIFU2X_CUNET_*` | `waifu2x_cunet_*.onnx` | 真实 cunet 权重 |
| `MODEL_WAIFU2X_PHOTO_*` | 复用 cunet | 该模型源里没有 photo 权重，如需请自行导出 |
| `MODEL_REALCUGAN_*` / `MODEL_REALESRGAN_*` | 需要自己导出 | 没有对应文件时引擎自动回退到 waifu2x 并在日志里提示 |

### 模型来源（实测可用）

```bash
# hf-mirror 上 deepghs/waifu2x_onnx(镜像了 Library-Mutsumi/waifu2x_onnx)：
#   <tag>/onnx_models/cunet/art/noise{0..3}[_scale2x].onnx  -> 1x/2x + 降噪等级
# 用 android/tools/wsl_prepare_models.sh 可一键下载 + 固化 shape
python android/tools/prepare_models.py --src <下载的 onnx> --tile 192 --scale 2 \
       --name waifu2x_cunet_up2x_denoise3.onnx --verify
```

### cunet 的几何特性（引擎已自动处理）

cunet 不是"输入多大输出就乘几倍"的等变网络，实测（`--tile 192`）：

| 模型 | 输入 | 实际输出 | 每边收缩(输出像素) |
| --- | --- | --- | --- |
| cunet up1x | 192×192 | **136×136** | 28 |
| cunet up2x | 192×192 | **312×312** | 36 |

也就是说要得到"精确 N 倍"的输出，必须按 `m' = (T*s - O)/2` 在**输入侧**留出 `m'/s`
像素的边界。`sr_qnn.cpp` 现在会：

1. 会话建立后用一块全 0 的 `T×T` 做**一次探针推理**，量出真实输出边长 `O`
   （不猜、也不依赖 ONNX metadata）；
2. 据此算 `m' = (T*s - O)/2`，取 `pad = ceil(m'/s)`、`step = T - 2*pad`，
   有效区读取偏移 = `pad*s - m'`（恰好为 0），因此分块既不位移也不会缺带。

对不收缩的模型（`O == T*s`，如 Real-ESRGAN）`m' = 0`，引擎退回原来的小重叠策略，
行为与之前一致。回归测试见 `android/tools/host_test_sr_qnn.py` 的"收缩模型"用例
（它用一个"裁掉每边 18 像素再 2x 放大"的合成模型精确复现 cunet 几何）。
`prepare_models.py --verify` 仍会打印真实输出边长，可用来核对手上的模型属于哪一类。


## 参数调试(环境变量)

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `JM_QNN_BACKEND` | `libQnnHtp.so` | QNN 后端库，可换 `libQnnGpu.so` / `libQnnCpu.so` |
| `JM_QNN_PERF` | `sustained_high_performance` | HTP 性能模式，可试 `burst`(更热更快) |
| `JM_QNN_FP16` | `1` | fp32 模型以 fp16 精度在 HTP 上推理 |
| `JM_QNN_FINALIZE` | `2` | 图编译优化档位，越大越慢但更快 |
| `JM_QNN_VTCM` | `8` | HTP VTCM 大小(MB) |
| `JM_QNN_SOC_MODEL` / `JM_QNN_HTP_ARCH` | 空 | 机型需要时显式指定(见 QNN SDK) |
| `JM_SR_CACHE` | `models/context` | QNN context binary 缓存目录 |
| `JM_SR_MODELS` | 应用私有目录 | 模型目录 |
