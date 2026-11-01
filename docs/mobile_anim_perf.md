# 移动端动画性能：现状、RHI 后端选择与实测数据

面向 Android 真机（vivo V2463A / SM8750 / Adreno / Android 14，1440×3168，DPR 3.75，
刷新率 120Hz → 每帧预算 8.33ms）。桌面端不需要这些取舍，全部逻辑只在 Android 生效。

## 1. 现在的架构

```
QWidget 顶层窗口（raster 绘制 → QRhi 合成 → Android TextureView）
  └─ AnimationStackWidget（页面栈）
       ├─ 两页快照（QPixmap，DPR 正确）
       ├─ _AnimCover（raster 覆盖层：按揭示进度只刷接缝窄带）
       └─ _TimerDriver（6ms 精确计时器驱动，Linear 缓动）
```

为什么不用 `QPropertyAnimation`：Qt 的动画驱动统一按 16ms 打点，实测封顶 62.8fps，
绘制再快也上不去。换成自建 6ms 计时器后，帧间隔 p50 从 16.5ms 降到 7.8~8.8ms。

为什么每帧只刷窄带：raster 的绘制代价 ≈ 脏区面积。整页脏区 30.4ms/帧（≈32fps），
120×120 脏区 9.2ms/帧，接缝窄带（12~19 逻辑px）1.5ms/帧。

## 2. RHI 后端：钉成 Vulkan（`android/main.py: ApplyRhiBackend`）

```
QT_WIDGETS_RHI_BACKEND=vulkan
QSG_RHI_BACKEND=vulkan
```

- 本机 Qt 默认就走 Vulkan，显式钉住是为了不同机型/Qt 版本行为一致。
- 覆盖率例外：`<AppDataDir>/sr_env.txt` 里写 `JM_WIDGETS_RHI=opengl` 可覆盖（仅排查）。

## 3. GPU 合成层：QOpenGLWidget 走不通，改用 QRhiWidget + .qsb（0.82 已落地）

### 3.1 为什么 QOpenGLWidget 不行（历史结论，别再回头）

1. `QOpenGLWidget` 构造不报错，但 `context()` 为 None、`isValid()` 恒 False —— 静默失效。
2. logcat 给出原因：

   ```
   W default: The top-level window is not using OpenGL for composition,
              'Vulkan' is not compatible with QOpenGLWidget
   ```

3. 把窗口后端切成 `QT_WIDGETS_RHI_BACKEND=opengl` 后同一段代码 `isValid()=True`，
   证明代码没问题，是"Vulkan 合成窗口"这个前提不满足。

### 3.2 补齐 qsb 工具链（0.82 解决）

PySide6 的 Linux 轮子只带运行时：`pyside6-qsb` 只是个包装器，最终 exec
`site-packages/PySide6/qsb`，而这个文件不存在，也没有 `libQt6ShaderTools`：

```
FileNotFoundError: .../site-packages/PySide6/qsb
```

`android/tools/setup_qsb.sh` 用 `apt-get download`（不需要 root）拉
`qt6-shader-baker`（提供 `qsb`）+ `libqt6shadertools6`（提供 `libQt6ShaderTools.so.6`），
解包后装进 venv：

```
site-packages/PySide6/qsb.real                            # 真正的 qsb 二进制
site-packages/PySide6/qsb                                 # shim：补 LD_LIBRARY_PATH
site-packages/PySide6/Qt/lib/libQt6ShaderTools.so.6*      # 唯一缺失的依赖
```

之后 `pyside6-qsb --version` 正常（实测 `qsb 6.10.2` 二进制 + Qt 6.12 运行时可用，
`.qsb` 容器版本向后兼容）。烘焙：

```bash
bash android/tools/setup_qsb.sh            # 安装工具链 + 烘焙 + 校验
bash android/tools/setup_qsb.sh --skip-install   # 只烘焙
```

产物 `animcover.{vert,frag}.qsb`（各 ~900 字节）里有 `SpirvShader`（Vulkan 必需）
+ `GlslShader/HLSL/MSL`，`host_test_gpu_layer.py` 会断言这一点。

### 3.3 踩坑：不要设 `QT_WIDGETS_RHI=1`

