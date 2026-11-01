# Qt-Py（PySide6）→ Qt C++ 迁移方案评估

日期：2026-11-01
范围：`JMComic-qt` 桌面（Linux/Windows/macOS）+ Android
前置文档：`docs/pyside6_to_cpp_performance_assessment.md`（2026-10-31，性能实测）

本文只回答三个问题：**收益有多大 / 代价有多高 / Windows 上能不能不走 pyside6-android-deploy**。
所有数字都标了来源：`[实测]` 指本仓库内已有测量或本次直接测得的文件级数据，`[估算]` 指按假设外推。

---

## 0. 结论摘要

| 维度 | 结论 | 一句话依据 |
|---|---|---|
| **性能** | 收益真实但高度集中；**设备端体感收益远小于桌面端** | 桌面冷启 998 ms → 100~150 ms；但设备首帧已 204~261 ms，迁移只值 0~15%；稳态渲染/网络/解码内核/超分收益 = 0 |
| **包体积** | 能减，但**减不出数量级**；大头是模型不是语言 | APK 433 MB → 约 280 MB（-35%）；去掉 178 MB 模型后才是 252 MB → 100 MB（-60%）；桌面 306 MB → 约 245 MB（-20%） |
| **可维护性** | 稳态略优，**过渡期与迭代速度严重恶化** | 消除 PySide6 双版本 API、ctypes/PYTHONOPTIMIZE 类 Android 坑；代价是设备端热更新从 10 秒变 40~60 分钟 |
| **重写成本** | **24~45 人月**（3~4 人 8~12 个月），生态缺口集中在网络层 | 51,260 行手写逻辑 → 约 62k 行 C++；唯一的硬骨头是 Android 上的 curl-impersonate，不是 jmcomic |
| **Windows 原生构建** | **当前技术栈下没有受支持的做法**；迁移后才是官方支持路径 | Qt 文档明确 `pyside6-android-deploy` 仅支持 Unix 宿主；Qt for Android（C++）官方支持 Windows 宿主 |

**总建议**：不为"整体更现代"做全量迁移；把"Windows 原生构建"当作独立目标评估。
若它只是便利性问题 → 用 CI/容器解决，迁移收益不抵成本；若是硬性约束 → 迁移是唯一干净路径，但应分三段走并设止损门（见 §5）。

---

## 1. 评估基线

### 1.1 代码规模 `[实测]`

| 分层 | 文件 | 行数 | 迁移性质 |
|---|---:|---:|---|
| `src/interface/` | 50 | 11,291 | **uic 生成**（49 个 `.ui` 编译产物），C++ 侧重新 `uic` 即可，≈0 成本 |
| `src/view/` | 79 | 17,266 | 页面级逻辑，手写 |
| `src/component/` | 84 | 11,753 | 自绘控件/列表/动画，手写，迁移成本最高 |
| `src/tools/` | 34 | 22,983 | 其中 `mobile_*.py` **8,309**（Android 适配胶水）、`zh_wiki.py` **8,274**（简繁映射数据表） |
| `src/server/` | 5 | 3,326 | 网络/协议/加解密 |
| `src/task/` | 14 | 2,646 | 下载、解码、超分调度 |
| `src/config/` | 4 | 816 | 配置 |
| **合计（不含 `images_rc.py`）** | **274** | **70,825** | |
| `src/images_rc.py` | 1 | 468,665（22.3 MB） | rcc 生成的 Python 字节字面量，C++ 侧变 `.qrc` |

**真实迁移面** = 70,825 − 11,291（生成）− 8,274（数据表）= **51,260 行**。

Qt 使用密度 `[实测]`：394 个类、71 个 `QWidget` 子类、526 处 `.connect(`、20 个 `paintEvent`、
21 处 `setItemWidget`、21 处 `QGraphicsProxyWidget`、145 处 `setStyleSheet`、281 处 `getattr`、47 处 `pickle`。

### 1.2 构建与测试资产 `[实测]`

