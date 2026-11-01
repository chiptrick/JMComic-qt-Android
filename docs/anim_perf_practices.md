# 换页转场性能：业界实践筛选与落地建议

日期：2026-10-31
基线：0.87 P1（双纹理位移），V2463A / Android 17 / 144Hz，实测 fps 110–116、p50 6.5ms、
p95 20–22ms、>16.7ms 2.4 帧/次、整进程 CPU 204ms / 250ms 窗口、覆盖层 paint 0.10ms/帧。

**先看结论**：合成层已经到底了（每帧 2 draw、0.1ms CPU），瓶颈在
①每次切页的整页 `render()`、②后台封面解码/网络回调抢主线程、③每页 14.3MB 的纹理上传与常驻。
下面的措施按"能不能真的改善体感"排序，而不是按实现难度。

## 1. 候选实践与筛选

| # | 实践 | 来源 | 适用性 | 优点 | 缺点/风险 | 预期收益（相对本组件） |
|---|---|---|---|---|---|---|
| 1 | 快照/栅格缓存加**容量上限 + LRU 淘汰** | Android `LruCache`、iOS `NSCache`、Flutter raster cache 的预算/淘汰机制 | **高** | 内存可预测；避免低内存抖动 | 淘汰后重访要重渲染（~30ms） | 内存：无界 → 约 43MB（3 页）；fps 不变 |
| 2 | 只缓存"静止且复杂"的内容，内容一变立即失效 | Apple `shouldRasterize` 指南（静态复杂图层才缓存；动画/变化时缓存反而更慢）、Flutter `RepaintBoundary` | **高** | 命中率高、避免无效缓存 | 失效判断要准（漏判=脏帧） | 与 #3 配套，减少一次整页 render |
| 3 | **动画期间不抢主线程**（暂停解码/网络解析/列表构建） | Android 卡顿指南：CPU 争抢是 UI 线程掉帧的常见原因；RenderThread 与 UI 线程分离的设计 | **高** | 直接改善 p95/长帧；实现集中 | 封面晚 250ms 出现（无感） | p95 20ms → 10–12ms；>16.7ms 2.4 → <1；fps +10–20%（预估） |
| 4 | 帧率与刷新率对齐，避免 buffer stuffing | Android Choreographer / Swappy 帧同步库：提交快于显示会排队、增加延迟 | **中** | 降延迟与抖动；省电 | Qt 不锁 vsync，需自己按屏幕刷新率算间隔 | 不提 fps；延迟/抖动改善（预估 1–2 帧） |
| 5 | 不透明图元、关闭 blending、避免过度绘制 | Qt Quick 场景图默认渲染器：opaque 批次不启用 GL_BLEND，可用 early-z；Apple `isOpaque` | **已满足** | 省填充带宽 | 页面快照本身不透明才成立 | 0（当前 QRhi 管线默认无混合；补一条守卫测试即可） |
| 6 | 减少 draw call / 状态切换、批处理 | Qt Quick 场景图 batching 文档 | **不适用** | — | 本组件固定 2 个 draw、2 次视口切换，已是最小 | 0 |
| 7 | 纹理/快照**降采样**（动画期半分辨率） | iOS `rasterizationScale` 的类比；移动端转场常用"动画期降质、结束还原" | **中** | 显存/带宽/上传都降 75% | 文字与细线会软，需要 A/B | 纹理 28.6→7.2MB；上传 −75%；带宽 −75% |
| 8 | 纹理复用、只上传变化的纹理 | 引擎通用做法（避免重复 upload） | **高** | 省带宽与 CPU | 需要跟踪"哪张图变过" | 命中缓存时 −14MB/次（约 2–4ms） |
| 9 | 预渲染/预热（idle 时提前拍上一页快照） | Flutter raster cache 的"稳定后缓存"思路 | **中** | 消除首次回退的 ~30ms 长帧 | 可能白做（用户没回退）；要限预算 | 首次回退长帧 −20–30ms |
| 10 | 纹理压缩（ETC2/ASTC） | 移动 GPU 常规 | **不适用** | 显存减半 | UI 快照编码成本高、文字质量差 | 不推荐 |
| 11 | 共享元素/英雄转场 | 平台转场框架 | **不适用** | 观感好 | 需要页面级元素映射，改动远超收益 | 不推荐 |

## 2. 逐项落地建议

### P0-A 快照缓存加 LRU 上限（3 页）
现状 `_cache` 是普通 dict，按 `id(page)` 存 `(QPixmap, size)`，每页 DPR 3.75 时约
1395×2685×4 ≈ **14.3MB**；访问 20 个页面就 286MB，且 `id()` 复用还可能拿到脏 entry。
做法：`OrderedDict` + `move_to_end`，超过 3 页 `popitem(last=False)`；`InvalidatePage` 同步删除。
代价：回退超过 3 层要重渲染（~30ms），可接受。