Qt 源码里有 `QT_WIDGETS_RHI`，看起来像"打开 RHI 合成"的总开关。0.82 包加上它之后
`QRhiWidget` 一律拿不到 RHI（logcat：`QRhiWidget: No QRhi`），GPU 覆盖层全废，
主窗口内容区高度还错成 384×486。去掉后 `No QRhi` 归零、帧率回到 ~107fps。
**Android 上 Qt 默认就用 RHI 合成，只设 `QT_WIDGETS_RHI_BACKEND` 即可。**

### 3.4 实现要点（`component/widget/gpu_anim_cover.py`）

* `QRhiWidget` 跟随窗口后端（Android 是 Vulkan），不硬写 `Api.Vulkan`（否则桌面无 Vulkan
  时直接建不起来）。
* 逐帧**零上传、零 uniform**：`beginPass` → 视口 x=-off 画旧页 → 视口 x=W-off 画新页。
  每帧 CPU 侧只剩两次 draw call（实测 `PaintMs` ≈ 0.1ms）。0.87 起由 scissor 揭示
  改为双纹理同步位移，偏移只算一次整数设备像素，两页共用（见 `mobile_vulkan_migration.md` §4.2.1）。
* 纹理尺寸 = 渲染目标像素尺寸；快照尺寸不一致时 `_FitImage()` 裁左上/平滑放大
  （否则 Qt 报 `Invalid texture upload issued ... will be clamped`，画面错内容或黑块）。
* Vulkan 的 NDC **y 轴朝下**，顶点 UV 按后端翻（`_VertexData(yDown)`），否则整个动画上下颠倒。
* `QRhiResource.setName()` 只接受 `bytes`。
* 看门狗：`Begin()` 后 120ms 若一帧都没渲染，判定 RHI 不可用 → 回调降级。
* 降级链：`initialize()/render()` 失败 → `BrokenHook` → `AnimationStackWidget._OnGpuBroken()`
  → `singleShot(0)` 用同一对快照切回 raster 覆盖层，动画不中断。

## 4. 实测

### 4.1 三代实现对比（首页→设置页，250ms，同机同条件）

| 指标 | 0.76 raster（Qt 驱动 16ms） | 0.80 raster（6ms + Linear） | **0.82 GPU（6ms + Linear）** |
|---|---|---|---|
| 帧率 | 39~44 fps | 92.9 / 111.5 fps | **122.8 fps**（稳态均值） |
| 帧间隔 p50 | 16.5~18.7 ms | 7.8~9.2 ms | **6.2 ms** |
| 帧间隔 p95 | 40~53 ms | 12.6~20.7 ms | **16.3 ms** |
| ≤8.33ms（120Hz 预算内） | — | — | **72%** |
| >16.7ms（明显掉帧） | 每帧 | 2~15 次/1.5s | **1 次 / 250ms** |
| 每帧 CPU 绘制 | 4.2~4.6 ms | 1.5~1.8 ms | **0.1 ms** |
| 主线程空闲停顿（1.5s） | — | 12 次 >16.7ms | **5 次 >16.7ms，max 36ms** |

### 4.2 驱动间隔扫描（0.82 GPU，稳态）

| 驱动间隔 | 帧率 | p50 | p95 | ≤8.33ms | >16.7ms |
|---|---|---|---|---|---|
| **6 ms** | **122.8 fps** | 6.2 ms | 16.3 ms | 72% | 1 次 |
| 7 ms | 100.5 fps | 7.1 ms | 35.3 ms | 77% | 4 次 |
| 8 ms | 115.5 fps | 8.0 ms | 14.9 ms | 63% | 1 次 |
| 9 ms | 90.4 fps | 9.0 ms | 29.4 ms | 9% | 3 次 |
| 10 ms | 93.5 fps | 10.0 ms | 18.7 ms | 38% | 4 次 |

6ms 最优（接缝更窄、每帧更便宜，形成正反馈）。注意这里的 "fps" 是**应用侧产出帧**，
不是屏幕实际刷新次数：Qt 在本机不会把帧率压到 vsync，所以平均 122.8fps 略高于 120Hz。

### 4.3 0.87：scissor 揭示 → 双纹理同步位移（P1）

* 合成方式变了（视口位移取代 scissor），**每帧仍然只有 2 次 draw、零 uniform/顶点上传**，
  填充率不变（屏幕外部分被光栅化裁掉，两页合计约一屏）。
* 帧率指标应当与 §4.1 的 GPU 行持平（同样的绘制量），真机复测入口见
  `mobile_vulkan_migration.md` §7.2；AVD 侧的功能性验证记录见同文 §7.4。
