# 厂商原生库（可选）

把**本机**的厂商库放进这个目录，重新打包 APK 时会自动并入 `libs/arm64-v8a/`
（见 `android/tools/wsl_build_apk.sh` 第 3 阶段的 `vendor_libs` 处理）。

## 为什么需要

QNN HTP 后端（Hexagon NPU）通过 **FastRPC** 与 DSP 通信，而 FastRPC 的客户端库
`libcdsprpc.so` 是厂商库，在 Android 10+ 上**不在应用的链接器命名空间里**：

```
[ sr_qnn] 警告: 加载 libcdsprpc.so 失败(FastRPC，HTP 必需):
          dlopen failed: library "libcdsprpc.so" not found
```

结果是：QNN EP 能挂上、会话能建，但 **HTP 设备建不起来**，QNN 一个节点都不接，
每块 tile 都回退到 CPU（实测 SM8750 上 ~400ms/块，是 NPU 应有水平的 10 倍）。
把库打进 APK 后，`dlopen("libcdsprpc.so")` 就能在应用自己的 lib 目录里找到它。

## 怎么拿

```bash
# 在连了手机的机器上执行（同一个机型，版本才对得上）
adb pull /vendor/lib64/libcdsprpc.so android/vendor_libs/libcdsprpc.so
```

如果这一步失败（部分机型 /vendor 不可读），可以试：

```bash
adb shell "su -c 'cp /vendor/lib64/libcdsprpc.so /sdcard/Download/'"
adb pull /sdcard/Download/libcdsprpc.so android/vendor_libs/libcdsprpc.so
```

## 打包

```bash
bash android/tools/wsl_build_apk.sh          # 或你平时用的打包入口
```

打包日志里会出现 `已并入厂商库: libcdsprpc.so`。装好后自检会打印：

```
FastRPC(libcdsprpc.so): 已打包
session waifu2x_cunet_up2x_denoise3.onnx -> HTP(整图)
```

## 注意

- 这个库是**设备专属**的，不要提交到仓库、也不要跨机型复用（不同 SoC/驱动版本
  的 FastRPC 协议不兼容，反而会让 HTP 直接崩）。
- 只解决 HTP。QNN 的 GPU(Adreno) 后端不走 FastRPC，不需要这个库。