| 项 | 现状 |
|---|---|
| Android 构建 | `pyside6-android-deploy` → buildozer → python-for-android → Gradle；**每个 ABI 打包两次**（打完再补 minSdk/local_libs 再打） |
| 单 ABI 耗时 | 冷构建 **40~60 分钟**，缓存命中约 5 分钟 |
| 宿主约束 | Linux / WSL2 / macOS；宿主 venv 固定 Python 3.11 |
| 设备迭代 | `android/tools/hotpush.sh`：push 单个 `.py` → 重启应用，**约 10 秒** |
| 回归测试 | 30 个 `android/tools/host_test_*.py`，**9,100 行**，宿主 offscreen 直接跑 |
| 桌面打包 | PyInstaller，产物 **306 MB** |

### 1.3 体积基线（本次直接拆包测得）`[实测]`

APK（`JMComic-0.87-arm64-v8a-debug.apk`，433 MB；条目未压缩合计 679 MB）：

| 组成 | 原始 | 压缩后 | 迁移后 |
|---|---:|---:|---|
| Qt 库（63 个模块全量） | 135.0 MB | 52.2 MB | 仅需 27 MB（含插件）→ 约 12 MB |
| PySide6 绑定（12 个 `*.abi3.so`） | 18.7 MB | 6.9 MB | 0 |
| `libpybundle.so`（stdlib + site-packages） | 99.0 MB | 98.1 MB（几乎不压缩） | 0 |
| `libpython3.14.so` | 5.3 MB | 1.8 MB | 0 |
| QNN / ORT / libsr_qnn | 206.9 MB | 约 85 MB | 不变 |
| `assets/private.tar`（gzip 存储） | 181.2 MB | 181.2 MB | 模型 178 MB 不变；应用源码 26 MB（含 `images_rc.py` 23 MB）可去 |
| 其它（ffmpeg/ssl/sqlite/插件） | 31.7 MB | 约 15 MB | 略减（ffmpeg 17.7 MB 属 Qt6Multimedia，可去） |

桌面 PyInstaller 产物（306 MB）：sr_vulkan 模型 123 MB、PySide6 98 MB（其中绑定 25.7 MB）、
PIL 11 MB、cryptography 9.6 MB、lxml 6.6 MB、tcl/tk 6.5 MB、python310.dll 4.3 MB。

---

## 2. 维度一：收益

### 2.1 性能：收益集中在四处，另外六处为零

沿用 2026-10-31 的实测（Intel Ultra 5 125H / Fedora 44 / PySide6 6.12 / offscreen；设备侧 vivo V2463A）：

| 场景 | 现状 | 迁 C++ 预估 | 收益 | 迁移能否拿到 |
|---|---|---|---|---|
| 桌面冷启到首帧 | 998 ms | 100~150 ms | -85% | 能（其中 198 ms 属 `images_rc`，不迁移也能去） |
| 设备首帧 | 204~261 ms | 持平~略好 | 0~15% | 基本拿不到（重活已挪到首帧后） |
| 桌面空壳 RSS | 138 MB | 30~45 MB | -70% | 能 |
| 设备 PSS | 669 MB | 400~480 MB | -30% | 能（大头是图像缓冲，语言无关） |
| 列表首屏 60 条 | 250~500 ms | 60~120 ms | -70% | **需同时改 delegate**，只换语言仅 -50~60% |
| 打开一章（60 页） | 154 ms | 40~50 ms（保留 proxy）/ 5~10 ms（自绘） | -70~95% | 需同时去 proxy |
| 单页解码显示 | 39.6 ms | 19~24 ms | -40~50% | **不迁移也能拿到**（桌面已有 Qt 域内实现） |
| 预加载吞吐 | 1×（串行） | 2.5~4× | +150~300% | **唯一必须离开 Python 的收益**（GIL 下 `loadFromData` 加线程 0.91×，PIL 对照 1.82×） |
| 换页动画（GPU 路径） | 0.10 ms/帧，110~123 fps | 0.10 ms/帧 | 0 | 已经是 C++/RHI |
| 稳态滚动、网络、超分、SQLite | — | — | 0 | 本来就是原生 |

