# 超分模型(高通 NPU 用)

这个目录存放 `libsr_qnn.so` 使用的 **固定输入 shape** ONNX 模型，以及模型清单
`models.txt`。手机端默认从应用的 `waifu2x-models` 目录读取（`JM_SR_MODELS` 可覆盖）。

## 为什么必须固定 shape

高通 QNN Execution Provider 不支持动态 shape，模型输入必须是确定的
`1×3×T×T`（T 见 `models.txt` 最后一列，默认 192）。引擎会把原图切成 T×T 的块、
用边缘像素补齐后送 NPU，回读后按有效区域无缝拼接，因此块大小不匹配也不会出错，
只是会失去“按图片自适应块大小”的能力。

## 为什么还必须“静态化”（这一步最容易漏，漏了整个 NPU 就白跑）

固定 shape 只解决输入维度；**图里如果有 `Shape` / `Reshape` / `ConstantOfShape`
这类动态 shape 写法，QNN 依然吃不下** —— QNN EP 的算子白名单里没有它们。

原来的 cunet 模型就是这种写法（257 个节点里 100+ 个是
`Shape`/`Gather`/`Concat`/`Reshape`/`ConstantOfShape`/`Where`/`Expand`），后果是：

* 严格 HTP 会话（`session.disable_cpu_ep_fallback=1`）失败；
* 退成“HTP + 允许 CPU 回退”，图被切成 NPU / CPU 两段，
  **每块 tile 都要在 NPU 与 CPU 之间来回搬张量** —— QNN 超分慢一大截的主因。

用 `android/tools/simplify_models.py` 把 shape 子图常量折叠掉即可
（输入固定，全部可折叠）：

```bash
# 先 dry-run 看报告：非 QNN 算子一列必须为空、max|Δ| 必须为 0
python android/tools/simplify_models.py android/sr_qnn/models

# 确认后写回（建议先备份原文件到仓库外）
python android/tools/simplify_models.py android/sr_qnn/models --write --backup /tmp/sr_models_orig
```

实测：**257 → 79 节点，只剩 Conv/LeakyRelu/Relu/Sigmoid/GlobalAveragePool/Mul/Add/
Pad/Expand/ConvTranspose/Clip（全部在 QNN 白名单内），输出与改写前逐位相同
（max|Δ| = 0）**。仓库里现在这 27 个模型（5 waifu2x + 17 Real-CUGAN +
5 Real-ESRGAN；4 个 cunet up1x 纯降噪模型不随包分发，需要时按 models.txt 自备）全部是静态化后的版本：非 QNN 算子为 0，且都与 PyTorch 参考输出
对账过（CUGAN/ESRGAN 的 max|Δ| ≤ 3.5e-5）。

> 换了模型文件后 context 缓存会自动失效：缓存的 key 现在是
> `文件名-大小-mtime-头部哈希`，旧缓存会被顺手清掉，不需要用户手动清数据。

## 生成模型

仓库现有的 27 个模型来自**官方 PyTorch 权重直接导出**（waifu2x upcunet 5 个、
Real-CUGAN 17 个、Real-ESRGAN 5 个；另有 4 个 cunet up1x 纯降噪模型不随包分发，
需要时自备同名 onnx），导出/静态化/对账脚本在
`android/tools/models_stage/`（在 WSL 里跑，见其中的 README）。要点：

* CUGAN 的 pro/se 只是前后缀变换不同（pro 输入 `x*0.7+0.15`、输出 `(y-0.15)/0.7`），
  导出时包在 wrapper 里，产出的 onnx 与官方行为逐位对齐（torchΔ ≤ 3.5e-5）；
* ESRGAN 的 HF safetensors 是 TF 布局（4D 权重 `[out,kh,kw,in]`），加载时要
  `permute(0,3,1,2)`；
* 每个模型导出后都过一遍静态化 + torch 参考对账 + 输出边长探针，才允许进 models/。

如果只是想拿现成的动态 shape onnx 做 NPU 适配（不走 PyTorch），用通用工具：

