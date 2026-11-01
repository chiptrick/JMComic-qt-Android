# PySide6 → 纯 Qt C++ 迁移性能评估

日期：2026-10-31
范围：`JMComic-qt`（桌面 Linux/Windows/macOS + Android）
结论先行：**为性能做整体迁移，投入产出比不成立**。收益集中在「启动 / 内存 / 列表与页面构建 / 解码并行度」四处，
而「解码本身、绘制合成、网络、超分」几乎没有收益；其中收益最大的两项（资源二进制化、单页解码链路）
**不迁移也能拿到**，已在本文第 8 节给出实测证据。

---

## 0. 术语与前提

项目代码里用的是 **PySide6**（`from PySide6.QtWidgets import ...`），不是 `QtPy` 那个兼容层。
两者性能特征一致（PySide6 官方绑定、shiboken6 封装），下文统一按 PySide6 讨论。

项目锁定 `PySide6==6.5.3`（`src/requirements.txt`），本文实测环境是 **PySide6 6.12.0**
（本机唯一可用的 wheel）。6.5 的绑定层开销通常比 6.12 高 10~30%，**结论方向不变，绝对值偏乐观**。

### 测量环境

| 项 | 值 |
|---|---|
| CPU | Intel Core Ultra 5 125H（18 线程） |
| 系统 | Fedora 44 / KDE Plasma 6 / Wayland |
| Python | 3.13.12 |
| Qt 绑定 | PySide6 6.12.0（PySide6-Essentials） |
| 平台插件 | `QT_QPA_PLATFORM=offscreen`（离屏光栅，无 GPU 合成） |
| 基准脚本 | `.workbuddy/tmp/bench_*.py`（可复跑） |
| 真机数据 | 引自项目自带 `docs/p1_perf_ab_2026-10-31.md`、`docs/mobile_anim_perf.md`（vivo V2463A / Android 17 / 1440×3168 / DPR 3.75 / 144Hz） |

> 离屏平台会让「绘制类」数字偏低（没有真实 GPU 合成与 vsync），因此绘制相关结论只用**相对值**，
> 绝对值以真机 A/B 报告为准。

---

## 1. 绑定使用范围：这是一个"重 UI 逻辑"的 PySide6 应用

| 指标 | 数值 |
|---|---|
| Python 文件 / 行数（排除 `images_rc.py`） | 273 个 / **70,825 行** |
| `component/`（自绘控件、列表、滚动、动画） | 11,753 行 |
| `view/`（页面级逻辑） | 17,266 行 |
| `interface/`（pyside6-uic 生成） | 11,291 行 |
| `tools/`（其中 `mobile_*.py` 8,309 行，Android 专用 UI 胶水） | 22,983 行 |
| `server/` + `task/`（网络、下载、解码、超分） | 5,972 行 |
| `images_rc.py`（编译后的资源模块） | **22.3 MB / 468,665 行** |

Qt 使用密度：

| 统计项 | 数量 | 含义 |
|---|---|---|
| `.connect(` 调用 | **526** | 信号槽是主要耦合方式，跨线程回投大量使用 |
| `setStyleSheet` 调用点 | **145** | 每处都会触发 QStyleSheetStyle 重新 polish |
| 动画对象（QPropertyAnimation/QVariantAnimation 等） | 33 | 换页、滚动、进度条 |
| `QTimer(` | 28 | 含 6ms 精确定时器驱动动画 |
| `def paintEvent` | **20** | 自绘控件（每帧进 Python） |
| `setItemWidget` | **21** | widget-per-item（列表里每项一棵控件树） |
| `QGraphicsProxyWidget` | 21 | 阅读器每页一个 proxy + QLabel |
| `pickle.dumps/loads` | **47** | 跨线程传数据靠 pickle 中转 |

**判断**：这不是"薄壳调 C++"的应用，UI 逻辑、布局计算、绘制、解码调度都在 Python 里。
这意味着迁移**不会**自动变快——只有把 Python 侧真正在跑的循环搬走才有收益（见第 7 节）。

---

## 2. 热点代码路径

按"每秒/每次操作消耗的 CPU 时间"排序：

### H1 图片解码与还原（阅读器主路径）

* `src/task/task_qimage.py:44` `TaskQImage.Run()` —— **单线程**消费队列，`ConverQImage()` 在 `:154`：
  `QImage.loadFromData()` → `q.scaled(..., SmoothTransformation)`。