**结论**：迁移的性能收益 ≈「启动 + 常驻内存 + 控件构建 + 解码并行度」。
设备端用户真正能感知的是"打开列表/翻章不卡"，而这一项**只换语言只值一半**——另一半要靠
去 widget-per-item、去 `QGraphicsProxyWidget`，属于架构改造，与语言无关。

### 2.2 包体积：能减 35%，但天花板由模型决定

按 §1.3 的实测拆解推算：

| 目标 | 现状 | 迁移后 `[估算]` | 变化 | 说明 |
|---|---:|---:|---:|---|
| Android APK（含模型） | 433 MB | 约 275~285 MB | **-35%** | 去掉 112 MB Python 运行时 + 40 MB 无用 Qt 模块 |
| Android APK（不含模型） | 252 MB | 约 100 MB | **-60%** | 这才是"语言红利"的真实幅度 |
| 桌面包 | 306 MB | 约 240~250 MB | -20% | 模型 123 MB 占 40%，去掉后 183 → 120 MB |

两项容易被忽略的事实：

1. **APK 里 41% 是 27 个 ONNX 模型（178 MB）**。这是产品分发策略问题，不是语言问题——
   拆成"基础包 + 模型按需下载"能省 150 MB 以上，收益大于迁移。
2. **现在 APK 里 63 个 Qt 模块全量打包**（Quick3D、Charts、Graphs、Designer、Pdf、Multimedia…），
   实际只用到 Core/Gui/Widgets/Network/Svg/Sql/Xml/OpenGL/OpenGLWidgets/Concurrent。
   死代码约 108 MB 原始 / 40 MB 压缩，**外加 Qt6Multimedia 拖进来的 17.7 MB FFmpeg**。
   C++ 只链接用到的模块，这部分是"免费"的，但也说明当前体积有相当一部分是打包策略造成的浪费。

### 2.3 可维护性：稳态略优，过渡期明显变差

**迁移能消除的长期负担**（有据可查）：

- **PySide6 双版本 API**：桌面 `requirements.txt` 钉 `6.5.3`，Android 实际是 `6.11.2/6.12.0`
  （`requirements_android_ci.txt` 明确写了"用桌面端钉的 6.5.3 会掩盖移动端适配层依赖新 API 的问题"）。
  C++ 侧只有一个 Qt 版本。
- **Android 上的 Python 专有坑**：`bootstrap=qt` 下 `ctypes.util` 必须补（README §3.1）、
  `PYTHONOPTIMIZE=2` 让 ctypes 后端必死（§3.2）、`curl_cffi` 垫片（`android/shims/`）、
  p4a recipe、`PYTHONPATH`/`sys.path` 修补。这些在 C++ 里整体消失。
- **类型契约靠约定**：281 处 `getattr`、70 处 `**kwargs`、47 处 `pickle` 跨线程传参。
  C++ 强制显式契约，能消掉一类"字段改名/结构漂移"的线上问题。
- **工具链**：CMake 一套吃三端；无 PyInstaller、无 pyc 打包、无 onefile 解压。

**迁移会引入的长期负担**：

- **迭代速度**：设备端 10 秒热更新 → 完整重建 + 安装。项目在 2026-09-30 ~ 10-28 之间做了
  **11 轮真机反馈修复**（README §3.4~§3.15 有完整记录），这个节奏是靠热更新撑起来的。
  C++ 下同样的节奏要么变成"每次 40~60 分钟"，要么退回模拟器自测再上真机。
- **单兵可维护性**：70k 行 Python 一个人能装下整个应用；62k 行 C++ 需要至少 2~3 人才能并行。
- **协议跟进**：站点改加密/改 CDN 策略时，Python 侧可能是 `pip install -U` 一次就完事
  （当前只依赖 `jmcomic` 的 `JmCryptoTool`，见 §3.4），C++ 侧是改代码 + 发版。
- **测试网重建**：9,100 行宿主回归测试基于 PySide6 + 直接读源码，迁移后必须改写为 QtTest，
  否则失去唯一的快速回归手段。

**结论**：可维护性是"换一类负担"，不是净减少。真正决定体验的是**设备调试闭环**，
从 10 秒退化到 40 分钟这一项，对当前这种"每周一轮真机反馈"的开发模式是实质性打击。