```bash
# 1) 准备源 onnx(动态 shape 也行)，例如 HuggingFace 上的 waifu2x_onnx 转换版
# 2) 固化 shape 并校验
python android/tools/prepare_models.py --src D:/waifu2x_onnx --tile 192 --verify

# 3) 静态化(必须！见上一节)，否则 QNN 只能跑"HTP+CPU 回退"
python android/tools/simplify_models.py android/sr_qnn/models --write

# 4) 想要 HTP 上最快，再生成量化模型(QNN HTP 原生只吃量化模型)
python android/tools/prepare_models.py --src D:/waifu2x_onnx --tile 192 \
       --quantize --calib-dir D:/anime_pics
#    默认 uint16 激活 + uint8 权重(minmax 标定)；--act-type uint8 更快、--per-channel 更准
#    注意：量化后仍要再跑一次第 3 步静态化

# 5) 生成结果在本目录(或 --out 指定目录)，文件名要和 models.txt 对上
```

把生成的 `*.onnx` 与 `models.txt` 一起：
* 打包进 APK：由 `android/tools/patch_buildozer_spec.py --models android/sr_qnn/models`
  把 `onnx/txt` 加进 `source.include_exts`，模型随 `assets/private.tar` 分发
  （刻意不用 `android.add_assets`：那会往 APK 里再塞一份副本，且原生 `fopen`
  读不了 assets，只能走 Qt AssetManager）；或
* 安装后推送：

```bash
adb push android/sr_qnn/models/. \
    /sdcard/Android/data/<包名>/files/waifu2x-models/
```

## 默认模型映射

| 应用里选的模型 | 实际使用的 onnx | 说明 |
| --- | --- | --- |
| `MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X`（默认看图/下载） | `waifu2x_cunet_up2x_denoise3.onnx` | 动漫风格 2x + 降噪 3 |
| `MODEL_WAIFU2X_CUNET_*` | `waifu2x_cunet_*.onnx` | 真实 cunet 权重（官方 upcunet 导出） |
| `MODEL_WAIFU2X_PHOTO_*` | 复用 cunet | 该模型源里没有 photo 权重，如需请自行导出 |
| `MODEL_REALCUGAN_*` | `realcugan_{se,pro}_*.onnx` | 17 个全部随 APK 分发（se 11 + pro 6） |
| `MODEL_REALESRGAN_*` | `realesrgan_*.onnx` | 5 个全部随 APK 分发 |

models.txt 的 41 条引用对应 **31 个唯一 onnx**（waifu2x 的 PHOTO/CUNET 条目按设计
复用 ANIME 文件）；其中 4 个 cunet up1x 纯降噪模型**不随包分发**，随包实际为 27 个，
引擎在文件缺失时会跳过它们（界面也只列出可用的）。全部模型都是**官方 PyTorch 权重直接导出**（不是拿别人的 onnx 改
shape），导出/静态化/对账工具链见 `android/tools/models_stage/README.md`；
模型文件体积大（随包 27 个共约 198MB），由构建流程同步进 APK；
4 个 cunet up1x 纯降噪模型不入库，需要时自备（见上）。

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


## 独立进程模式（为什么 HTP 必须这么跑）

QNN HTP 依赖厂商库 `libcdsprpc.so`（FastRPC 通道）。**App 进程的链接器命名空间只允许
加载 `nativeLibraryDir` + `/vendor/etc/public.libraries.txt` 里列出的库**，而不少机型
（实测 vivo V2463A / SM8750）没把 `libcdsprpc.so` 列进去 —— 结果：

```
加载 libcdsprpc.so 失败(FastRPC，HTP 必需): dlopen failed: library "libcdsprpc.so" not found
→ HTP 设备建不起来 → QNN 0 个分区 → 每块 tile 退回 CPU（~400ms/块）
```

`android/sr_qnn/cpp/sr_qnn_proc.cpp` 把引擎放进**独立 native 进程**跑（产物
`libs/arm64-v8a/libsr_qnn_proc.so`，由 `sr_qnn/__init__.py` 用 subprocess 启动）：

- 子进程没有 classloader 命名空间限制，`LD_LIBRARY_PATH` 生效，
  `/vendor/lib64/libcdsprpc.so` **用设备自带的那份**即可，不必打包、不必按机型适配；
- QNN 库（Htp/System/Stub/Skel）仍随 APK 放在 `nativeLibraryDir`，通过
  `ADSP_LIBRARY_PATH` 提供给 DSP 侧；
- 只有 `extractNativeLibs=true`（本工程已满足）时 `nativeLibraryDir` 才可执行。