* `src/tools/tool.py:1271` `SegmentationPicture()` —— 桌面端走 **PIL**：解码 → `crop/paste` 分块还原 → **重新编码**成 JPEG/PNG 字节。
* 回流 `src/view/read/read_view.py:589` `ShowImgAll()` → `read_graphics.py:715` `SetPixIem()`：
  再 `QPixmap(data)` + `scaled(SmoothTransformation)`。

**问题**：一张图被"解码 + 编码 + 再解码"三次，其中一次编码完全是浪费。
Android 端已经改走 Qt 域内还原（`ToolUtil.SegmentationQImage`），桌面端没有。

### H2 阅读器建场（打开一章）

`read_graphics.py:459` `InitAllQLabel()` 为**每一页**建一个 `QGraphicsProxyWidget + QLabel`（60 页 = 60 套）。
实测 60 页建场 **154 ms**、常驻 +8 MB。

### H3 列表卡片（首页/分类/下载）

`component/list/comic_list_widget.py:334` `AddBookItem()` → `ComicItemWidget`（`component/widget/comic_item_widget.py:145`，
约 15 个子控件）+ `setItemWidget`。
项目自己的注释写明：**单条约 4~8 ms（建控件 + 5 处 QSS + 排版 + sizeHint），60 条 = 250~500 ms 主线程阻塞**，
并用 `AddBooksDeferred()` 分批让出来掩盖。

### H4 封面解码（已优化过，可作为"正确做法"的样板）

`comic_item_widget.py:12` `DecodeCoverImage()` 用 `QImageReader.setScaledSize()` 按目标尺寸解码（JPEG 走 DCT 缩放），
放 `QThreadPool(2)`，再以 16 ms/批、每批 2 张铺图。
注释记录的实测：整图解码 + SmoothTransformation 约 **3 ms/张**，一屏 60 张 = 180 ms；
改后一屏封面不再砸在主线程。

### H5 换页动画

`component/widget/animation_stack_widget.py` 自建 6 ms 精确计时器（Qt 自带动画驱动固定 16 ms，封顶 ~62 fps），
GPU 覆盖层 `component/widget/gpu_anim_cover.py` 用 `QRhiWidget` + 视口位移，**每帧 2 次 draw、CPU 侧 0.10 ms**。
真机 110~123 fps。

### H6 跨线程数据回流

`src/task/qt_task.py:16` `taskBack = Signal(int, bytes)`，载荷是 `pickle.dumps(data)`（`server/user_handler.py` 40+ 处）。
`downloadStBack = Signal(int, dict)`、`localBack = Signal(int, int, list)` 同理。

### H7 启动资源

`src/start.py:78` `import images_rc` —— 22.3 MB Python 源码，468k 行字节字面量。

---

## 3. 运行时开销：跨语言调用、信号槽、类型转换（实测）

单次调用的固定成本（PySide6 6.12 / 离屏）：

| 操作 | 实测 |
|---|---|
| `QSize.width()`（空 C++ 调用） | **0.058 µs** |
| 绑定属性读（`objectName()`） | 0.131 µs |
| `QLabel.setText` / `.text()` | 0.167 / 0.180 µs |
| 纯 Python 属性读（基线） | 0.019 µs |
| **一次 QPainter 绘制调用**（含 QRect/QColor 构造与转换） | **≈1.5~1.8 µs** |
| 信号 emit → Python 槽（int） | 0.555 µs |
| 信号 emit → lambda | 0.510 µs |
| 跨线程 QueuedConnection emit | 0.698 µs |
| QImage（700×1000）过信号 | 0.45 µs（隐式共享，只传指针） |
| `Signal(int, dict)`，dict 10 项 | 4.0 µs |
| `Signal(int, dict)`，dict 1000 项 | **469 µs** |
| `Signal(int, list)`，list 1000 项 | **182 µs** |
| `bytes`(2.8MB) → `QByteArray` | 102 µs（一次全量拷贝） |

**解读**

1. 单次调用 0.06~0.2 µs，本身不贵。贵的是**次数**：一个自绘控件一帧 7 次绘制调用 = 74.6 µs，
   而空控件基线只有 7.9 µs —— **Python 自绘一帧的成本约为 C++ 的 9 倍**（真机上 raster 动画
   实测 1.5~1.8 ms/帧，也是这个量级）。