---

## 3. 维度二：风险与成本

### 3.1 重写工作量

行数外推（含头文件，按分层系数）：

| 层 | Python 行数 | C++ 系数 | C++ 行数 `[估算]` |
|---|---:|---:|---:|
| uic 生成 | 11,291 | 0 | 0（重新生成） |
| `zh_wiki` 数据表 | 8,274 | 0 | 0（转数据文件） |
| `mobile_*.py` 胶水 | 8,309 | 1.0 | 8,300 |
| `component/` | 11,753 | 1.3 | 15,300 |
| `view/` | 17,266 | 1.2 | 20,700 |
| `tools/`（非 mobile） | 14,674 | 1.2 | 17,600 |
| `server/` + `task/` | 5,972 | 1.4 | 8,360 |
| `config/` | 816 | 1.0 | 816 |
| **合计** | **51,260** | — | **约 62,000** |

产能假设：移植 + 行为对齐 + 自测 **60~120 行/天**（不含真机回归）。→ **520~1,040 人日 ≈ 24~48 人月**，
取规划值 **30~40 人月**；再叠加 25~35% 联调/真机回归 → **整体 30~45 人月**。

排期含义：3 人 → 10~12 个月；4 人 → 8~10 个月。这与前置文档的"6 个月+"方向一致，但更贴近实际。

**敏感性**：若为了省时间做"逐行翻译"（保留 widget-per-item、每项 5 次 QSS、每页一个 proxy），
工期能压到 20 人月左右，但 C++ 版列表只从 4~8 ms/条降到 1.5~2 ms/条——**付了全款，拿了一半收益**。
这是这类迁移最常见的失败模式。

### 3.2 跨语言交互复杂度

"仅保留无法迁移的 Python 组件"有三种落地方式，代价完全不同：

| 方式 | 实现 | 增量成本 | 适用 |
|---|---|---|---|
| **A 嵌入解释器** | 链接 `libpython`，pybind11 暴露接口，启动时 `Py_Initialize` | +5.3 MB `libpython` + 最小 stdlib（15~25 MB）+ 启动 50~200 ms（可延迟到首次使用）；GIL 与 Qt 事件循环要人为对齐；Python 侧崩溃带走整个进程 | 调用频繁、数据量小的组件（解密） |
| **B 子进程** | 独立 `python` 进程 + stdin/JSON 或共享内存；项目已有此模式（`--sr-probe`、`TaskMulti`） | 仍需随包带 Python 运行时与依赖 wheel（体积省不下来）；IPC 序列化（图片走共享内存）；生命周期/僵尸进程管理 | 崩溃隔离要求高（sr_vulkan 初始化会崩） |
| **C 重写** | 直接用 C/C++ 库 | 零运行时成本，但要重做协议/算法 | 逻辑简单、有等价 C 库的（AES、QImage 分块） |

**关键判断：这些 Python 组件是否在启动路径上？**

- 在（网络会话、解密）→ 保留 Python 就等于保留 `libpython` + stdlib + 部分 wheel，
  **APK 只能省 112 MB 里的 60~70 MB，启动收益也要打折**（解释器初始化 50~200 ms 回来了）。
- 不在（超分，Android 侧已经是 C++ 的 `libsr_qnn.so`，桌面侧是 `sr_vulkan` 且已在子进程探测）→ 影响可控。

按组件给出的归属建议 `[依据：§3.4 的依赖盘点]`：

| 组件 | 现状 | 建议 | 难度 |
|---|---|---|---|
| `JmCryptoTool.decode_resp_data` | 唯一用到的 jmcomic 能力（AES 响应解密） | **C 重写**（OpenSSL，100~200 行） | 低 |
| `curl_cffi`（TLS 指纹 + ECH + HTTP/3） | 桌面：随包 `libcurl-impersonate-chrome`；Android：静态编在 `_wrapper.abi3.so` 里 | **A/B 保留**（见 §3.4） | **高** |
| `sr_vulkan`（桌面超分） | Python 扩展，初始化可能崩进程 | A 或 B（若闭源则只能 B） | 中 |
| `libsr_qnn.so`（Android 超分） | 已是 C++ + ctypes | 直接编译进主程序 | 低 |
| `PIL` 分块还原 | 桌面路径 | **C 重写**（QImage/QPainter，Android 已有实现） | 低 |
| `webdav3` / `smbprotocol` | NAS 上传 | C 重写（libneon / libsmbclient2）或 B | 中 |
| `lxml` / `bs4` | 少量 HTML 解析 | C 重写（lexbor/gumbo 或 QXmlStreamReader） | 中 |