### P0-B 动画期间给后台工作让路
实测 250ms 窗口里整进程吃了 204ms CPU（≈0.8 核），p95 20ms 的长帧基本都落在
封面解码/网络回调上。做法：`SwitchWidgetByIndex` 开始时把 `TaskMulti`/封面解码队列
挂起（或把 worker 线程优先级降到 `THREAD_PRIORITY_BACKGROUND`），`Finished` 后恢复；
只暂停 250ms，用户无感。这是**唯一能明显改善 fps/长帧**的一项。

### P1-C 复用"没变过"的当前页快照
现在每次切页都 `_RenderPage(current, useCache=False)` 强制重拍（~30ms + 14MB 分配）。
用事件过滤器盯当前页的 `QEvent.Paint`：拍完快照后若没有再 paint，就直接复用；
有 paint 才重拍。预期 CPU 204 → ~175ms/次，GC 尖峰变少。风险：个别页面用
`update()` 之外的手段改内容（如直接改 backing store）会漏判，需要保留 `InvalidatePage` 兜底。

### P1-D 纹理上传去重
`Begin()` 目前无条件 `_pending=True`，两张纹理各 14.3MB 全部重传。目标页快照常常
来自缓存（同一 `QPixmap` 对象），可以记住上次上传的 `id(pixmap)`，相同就跳过。
缓存命中时省 ~14MB/次；对 fps 影响小，但能减少 GPU 带宽与驱动抖动。

### P2-E 动画期半分辨率快照
按 0.5×DPR 拍快照（或上传前下采样），动画结束再换回全分辨率。纹理 28.6→7.2MB，
上传与采样带宽 −75%。文字在 250ms 内会略软，建议先用 A/B 看观感；
如果接受，低端机的收益比旗舰明显。

### P2-F 帧率对齐屏幕刷新率
现在固定 6ms 驱动，144Hz 屏幕的预算是 6.94ms，等于**故意跑得比屏幕快**，
按 Android 帧同步的结论会排队、增加延迟。改成 `1000 / QScreen.refreshRate()`（夹在 6–8ms），
或直接读 `QGuiApplication.primaryScreen().refreshRate()`。预期不提 fps，但降延迟/抖动。

### P3-G 预热返回栈
在 `Finished` 后的 idle 里，用 `QTimer.singleShot(0/50)` 预拍 `subStackList[-2]` 的快照
（每页 30ms、14MB，需受 P0-A 的 LRU 约束）。只对"很可能返回"的上一页做，别全栈预热。

## 3. 优先级与预期收益汇总

| 优先级 | 措施 | 目标指标 | 现状 → 预期 | 置信度 |
|---|---|---|---|---|
| P0 | 快照 LRU(3) | PSS | 无界（20 页 ≈286MB）→ ≤43MB | 高（可直接测） |
| P0 | 动画期暂停后台 | p95 / 长帧 / fps | 20ms → 10–12ms；2.4 → <1 帧；110 → 125+ | 中高（需实测） |
| P1 | 复用未变快照 | CPU/次 | 204ms → ~175ms | 中 |
| P1 | 纹理上传去重 | 上传量 | 28.6MB → 14.3MB（命中时） | 高（逻辑确定） |
| P2 | 半分辨率 | 显存/带宽 | 28.6MB → 7.2MB | 高（画质待 A/B） |
| P2 | 刷新率对齐 | 延迟/抖动 | 6ms → 6.94ms（144Hz） | 中 |
| P3 | 预热上一页 | 首次回退长帧 | −20–30ms | 中 |

## 4. 参考

* Android 卡顿（16/11/8ms 预算、CPU 争抢、Systrace）：
  https://developer.android.com/topic/performance/vitals/jank
* Android 帧同步（Choreographer）：
  https://developer.android.com/ndk/reference/group/choreographer
* Android Frame Pacing / Swappy（避免 buffer stuffing、按刷新率匹配）：
  https://developer.android.com/games/optimize/frame-pacing
* Qt Quick 场景图默认渲染器（不透明批次、批处理、变换节点）：
  https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph-renderer.html
* Flutter 性能分析（raster cache 昂贵、RepaintBoundary 只给静态内容）：
  https://flutter.dev/docs/perf/ui-performance
* CALayer `shouldRasterize` 的适用边界（静态复杂图层才缓存；内容/几何一变就失效）：
  https://stackoverflow.com/q/19405741（引自 WWDC 2012 "Polishing Your Interface Rotations"）
  与 https://www.codestudy.net/blog/what-triggers-color-copied-images-and-color-hits-green-and-misses-red-in-instruments