2. 小对象信号（int/QImage）几乎免费，**大 dict/list 过信号是灾难**：1000 项 dict 一次 0.47 ms，
   如果按进度条 20 Hz 更新，单这一项就吃掉 1% CPU。迁移后这里变成原生结构体指针，成本≈0。
3. `bytes` 每过一次信号就整份拷贝，图片 300~800 KB 就是 20~60 µs/次；不如传 `QByteArray`/`QBuffer`
   或直接在 C 侧持有。

---

## 4. 内存占用

分阶段 RSS（同一进程逐步加载，峰值由 `/usr/bin/time` 复核）：

| 阶段 | 耗时 | 峰值 RSS | 增量 |
|---|---|---|---|
| 裸 Python 解释器 | 197 ms | 19.7 MB | — |
| + `import PySide6.QtWidgets` | 592 ms | 49.5 MB | **+29.8 MB**（Qt 库 + shiboken + 模块） |
| + `QApplication` | 752 ms | 59.5 MB | +10.0 MB |
| + `import images_rc`（22.3 MB 源码） | 950 ms | 134.2 MB | **+74.7 MB** |
| + 建窗口、50 个 QLabel、出首帧 | 998 ms | 138.6 MB | +4.4 MB |

其它实测：

| 对象 | 单件内存 |
|---|---|
| `ComicItemWidget`（约 15 个子控件 + Python 封装） | **146 KB/个** → 60 个 ≈ 8.6 MB |
| 空 `QWidget` | 3.5 KB/个 |
| 单页 QImage（720×1080 ARGB32） | 3.0 MB（QPixmap 再一份 = 6.0 MB/页若都留着） |

真机（vivo V2463A）`dumpsys meminfo` 的 **TOTAL PSS = 669 MB**。拆解：
其中 ~286 MB 是 20 页整页快照（`_cache` 无 LRU，项目文档已标注）、页面缓冲与纹理，
这部分**迁移后照样存在**；可归因于 Python 侧的约 100~200 MB（资源 75 MB + 控件树 + 解释器 + 封装）。

**迁移后预估**：桌面空壳 138 MB → 30~45 MB（-70%）；设备 PSS 669 MB → 400~480 MB（-30%）。
图像缓冲是内存大头，语言换了它不变。

---

## 5. 启动时间

| 阶段 | 耗时 |
|---|---|
| 裸解释器 | 197 ms |
| + QtWidgets | 592 ms |
| + QApplication | 752 ms |
| + 资源模块 | 950 ms |
| + 首帧 | **998 ms** |

其中 **197 ms 解释器 + 395 ms 绑定导入 + 198 ms 资源解析**几乎全是迁移可消除项（约 790 ms）。
C++ 程序同机冷启到首帧的经验值 100~150 ms，**-85%**。

真机 `am start -W` TotalTime 实测 204~261 ms —— 这个数字已经很好，因为项目把模型检查、超分探测等重活
挪到了首帧之后（`start.py:160` 的 `afterShow`）。**设备端启动收益远小于桌面端**，别拿桌面数字去推设备。

另注：`main.Init()` 里的超分探测会 `Popen([sys.executable, start.py, ...])` 起**第二个 Python 进程**，
一次解释器冷启（~200 ms）就花在这上面；C++ 里这是 5~20 ms 的事。它不挡首帧，但挡"可交互"。

---

## 6. 图像链路：单页从字节到可显示 pixmap

1200×1700 JPEG（954 KB）、10 块分割、目标 720×1080：

| 路径 | 耗时 |
|---|---|
| **A 桌面现状**：PIL 解码 → crop/paste 分块 → 重编码 JPEG → Qt 解码 → 平滑缩放 | **39.6 ms/页** |
| **B Qt 域内**：Qt 解码 → QPainter 分块 → 平滑缩放 | **24.0 ms/页** |
| C 下界：Qt 解码 → 平滑缩放（不分块） | 17.6 ms/页 |

分项：

| 步骤 | 耗时 | 迁移能省掉吗 |
|---|---|---|
| Qt 解码（libjpeg） | 14.9~28.7 ms | **否**（本来就是 C） |
| PIL 解码 | 10.6 ms | 是（重复解码） |
| PIL 重编码 JPEG q75 | 10.4 ms | 是（纯浪费） |
| QPainter 10 块还原 | 6.4 ms | 部分（主要是像素搬运，Python 调用只占 ~20 µs） |
| 平滑缩放 | 0.14 ms | 否 |