* 视觉收益：旧页与新页同时位移，观感接近"叠加式"转场；这是 P1 的目的，
  但**像素级验收必须真机做**（AVD 抓不到 QRhiWidget 层）。

### 4.2.1 同条件 A/B：GPU vs raster（0.84，帮助页↔设置页，384x787）

`probe_ab.py` 交替切换 `stack._gpuOk` 跑三轮，只有覆盖层不同：

| 覆盖层 | 各轮 fps | 最好一轮 | p50 | p95 | ≤8.33ms | >16.7ms |
|---|---|---|---|---|---|---|
| **GPU（QRhiWidget/Vulkan）** | 123.6 / 157.4 / 136.4 | **157.4 fps** | 6.1 ms | 10.3 ms | **85%** | 1 |
| raster（窄带 blit） | 113.3 / 142.0 / 136.3 | 142.0 fps | 5.7 ms | 11.2 ms | 78% | 1 |

结论：
* 满尺寸（384×787）下 GPU 比 raster 高 ~10%，120Hz 预算内帧占比从 78% 提到 85%；
* 窗口小或页面静态时两者接近（raster 的窄带本来就很便宜），GPU 的优势来自
  "页面越重、窗口越大"时的整窗合成成本；
* 真正的剩余瓶颈是主线程事件循环（空闲 1.5s 内仍有 5~16 次 >16.7ms 停顿），
  与覆盖层实现无关。

### 4.3 raster 时代的缓动曲线影响（0.80 数据，保留作对照）

| 曲线 | 帧率 | 接缝宽度 p50 | paint |
|---|---|---|---|
| OutCubic | 74~80 fps | 150+ 逻辑px（起步） | 15~18ms（头几帧） |
| OutQuad | 75~98 fps | 21 逻辑px | 2.0ms |
| InOutSine | 65.8 fps | 22 逻辑px | 2.2ms |
| **Linear** | **111.5 fps** | **12 逻辑px** | **1.5ms** |

结论：raster 时代"能不能到 120fps 取决于每帧接缝有多宽"；上了 GPU 合成层之后接缝宽度
不再主导帧成本（GPU 侧恒定 2 个 draw），瓶颈转移到了**主线程事件循环的调度抖动**。

## 5. 已知上限

- 纯 raster 路径在 3.75 DPR 下每帧固定成本 ≈ 9ms（整窗合成），这是 110fps 级别
  的天花板，破不了；要稳定 120fps 必须让动效离开 raster 覆盖层（见第 3 节的 QRhiWidget）。
- `QT_ANDROID_SURFACE_CONTAINER_TYPE=0`（SurfaceView）能省掉一层合成，但会让多任务
  快照/截屏拿不到画面（见 `android/main.py: ApplySurfaceContainer` 的说明），不可取。
- 降 DPR（3.75 → 2.0）能把每帧成本砍到 28%，代价是整屏变糊。

## 6. 复测方法

把 `.workbuddy/probe/probe_perf5.py` 覆盖到设备上的
`files/app/app_src/tools/mobile_ui_diag.py`，`touch files/perf_probe`，重启应用，
读 `files/android_startup.log`。它会输出：驱动间隔/缓动组合扫描、接缝宽度、
paint 耗时、空闲停顿分布、项构建成本、图文几何。

注意：测量时不要在动画中途 `grab()` 抓帧（会引入 ~360ms 停顿，把 111fps 测成 10fps）。

## 7. 顺带修掉的排版回归（0.78 → 0.80）

0.78 上出现过「封面只有 96px 宽、标题竖排叠字」，根因不在动画，在栅格排版和封面项
互相触发：

1. `RefreshItemSizeHints` 用 `sizeHint` 定栅格宽；而 QSS 内边距让 `sizeHint` 比实际宽 4px，
   `_GridOverflow` 于是每轮判"超宽"，`ApplyGridCoverSize` 把封面越收越窄（96px → 48px）。
   修法：`_ItemWidth()` 优先用已钉住的宽度；并**始终**把 item widget 钉到 cellW。
2. 定宽后没有重算 cellH，标题换行后变高 → 文字溢出压到下一项。
   修法：定宽后重算一遍 sizeHint 再 `setGridSize`。
3. `SyncContentWidth` 在 resizeEvent 里跑，和栅格排版互相触发（越排越小）。
   修法：去掉 resizeEvent 钩子，由栅格段落显式调用 `SyncContentWidth(notify=False)`。