协议是 stdin/stdout 上的锁步二进制帧（`u32 cmd` + 定长字段 + 变长 blob），
Python 侧 `_ProcEngine` 负责排队/取消/编码。**进程模式启动失败会自动回退 ctypes
（进程内）**，功能不会丢，只是拿不到 NPU。

关闭方式：`JM_SR_PROC=0`（回到进程内，HTP 大概率不可用）。

## HTP 提速项与分级降级

`libsr_qnn.so` 挂 QNN EP 时按 **档位** 组装选项，任一档失败就降一级（`GetSession`）：

| 档位 | 内容 | 失败含义 |
| --- | --- | --- |
| 3（默认首选） | 基础项 + 全部提速项（性能模式、图编译档位、优先级、共享内存）+ **VTCM** | 多半是 VTCM 超出机型能力 |
| 2 | 同上但**不含 VTCM** | 某个非 VTCM 的提速项不被支持 |
| 1 | 基础项：`backend_path` + `enable_htp_fp16_precision` + `device_id` | QNN EP 本身挂不上 |
| 0 | 最小项：只给 `backend_path` | 连 fp16 都不被接受（极少见） |
| 兜底 | HTP + 允许 CPU 回退 → 最后才是纯 CPU EP | 面板会如实显示降级状态 |

> VTCM 之所以单独成档：它有实打实的卷积加速效果，但 2/4MB 的小 VTCM 机型上设 8MB 会让
> QNN 图编译失败。早期版本把它无条件放进**所有**尝试里，结果这些小机型整页静默退回
> CPU EP —— 这正是“QNN 超分比正常慢一大截”最常见的原因。现在它只在最高档尝试，
> 失败自动降到不含 VTCM 的档位，两头都不吃亏。

| 项 | 默认 | 作用 |
| --- | --- | --- |
| 性能模式（`JM_QNN_PERF`） | `burst` | QNN EP 官方示例用的最高性能档；交互式看图是突发负载，最适合 |
| 图编译优化档位（`JM_QNN_FINALIZE`） | `2` | 编译更久但运行时图更优；`3` 更极端（首次编译更慢） |
| fp16（`JM_QNN_FP16`） | `1` | fp32 模型以 fp16 在 HTP 上推理，带宽/内存减半 |
| 会话优先级（`JM_QNN_PRIORITY`） | `high` | DSP 上同时有其它 QNN 负载时降低排队延迟 |
| HTP 共享内存零拷贝 I/O（`JM_QNN_SHARED_MEM`） | `1` | 省掉每块 tile 的来回复制（需 `libcdsprpc.so`，探测不到自动跳过） |
| VTCM（`JM_QNN_VTCM`） | `8` | 有 VTCM 的机型卷积更快；编译不过会自动退回不含 VTCM 的档位 |
| context 缓存内嵌（`JM_QNN_EMBED_CTX`） | `1` | 缓存做成单个 onnx，避免 `.onnx`/`.bin` 分离后不同步就整块失效 |
| SSR 会话重建（`JM_QNN_SSR_RECOVER`） | `1` | HTP 子系统重启（SSR）后自动重建会话并重试当前分块，超分不会永久失效 |

量化模型建议：默认 `uint16` 激活 + `uint8` 权重（`minmax` 标定，QNN 推荐），追求速度可用
`--act-type uint8`，追求精度可加 `--per-channel`。

参考：ONNX Runtime QNN EP 文档的 *EP Provider Options*、*QNN context binary cache feature*、
*HTP SubSystem Restart* 小节（<https://onnxruntime.ai/docs/execution-providers/QNN-ExecutionProvider.html>），
以及 ORT 1.23.2 源码 `onnxruntime/core/providers/qnn/qnn_execution_provider.cc`、
`.../python/tools/quantization/execution_providers/qnn/quant_config.py`。

## 运行时结构（为什么不是线程越多越快）

NPU 是**单个计算引擎**：多个线程对同一个 QNN 上下文并发 `Run()` 只会在驱动里排队，
不会并行加速，反而多出锁竞争与 CPU 抢占。因此：

* HTP 模式固定 2 个 worker：一块在 NPU 上跑，另一块在 CPU 上打包/拆包，形成流水；
* 纯 CPU EP（没有 QNN 库）时才按核数开线程；
* 分块打包/拆包改成无内部分支的行级实现（arm64 用 NEON 做 RGB↔NCHW 与 fp16 互转），
  单块约 0.2ms 量级，主要意义是少跟 NPU 抢 CPU，不是主要收益来源。