**所以单页链路的 1.65× 提升，来自"别做无用功"，不来自"换成 C++"。** Android 端已经这么做了。

### 解码并行度（本次最有价值的发现）

PySide6 在 `QImage.loadFromData()` 期间**不释放 GIL**，因此 Python 线程池解不了码：

| 线程数 | Qt 解码+缩放 单页均摊 | 加速比 |
|---|---|---|
| 1 | 20.0 ms | 1.00× |
| 2 | 21.6 ms | 0.93× |
| 4 | 22.0 ms | **0.91×** |
| 8 | 22.1 ms | 0.91× |
| *PIL 对照（4 线程）* | *12.2 ms* | ***1.82×*** |

拆开看：`loadFromData` 单独 4 线程 **0.97×**（完全不释放），`scaled` 单独 **1.30×**（部分释放）。

结论：**当前预加载 10 页 = 200 ms 串行，且无论加多少线程都不会变快**。
C++ 里同样的代码放 `QThreadPool(4)` 就是 3~4× 吞吐（真机 8 核约 2.5~3×）。
这是唯一一项"只能在 C++/独立进程里拿到"的收益。

---

## 7. 收益矩阵：哪里明显、哪里有限、哪里为零

| 场景 | 现状（实测） | 迁 C++ 预估 | 收益 | 归因 |
|---|---|---|---|---|
| 冷启动（桌面） | ~1.0 s | 0.10~0.15 s | **-85%** | 解释器 + 绑定导入 + 资源解析 |
| 冷启动（设备首帧） | 204~261 ms | 持平~略好 | 0~15% | 首帧已在重活之前 |
| 空壳常驻内存（桌面） | 138 MB | 30~45 MB | **-70%** | 解释器 + 资源 + 封装 |
| 设备 PSS | 669 MB | 400~480 MB | -30% | 图像缓冲占大头，语言无关 |
| 列表首屏 60 条 | 250~500 ms | 60~120 ms | **-70%** | 控件/委托 + 每项 1 ms 级 Python 开销 |
| 打开一章（60 页建场） | 154 ms | 40~50 ms（保留 proxy）/ 5~10 ms（自绘页项） | **-70~95%** | proxy+QLabel 每页一套 |
| 单页解码显示 | 39.6 ms | 19~24 ms | -40~50% | 去掉重复解码/编码（**不迁移也能做**） |
| 预加载吞吐 | 1×（串行） | 2.5~4× | **+150~300%** | GIL 解除，真并行解码 |
| 换页动画（GPU 路径） | 0.10 ms/帧，110~123 fps | 0.10 ms/帧 | **≈0** | 已经是 C++/RHI |
| 换页动画（raster 回退） | 1.5~1.8 ms/帧 | 0.2~0.4 ms | -75% | Python 驱动的 QPainter |
| 稳态滚动/重绘 | 0.7~1.1 ms/帧 | 0.7~1.1 ms/帧 | **0** | 已是 C++ |
| 切页整页快照 `render()` | ~30 ms + 14 MB | ~30 ms + 14 MB | **0** | 已是 C++ |
| 网络（curl_cffi/libcurl） | — | — | **0** | 已经是原生 |
| 超分（`sr_vulkan` / QNN） | — | — | **0** | 已经是原生 |
| SQLite / 文件 IO | — | — | **0** | 已经是原生 |

**一句话**：迁移对"启动、内存、控件构建、并行解码"是数量级收益；
对"绘制、合成、网络、编解码内核"是零收益——因为这些本来就是 C++ 在跑，Python 只是在旁边指挥。

---

## 8. 反证：两个最大收益点，不迁移也能拿到

### 8.1 资源二进制化（实测）

`images_rc.py` 是 `pyside6-rcc` 生成的 Python 源码，22.3 MB / 468k 行，导入即构造几十万个 bytes 对象。

| 方案 | 导入/注册耗时 | RSS 增量 | 体积 |
|---|---|---|---|
| `import images_rc`（现状） | **198 ms** | **+74.7 MB** | 22.3 MB 源码 |
| `images.rcc` + `QResource.registerResource()` | **1.7 ms** | **+0.1 MB** | 4.5 MB（rcc 自带 zlib） |