4. 文字块只设 `maximumWidth` 不够（标签只拿 sizeHint 那么宽，右边界差 4~20px）。
   修法：标题 `setFixedWidth(contentWidth)`，其余小控件保持上限。

顺带修了返回键的老问题：`SwitchWidgetLast` 只切页面不裁 `subStackList`，导致
面包屑留着已退掉的层级、且下一次返回被判定为"已在第一级"直接弹"再按一次退出"。

## 8. 封面左右边界与标题对齐（0.81）

现象：封面比标题窄一圈（左右各留一条边），旧版是撑满的。

根因：缓存封面 400×533，比 label(147×200 逻辑 = 551×750 设备像素)小；
`DecodeCoverImage` 只在原图更大时才缩放，小图原样返回；而 `QLabel` 默认**居中绘制、
不缩放**，于是四周留白。旧版无条件 `scaled(label*ratio, KeepAspectRatio, Smooth)`
所以刚好铺满。

改动：

| 位置 | 改动 |
|---|---|
| `comic_item_widget.DecodeCoverImage()` | 解码后无论放大缩小都精确缩放到目标框 |
| `comic_item_widget.SetPicture(data, targetW, targetH)` | 支持显式目标尺寸（`setFixedSize` 尚未生效时不能读 `width()`） |
| `comic_item_widget.SyncContentWidth()/ResizeCover()` | 尺寸变化后用新算出的 width/height 重新解码 |
| `comic_item_widget._OnCoverDecoded()` | 解码期间 label 变大的兜底重解，只比「label vs 解码目标」（比 pixmap 实际尺寸会无限重解） |
| `mobile_ui_grid.RefreshItemSizeHints()` | 始终把 item 钉到 cellW；定宽后重算 cellH |
| `mobile_ui_grid._ItemWidth()` | 判超宽用「已钉住的宽度」而不是 sizeHint（QSS 内边距会大 4px，导致越排越窄） |

验收：`picLabel.width() == nameLable.width() == item 内容宽度`，
pixmap 逻辑宽度 == label 宽度（实测 147×196 vs 147×200，竖向 4px 属宽高比差异）。
宿主回归 `host_check_grid.py` / `host_check_cover.py` 必须 ALL PASS。

## 9. 换页黑屏闪烁 / 动画丢失（0.85 修复）

### 9.1 现象

* 每次页面切换，内容区整块变黑 20~280ms（既有"闪一下"也有"黑一段"）；
* 只有"旧页 → 黑 → 新页"，看不到滑动过渡（动画丢失）；
* 点菜单项之后再点设置页、按返回键回首页、从登录页切走时最明显。

### 9.2 三个叠加根因（按影响排序）

**① 隐藏页的尺寸不是栈尺寸，快照裁的是"另一个布局的左上角"**

`QStackedLayout` 只调整**当前页**的几何；隐藏页还停在自己的设计尺寸上。实测：

```
stack 372x716
当前页 IndexView   visible=True  size=372x716   ← 正确
目标页 SettingView visible=False size=880x805   ← 错
```

`_RenderPage` 按 880×805 拍出 3300×3019 的快照，覆盖层再把它裁到 1395×2685 ——
裁出来的是"880×805 布局的左上 42%"，动画里就是一张错位/空白图
（用户感知：动画没了，只闪一下）。

修：`_RenderPage` 拍之前先把目标页 `resize()` 到栈尺寸。

**② 快照渲染到未初始化的 QPixmap，透明区域是纯黑**

页面容器是 `WA_TranslucentBackground`（`component/widget/main_widget.py:25`），
页面本身也可能半透明（登录弹层）。`QPixmap(widget.size()*dpr)` 的内容未初始化，
`widget.render(pixmap)` 只画不透明部分，其余保留"未初始化内存"，实测呈纯黑。

修：`pixmap.fill(_BackgroundColor())` 先铺底色。

**③ 时序：先藏旧页再画覆盖层 / 先撤覆盖层再显新页**

* `SwitchWidgetByIndex` 原来是 `current.hide()` → `cover.Begin()`。GPU 覆盖层首帧
  要建管线 + 上传两张整页纹理（实测 +15~37ms），这段时间屏幕上什么都没有。
