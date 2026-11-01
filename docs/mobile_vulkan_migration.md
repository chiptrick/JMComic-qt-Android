# 图形后端统一到 Vulkan：现状盘点与迁移方案

> 适用版本：0.82（RHI 后端 = Vulkan，换页动画 GPU 合成层已落地）
> 目标机型基线：vivo V2463A / Adreno / Android 14 / 1440×3168 / DPR 3.75 / 120Hz

## 0. 结论摘要

1. 本项目**从来没有"自己写 OpenGL 渲染代码"**，所有图形加速都是让 **Qt 用哪个 RHI 后端**
   的问题。QOpenGLWidget 只有一处（换页动画覆盖层），已在 0.82 改成 `QRhiWidget`，
   源码里不再有任何 `QOpenGL*` 依赖。
2. 剩下的"OpenGL 字样"分三类：已废弃的注释/历史错误串匹配、Qt 平台插件自己的报错文本、
   以及看图模块的**后端开关**（`tools/vulkan_accel.py`）。没有需要重写的 GL 绘制逻辑。
3. 统一到 Vulkan 的改造量集中在 **5 个文件 + 1 个打包脚本**，属于"收敛开关 + 补齐工具链"，
   不是"重写渲染层"。
4. 主要风险不在 Vulkan 本身，而在 **qsb 工具链（版本匹配）**、**无 Vulkan 机型/桌面端的降级**
   与 **Vulkan 的 Y 轴/纹理尺寸约束**。三处都已有明确兜底与回归。

## 1. 现状盘点：所有与图形后端相关的代码点

| # | 位置 | 作用 | 与 GL 的关系 | 处置 |
|---|---|---|---|---|
| 1 | `android/main.py: ApplyRhiBackend()` | QApplication 之前钉 `QT_WIDGETS_RHI=1` + `QT_WIDGETS_RHI_BACKEND=vulkan` | 决定窗口合成走 Vulkan | **保留**，唯一权威开关（见 §4.1） |
| 2 | `android/main.py: ApplySurfaceContainer()` | `QT_ANDROID_SURFACE_CONTAINER_TYPE=1`（TextureView） | 与 GL 无关，但决定"每帧一次纹理合成"的成本模型 | 保留 |
| 3 | `src/tools/vulkan_accel.py` | 探测 Vulkan 可用性 + 按设置写环境变量 + 状态查询 | **旧的 GL 加速入口**，已改为 Vulkan 语义 | **收敛**：不再与 #1 争夺开关（见 §4.1） |
| 4 | `src/config/setting.py: IsOpenVulkan`（旧键 `IsOpenOpenGL` 自动迁移） | 用户可见的"图片加速"开关 | 从 GL 改到 Vulkan | 保留；默认值建议改 1（见 §4.1） |
| 5 | `src/view/read/read_vulkan.py` | 看图视口（纯 QWidget，无图形上下文） | 旧实现是自带 GL 上下文的视口，已废弃 | 保留；改名/注释已澄清 |
| 6 | `src/view/read/read_graphics.py` | `QGraphicsView` 装配，按开关换视口 | 无 GL 调用 | 保留 |
| 7 | `src/component/widget/gpu_anim_cover.py` | 换页动画 GPU 合成层 | **原 QOpenGLWidget → 现 QRhiWidget** | **已迁移**（本轮） |
| 8 | `src/component/widget/animation_stack_widget.py` | 动画宿主、驱动、降级 | 依赖覆盖层接口 | 已适配（GPU/raster 双覆盖层） |
| 9 | `src/component/widget/shaders/animcover.{vert,frag,qsb}` | 着色器源码 + 预编译产物 | qsb = GLSL/Vulkan 通用容器 | 新增 |
| 10 | `android/tools/setup_qsb.sh` | 给 PySide6 轮子补 `qsb` 并烘焙 `.qsb` | 工具链 | 新增 |
| 11 | `android/tools/patch_buildozer_spec.py` | `source.include_exts` 放行 `qsb` | 打包 | 已加 |
| 12 | `src/qt_error.py`、`src/tools/mobile_ui_base.py`、`mobile_ui_window.py`、`mobile_ui.py` | 匹配历史崩溃文本 | 只匹配字符串 `QAndroidPlatformOpenGLWindow::eglSurface()` / `QOpenGLContext::makeCurrent` | **保留**（见 §3） |
| 13 | `src/tools/platform_mobile.py:606` | 关掉托盘/无边框等桌面特性 | 注释提到 GLES，无代码依赖 | 保留 |