已在本机验证：`rcc --binary` 生成 4.5 MB 包，PySide6 的 `QResource.registerResource("images.rcc")`
返回 `True`，`:/png/icon/new.svg` 等路径可正常访问。**改动量约 10 行，收益 196 ms + 74 MB。**

### 8.2 单页解码链路

把 `SegmentationPicture()` 的桌面分支也切到 `ToolUtil.SegmentationQImage()`（Android 已在用），
39.6 ms → 24 ms/页，**改动量约 5 行**。

这两条加起来，已经覆盖了"迁移收益"里最确定的部分（启动 -20%、内存 -50%、翻页 -40%），
而成本是"一个下午"。

---

## 9. 迁移过程中的性能影响因素与风险

### 9.1 决定成败的五个架构点（不做这五件事，C++ 也快不了多少）

1. **列表必须去 widget-per-item**：改 `QStyledItemDelegate` 自绘。只换语言、仍保留 21 处 `setItemWidget`
   + 每项 5 次 `setStyleSheet`，C++ 也只能从 4~8 ms/条降到 1.5~2 ms/条（QSS polish 实测 0.2 ms/条是纯 C++ 成本）。
2. **解码必须进线程池**：C++ 里 `QImageReader` 放 `QThreadPool` 才是真并行；单线程 C++ 只等于现在的 24 ms/页。
3. **阅读器页项要去 proxy**：`QGraphicsProxyWidget` 在 C++ 里同样昂贵（60 页 154 ms 里相当一部分是它）。
   自绘 `QGraphicsItem` 才能到 5~10 ms。
4. **资源必须走 .qrc/.rcc**：否则 C++ 版还得自己管一堆文件路径。
5. **信号载荷必须强类型**：把 `Signal(int, dict)` / pickle 中转换成结构体，否则只是把转换成本从 shiboken 挪到别处。

### 9.2 风险清单（按严重度）

| 风险 | 说明 | 影响 |
|---|---|---|
| **生态缺口** | `jmcomic==2.6.20` 是 Python SDK（登录、API 签名、章节解析、图片分块算法全在里面）；`curl_cffi` 负责 TLS 指纹/CF 盾；`sr_vulkan`/`sr_qnn` 是 Python 扩展；`webdavclient3`/`pysmb` 负责 NAS。C++ 侧没有等价物，全部要照协议重写或重新绑定 | **极高**，可能占全部工作量的一半 |
| **Android 打包链重建** | 现在是 p4a + buildozer + PySide6-Android wheels（`android/tools/*.sh`）；C++ 要换 Qt for Android（CMake + Gradle + NDK），QNN/ONNX Runtime 集成方式完全不同。项目冷构建 40~60 min/ABI | **极高** |
| **70k 行重写 + 回归** | 273 个文件 / 70,825 行，其中 8.3k 行 Android 专用 UI 胶水、11.3k 行 uic 生成代码要重新生成。当前版本仍在修换页方向、封面错位这类 UI 细节 | 高 |
| **线程模型变化** | Python 有 GIL "保护"，QPixmap 只能在 GUI 线程、QImage 可跨线程这些规则在 C++ 里变成实打实的崩溃/数据竞争；对象所有权（parent/智能指针）要重新设计 | 高（新 bug 高发区） |
| **迭代效率** | 现在改一行 Python 直接跑；C++ 改一行要编译（Android 40~60 min）。调 UI 参数、试动画曲线的成本上升一个数量级 | 中高（长期） |
| **"逐行翻译"反噬** | 直接照搬 Python 结构（widget-per-item、每项 QSS、每页 proxy），C++ 版可能只快 20~30%，但工期和风险已经付了 | 中（最常见的失败模式） |

### 9.3 也不要高估的几件事

* 帧率：真机 110~123 fps，`paint/帧 0.10 ms`，剩余长帧来自**后台解码/网络/列表构建抢主线程**
  （项目文档已定位：250 ms 窗口里整进程 204 ms CPU ≈ 0.8 核）。迁移能减少"抢"，但不会把 110 fps 变成 144 fps。
* 功耗：CPU 时间在 250 ms 窗口 204 ms，其中大头是解码与快照，语言无关。

---

## 10. 结论与建议

### 结论