* `Finished()` 原来是 `cover.End()`（撤覆盖层）→ `setCurrentIndex` → `widget.show()`，
  中间同样有"两边都不可见"的窗口。
* 切页时面包屑要重建（`ClearTabBar` + `UpdateTabBar` 增删 `QToolButton`），
  `menuLayout` 会重排一次并连带触发 `subStackWidget.resizeEvent`；
  原来按钮文字是在动画**开始后**才改的，等于动画刚起步就被一次布局重排打断。

修：
* 覆盖层**先画出第一帧**（`GpuAnimCover.FirstFrame` 信号）再 `hide()` 旧页；
* `Finished()` 先 `setCurrentIndex` + `widget.show()`，跑完 `SwitchCurrent` 并
  `repaint()`，**最后**才 `cover.End()`；
* 面包屑按钮状态/文字在动画**开始前**改完，并 `menuLayout.activate()` 当场算完布局；
* `resizeEvent` 只在尺寸真的变了（>8px）时才落位，避免布局抖动掐掉动画；
* 落位（`_LandOnTarget`）必须先 `show()` + `repaint()` 新页再撤覆盖层。

**④ `_AnimCover` 没有快照时什么都不画**

它带 `WA_OpaquePaintEvent`，Qt 不会替它填背景，`_prev is None` 时 `return` 就是一块黑。
修：填 `_BackgroundColor()` 兜底。

### 9.3 修前后对比（V2463A，同一套操作：首页→设置→返回→设置→返回）

判据：逐帧 `YAVG`（ffmpeg `signalstats`）。深色主题下
"纯黑" ≈ 16~20、"只有底色" ≈ 23~27、"正常页面" ≈ 53~66。

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 低于 22（近纯黑）的帧 | 每次切换 2~5 帧 | **0 帧**（全片 min=22.8，仅 1 帧） |
| 每次切换的"只剩底色"时长 | **280ms**（正好覆盖整段动画） | 40~140ms（深色底，非纯黑） |
| 动画过渡 | 无（旧页→黑→新页） | 有（接缝从 1/3 推到 0，`YAVG` 平滑变化） |
| 快照亮度（目标页） | 底色级（~24） | 53.4（与正常显示一致） |
| 快照尺寸 | 3300×3019（错） | 1395×2685（= 372×716 × 3.75） |
| 快照亮度（目标页，首次进入） | 底色级（~24） | 53.4（与正常显示一致） |

### 9.3.1 仍未完全解决的一点

`SettingView` 这类页面**第一次**被拍快照时，`_PrepareForRender`（polish + 逐层
`layout().activate()`）只能让它画出一部分内容：实测快照亮度已经和正常页一致（53.4），
但撤掉覆盖层后仍有 100~140ms 是"深色底 + 还没画全"。

已试过但**不能用**的方案：`WA_DontShowOnScreen` + `show()` 让隐藏页"逻辑显示"一遍
再 render。它确实能让快照完整，但栈上会短暂出现两个可见页，`QStackedLayout` 状态打架，
切页瞬间反而整块空白（比原来更糟）。

当前采用的折中：
1. `Finished()` 里跑完 `SwitchCurrent` 后再等 48ms、`repaint()` 一次，最后才撤覆盖层；
2. 挂 `_FirstPaintWatcher`（新页 `Paint` 事件或 400ms 超时）兜底，页面首帧特别慢时也不会一直挡着。

彻底解法是"页面首次显示后立刻拍一张快照存缓存"（第二/三次切换就完美），
或者把页面内容的构建挪到"进入动画前"完成。

### 9.4 复测方法

```bash
adb shell screenrecord --time-limit 14 --bit-rate 24000000 --size 720x1584 /sdcard/t.mp4 &
# 期间做：首页 → 菜单 → 设置 → 返回 → 菜单 → 设置 → 返回
adb pull /sdcard/t.mp4
python .workbuddy/probe/framescan2.py t.mp4      # 逐帧 YAVG（signalstats，帧号与时间严格对应）
```

注意：**不要用"我自己按 -ss 抽帧 + 自己算 mean"那套**——screenrecord 是可变帧率
（实测 15fps 左右），`-ss` 抽到的帧和自算的帧序号会对不上，会把正常帧误判成黑帧
（本项目在排查中就被这个坑带偏过两轮）。用 `signalstats` 的 `YAVG`，它的
`pts_time` 与帧一一对应；要抽某一帧就用 `select=eq(n\,帧号)`。