### 1.1 为什么"GL 上下文"这条路在本项目里本来就走不通

Android 上**第二个顶层窗口**一渲染就会撞平台插件的全局死锁保护器直接 abort：

```
Abort message: 'Failed to acquire deadlock protector for
                QAndroidPlatformOpenGLWindow::eglSurface().'
栈: QWidget::setVisible -> show_sys -> flushWindowSystemEvents
    -> paintAndFlush -> QBackingStoreRhiSupport::create -> QRhi::create
    -> QOpenGLContext::makeCurrent -> eglSurface -> qFatal
```

这就是为什么：
* 所有提示框/错误框都改成了主窗口内的子控件（`qt_error.ShowAndroidError`）；
* 看图视口不再持有自己的 GL 上下文，而是把"最后一跳"交给窗口合成后端。

**结论：在本项目里，任何"自己拿 GL 上下文做渲染"的设计都是死路，Vulkan/RHI 是唯一方向。**

## 2. 现在的图形栈（一张链路图）

```
Python 业务/控件 (QWidget + QPainter，全部 CPU 栅格化)
        │  后备存储 (QBackingStore 位图)
        ▼
QBackingStoreRhiSupport  ── 环境变量 QT_WIDGETS_RHI=1 / _BACKEND=vulkan
        │  （把脏区上传成纹理，交给 GPU 合成）
        ▼
QRhi (Vulkan) ──► Adreno 驱动 ──► SurfaceTexture(TextureView) ──► 屏幕
        ▲
        │ 唯一的"自绘"旁路：换页动画覆盖层
QRhiWidget(GpuAnimCover)：两张页面纹理 + 2 次 draw + 视口位移
```

要点：**普通控件的绘制没有变**（仍是 QPainter 画到位图），Vulkan 只接管"位图→屏幕"这一跳；
GPU 覆盖层是唯一在 GPU 上直接画的东西，它必须用 `QRhiWidget` 才能和 Vulkan 合成共存。

## 3. "OpenGL 字样"的处置原则

| 类别 | 例子 | 处置 |
|---|---|---|
| 已废弃实现的注释 | `animation_stack_widget.py` 里的历史演进说明 | **保留**（解释为什么不能回头用 QOpenGLWidget，防止后人改回去） |
| 历史崩溃的错误串匹配 | `qt_error.py` / `mobile_ui_*.py` 里的 `eglSurface()` 文本 | **保留**：这是"日志匹配"，不是 API 调用；Qt 版本变了也可能再出现 |
| 真实 API 依赖 | `PySide6.QtOpenGL*`、`QOpenGLWidget` | **清零**（`host_test_gpu_layer.py` 会断言源码里不再出现） |

## 4. 统一迁移方案

### 4.0 一个必须记住的反直觉结论：不要设 `QT_WIDGETS_RHI=1`

Qt 的源码里确实有 `QT_WIDGETS_RHI`（libQt6Gui 的 `QBackingStoreRhiSupport`），看起来像
"打开 RHI 合成的开关"。但在本机（Qt 6.12 + TextureView 容器 + Adreno）实测：
**加上它之后 `QRhiWidget` 一律拿不到 RHI**，logcat 反复刷

```
W default : QRhiWidget: No QRhi
```

表现为 GPU 覆盖层全部降级，而且主窗口内容区高度错成 384×486（下半屏只剩背景色）。
去掉这一行、只留 `QT_WIDGETS_RHI_BACKEND=vulkan`，`No QRhi` 立刻归零、GPU 覆盖层恢复，
帧率也从 ~56fps 回到 ~107fps。

**结论：Android 上 Qt 默认就用 RHI 合成窗口，只设后端即可，别去"打开开关"。**

这个名字出现了**两个**写入点，0.84 已全部清除（原来只盯一处会以为已经修好）：

| 位置 | 原来写的 | 现在 |
|---|---|---|
| `android/main.py: ApplyRhiBackend()` | `QT_WIDGETS_RHI = "1"`（0.82 新加） | 只写 `QT_WIDGETS_RHI_BACKEND` |
| `src/tools/vulkan_accel.ApplyFromSetting()` | `os.environ[ENABLE_ENV] = "1"` | `os.environ.pop(ENABLE_ENV)`，只写后端 |