### 3.3 调试与验证难度

| 环节 | 现在 | 迁移后 |
|---|---|---|
| 改一行看效果（设备） | `hotpush.sh` ~10 s | 全量重建 40~60 min；增量 3~8 min + 安装 |
| 改一行看效果（桌面） | 直接跑 | 增量编译 10~60 s |
| 现场取证 | 临时提高日志级别、REPL attach、`run-as` 改 `.py` | gdb/lldb + tombstone + `ndk-stack`；要额外保留符号产物（当前 APK 是 strip 过的） |
| 崩溃归因 | Python traceback 带行号 | 混合栈：C++ 栈里夹 Python 帧，Android 上没有 `python-gdb.py` 辅助 |
| 线程问题 | GIL 掩盖了大部分竞态（很多问题表现为"偶发不刷新"） | 变成实打实的 use-after-free / 数据竞争；`QPixmap` 只能在 GUI 线程、对象父子关系要重新设计 |
| 回归 | 30 个宿主脚本 9,100 行，几秒出结果 | 需重写为 QtTest；重写期间等于裸奔 |

项目已有两处"生命周期脆弱"的证据：退出阶段 `QRhiWidget` 析构触发 `bool_dealloc` 崩溃
（`host_test_switch_direction.py` 用 `os._exit()` 规避）、`sr_vulkan` 初始化会崩所以要子进程探测。
这两类问题在 C++ 里不会自动消失，只会换一种形式出现——**而且不再有 GIL 帮忙兜底**。

### 3.4 生态缺口重新评估（对前置文档的修正）

前置文档把 `jmcomic==2.6.20` 描述为"登录、API 签名、章节解析、图片分块算法全在里面 … 可能占全部工作量的一半"。
**本次全仓检索的结论是：不成立。**

```
$ grep -rn "from jmcomic\|import jmcomic" src
src/server/req.py:365:        from jmcomic import JmCryptoTool
src/server/user_handler.py:1254:    from jmcomic import JmCryptoTool
```

只用到 `JmCryptoTool.decode_resp_data(data, ts=...)` 一个静态方法（响应体 AES 解密）。
请求构造、分页、图片分块还原都在本仓库 `src/server/`、`src/tools/tool.py` 里。
**这一项的迁移成本从"半年"降到"一到两天"。**

真正的高风险项是另一个：

> `curl_cffi` 依赖 **curl-impersonate** 版 libcurl（Chrome TLS/HTTP2 指纹 + HTTP/3 + ECH）。
> Android 上它是**静态编进** `curl_cffi/_wrapper.abi3.so` 的（BoringSSL + ngtcp2/nghttp3 + ECH），
> 仓库里没有独立的 `libcurl-impersonate.so` 可以复用。
> `android/recipes/curl_cffi/__init__.py` 的注释直接写明：早期"用 NDK 自编 curl-impersonate"的
> recipe **在 p4a 下跑不通**，最后是靠上游发布官方 Android wheel 才解决（README §3.10）。

桌面侧则相反：`lib/linux/libcurl-impersonate-chrome-*.so.4.8.0`（20 MB）、
`lib/win/libcurl-*.dll`、`lib/macos/libcurl-impersonate-chrome.4.dylib` 都是**可链接的 C 库**，
C++ 直接用 `CURLOPT_IMPERSONATE` 即可。

所以：**桌面迁移的网络成本 ≈ 0；Android 迁移的网络成本 ≈ 重新做一遍 curl-impersonate 的交叉编译**
（BoringSSL + ngtcp2 + nghttp3 + ECH + curl 补丁，arm64-v8a 与 x86_64 两套，还要长期跟上游）。
这是整个方案里唯一"可能做不出来"的部分，应作为 Go/No-Go 的第一个验证项。