## 分块边长：想再快一档就动这里

每块 tile 都是一次独立的 HTP 推理，**块数越少、每块浪费的补边越小，总耗时越低**。
cunet 的收缩边距固定（up2x 每边 18 像素输入），所以：

| tile | 实际输出 | 每块前进 | 1200×1800 一页的块数 |
| --- | --- | --- | --- |
| 192（当前默认） | 312×312 | 156 | 8×12 = 96 |
| 256 | 440×440 | 220 | 6×9 = 54 |
| 320 | 568×568 | 284 | 5×7 = 35 |

```bash
python android/tools/prepare_models.py --src <源 onnx> --tile 256 \
       --name waifu2x_cunet_up2x_denoise3.onnx --verify
```

并把 `models.txt` 最后一列改成 `256`。已实测 192 与 256 的输出差异（`mean |Δ|≈0.1/255`，
分块边界无位移、无缺带），但**单块计算量增长略超线性**：CPU EP 上 256 反而略慢，
HTP 上收益取决于机型 VTCM，建议在真机上对比 `tick` 后再决定是否换。

## 排查“QNN 比预期慢”

先把 native 日志打开（`android/main.py` 里 `sr_qnn.setDebug(True)` 会写 `sr_native.log`），
日志里现在会给出三条关键信息：

1. `session xxx.onnx -> HTP(整图) / HTP(CPU 回退) / CPU EP` —— 是否真的整图跑在 NPU 上；
   出现 **`HTP(CPU 回退)`** 通常就是模型没静态化（见上文），日志里还会有对应警告；
2. `workers=2 (htp:1, cpu threads:4)` —— 运行时线程数；
3. `task N: WxH step=156 tiles=96 pack+unpack=..ms run=..ms(total ..ms)` ——
   `run` 是 NPU 推理累计时间，`pack+unpack` 是 CPU 侧打包/回写。若 `pack+unpack` 占比
   明显（>20%），说明瓶颈在 CPU 侧；若 `run` 本身就大，说明 NPU 没用上/被降频。

面板地址（`srq_get_backend_info`）也会区分 `QNN HTP (部分算子 CPU 回退)` 与
`CPU (ONNX Runtime, QNN 未生效)`，不再一律显示成 NPU。

## 参数调试(环境变量)

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `JM_QNN_BACKEND` | `libQnnHtp.so` | QNN 后端库，可换 `libQnnGpu.so` / `libQnnCpu.so` |
| `JM_QNN_PERF` | `burst` | HTP 性能模式；长时间批量转换发热降频可试 `sustained_high_performance` |
| `JM_QNN_FP16` | `1` | fp32 模型以 fp16 精度在 HTP 上推理 |
| `JM_QNN_FINALIZE` | `2` | 图编译优化档位，越大编译越久但运行时更快(首次编译也会更慢) |
| `JM_QNN_VTCM` | `8` | HTP VTCM 大小(MB)；设 `0` 表示不下发(小 VTCM 机型的兜底手段) |
| `JM_QNN_RPC_LATENCY` | 不下发 | FastRPC 控制延迟(微秒)；块多时可试 `50`，代价是 CPU 占用略升 |
| `JM_QNN_WORKERS` | `2`(HTP) | 引擎工作线程数；NPU 上超过 2 没有收益 |
| `JM_QNN_PRIORITY` | `high` | QNN 上下文优先级：`low`/`normal`/`normal_high`/`high` |
| `JM_QNN_SHARED_MEM` | `1` | HTP 共享内存零拷贝 I/O(需 rpcmem/`libcdsprpc.so`) |
| `JM_QNN_VTCM_SHARE` | `0` | 多会话共享 VTCM 备份缓冲(省内存；与缓存内嵌互斥) |
| `JM_QNN_EMBED_CTX` | `1` | context 缓存内嵌成单个 onnx |
| `JM_QNN_SSR_RECOVER` | `1` | HTP 子系统重启后自动重建会话 |
| `JM_QNN_SOC_MODEL` / `JM_QNN_HTP_ARCH` | 空 | 机型需要时显式指定(见 QNN SDK) |
| `JM_SR_CACHE` | `models/context` | QNN context binary 缓存目录 |
| `JM_SR_MODELS` | 应用私有目录 | 模型目录 |