`vulkan_accel` 那处更隐蔽：它执行时机（窗口是否已经建好）决定了这一行是否生效，
所以会出现"同一份代码，热推时好、装包后坏"的抽风现象。`IsActive()` 也相应改成
只看后端（外部显式设 `QT_WIDGETS_RHI=0/false` 才视为关闭）。

### 4.1 启动期：唯一权威开关（必须最先执行）

问题现状（本次审计发现）：**两处在抢同一个开关**

* `android/main.py: ApplyRhiBackend()`（QApplication 之前）无条件写 `vulkan`
* `src/tools/vulkan_accel.ApplyFromSetting()`（start.py，QApplication 之后）按
  `Setting.IsOpenVulkan` 决定，且 `IsOpenVulkan` 默认是 **0（关）**

后果：默认安装的用户拿到的是"main.py 强制开的 Vulkan"，而设置里明明写着"关"；
一旦有人把 `ApplyRhiBackend` 的默认改掉，开机行为就随"设置默认值"漂移，很难排查。

**改造（建议，未实施）**：把决策收敛到一个函数，语义为"Android 默认开、桌面端跟随设置"：

```python
# android/main.py
def ApplyRhiBackend():
    # 只负责"默认值"：Android 默认 Vulkan；显式 env / sr_env.txt 可覆盖
    want = (os.environ.get("JM_WIDGETS_RHI") or "vulkan").strip().lower()
    os.environ["QT_WIDGETS_RHI"] = "1"
    os.environ["QT_WIDGETS_RHI_BACKEND"] = want
    os.environ.setdefault("QSG_RHI_BACKEND", want)

# src/tools/vulkan_accel.ApplyFromSetting()
#   已有逻辑不变，只是当 env 已经指到 vulkan 时把状态标成 "on(由启动器指定)"，
#   不再因为 Setting.IsOpenVulkan=0 就报 "off"，避免日志与实际不一致。
```

`IsOpenVulkan` 保留为"桌面端/高级用户开关"，Android 上以启动器为准（写进日志）。

### 4.2 合成层：动画用 QRhiWidget，普通控件继续走 RHI 合成

已实施，接口如下（`GpuAnimCover`）：

| 时机 | 动作 |
|---|---|
| `Begin(prev, next, type)` | 存两张 `QImage`、`show()`、`update()`、启动 120ms 看门狗 |
| `initialize(cb)` | 建 vbuf / 两张纹理 / sampler / 两个 srb / pipeline（`.qsb` 取不到就 `_broken`） |
| `render(cb)` | 有新快照时上传；`beginPass` → 视口 x=-off 画旧页 → 视口 x=W-off 画新页 → `endPass` |
| `SetReveal(v)` | 只改进度整数 + `update()`；每帧只改两个视口，仍无 uniform / 顶点上传 |
| 失败 | `BrokenHook` → `AnimationStackWidget._OnGpuBroken()` → `singleShot(0)` 切回 raster 覆盖层 |

关键约束（都是踩过的坑，写进代码注释）：
* 纹理尺寸**必须等于渲染目标像素尺寸**，否则 Qt 报
  `Invalid texture upload issued ... will be clamped`，画面错内容/黑块；
* Vulkan 的 NDC **y 轴朝下**，顶点 UV 要按后端翻（`_VertexData(yDown)`）；
* `QRhiResource.setName()` 只接受 `bytes`；
* `QRhiWidget` 取不到 RHI 时**不报错也不渲染**，必须有"一帧都没画"的看门狗。

#### 4.2.1 双纹理同步位移（P1，0.87）

不再用 scissor 揭示，改成两张纹理按同一个偏移一起移动：

```
off = round(reveal / logicalW * Wpx)        # 只算一次，两页共用
前进: prev.x = -off      next.x = Wpx - off  # 旧页左移、新页从右滑入
后退: prev.x = +off      next.x = off - Wpx  # 旧页右移、新页从左滑入
```

不变量（`host_test_gpu_layer.py` 逐条断言）：

* `next.x - prev.x == Wpx`（前进）/ `prev.x - next.x == Wpx`（后退）→ 接缝严格相接，
  不会漏出 clear color，也不会 1px 重叠；