### 3.5 风险清单

| # | 风险 | 严重度 | 概率 | 缓解 |
|---|---|---|---|---|
| R1 | Android 上重建 curl-impersonate（TLS 指纹/ECH/H3）失败或长期不可维护 | 极高 | 中高 | **第一周做技术验证**；退路是保留 Python 网络子进程（体积/启动收益打折） |
| R2 | 过渡期双轨维护，功能迭代停摆 | 高 | 高 | 冻结新特性 or 只维护 Python 版到切换日；按模块灰度 |
| R3 | 线程/对象生命周期缺陷（GIL 兜底消失） | 高 | 中高 | 先补 ThreadSanitizer/ASan 流水线；对象所有权统一用父子关系 + 值语义 |
| R4 | 逐行翻译 → 只快 20~30% 却付了全款 | 中高 | 高 | 迁移前先做 P1/P2 架构改造（delegate、去 proxy），让收益与语言解耦 |
| R5 | 9,100 行宿主回归测试失效 | 中高 | 高 | 与迁移同步重写为 QtTest，按模块迁移即迁测试 |
| R6 | 真机调试闭环从 10 s 变 40 min | 中高 | 确定 | 增量构建流水线（ccache + ninja + `adb install -r`）、真机联调机常驻 |
| R7 | Android 构建链重建（CMake/Gradle/QNN 集成） | 中 | 中 | 比 p4a 简单；`sr_qnn` 的 CMake 已与宿主无关，可直接复用 |
| R8 | PySide6 版本漂移、ctypes/PYTHONOPTIMIZE 类坑 | 低 | 已存在 | 迁移可消除（这是迁移的正收益） |

---

## 4. 维度三：能否绕过 `pyside6-android-deploy`，在 Windows 上完成构建

### 4.1 官方约束（不是本项目的问题）

Qt 官方文档原文：

> `pyside6-android-deploy` only works with a Unix (Linux or macOS) host at the moment.

依赖链是 `pyside6-android-deploy → buildozer → python-for-android → Gradle`，
而 p4a 需要 POSIX 工具链（autoconf/automake/libtool/pkg-config/perl-core，见 README §5）。

仓库里也已经把这条约束写死：

```bash
# android/build_android.sh:240
*) die "pyside6-android-deploy 只支持 Linux / WSL / macOS 主机(当前: $(jm_host_desc))；
   Windows 请在 WSL2 里运行: wsl --cd /mnt/c/<路径>/android -e ./build_android.sh" ;;
```

**所以"直接在 Windows 上编译当前 Python 版 APK"没有受支持的路径。**

### 4.2 不改语言时的可行替代路径

| 路径 | 怎么做 | 能拿到什么 | 限制 |
|---|---|---|---|
| **A1 WSL2**（现状） | `build_apk_from_windows.ps1` → WSL 内 `build_android.sh` | 已验证可用；冷 40~60 min/ABI，缓存 5 min | 构建树必须在 ext4（`/mnt/c` 走 9p 极慢）；宿主 venv 固定 3.11；终端不能关；WSL 内存/磁盘占用 |
| **A2 Linux 容器** | Docker/Podman + 官方 Ubuntu 镜像，预装 SDK/NDK/JDK | 环境可复现、可进 CI；与 A1 等价 | SDK/NDK/Gradle 缓存要挂 volume；无 GUI；产物靠 bind mount |
| **A3 CI 构建** | GitHub Actions `ubuntu-latest` 跑 `build_android.sh` | 最干净，机器不占本地 | 队列/6 小时上限；433 MB artifact 上传下载；无真机验证 |
| **A4 远程 Linux 机器** | SSH + 同一套脚本 | 最快（无 WSL 开销） | 要有机器；代码同步 |
| **A5 两段式（Linux 出 dist + Windows 打包）** | Linux 侧 `--keep-deployment-files` 保留 p4a 产出的 Gradle 工程；Windows 侧改 `assets/private.tar` 后直接 `gradlew assembleDebug` | **唯一能在 Windows 上"跑打包"的折中**：只改 Python 代码/资源时不必回 Linux | 原生依赖（recipes、`local_libs`、minSdk 补丁）一变就得回 Linux 重跑；p4a 每次会重建 build 目录，需固定工作副本；本质是自维护的双机流水线，脆弱 |
| **A6 自建 p4a 等价物** | 手写 Gradle 工程 + 预编译 CPython for Android + 自己写 JNI bootstrap 与 assets 解包 | 完全掌控 | 等于重写 p4a；工作量以人月计，不建议 |