1. **不要为性能做整体迁移。** 预期收益：启动 -85%（桌面）、内存 -30~70%、列表/建场 -70%、预加载 +2~3×；
   但**稳态渲染、网络、解码内核、超分没有收益**，而代价是 70k 行重写 + 生态重建 + Android 打包链重建。
2. 收益最大的两项（资源 75 MB/198 ms、单页 15.6 ms）**不迁移就能拿到**，实测已给出。
3. 唯一必须"离开 Python"的收益是**解码并行度**（GIL 下 0.91×，加线程完全无效）。这一项可以用
   **独立解码进程池**或 **pybind11 C++ 扩展**单独解决，不必重写整个 UI。

### 建议路线（按 ROI 排序）

| 阶段 | 动作 | 预期收益 | 成本 |
|---|---|---|---|
| **P0** | `images_rc.py` → `images.rcc` + `QResource.registerResource()` | 启动 -196 ms、内存 -75 MB（设备同理） | ~0.5 天，~10 行 |
| **P0** | 桌面 `SegmentationPicture` 切到 Qt 域内还原（去掉 PIL 重编码） | 单页 39.6 → 24 ms（-40%），预加载同步变快 | ~0.5 天，~5 行 |
| **P1** | 解码搬出主进程：复用 `TaskMulti` 的进程池模式做"解码 worker"，或写 pybind11 扩展 + `QThreadPool` | 预加载 2.5~4×（真机 2~3×） | 1~2 周 |
| **P1** | 列表改 `QStyledItemDelegate`（封面/文字自绘，去掉 widget-per-item） | 首屏 250~500 → 80~150 ms | 1~2 周 |
| **P2** | 阅读器页项从 `QGraphicsProxyWidget+QLabel` 改成自绘 `QGraphicsItem` | 开章 154 → 20~40 ms，内存 -8 MB/章 | 2~4 周 |
| **P3** | 只把"阅读器渲染层 + 解码"用 C++ 重写（Python 保留业务/网络），通过 pybind11 暴露 | 渲染与预加载接近 C++ 水平，重写面 <15% | 1~2 个月 |
| **P4** | 整体 C++ 化 | 见第 7 节全表 | 6 个月+，且要重建 Android 链与全部 SDK |

若目标只是"设备内存 -200 MB、启动 -50%、翻页 2×"，**P0+P1+P2 能拿到 60~70% 的总收益，成本约为整体迁移的 1/5**，
且每一步都能独立验证、独立回滚。

### 验证方式

沿用项目已有的探针，不要新造轮子：

* 启动：`am start -W` 的 TotalTime（3 次冷启取中位）
* 内存：`dumpsys meminfo` 的 TOTAL PSS（注意"刚启动只访问 1 页"和"连续翻 20 页"是两种状态，不可混比）
* 帧率：`FrameTick` 时间戳算 fps / p50 / p95 / >16.7ms 帧数
* 绘制：覆盖层 `PaintMs / PaintCount`
* 解码：`time_me` 装饰器已在 `TaskQImage.ConverQImage` 上，`>=100ms` 才打日志；验收时临时降到 10 ms 即可看到分布

---

## 附录：基准脚本

| 脚本 | 内容 |
|---|---|
| `.workbuddy/tmp/bench_qtpy.py` | 调用/信号/类型转换/绘制基线 |
| `.workbuddy/tmp/bench2.py` | 真实负载：解码、pickle、卡片构建、自绘一帧 |
| `.workbuddy/tmp/bench_startup.py` | 启动分段 + 峰值 RSS |
| `.workbuddy/tmp/bench_pipeline.py` | 单页解码全链路 A/B |
| `.workbuddy/tmp/bench_card.py` | 真实 `ComicItemWidget` 单件成本与内存 |
| `.workbuddy/tmp/bench_qss.py` | 全局 QSS polish 的 A/B |
| `.workbuddy/tmp/bench_reader.py` | 阅读器 60 页建场/重绘/缩放 |
| `.workbuddy/tmp/bench_parallel.py` | 解码并行度（GIL）与 PIL 对照 |

复跑：`/run/media/kokomi/Data/jm-build/JMComic-qt/android/.venv/bin/python <script>`
（该 venv 的 PySide6 是 6.12；如需对齐 6.5.3 结论，建议在 pin 环境中复测 `bench_parallel.py` 与 `bench_startup.py`）