* `off == Wpx` 时 `prev.x == -Wpx` → 落地瞬间旧页完全移出，左边缘不留 1px 残边；
* 偏移是**整数设备像素**，且两页共用同一个值（分别 `round` 会在 DPR=3.75 时差 1px）。

为什么用视口而不是 uniform：视口偏移不需要改 `.qsb`、不需要 UBO/顶点上传；
视口允许负 x，屏幕外部分由光栅化裁剪，每帧实际着色像素仍约一屏，填充率不翻倍。

已知限制：GPU 已经画出若干位移帧后中途失败时，`_FallbackToRaster()` 会用 raster 的
"揭示"语义续播，画面从"位移"切成"擦除"。首帧都没画出来（120ms 看门狗）的情况反而
看不到这个切换——那 120ms 屏幕上一直是静止的旧页，回退后直接从当前进度开始揭示。
GPU 一开始就不可用时全程走 raster，也不存在切换。

### 4.3 看图链路：保持"无图形上下文"

`ReadVulkan` 只是个普通 `QWidget` + 正确的背景角色，绘制仍由 `QGraphicsView` 完成。
**不要**为了"更快的看图"再引入 `QOpenGLWidget` / `QVulkanWindow`：

* `QVulkanWindow` 在 PySide6 里**没有绑定**，Python 侧拿不到 VkDevice/swapchain；
* 第二个 GL 上下文会撞 §1.1 的死锁保护器。

### 4.4 打包：`.qsb` 必须进 private.tar

`p4a` 只复制 `source.include_exts` 放行的文件。已在 `patch_buildozer_spec.py` 里保证
`qsb` 在列表中（与 `onnx/txt` 同机制），并在构建日志里打印最终值：

```
.qsb 随 private.tar 分发, source.include_exts=py,png,jpg,kv,atlas,qml,js,onnx,txt,qsb
```

运行时 `.qsb` 位于 `<private>/app/app_src/component/widget/shaders/`，
`gpu_anim_cover._SHADER_DIR` 按 `__file__` 定位，`GpuAvailable()` 会先检查文件是否存在。

### 4.5 诊断与状态出口

* `vulkan_accel.GetStatus()` / `IsActive()` / `GetBackendName()`：日志与设置页显示"当前后端"。
* 探针（`.workbuddy/probe/probe_fps.py`、`probe_gpuvis.py`）报告：覆盖层类型、驱动间隔、
  帧间隔分位、≤8.33ms 占比、>16.7ms 次数、`paintEvent` 耗时。
* `host_test_gpu_layer.py`：宿主侧守 `.qsb` 合法性、无 GL 依赖、UV 方向、位移偏移语义。

## 5. 迁移范围

### 已完成（0.82 → 0.84）

| 文件 | 改动 |
|---|---|
| `src/component/widget/gpu_anim_cover.py` | QOpenGLWidget → `QRhiWidget`；`.qsb` 着色器；双纹理视口位移；纹理尺寸/UV/看门狗 |
| `src/component/widget/animation_stack_widget.py` | `UseGpuCover=True`；`BrokenHook` 中途降级；快照留存 |
| `src/component/widget/shaders/*` | 着色器源码 + 预编译 `.qsb` |
| `android/main.py` | 只写 `QT_WIDGETS_RHI_BACKEND`（**不能**写 `QT_WIDGETS_RHI=1`，见 §4.0） |
| `src/tools/vulkan_accel.py` | 不再写 `ENABLE_ENV`（同上），`IsActive()` 改成只看后端 |
| `android/tools/patch_buildozer_spec.py` | `.qsb` 放行 |
| `android/tools/setup_qsb.sh` | 补 qsb 工具链 + 烘焙（无需 root） |
| `android/tools/host_test_gpu_layer.py` | 新增回归 |

### 待办（按优先级）

1. **收敛启动开关**（§4.1）：`vulkan_accel` 与 `ApplyRhiBackend` 二选一，默认值写清楚。
2. `IsOpenVulkan` 默认值改 **1**（或按机型探测结果决定），并让设置页直接显示
   `vulkan_accel.GetBackendName()`（现在是 "raster"/"vulkan"，用户能自检）。
3. 桌面端（Windows）验证：`QRhiWidget` 在 D3D11 合成下的行为（本项目桌面端默认可能
   仍是 raster 合成，此时 `GpuAnimCover` 会走看门狗降级；日志会留一条 ERROR，建议改成 INFO）。