补充一条对 A5 有利的事实：应用代码是以**明文 `.py` 放在 `assets/private.tar`** 里的
（所以 `hotpush.sh` 能直接改 `files/app/app_src/tools/*.py`），
而 stdlib/site-packages 在 `libpybundle.so` 里。这意味着"只改业务代码"时，理论上是
"重打 private.tar + gradle 打包"，不需要 p4a 重新编译——但这条链路目前没人维护，要先验证。

**结论（不改语言）**：A1/A2/A3 都是工程上成熟的替代，本质是"在 Linux 环境里编，Windows 只做触发器"；
A5 是唯一能让 Windows 承担打包步骤的折中，但把复杂度转移到了流水线维护上。
**没有任何路径能做到"纯 Windows、无 Linux 环节、官方支持"。**

### 4.3 迁移到 C++ 之后：Windows 是官方支持的宿主

Qt for Android（C++）文档里，Windows 是明确支持的宿主（连 SDK 路径 `C:\Users\<USER>\AppData\Local\Android\Sdk\`
和 Windows 专属的 `extras;google;usb_driver` 步骤都单独写了）。构建链变成：

```
CMake → Ninja → androiddeployqt → Gradle → APK
```

Qt 6.12 的版本矩阵 `[官方文档]`：JDK 21、NDK 27.2.12479018、`platforms;android-36` + `build-tools;36.0.0`、
Gradle 9.5.1 / AGP 9.2.1、支持 API 28~36。

收益（这是迁移最"确定"的一项，与性能无关）：

| 项 | 现在 | 迁移后 |
|---|---|---|
| Windows 原生构建 | 不支持 | 官方支持 |
| 单 ABI 全量构建 | 40~60 min | 约 5~15 min（首次含依赖下载） |
| 增量构建 | 不支持真正增量（p4a 每次重打） | 1~3 min（ninja 增量 + gradle） |
| 调试 | 只能靠日志/热更新 | Qt Creator + lldb 直接断点 |

**限制条件**（迁移后仍需处理）：

1. **16 KB 页对齐**：Qt 6.12 在 NDK < 28 时会给链接目标自动加 `-Wl,-z,max-page-size=16384`
   （`android_16kb_pages` 特性），但项目自己的 `.so`（`libsr_qnn.so`）仍需过
   `android/tools/check_elf_page_align.py` 这道门。用 NDK 28+ 则由 Clang 默认保证。
2. **NDK 版本对齐**：Qt 官方 Android 库是用 NDK 27.2 编的，混用更高版本可能出现符号缺失；
   项目当前用 r28（为了 16 KB 默认对齐），需要实测确认，或统一钉到 27.2 + 显式链接参数。
3. **Windows 文件系统副作用**：长路径（>260）、大小写不敏感（掩盖 Linux CI 才会暴露的问题）、
   杀软扫描拖慢编译；建议短构建目录 + Defender 排除。
4. **QNN/ORT/模型仍是外部产物**：预编译 `.so` 与 27 个 ONNX 模型按 ABI 引入，与语言无关。
5. **签名/发布**：keystore 路径、`apksigner`、AAB（release）流程要重建。

### 4.4 这一问的分场景答案

| 你的真实诉求 | 答案 |
|---|---|
| "我不想开 WSL/等 40 分钟" | 不需要迁移：A2/A3（容器或 CI）+ 增量缓存即可，成本 1~3 天 |
| "我要在 Windows 上能断点调试 Android 端" | 需要迁移（或至少把 UI 层迁走），C++ + androiddeployqt 是唯一干净路径 |
| "我要 APK 小一半" | 不必迁移：先拆模型分包（-150 MB）+ `images.rcc`（-22 MB），比迁移收益大 |
| "我要启动快、翻页不卡" | 不必迁移：P0+P1+P2 能拿 60~70% 收益（见 §5） |

---

## 5. 总体建议

### 5.1 分阶段路线（按 ROI 排序）

| 阶段 | 动作 | 收益 | 成本 |
|---|---|---|---|
| **P0** | `images_rc.py` → `images.rcc` + `QResource.registerResource()` | 启动 -196 ms、RSS -75 MB、**APK -22 MB**（private.tar 里这份是明文存储） | 0.5 天 |
| **P0** | 桌面 `SegmentationPicture` 切到 Qt 域内还原 | 单页 39.6 → 24 ms | 0.5 天 |
| **P0** | 模型分包（基础包 + 按需下载） | APK -150 MB 量级 | 2~5 天 |
| **P1** | 解码进程池 / pybind11 扩展（绕开 GIL） | 预加载 2.5~4× | 1~2 周 |
| **P1** | 列表改 `QStyledItemDelegate` | 首屏 250~500 → 80~150 ms | 1~2 周 |
| **P2** | 阅读器页项去 `QGraphicsProxyWidget` | 开章 154 → 20~40 ms，-8 MB/章 | 2~4 周 |
| **P3** | 渲染层 + 解码用 C++（pybind11，<15% 代码） | 接近 C++ 水平 | 1~2 月 |
| **P4** | 整体 C++ 化 | 见 §2 | 30~45 人月 |

P0+P1+P2 合计约 **2~3 人月**，可拿到 §2.1 里 60~70% 的收益，且每步可独立验证、独立回滚。

### 5.2 如果决定走整体迁移（P4），建议这样切

1. **第 0 阶段（2~3 周，Go/No-Go 门）**：只做技术验证——curl-impersonate 在 Android 上自编并跑通
   一次真实请求（TLS 指纹 + ECH + H3）；Qt C++ 空壳在 Windows 上 `androiddeployqt` 出包并装上真机；
   `libsr_qnn.so` 被主程序直接链接（去掉 ctypes）。
   **任一项失败 → 停在 P3，不要开 UI 重写。**
2. **第 1 阶段**：壳 + 导航 + 设置 + 阅读器（先只读本地），保留 Python 网络子进程。
3. **第 2 阶段**：列表/下载/登录/收藏，逐个替换，Python 侧同步下线对应模块。
4. **第 3 阶段**：网络层收编（curl-impersonate），删掉 Python 运行时。

每阶段结束用固定口径复测：`am start -W` TotalTime、`dumpsys meminfo` TOTAL PSS、
FrameTick p95、单页解码耗时。**若 PSS 未降 25% 或首帧未降 50%，止损回 P3。**

### 5.3 一句话结论

> 这次迁移买的不是"性能"，是**构建与调试的自主权**（Windows 原生、可断点、单一工具链）和
> **约 35% 的包体积**；代价是 30~45 人月、丢失 10 秒级设备迭代闭环、以及一个可能做不出来的
> curl-impersonate Android 交叉编译。若这三样里有任意一样不是硬需求，先做 P0~P2 更划算。

---

## 附录：本次测量方法

| 数据 | 方法 |
|---|---|
| 代码行数/类/信号 | `find src -name '*.py' \| xargs wc -l`、`grep -c`（排除 `images_rc.py`） |
| APK 体积构成 | `unzip -l` / `unzip -v` 按条目聚合；`assets/private.tar` 为 gzip（magic `1f8b`），`tar -tvf` 逐项统计 |
| 桌面包体积 | `du -sh build_out/JMComic_windows_x64_py310` + 子目录聚合 |
| 依赖盘点 | `grep -rn "from jmcomic\|import jmcomic"`、`grep -rn impersonate`、`ls lib/*` |
| 构建约束 | Qt 官方文档（pyside6-android-deploy / Qt for Android Prerequisites）+ `android/build_android.sh` |
| 性能数据 | 引用 `docs/pyside6_to_cpp_performance_assessment.md`（实测脚本见其附录） |