4. 着色器工具链固化：把 `qt6-shader-baker` 的版本写进构建文档；升级 PySide6 时重跑
   `setup_qsb.sh`（Qt 与 qsb 主版本跨度大时优先用 aqtinstall 装同版本）。

## 6. 兼容性风险

| 风险 | 触发条件 | 表现 | 现有兜底 | 建议 |
|---|---|---|---|---|
| 设备/驱动无 Vulkan | 老机型、模拟器（部分） | `QT_WIDGETS_RHI_BACKEND=vulkan` 下 Qt 退回 raster 并打警告 | `vulkan_accel.IsSupported()` 探测；覆盖层看门狗降级 | 构建期/首启探测后自动改写 `JM_WIDGETS_RHI=raster` |
| 误设 `QT_WIDGETS_RHI=1` | 有人"好心"把它当成开关打开 | `QRhiWidget: No QRhi` ×N，GPU 层全废，窗口高度错乱（384×486） | 无自动兜底，靠 `host_test_gpu_layer` + 这份文档 | **不要设**；`main.py` 里已写死注释 |
| 窗口没有 RHI 合成 | 桌面 Linux 无 GL 驱动、Qt 未启用 RHI 合成 | `QRhiWidget` 永不 `render()` → 动画期间页面被藏住 | **120ms 看门狗** → raster 覆盖层 | 同左；把日志级别降到 INFO |
| qsb 版本不匹配 | 升级 PySide6 到跨大版本 | `QShader.fromSerialized` 返回 `isValid()=False` | `initialize()` 抛错 → `_broken` → raster | `host_test_gpu_layer.py` 在 CI/构建前跑 |
| `.qsb` 没进包 | 有人改了 `include_exts` | `GpuAvailable()` 假 → 一直 raster（功能正常，只是慢） | `GpuAvailable()` 检查文件存在 | 构建日志断言 include_exts 含 qsb |
| 纹理尺寸不匹配 | 页面快照与栈尺寸不一致（页面没被重新布局） | `Invalid texture upload ... clamped`，画面错内容/黑块 | `_FitImage()` 裁剪/缩放 | 同左 |
| Y 轴方向 | 切到 OpenGL 后端 | 动画画面上下颠倒 | `_VertexData(yDown)` 按后端选 | 同左 |
| 显存压力 | 两张 1395×2685 RGBA ≈ 15MB ×2 | 低端机可能 OOM/掉帧 | 动画结束即 `End()`；资源随 widget 复用 | 必要时改成"只上传脏带"的下采样纹理 |
| TextureView 额外合成 | 所有 Android 设备（当前默认） | 每帧多一次纹理合成（量级 ≤1ms） | `QT_ANDROID_SURFACE_CONTAINER_TYPE=0` 可切回 SurfaceView（多任务快照会黑） | 保持 TextureView |
| QNN/超分共存 | 超分在跑时切页 | 主线程被推理回调占用 → 帧间隔抖动 | 动画只依赖主线程事件循环，无法完全避免 | 超分排队（已有队列）时避免触发换页动画 |
| 多窗口 | 任何第二个顶层窗口 | 见 §1.1 的 abort | 全部改子控件覆盖层 | 继续保持"单顶层窗口"约定 |
| 位移依赖负视口 x | 某些驱动对 viewport x<0 处理不同 | 旧页不移动或被裁掉 | 偏移已钳制在 [-W, W]；实在不行改用 uniform 偏移 | **真机复测**：V2463A 上抽帧确认旧页整体左移 |

## 7. 验证方式

### 7.1 宿主（不需要手机，几十秒）

```bash
cd <构建树>/src && export QT_QPA_PLATFORM=offscreen
python3 ../android/tools/host_test_gpu_layer.py     # .qsb / 无 GL 依赖 / UV / 位移偏移
python3 ../android/tools/host_test_anim_cover.py    # 窄带、快照缓存、延后 SwitchCurrent
python3 ../android/tools/host_test_back_reader.py   # 返回键与看图栈
python3 ../.workbuddy/probe/host_check_grid.py      # 图文对齐（封面左右边界）
python3 ../.workbuddy/probe/host_check_cover.py     # 封面 pixmap 跟随 label 尺寸
```

### 7.2 真机（V2463A）

```bash
adb shell screenrecord --time-limit 20 --bit-rate 24000000 --size 720x1584 /sdcard/t.mp4 &
# 期间做：菜单 → 设置 → 返回 → 菜单 → 设置
adb pull /sdcard/t.mp4
python .workbuddy/probe/framescan2.py t.mp4     # 逐帧 YAVG，查黑帧/底色帧
adb logcat -d | grep -iE "GpuAnimCover|Invalid texture upload|watchdog|fallback"
```

抽帧看几何（`select=eq(n\,N)`，别用 `-ss`，screenrecord 是可变帧率）：

* 转场中段应看到**两页各占半屏、中间一条接缝**，且旧页显示的是它的**右半部分**
  （说明旧页整体左移；scissor 揭示时旧页始终从 x=0 开始，左半部分不会消失）；
* 落地前一帧左边缘不应残留 1px 旧页；
* 接缝处不应有黑线/亮线。

验收线：
* `覆盖层=GpuAnimCover`（不是 raster）
* 换页 ≥ 100fps 且 >16.7ms 的帧 ≤ 2 次/250ms（旧指标，位移版应不劣化）
* logcat 无 `Invalid texture upload` / `watchdog` / `fallback`
* 前进/后退各 3 次，抽帧均满足"两页同步位移"

### 7.3 打包校验

```bash
aapt dump badging android/JMComic-0.82-arm64-v8a-debug.apk | head -3
python3 android/tools/check_apk_qt_libs.py         # 构建脚本 4.5 步内置
unzip -p <apk> assets/private.tar | tar -tf - | grep '\.qsb$'
```

### 7.4 P1（双纹理位移）0.87 实测记录

真机 V2463A 当次离线，改用 **AVD Pixel_9_Pro_XL**（x86_64 / API 36.1 / `-gpu host`，
guest Vulkan 1.3）验证，结论如下：

| 项 | 结果 |
|---|---|
| 覆盖层类型 | `cover=gpu`（`GpuAnimCover`，`ready=True` / `broken=False`） |
| 首帧偏移 | `prevX=0  nextX=1308`（rt=1308×2547，reveal=0），与 §4.2.1 的公式一致 |
| 动画时长 | 设定 4000ms（取证用慢动作），实测 `4032ms` 结束 |
| 渲染帧数 | 4s 内 `paintCount=192`（≈48fps），无 `watchdog` / `fallback` / `Invalid texture upload` |
| 宿主断言 | `host_test_gpu_layer.py` 全部通过（偏移、接缝、落地无残留、无 scissor 依赖） |

**AVD 的已知限制（不是 P1 的问题）**：AVD 的 `screencap` / `screenrecord` 抓不到
`QRhiWidget` 层的像素（host composition 路径），转场期间只能拍到控件树本身
（内容区是黑底）。用 0.86 的 scissor 路径在同一台 AVD 上做 A/B 对照，**表现完全一致**
（同样是黑底 + 同样看不到覆盖层），说明这是 AVD 抓屏链路的限制，不是位移实现引入的回归。

因此：**像素级验收（接缝无黑线、落地无 1px 残留、旧页是否真的整体左移）仍然要在真机
V2463A 上做**，步骤见 §7.2。AVD 这边只作为"不崩、不降级、偏移算对、动画按时长走完"的验证。

取证手法（已回滚，仅供复现）：
1. 临时把 `AnimationStackWidget.AnimationMs` 调大（4000），让慢速设备/抓屏能拍到中间帧；
2. 在 `GpuAnimCover.Begin/首帧/End` 和 `SwitchWidgetByIndex` 临时打 `Log.Warn`
   （注意应用默认日志级别是 WARN，`Log.Info` 会被丢弃，日志文件在
   `files/state/jmcomic-qt/logs/<日期>.log`）；
3. A/B：临时把渲染循环换回 0.86 的 scissor 路径跑同一台设备，确认差异归属。

## 8. 回滚开关

| 想退回的状态 | 怎么做 |
|---|---|
| 关掉 GPU 合成层（只留 raster 窄带动画） | `animation_stack_widget.UseGpuCover = False` |
| 换页动画回到 Qt 自带动画驱动（16ms） | `UseTimerDriver = False` |
| 整个窗口回 raster 合成 | `sr_env.txt` 写 `JM_WIDGETS_RHI=raster`（`ApplyRhiBackend` 支持） |
| 关掉看图加速 | 设置里关 `IsOpenVulkan`（重启生效） |
