# JMComic Android 移植说明

把桌面端(Python + PySide6 + sr_vulkan)的 JMComic 移植到 Android 手机：
**竖屏可用的界面 + 高通 NPU 加速的超分(waifu2x) + 最低 Android 14 (API 34)**。

> 桌面端行为**完全不变**：所有移动端适配都由 `tools/platform_mobile.py`、
> `tools/mobile_ui.py`、`tools/sr_backend.py` 在 `IsAndroid()` 为真时才生效。

---

## 1. 技术选型

| 关注点 | 方案 | 原因 |
| --- | --- | --- |
| Python + Qt 上 Android | 官方 `pyside6-android-deploy`（内部走 buildozer / python-for-android + aarch64 wheel） | 复用现有 700+ 个 Python 文件与全部 Qt Widgets 界面，不用重写 |
| 竖屏界面 | 运行时适配层（导航抽屉 / 最小尺寸放宽 / 详情页上下堆叠 / 触摸滚动） | 不复制一套 UI，也不影响桌面端 |
| 超分(waifu2x) | `sr_qnn`：ONNX Runtime **QNN Execution Provider** → Hexagon NPU (HTP) | 微软官方 Android QNN 包(`onnxruntime-android-qnn`)，头文件/库都现成；模型可量化 |
| 与现有代码接合 | `sr_qnn` 提供与 `sr_vulkan` **同构**的 API，并在 `sys.modules` 里注册成 `sr_vulkan` | `task_waifu2x.py` / `main_view.py` / `tool.py` 等原有调用点一行都不用改 |
| 存储 | 应用私有目录（内部）+ 应用外部私有目录（下载） | Android 14 上**不需要任何存储权限**，也不用处理分区存储 |
| 网络 | 原生 `curl_cffi`（curl-impersonate 指纹）优先；没有时用纯 python 垫片 | 保留桌面端的 Cloudflare 绕过能力，同时保证没编原生库也能跑 |

不支持/不需要：Android 14 以下兼容（`minSdk 34`）、系统托盘、无边框窗口、单实例 socket、子进程崩溃探测。

---

## 2. 目录结构

```
android/
├── main.py                  # 打包入口(pyside6-android-deploy 要求叫 main.py)
├── pysidedeploy.spec        # 部署配置(Qt 模块/插件、wheel、local_libs)
├── build_android.sh         # 一键构建：原生库 + 模型检查 + 打包 APK
├── README.md                # 本文档
├── app_src/                 # 构建时由 build_android.sh 从 ../src 复制(不入库)
├── libs/arm64-v8a/          # 原生库产物：libsr_qnn.so / libonnxruntime.so / QNN 库(不入库)
├── wheels/                  # PySide6 / shiboken6 的 android_aarch64 wheel(不入库)
├── sr_qnn/                  # 高通 NPU 超分后端
│   ├── __init__.py          # ctypes 封装，sr_vulkan 同构接口 + MODEL_* 常量
│   ├── cpp/                 # libsr_qnn.so 源码(ONNX Runtime C API + QNN EP)
│   │   ├── sr_qnn.h / sr_qnn.cpp / CMakeLists.txt
│   └── models/              # models.txt 清单 + onnx 模型(模型需自行生成)
├── recipes/curl_cffi/       # python-for-android recipe(编译 curl-impersonate)
├── shims/curl_cffi/         # 纯 python 垫片(原生库缺失时的降级方案)
└── tools/prepare_models.py  # 把动态 shape 的 waifu2x onnx 转成 NPU 可用的固定 shape
```

---

## 3. 竖屏界面适配（不影响主要功能）

实现位置：`src/tools/mobile_ui.py`（`Apply(mainView)` 在 `MainView.__init__` 末尾调用一次），
主窗口里的挂钩都是 `IsAndroid()` 守卫：

| 问题 | 处理 | 位置 |
| --- | --- | --- |
| 左侧导航栏固定 240px，竖屏把内容挤没 | 导航栏改成**浮动抽屉**：从横向布局里摘出来挂到 `subMainWindow`，宽度 = 屏宽 82%(≤300px)，默认隐藏，点“菜单”或右边手势切换后自动收起 | `SetupDrawer` / `CloseDrawer` |
| 各界面写死的最小宽度（如周表下拉 400px、SR 选择框 500px、代理框 450px） | 递归把 `minimumWidth > 屏宽-24` 的控件放宽（只降不升），对话框在 `Show` 事件里自动处理 | `RelaxMinSizes` / `_MobileFilter` |
| 详情页封面与信息左右并排，竖屏太挤 | 运行时把 `verticalLayout_2`(信息列) 从横向布局移到 grid 的下一行 → 上下堆叠，封面居中 | `StackBookInfo` |
| 设置页 `[左侧导航列, 内容区]` 左右并排，384px 下内容区只剩 ~230px，里面 `80+150+108` 的行全部显示不全 | 竖屏把外层布局改成**上下**、导航列改成**顶部横排**（`QBoxLayout.setDirection`，不重建布局也不动信号）；导航按钮清掉图标/说明并改用 `QSizePolicy.Ignored`，否则 `qSmartMinSize` 会按 sizeHint 要求 664px | `StackSideNavs`（通用，设置页 + 分流设置页都吃这一条）/ `StackSettingNav`（设置页补充） |
| 图片超分页 `[图像预览, 参数面板(max 300px)]` 左右并排，竖屏下预览只剩 80 多像素 | 竖屏改成预览在上(占大部分高度)、参数面板在下(整宽、限高可滚) | `StackSrTool` / `UpdateSrToolHeight` |
| 工具栏那一类**单行超宽**行(详情页的收藏/下载/评论按钮、收藏/历史/本地收藏/分类/周榜的分页栏)右侧控件被裁掉 | 顺序装箱拆成多行：控件全保留、顺序不变，每行都放得下（`QLayout.minimumSize()` 是判定依据，天然幂等，可反复调用） | `WrapWideRows` |
| 帮助页那种一整段说明文字的 QLabel，单行最小宽度 500+px | 对"本身放不下"的标签打开 `wordWrap` 折行；对长路径/长 URL 这种没有换行机会的文本检测到降不下来就还原 | `EnableLabelWrap` |
| 帮助页版本信息是 3 列 QGridLayout，列宽相加 524px | 压成单列(每个控件一行)；压完还放不下就**原样还原**，绝不帮倒忙 | `FlattenWideGrids` |
| 手指不能拖动滚动 | 给所有 `QAbstractScrollArea` 挂 `QScroller` 触摸手势 + 逐像素滚动（看图控件本身除外，它有自己的一套拖动逻辑，见下） | `EnableTouchScroll` |
| **滑动页面时会误改设置**：Qt 把触摸合成为鼠标事件后直接投给手指下的子控件，抬起时子控件把"滑动"当成了点击。下拉框/数值框更严重——它们在 **press** 时就弹列表/加减数值，数值框按住还会自动重复（而它只认 release 来停） | 对勾选框/单选/按钮/下拉框/数值框：**连 press 一起扣住**，位移超过阈值就丢弃（控件完全不知情），小于阈值才把 press+release **重放**给控件（语义与真实点击完全一致）。滑块/滚动条/列表视口仍只扣 release（它们需要按下拖动）。弹窗(Qt::Popup)里的操作不拦 | `_TouchGuard` / `InstallTouchGuard` |
| 顶部分页按钮溢出 | 窄屏降低按钮字号、允许压缩 | `CompactTabBar` |
| **改设置/输入就崩溃(SIGABRT)**：设置页每改一项都会弹一次"保存成功"提示条(`MsgLabel` 是独立顶层窗口)、切页签弹加载框，这些 `show()` 都是在**输入事件处理过程中**同步执行的，Qt 会在 `QWindowPrivate::setVisible` 里同步 flush 窗口系统事件 → 立刻 Expose → 立刻 paint → `QAndroidPlatformOpenGLWindow::eglSurface()` 重入 → `'Failed to acquire deadlock protector for ...'` → abort | 把顶层窗口的 `show/hide/close` 统一改成"延后到当前事件处理结束"(0ms 定时器)再执行：`QWidget.show/hide/close` 在 Python 侧套一层，只对顶层窗口生效（主窗口除外）。注意 `QEvent.Show` 是 `show_sys()` **之后**才发的，在事件过滤器里拦它来不及，必须拦在"调用 show()"这一层 | `InstallShowDeferral` / `DeferCall` |
| **看图界面无法滚动 + 菜单超出屏幕**：`ReadFrame.ScaleFrame` 写死 `qtTool.setGeometry(w-400, 0, 400, h)`，384px 屏上是 `x=-16`；看图区只有滚轮逻辑，触摸上既没滚轮也没有拖动实现 | 菜单改为占满看图区整宽；把拖动位移直接喂给和滚轮同一条路径(`ReadScroll.scrollValue`)，并在页尾复用滚轮的自动翻页；点按(|dx|、|dy| 都小于阈值)完全不碰，原来的"三分区点按"逻辑不变 | `SetupReadTool` / `ApplyReadToolGeometry` / `_ReaderDrag` |
| **返回键**：菜单收不起来；看图退不出去；根页面上什么都不做，事件继续下传导致 Activity 被 finish，而 Python 主线程已退出 → 前台留一个**白屏** | 统一在 `HandleBackKey` 里按优先级处理并 accept 事件、吞掉抬起事件（400ms 去抖）：弹出窗口 → 看图菜单 → 顶层对话框 → 抽屉 → 退出看图 → 回退页面 → **根页面退到后台**(最小化，不再白屏) | `HandleBackKey` / `MinimizeToDesktop` / `main_view.keyPressEvent` |
| **首页一行只放得下 1 本漫画**：封面按桌面写死 250x340 | 竖屏按屏宽反算封面宽，并用 `QListWidget` 的**真实几何**自校正到"一行 2 个"（只按 sizeHint 估算会被 item 自身的边距骗过去；改完 sizeHint 还必须显式 `setGridSize` + 强制重排） | `GridCoverWidth` / `ApplyGridCoverSize` / `RefreshItemSizeHints` / `ComicItemWidget.ResizeCover` |
| **导入本地漫画 / 导入本地图片卡死** | Android 上不再用 `QFileDialog`（它会创建一个回不来的顶层窗口 + 嵌套模态循环），改为**主窗口内的子控件选择器** + 嵌套 `QEventLoop`（不创建任何顶层窗口）；桌面端原样转发 `QFileDialog` | `tools/mobile_file_dialog.py` |
| 系统托盘不存在 | Android 下不创建 `QSystemTrayIcon`，关闭窗口即退出 | `platform_mobile.SupportSystemTray` |
| 旋转屏幕 | 窗口尺寸变化时重算宽度上限、抽屉几何、滚动区域，并重跑一次拆行/折行/封面尺寸 | `mobile_ui.OnShown` / `OnResize` |

功能层面**没有做减法**：下载、看图、搜索、收藏、评论、NAS、批量超分、设置等入口都在抽屉里，
只有桌面专属的系统托盘/无边框标题栏/单实例被去掉。

排版重排只**移动**控件、不改信号连接，测试里有一条硬约束：
重排前后每个页面的控件数量必须完全一致（`[ok] 竖屏重排没有丢失任何控件`）。

### 3.1 接口响应解密（AES）在 `bootstrap=qt` 下必须补 `ctypes.util`

禁漫所有接口的响应体都是 AES 密文，`jmcomic.JmCryptoTool.decode_resp_data` 解不开就
**登录报错、首页也报错**。真机上它必然失败，原因是两层叠加：

1. python-for-android 的 `python3` recipe 把标准库 `Lib/ctypes/util.py` 整个替换成
   `from android._ctypes_library_finder import find_library`；
2. 而 p4a 的 `android` 包顶层就是 `from android._android import *`，`_android.so` 依赖
   **SDL2/webview bootstrap** 里的 JNI 符号 `WebView_AndroidGetJNIEnv` ——
   `bootstrap=qt` 下没有这个符号，`dlopen` 必然失败：
   `ImportError: dlopen failed: cannot locate symbol "WebView_AndroidGetJNIEnv"`。
   （该 finder 自己也要 `from jnius import autoclass`，而 pyjnius 没打进 APK。）

pycryptodome 在 `sys.flags.optimize == 2` 时会**主动**放弃 cffi 后端回落到 ctypes 后端
（p4a 的 Qt bootstrap 在 `PythonActivity.java` 里硬编码了
`setEnvironmentVariable("PYTHONOPTIMIZE", "2")`），回落路径第一行就是
`from ctypes.util import find_library` → 于是 `Crypto.Cipher.AES` 永远导入失败。

修法（`platform_mobile.InstallCtypesLibraryFinder()`，由 `android/main.py` 在
`SetupPath()` 里调用）：往 `sys.modules` 里放一个**纯 python 的 `android` 垫片**，
提供不依赖 pyjnius 的 `find_library`，真实 android 包目录仍挂在 `__path__` 上。
这样 `ctypes.util` 那句被 p4a 替换过的 import 能成功，而 `_android.so` 根本不会被 dlopen。

pycryptodome 真正的原生库是用**绝对路径**加载的
（`load_pycryptodome_raw_lib()` 走 `pycryptodome_filename()`，路径里含 `.`，
`load_lib()` 因此不会再调用 `find_library`），所以只需要那句 import 不炸。

真机取证（`android_startup.log` 的 diagnostics 块）：

```
ctypes find_library: OK (from tools.platform_mobile)
  find_library('c') = /system/lib64/libc.so
  find_library('crypto') = /data/app/.../lib/arm64/libcrypto.so
ctypes.util: OK (find_library=ctypes.util)
pycryptodome: backend=cffi AES=<module 'Crypto.Cipher.AES' ...>
jmcomic decode_resp_data: True ('{"code":200,"data":[]}')
```

主机侧回归（用子进程复现"android 包导入即失败"）：
`android/tools/host_test_crypto_android.py`。

### 3.2 还有第二层：`PYTHONOPTIMIZE=2` 让 ctypes 后端在 Android 上必死

只修 `ctypes.util` 还不够。p4a 的 Qt bootstrap 在 `PythonActivity.java` 里硬编码了

```java
setEnvironmentVariable("PYTHONOPTIMIZE", "2");   // => sys.flags.optimize == 2
```

而 pycryptodome 在 optimize==2 时会**主动放弃 cffi 后端**
（`raise ImportError("CFFI with optimize=2 fails due to pycparser bug.")`），
回落到 ctypes 后端；ctypes 后端要 `ctypes.pythonapi.PyObject_GetBuffer`，
在 Android 上解析不到 —— libpython 是 `RTLD_LOCAL` 载入的，`dlopen(NULL)` 看不到
Python C API 符号，于是：

```
Crypto/Util/_raw_api.py: _PyObject_GetBuffer = ctypes.pythonapi.PyObject_GetBuffer
AttributeError: undefined symbol: PyObject_GetBuffer
```

**所以必须让 optimize != 2。** 改成 `1`（`-O`）而不是 `0`：
`-O` 同样会去掉 `assert`（和原来行为一致，代码里 193 个 assert 不会突然生效），
但**保留 docstring**，cffi/pycparser 因此可用。

由 `android/tools/wsl_patch_optimize.sh` 在 buildozer 之前打补丁（改所有副本：
venv311 里的 pythonforandroid、p4a 检出、`.buildozer/.../bootstrap_builds`、
以及 Gradle 真正编译的 `dists/*/src/main/java/.../PythonActivity.java`），
`wsl_build_apk.sh` / `wsl_repack_apk.sh` 都会调用并校验，改不动就直接失败退出。

宿主机实测（cffi 2.0.0 + pycparser 2.14，与 APK 里完全相同）：

```
python -OO android/tools/probe_cffi_backend.py  -> backend=ctypes   # 真机原来就是这条
python -O  android/tools/probe_cffi_backend.py  -> backend=cffi     # 改完这条，AES 可用
```

顺带确认过 `stdlib.zip` 用的是 legacy 命名（`module.pyc`，588 项），
zipimport 不区分 optimize 级别，所以改 `PYTHONOPTIMIZE` 不会丢标准库
（`android/tools/inspect_pybundle.py` 可复查）。

### 3.3 QFileDialog 在 Android 上会卡死 → 换成应用内选择器

真机(vivo V2463A / Android 16)反馈：**导入本地漫画、图片超分导入本地图片会卡死**。
根因是这些调用点用了 `QFileDialog.getExistingDirectory / getOpenFileName /
getSaveFileName`：Qt 在 Android 上没有原生对话框，会新建一个**顶层窗口**并在里面跑
**嵌套模态事件循环**，实测再也不返回调用点。

修法是 `src/tools/mobile_file_dialog.py`：`IsAndroid()` 为真时不再创建任何顶层窗口，
而是在**主窗口内部**放一个覆盖控件(parent 到主窗口、铺满、`raise_()`)，再用嵌套
`QEventLoop` 等用户操作 —— 原有同步阻塞调用点只换函数名即可。三条硬约束：

| 约束 | 做法 |
| --- | --- |
| 桌面端行为一个字都不能变 | `IsAndroid()` 为假时**原样转发**给对应的 `QFileDialog` 静态方法，返回值形状一致(`getExistingDirectory` 是 `str`，另两个是 `(文件名, 过滤器)` 元组，取消时分别是 `""` 与 `()`) |
| 竖屏 384px 宽 | 全部整宽、一行一个控件；路径用 `QFontMetrics.elidedText` 中间省略；`确定/上级/取消` 每个约 110px |
| 绝不能卡死 | 列目录一律 `os.scandir` + `try/except`，失败只显示红字"无法访问该目录: ..."并停在原地；`Key_Back`/`Esc` = 取消；所有出口(确定/取消/关窗)都 `loop.quit()`，外层再兜一层异常保护 |

顺带处理了 Android 存储权限的现实：APK 没有 `READ_MEDIA_IMAGES` /
`MANAGE_EXTERNAL_STORAGE`，targetSdk 34 下 `/storage/emulated/0` 的绝大多数目录
`os.scandir` 会抛 `PermissionError`。所以覆盖控件顶部有一行固定提示("读取手机存储
需要「所有文件访问权限」")，快捷入口(应用目录/私有目录/存储/下载/图片)里**读不了的
直接置灰**，而不是点进去报错。

改了这些调用点：`local_read_view`(3 处，导入本地漫画)、`waifu2x_tool_view`(2 处)、
`setting_view`、`download_dir_view`、`nas_add_view`、`batch_sr_tool_view`、
`read_view`(2 处)。

主机回归(不需要手机)：`android/tools/host_test_file_dialog.py`，覆盖桌面委托、
目录/文件排序、过滤器、进入子目录与上级、三种模式的确定/取消、返回键、
权限失败降级、以及**真的跑一次嵌套事件循环**确认不卡死：

```bash
QT_QPA_PLATFORM=offscreen python android/tools/host_test_file_dialog.py
```

### 3.4 第二轮真机反馈（2026-09-30，10 条）的根因与修法

| # | 现象 | 根因（实证） | 修法 |
| --- | --- | --- | --- |
| 1 | 在下拉菜单选项框/数值选项框**附近**滑动会误触它们 | Qt 把触摸合成的鼠标事件直接投给手指下的子控件；`QComboBox` 在 **press** 就弹列表，`QAbstractSpinBox` 在 press 就开始加减并**自动重复**（只认 release 来停，所以"吃掉 release"反而让它一直加） | 守卫改成"扣住 press + 点按重放"：位移超过 16px 就丢弃这次 press（控件完全不知情），小于阈值才把 press+release 原样重放。重放期间必须关掉守卫自己，否则无限递归 |
| 2 | 分流设置仍为双排排版 | 分流设置就是 `login_new.tab_4`，结构同样是 `[竖排标题列, scrollArea_3]`，之前只改了设置页 | 抽成通用规则 `StackSideNavs`：任何"外层横向布局 = [只有标题按钮的导航列] + [QAbstractScrollArea]"都改成上下 |
| 3 | 改设置/输入就**崩溃** | 真机 SIGABRT：`'Failed to acquire deadlock protector for QAndroidPlatformOpenGLWindow::eglSurface().'`。这是 **Android + Qt6.11 上"第二个顶层窗口"的渲染问题**：只要新建一个顶层窗口并开始渲染，第一层窗口的 EGL surface 还持有时，新窗口的 RHI backing store 创建(`QBackingStoreRhiSupport::create → QRhi::create → QOpenGLContext::makeCurrent → eglSurface`)就会撞上那个全局死锁保护器并直接 `qFatal`。第一版栈是"输入事件里同步 show"，第二版栈是"延后 show 时在 `sendPostedEvents` 里 show"——**延后是没用的**，因为窗口照样要建、要渲染 | 把"本该是顶层窗口"的东西全部改成**主窗口里的子控件覆盖层**(`MakeChildOverlay`)：提示条 `MsgLabel`(每次改设置都弹)、加载框 `LoadingDialog`(每次切页都弹)、以及 `BaseMaskDialog` 基类(登录/收藏夹/模型选择/目录选择/DoH/NAS/Sign…全部继承它)。子控件和主窗口共用同一个平台窗口，彻底不走这条渲染路径。另外仍保留"顶层窗口 show/hide/close 延后"这道兜底 |
| 4 | 看图界面里图片无法正常解密 | `TaskQImage.Run()` 的 `finally: emit(taskId, newQ)`：异常时 `newQ` 是**上一张图**(第一轮则是 `UnboundLocalError` 直接把工作线程弄死)，于是页面拿到错图/再也不出图；`if not info.data: return` 同样会终结线程 | 每轮 `newQ = None`、空数据 `continue`、只有真正解出非空 `QImage` 才回调；解码失败记 `len(data)+前 8 字节`；`TaskMulti` 的队列等待加超时(20s/60s)并把 worker 数夹到 `max(1, min(MultiNum, 8))`；`SegmentationPicture` 任何异常都**返回原始字节**而不是 `None` |
| 6 | 看图界面和它的菜单都滚不动，菜单宽度超出屏幕 | `ReadFrame.ScaleFrame` 写死 `qtTool.setGeometry(w-400,0,400,h)`，384px 屏上是 `x=-16`；看图区只有 `wheelEvent`，触摸设备既没有滚轮也没有拖动实现 | 菜单改为占满看图区整宽；新增 `_ReaderDrag`：拖动位移直接走和滚轮同一条 `ReadScroll.scrollValue` 路径(含页尾自动翻页)，点按完全不碰 |
| 7/8 | 菜单收不起来 / 看图退不出去 | 返回键只在 `keyReleaseEvent` 处理，优先级里没有"菜单"这一档 | `HandleBackKey` 统一优先级：弹出窗口 → 看图菜单 → 顶层对话框 → 抽屉 → 退出看图 → 回退页面 → 根页面；`keyPressEvent` 里处理并 accept，400ms 去抖吞掉抬起事件 |
| 9 | 主页返回不是回桌面，而是白屏 | 真机实测根因**不是**返回逻辑，而是 Qt 的"最小化"在 Android 上只隐藏了 Qt 窗口：`showMinimized()` 之后 `dumpsys activity` 里 Activity 仍是 `topResumedActivity`、窗口 `mViewVisibility=VISIBLE`，而 Qt 已经不再绘制 —— Android 那边还停在前台却没有任何内容，就是白屏。真正的 `moveTaskToBack(true)` 这个包调不到：`jnius.so` 在真机上 dlopen 失败(`cannot locate symbol "WebView_AndroidGetJNIEnv"`，bootstrap=qt 没有那个符号)，PySide6 6.11 也没有绑定 `QJniObject` | 根页面返回改为**保持窗口可见** + 一次提示，绝不隐藏/最小化窗口(不留白屏)；要回桌面用系统手势/Home(Android 标准做法)。顶栏另加一个看得见的**返回按钮**，走同一条 `HandleBackKey` |
| 7/8/9 | 返回键到底有没有到 Qt | `device_keys` 诊断(把应用收到的按键/窗口事件写日志)实测：Android 16 + Qt 6.11 上返回键**能**到，`back: root-page` / `close-read-tool` / `close-reader` 都真的被触发过 | 保留按键处理；`key diag` / `window diag` 记录按键与窗口生命周期，便于复现"白屏"前后的窗口序列 |
| 9 | 主页返回不是回桌面，而是白屏 | 根页面上什么都不做 → 事件下传 → Activity 被 finish，而 Python 侧 `app.exec()` 已返回、主线程退出，Activity 留在前台就是个白屏 | 根页面返回改为 `showMinimized()` 退到后台（无 pyjnius/无 `QJniObject`，调不到 `moveTaskToBack`，所以用 Qt 的最小化，真机结果由自检记录） |
| 10 | 主页每行只放得下 1 本漫画 | `ComicItemWidget` 按桌面写死 250x340，384px 屏上一行只放 1 个 | 竖屏按屏宽反算封面宽 + 用 `QListWidget` 真实 `sizeHint` 自校正到"一行 2 个"；改完 sizeHint 还要 `setGridSize` + 强制重排，否则视图不重新装箱 |
| 11 | 导入本地漫画/导入本地图片卡死 | `QFileDialog`(见 §3.3) + **APK 里根本没有存储权限**（只有 INTERNET/WAKE_LOCK/WRITE_EXTERNAL_STORAGE，Android 11+ 起后者已失效），targetSdk 34 下 `/storage/emulated/0` 基本不可读 | 换应用内选择器；`patch_buildozer_spec.py` 与 `patch_android_manifest.py` 补 `READ_EXTERNAL_STORAGE` / `READ_MEDIA_IMAGES` / `MANAGE_EXTERNAL_STORAGE`（后者需用户在系统设置里手动授予"所有文件访问权限"，APK 里没 `libjnius.so`、PySide6 也没绑定 `QJniObject`，无法在应用内弹权限申请） |

真机取证靠应用自检 + `adb input`（设备上没有 OCR，`uiautomator` 也读不到 Qt Widgets 的树）：
`device_verify`(首页/排版)、`ui_touch_selftest`(设置页触摸目标物理坐标)、`device_reader`
(看图界面：离线解密往返 + 菜单/滚动几何 + 返回键序列)。判定脚本
`android/tools/verify_on_device.ps1` 会把 touch guard 的
`presses/drags/suppressed/replayed` 计数、下拉框/数值框的**值**、看图区的
`v/h` 滚动值与菜单可见性、以及 `back:` 动作逐条判定。

#### 真机实测结果（vivo V2463A / Android 16 / arm64，2026-10-06 那版 APK）

```
sys.flags.optimize: 1
pycryptodome: backend=cffi AES=<module 'Crypto.Cipher.AES' ...>
jmcomic decode_resp_data: True ('{"code":200,"data":[]}')
接口解密统计: ok=10 fail=0                     # 10 个真实加密响应全部解开(登录/首页不再报错)
---- 图片解密自检(离线) ----
  QImage 解码: 原图=True 60x384 / 解密后=True 60x384 不同像素=0
  解密自检: PASS
  TaskQImage.ConverQImage: True 60x384 -> PASS  # 走应用真实链路
---- 首页网格自检(真机视口) ----
  真机列表: 控件 348x610, 视口 330x598
  反算封面宽: 视口 330px - 余量 36px -> 封面 147px (2 列)
首页网格: 封面宽 147px 控件宽 159px 栅格=159x318 / 可用 330px -> 每行 2 个(前 30 行 [2, 2, 2, ...])
  首页网格自检: PASS (一行 2 个, 期望 2)
---- 文件选择器自检(真机) ----
  选择器: isWindow=False 父控件=MainView 当前目录=/storage/emulated/0/Android/data/org.jmcomic.jmcomic/files
  不可读目录: 已降级处理(没有抛异常)
  选择器自检: PASS                       # 不开顶层窗口 + 能列目录 + 读不了的目录不卡死
reader tool: 面板=(0,0,384x787) 看图区=384x787 -> 整宽(在屏内)
reader 滚动: 菜单滚动区=已接管滚动 看图区(ReadGraphicsView)=拖动滚动已接管
window guard: ... 子控件覆盖层=6                # 6 个"本该是顶层窗口"的控件已改成主窗口子控件
touch guard: presses=40 drags=19 suppressed=19 replayed=2   # 真实手指: 19 次误触被挡下, 2 次点按被重放
reader t= 37s ... back=1 lastBack=close-read-tool    # 返回键先收看图菜单
reader t= 45s ... back=2 lastBack=root-page          # 再退到根页面(不隐藏窗口 -> 不白屏)
```

装完整轮后 `logcat -b crash` 是**空**的（旧包在设置页改几个选项就会刷一条
`Failed to acquire deadlock protector ... eglSurface()` 的 SIGABRT）。

> 装包注意：vivo 的"安装确认"弹窗会把 `adb install` 挡成
> `INSTALL_FAILED_ABORTED: User rejected permissions`(息屏/锁屏时必现)。
> 需要先 `input keyevent KEYCODE_WAKEUP` + `wm dismiss-keyguard`，并在手机上点"允许/继续安装"。

> 改 `android/tools/*.ps1` 之后必须跑一次 `android/tools/fix_ps_bom.ps1`：
> Windows PowerShell 5.1 在没有 BOM 时按 ANSI(GBK) 读脚本，中文会变成乱码并直接解析失败。

### 3.5 第三轮真机反馈：图片分割异常、图像错位

**现象**：真机看图时页面被"切成一条条"、带子错位。

**真机日志**（`files/state/jmcomic-qt/logs/20261006.log`，21:40）：

```
tool.py[line:1070] ERROR: SegmentationPicture failed, epsId:1479594 scrambleId:220980
    len:1091216 err:cannot identify image file <_io.BytesIO object at 0x71e5de54e0>
tool.py[line:188]  (GetPictureSize 里 Image.open 的 traceback，每次都刷)
```

**根因：不是分割算法，是 Android 上 Pillow 没有 webp 解码器。**
JM 下发的图是 webp（日志里 URL 就是
`https://cdn-msp.jmapiproxy1.cc/media/photos/1479594/00001.webp`），而 APK 里的
Pillow 是 p4a 编出来的：
`PIL/_imaging.so` 在、**`PIL/_webp.so` 不在**（包里只有 `_webp.pyi`，见
`android/tools/probe_pillow_android.sh`）。于是

- `SegmentationPicture`（图片分割合成）第一句 `Image.open` 就抛
  `cannot identify image file` → 兜底 `return imgData`，把**被打乱的原图**直接交给界面，
  用户看到的就是"分割异常、错位"；
- `GetPictureSize` 同样抛异常 → `mat` 兜底成 `"jpg"`（所以缓存文件名是 `1.jpg`、
  内容却是 webp）、`isAni` 恒为 `False`。

**离线取证**（`android/tools/probe_cached_page.py` + `probe_seam_score.py`）：
把真机缓存下来的那一页（1091216 字节）拉到宿主，桌面 Pillow 解出 `WEBP 2100x3018`；
`epsId=1479594 scrambleId=220980 pictureName=00001 → num=12`（`3018 % 12 = 6`）；
本仓库的分割算法与官方 `jmcomic` 的 `JmImageTool.decode_and_save` **逐像素完全相同
（不同像素=0）**，还原结果是一张完整封面（未还原那张能直接看到 12 条带子错位，
`android/build_logs/page_raw.png` vs `page_repo_decoded.png`）。所以问题在 Android 的
编解码器，不在分割算法。

**修法**（`src/tools/tool.py`、`src/task/task_qimage.py`）

1. 新增一套 **Qt 图像栈**的分割实现：`SegmentQImage` / `SegmentationQImage` /
   `SegmentationPictureQt` / `SegmentationPictureToDiskQt`。Qt 的 qwebp 插件本来就在
   APK 里（`libplugins_imageformats_qwebp_arm64-v8a.so`，看图界面一直靠它显示）：
   **Android 上优先用 Qt**，桌面端仍以 Pillow 为主，Pillow 抛异常时 Qt 也兜底；
   需要编码时按源格式编码（webp→WEBP，有损格式给 quality 95）。
2. 看图线程直接在 **QImage 域**还原（`TaskQImage._SegmentQImage`，统计里 `Qt分割=`
   计数），省掉"还原→编码→再解码"的一次来回；页面原始字节永远不被改写。
3. `GetPictureSize` / `GetAnimationFormat` 加 Qt 兜底（Android 上先问 Qt）：
   格式/尺寸/是否动图不再因为 Pillow 缺解码器而失真。

**为什么之前的自检没抓到**（同样修掉了）

- 旧自检的样本是 `height = 48 * num`，也就是 `rem = 0`。**`rem = 0` 时这个变换恰好是
  对合**（还原两次回到原图），而真机那页是 `3018 % 12 = 6`；`rem != 0` 时二次还原会
  彻底错位。而且旧自检是"自己造样本 → 自己还原"，属于循环论证。
- 新自检 `mobile_ui.DecryptSelfTest()` 改成**与独立实现的官方算法逐像素比对**：
  合成样本 `rem=5`、`encode/decode` 互逆校验、`SegmentationQImage`(看图那条)、
  `SegmentationPicture`(bytes)、落盘路径、以及 `TaskQImage` 真线程回调；
  再挑一张**真机缓存里的真 webp** 做同样的比对（`图片分割自检(真机样本 webp)`）。
- 宿主 `host_test_image_pipeline.py` 补了同样的用例，包括**把 Pillow 打坏的仿真**
  （`PIL.Image.open` 直接抛 `UnidentifiedImageError`）：Android 分支与桌面兜底分支
  都必须由 Qt 还原出正确的图、而不是原样返回打乱的字节。

**宿主实测**（`wsl_run_smoke.sh` 第 5 道门）：

```
--- 1d. 真机样本(webp) ---
PASS  真机样本: Qt 还原(看图线程那条) == 官方算法(逐像素 (2100, 3018))
PASS  真机样本: bytes 路径结果≈官方算法(有损重编码, 平均差 0.9) 且远好于未还原(75.8)
ALL 58 IMAGE PIPELINE CHECKS PASSED
```

> `rem != 0` 时**绝不能**对同一张图做两次还原；`SegmentationPicture` 的输入永远是
> 服务端原始字节（`read_view` 里的 `p.data` / `info.data` 不被改写）。

#### 真机实测结果（vivo V2463A / Android 16 / arm64，2026-10-06 23:08 那版 APK）

```
Pillow 11.3.0: jpg=True webp=False zlib=True PIL/_webp.so=缺失     # 设备侧确认根因(webp 解不了)
图片分割自检(合成, rem=5): PASS                                     # 与独立实现的官方算法逐像素一致
真机样本: 29.webp (131422 字节, 书 1479694 章节 1 页 29)
真机样本解码: Pillow=失败 (UnidentifiedImageError) Qt=True 960x1280
解密自检: PASS

图片解码: 任务=6 成功=6 失败=0 空图=0 Qt分割=6 bytes分割=0        # 看图真的每页都走 Qt
---- 真机看图页分割对账(真数据) ----
  真机看图页: 页=0 epsId=1478519 scrambleId=220980 pictureName=00001 num=8 960x1356 107784 字节
  真机看图页还原: 与官方算法 可比=True 不同像素=0 / 未还原平均差=63.0
  真机看图页分割: PASS
```

最后这段是**最硬的证据**：用的是看图界面**当前正在显示的那一页**（服务端原始字节）+
它**自己算出来的** `saveParams`，还原结果与独立实现的官方算法**逐像素完全相同**
（未还原的那份平均差 63.0 —— 确实是被打乱的原图）。

同一套操作下，旧包（22:08 那版）的应用日志里是**一串**
`SegmentationPicture failed ... cannot identify image file`；
新包里这条命中 **0 次**，`logcat -b crash` 也是空的 —— 那条失败链已经彻底断开。

复现命令：`android/tools/run_device_reader_selftest.ps1`（重新打标记、启动、等自检落盘并回读），
或整轮 `android/tools/verify_on_device.ps1`。

> 注意：老包"下载到手机/导出"时也是走 `SegmentationPicture`/`SegmentationPictureToDisk`，
> 所以**旧版本下载目录里已经存下来的图本身就是被打乱的**（还原失败后原样写盘）。
> 升级后这些旧文件不会自动修好：需要重新下载，或删掉重下。

### 3.6 第四轮真机反馈：首页双列"打开时不生效，进设置页再返回才对"

**现象**：冷启动进首页，漫画是一行 1 个；进一次设置页再返回首页，才变成一行 2 个。

**根因**（时序，不是算法）：封面宽度是**全局缓存 + 自校正**的（`mobile_ui` 里的
`_gridCoverFinal` / `_gridCoverAvail` / `_gridAvail`），而首页的漫画是网络回来后
**一条条 `AddBookItem`** 建出来的：

1. `MainView.__init__` 里就跑 `mobile_ui.Apply()` → `ApplyGridCoverSize`。那一刻窗口还是
   `.ui` 的设计尺寸（远宽于手机），列表也还没被布局（`ComicListWidget.__init__` 里写死了
   `resize(800, 600)`）——**空列表**就把封面宽 freeze 成了 `GridCoverMax`(240px)。
   ```python
   # GridCoverWidth() 的算法：(可用宽 - 余量) / 2，再夹到 [96, 240]
   (780 - 36) / 2 = 372  ->  夹到 240px        # 真机真的是 240，不是 165
   ```
2. 窗口随后被 Android 拉成竖屏 384px，但 `OnResize` 只在 `_limit` **变化**时才重排；
   而 `_limit = max(240, min(320, 宽-24))` 在宽 ≥ 344 时恒等于 320 —— **缩窗口走不到那一支**，
   所以没有任何时机纠正上面那个 240。
3. 网络回来的漫画按 240px 建控件（`ComicItemWidget._CoverSize` 读的就是 `GridCoverWidth`），
   240 + 边距 > 视口/2 → 一行 1 个。
4. 用户切页 → `InstallReflowHook` 的 `currentChanged` → `ApplyGridCoverSize(那一页)`：
   这时视口是真的 366px ≠ 缓存的 780px → 缓存作废重算 → 165px → 一行 2 个。
   **这就是"进设置页再返回才对"**。

**修法**（四层，互相兜底）：

| 位置 | 改动 |
| --- | --- |
| `mobile_ui.MeasureGridAvail` | 视口宽度按**页面宽度**夹住（列表不可能比页面还宽）。设计尺寸/未布局的 800px 混进竖屏的入口在这里被掐掉 |
| `mobile_ui.ScheduleGridCoverSize` | 新增去抖重排（80ms）：加完一批漫画就对一次"一行 2 个"。`ApplyGridCoverSize` 内部有 `_jmGridSized == width` 短路，所以重复调用只处理新 item，翻页加载没有额外开销 |
| `comic_list_widget.AddBookItem` / `AddBookByLocal` | 每加一个封面就 `ScheduleGridCoverSize(self)`；非 Android 下直接返回，桌面端不受影响 |
| `mobile_ui.OnResize` | `_limit` 没变也要排一次重排（覆盖"设计尺寸 → 手机宽度"这种缩放） |
| `comic_item_widget.ResizeCover` | 变小时先 `setMaximumWidth(16777215)` 松绑：`RefreshItemSizeHints` 会用 `setFixedWidth` 把 item 钉在栅格宽上，不松绑的话 `adjustSize()` 缩不回去，封面小了控件还是旧宽 → 仍然一行 1 个 |

顺带把一个测试自身的坑修了：§③ 断言的是"快照一致性"（自校正出的封面宽要原样缓存给
后加的 item），而新加的去抖重排可能在断言前测量**另一个宽度的列表**并改写全局缓存，
所以 §③ 开头先 `_StopPendingGrid()` 固定快照（真机上所有列表同宽，不存在这种情况）。

#### 真机实测（vivo V2463A / Android 16，新包启动那一次）

```
00:27:07,248  mobile ui adapted, limit:320
00:27:07,268  ui: shown: 863x633 windowState=WindowMaximized          # 启动时窗口真的是 863px 宽(设计尺寸)
00:27:07,273  portrait: 列表视口 384px -> 618px，重算封面宽             # 旧代码就是在这里把封面宽 freeze 成 240
00:27:07,584  portrait: 列表视口 618px -> 372px，重算封面宽             # 窗口被拉成竖屏：_limit 没变也重排(修复④)
00:27:12,628  ui: page -> IndexView[首页] (index 0)
00:27:12,772  portrait: 列表视口 372px -> 338px，重算封面宽
00:27:18,178  portrait: 列表视口 338px -> 330px，重算封面宽             # 没有切页，是"加完封面"排的重排(修复②)
00:27:18,201  portrait: 80 个封面改为一行 2 个(封面宽 147px)           # ★ 首屏 80 个封面直接就是一行 2 个
```

关键是最后两行：**中间没有任何 `page ->`**，也就是用户还停在首页，80 个封面就已经被
改成一行 2 个了 —— 修复前这条只能在切页之后才出现（旧包日志里对应的是
`首页网格: 封面宽 151px 控件宽 163px 栅格=-1x-1 / 可用 330px -> 每行 1 个(前 60 行 [1,1,…])`）。

主机侧回归用例（`android/tools/smoke_test_android.py` §③.5，offscreen 不联网，已进 `wsl_run_smoke.sh`）
走的是**真实的 `ComicListWidget.AddBookItem`**：先按设计宽度给空列表 freeze 一次，再按真机视口
建两个 item，然后只等去抖重排：

```
[ok] 复现首屏: 空列表在设计宽度下就把封面宽冻结成 165px(视口按页面宽 366px 夹住)
     -> 首屏 item 183px 超出可用宽/2 共 23px(一行 1 个)          # 先复现出旧行为
[ok] 首屏自动收敛(无需切页): 封面 165 -> 138px / item 156px <= 可用 312px 的一半 -> 一行 2 个
```

---

## 4. Waifu2x on 高通 NPU

### 4.1 调用链

```
task_waifu2x.py
   └─ from sr_vulkan import sr_vulkan as sr     ← Android 下被替换成 sr_qnn(同构 API)
        └─ sr_qnn/__init__.py (ctypes)
             └─ libsr_qnn.so (C++, ONNX Runtime C API)
                  └─ QNN Execution Provider → Hexagon NPU (HTP, fp16)
                        └─ models/*.onnx (固定 1×3×192×192 输入)
```

图片解码/编码由 Python 侧的 `QImage` 完成（jpg/png/**webp**/gif/bmp 全支持），
C++ 只处理 RGB 原始像素，所以不依赖任何图像库。

### 4.2 QNN 要点（这几点决定能不能真的跑在 NPU 上）

1. **固定 shape**：QNN EP 不支持动态 shape。模型必须是 `1×3×T×T`，
   引擎按 T 切块、边缘补齐、回读拼接，保证无缝（`prepare_models.py` 负责固化 shape）。
2. **精度**：fp32 模型通过 `enable_htp_fp16_precision=1` 以 fp16 在 HTP 上推理；
   想要更快可以用 `--quantize` 生成 uint16/uint8 量化模型（QNN HTP 原生只吃量化模型）。
3. **整图跑在 NPU**：先按 `session.disable_cpu_ep_fallback=1` 建会话（严格模式），
   失败再允许 CPU 兜底，再失败退到纯 CPU EP —— 三层兜底，保证任何机型都有超分可用。
4. **context binary 缓存**：HTP 首次图编译很慢，引擎把编译结果缓存到
   `JM_SR_CACHE`(默认 `models/context`)，第二次启动直接加载。
5. **ADSP_LIBRARY_PATH / LD_LIBRARY_PATH**：引擎启动时自动把自身目录（含
   `libQnnHtpV*Skel.so`）加进去，否则 HTP 初始化会失败。

### 4.3 模型准备（必须做一次）

```bash
python android/tools/prepare_models.py --src <waifu2x onnx 目录> --tile 192 --verify
#   可选：--fp16 生成半精度；--quantize --calib-dir <图片目录> 生成 HTP 最快的量化模型
```

产出放到 `android/sr_qnn/models/`（文件名与 `models.txt` 对应，见该目录的 README）。
默认映射：`MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X` 等 → `waifu2x_anime_up2x_denoise3.onnx`；
cunet 在 NPU 上默认复用 anime 模型（分组反卷积对 HTP 不友好）；
Real-CUGAN / Real-ESRGAN 缺失时自动回退到 waifu2x 并在日志里提示。

**没有模型时**：`sr_qnn` 会明确报告“未找到任何 ONNX 模型”，
`config.CanWaifu2x=False`，界面自动禁用超分相关选项（不会崩、不会卡）。

### 4.4 设备侧自检

```bash
adb logcat | grep sr_qnn
# sr_qnn loaded: /data/app/.../lib/arm64/libsr_qnn.so, models:12/39, htp:1, backend:Qualcomm Hexagon NPU (QNN HTP, fp16)
adb shell getprop ro.soc.model          # 确认是高通芯片(8 Gen 1 及以上 HTP 更稳)
```

`htp:0` 说明该机型没有可用 HTP（非高通/驱动缺失），此时自动走 CPU EP，功能仍可用但慢。

---

## 5. 构建（宿主机需 Linux/macOS，Windows 请用 WSL2）

```bash
# 依赖：JDK 17、Android SDK(platform-tools, platforms;android-34, build-tools;35.0.0)、
#       Android NDK 26.1.10909125、Python 3.11/3.12
export ANDROID_HOME=$HOME/Android/Sdk
export ANDROID_NDK_HOME=$HOME/Android/Sdk/ndk/26.1.10909125

# PySide6 / shiboken6 的 android_aarch64 wheel(放到 android/wheels/)
qtpip download PySide6   --android --arch aarch64 && mv PySide6*.whl   android/wheels/
qtpip download shiboken6 --android --arch aarch64 && mv shiboken6*.whl android/wheels/

# 一键构建(会下载 onnxruntime-android-qnn、用 NDK 编 libsr_qnn.so、调用 pyside6-android-deploy)
cd android && ./build_android.sh

# 只改 python 代码时
SKIP_NATIVE=1 ./build_android.sh

adb install -r android/*.apk
```

`build_android.sh` 会打印 `adb push` 模型的命令；如果希望模型直接打进 APK，
在生成的 `buildozer.spec` 里加：

```ini
android.add_assets = sr_qnn/models:models
```

### 5.1 minSdk 34 与屏幕方向怎么落地

`pyside6-android-deploy` 没有暴露 minSdk/屏幕方向/资产目录，所以构建流程是
**打包 → 打补丁 → 再打包**（`build_android.sh` 已自动完成）：

```bash
# 手动执行(默认 API=34, minSdk=34, 屏幕方向=fullUser 跟随系统旋转锁定)
API=34 MINAPI=34 ORIENTATION=portrait ./tools/pin_min_sdk.sh
```

补丁内容：`android.api/minapi=34`、`archs=arm64-v8a`、`local_libs`(NPU 运行库)、
`add_assets`(模型)、Manifest 的 `screenOrientation` 与 `INTERNET` 权限。
需要强制竖屏就设 `ORIENTATION=portrait`；默认 `fullUser` 允许用户旋转，
旋转后界面由 `mobile_ui.OnShown` 重新适配。

验证：

```bash
adb shell dumpsys package <包名> | grep -E "minSdk|targetSdk"
```

### 5.2 依赖打包情况

| 包 | 在 Android 上 | 说明 |
| --- | --- | --- |
| PySide6 / shiboken6 | ✅ 官方 aarch64 wheel | Qt Widgets/Network/Svg 等 |
| pillow, bs4, lxml, natsort, tqdm | ✅ p4a 官方/纯 python recipe | 图像与解析 |
| pycryptodomex, PySocks | ✅ p4a recipe | 加解密、socks 代理（垫片也用它） |
| webdavclient3, pysmb, smbprotocol, jmcomic | ✅ 纯 python | p4a 直接 pip 安装 |
| **curl_cffi** | ⚠️ 需要 `android/recipes/curl_cffi` 编译 curl-impersonate | 编不出来时自动使用 `android/shims/curl_cffi`（功能可用，但**没有 Chrome TLS 指纹**，遇到 Cloudflare 严格校验可能被拦） |
| sr-vulkan / sr-vulkan-model-* | ❌ 不安装 | 由 `sr_qnn` 顶替（`sys.modules["sr_vulkan"]`） |

### 5.3 与桌面端共存的注意点

* `src/start.py` 被拆成 `InitSrEngine() / CheckProbeArgs() / InitQt() / Run()`，
  桌面端入口 `python src/start.py` 仍然照旧（`__main__` 里依次调用）。
* 桌面端超分仍然是 `sr_vulkan`；只有在 Android 上 `sr_backend.InstallQnnCompat()`
  才会把 `sr_qnn` 注册成 `sr_vulkan`。
* `Setting.InitLoadSetting()` 里 Android 的默认下载目录改为应用外部私有目录，
  其他平台分支未变。
* `TaskMulti`（拼图）在 Android 上用线程代替多进程（p4a 下 fork 不稳定），桌面端仍用进程。

---

## 6. 运行时目录与权限

| 用途 | 路径 | 权限 |
| --- | --- | --- |
| 配置/数据/缓存/日志 | `/data/data/<包名>/files/{config,data,cache,state}` | 无需申请 |
| 下载目录 | `/storage/emulated/0/Android/data/<包名>/files/JMComic` | 无需申请(Android 10+) |
| 模型 | `/data/data/<包名>/files/waifu2x-models` | 无需申请 |

需要申请的权限只有网络：`android.permission.INTERNET`（p4a 默认已加）。
因为**不考虑 Android 14 以下**，所以不需要 `READ/WRITE_EXTERNAL_STORAGE`、
不需要 `MANAGE_EXTERNAL_STORAGE`，也不用 `requestLegacyExternalStorage`。

**注意**：应用私有目录之外(即手机存储的 `Download`/`Pictures`/`DCIM` 等)在这个权限
配置下是**读不到**的(`os.scandir` 抛 `PermissionError`)。要导入手机里已有的漫画/图片，
需要在清单里加 `MANAGE_EXTERNAL_STORAGE` 并引导用户到系统设置里授权；在此之前，
应用内文件选择器(见 3.3)会把这些入口置灰并给出"需要「所有文件访问权限」"的提示。

---

## 7. 已知限制

1. `curl_cffi` 垫片没有 TLS 指纹伪装，遇到 Cloudflare 严格模式可能 403 —— 正式分发请编原生 recipe。
2. QNN 后端只支持 HTTP/1.1 时代的同步取图流程不受影响；网络层的 HTTP/2-HTTP/3、ECH 在垫片下不可用（原生 curl_cffi 可用）。
3. cunet 模型在 NPU 上默认复用 anime 模型（质量接近，速度更好）；要精确一致需要自己导出 cunet onnx。
4. 看图界面（`read_view`）沿用桌面端的自绘滚动逻辑，未挂 QScroller；竖屏条漫滚动本来就是它的强项。
5. `Android 14 以下` 未做兼容（用户明确要求）：`minSdk 34`。

---

## 8. 调试与自检

```bash
adb logcat -s python:V Qt:V sr_qnn:V            # 运行日志
adb shell run-as <包名> cat files/crash.log      # 启动阶段崩溃堆栈
adb shell ls /data/data/<包名>/files            # 看目录是否创建成功
adb shell dumpsys package <包名> | grep minSdk  # 确认 minSdk=34
```

超分相关的日志关键字：`sr_qnn loaded` / `模型回退` / `严格 HTP 失败` / `使用 CPU EP`。

不需要手机、不需要 Android SDK 也能跑的两个自检脚本（本地开发用）：

```bash
# 1) C++ ↔ python ctypes 接口一致性(参数个数、声明/定义是否齐全)
python android/tools/check_interfaces.py

# 2) 强制 Android 模式跑一遍竖屏适配(offscreen，不联网)
#    覆盖：抽屉、详情页堆叠、最小尺寸放宽、返回键、无系统托盘、
#          sr_qnn 缺失时降级、模型表与界面列表一致、curl_cffi 垫片
python android/tools/smoke_test_android.py

# 3) 引擎逻辑自测(Linux 宿主构建 libsr_qnn.so 后)：固定 shape 分块拼接是否与
#    参考实现一致、任意倍数/目标尺寸缩放、jpg/png 编码、任务 API、模型回退
JM_SR_QNN_LIB=build-host/libsr_qnn.so python android/tools/host_test_sr_qnn.py

# 4) 应用内文件选择器(见 3.3)：桌面委托/排序/过滤器/上级/三种模式/返回键/
#    权限失败降级/嵌套事件循环不卡死
QT_QPA_PLATFORM=offscreen python android/tools/host_test_file_dialog.py
```

WSL 构建树同步 + 语法检查（`/root` 只有 root 能读，所以 WSL 命令一律 `wsl -u root`）：

```bash
wsl -u root -e bash -lc 'bash <仓库根>/android/tools/wsl_sync_file_dialog.sh'
```

同一套用例再用非 root 用户跑一遍（root 无视权限位，`chmod 000` 那条分支只有普通用户
才真正走到；脚本会把 venv 和基础解释器复制到 /tmp 并放开读权限）：

```bash
wsl -u root -e bash -lc 'bash <仓库根>/android/tools/wsl_run_file_dialog_asuser.sh'
```

---

## 9. WSL2 上构建（实测流程与本环境的坑）

仓库里的 `android/tools/wsl_*.sh` 是我在一台 Windows + WSL2(Ubuntu 26.04) 机器上
实际跑通的脚本，可以直接复用；下面是它们解决的具体问题。

| 步骤 | 脚本 | 解决的问题 |
| --- | --- | --- |
| 基础环境 | `wsl_setup_base.sh` / `wsl_setup_base2.sh` | apt 装 JDK17/gcc/cmake；**WSL 可以直接 `wsl -u root` 提权**，不需要 sudo 密码 |
| Android SDK/NDK | `wsl_setup_android.sh` | cmdline-tools + platform-34 + build-tools 35 + **NDK 26.1.10909125** |
| 镜像配置 | `wsl_config_mirrors.sh` | ① pip 走清华镜像(PyPI 直连只有 ~11KB/s) ② git 全局 `insteadOf` 走 `ghproxy.net`（本机 DNS 把 github.com 污染成 127.0.0.1）③ **把 p4a 里 102 个 recipe 的 GitHub 直链批量改写成镜像**，否则编译 python3/openssl/libffi 时全部下载失败 |
| ONNX Runtime | `wsl_fetch_ort.sh` | `onnxruntime-android-qnn` AAR(含 libonnxruntime.so 与 ORT 头文件) + NuGet 的 linux-x64 库(宿主自测用) |
| QNN 运行库 | `wsl_fetch_qnn.sh` | **关键**：ORT 的 Android QNN AAR 只有 2 个 .so，QNN 运行库在同 POM 依赖的 `com.qualcomm.qti:qnn-runtime:2.37.1` 里（libQnnHtp.so / libQnnSystem.so / libQnnHtpPrepare.so / V68–V79 的 Stub+Skel），从 Maven 取即可，不需要登录 QNN SDK |
| 宿主工具链 | `wsl_install_toolchain.sh` | PySide6-Essentials + shiboken6(local wheel；`pyside6-android-deploy` 就在 Essentials 里) + buildozer/cython |
| **Python 3.11** | `wsl_build_py311_src.sh` | `pyside6-android-deploy` 硬性要求**宿主 Python ≤ 3.11**（buildozer 限制），而 Ubuntu 26.04 只有 3.14；从阿里云镜像下 CPython 源码自行编译安装 |
| 同步 | `wsl_sync.sh` | 把 Windows 仓库同步到 ext4（`/mnt/c` 慢且符号链接行为不一致） |
| 原生库 | `wsl_build_native.sh` | NDK 编译 arm64 `libsr_qnn.so` + 宿主 x86_64 构建 + 跑 `host_test_sr_qnn.py` |
| 打包 | `wsl_build_apk.sh` | 两阶段生成并补丁 buildozer.spec（含**应用图标**），再正式打包 |
| 等构建 | `wsl_wait_build.sh` | **等 `detached_build.log` 出现"结束"** 再收集产物（见下面那条坑） |
| 校验 | `wsl_check_sync.sh` | 仓库 vs 构建树 + **直接读 APK 里 `assets/private.tar` 的 `.pyc`**，确认打进去的真是当前代码 |
| 校验图标 | `probe_apk_icon.py` | 解出 APK 里 `res/mipmap/icon.png` 与源图**逐像素比对**，并报告是否残留 PySide 自带图标 |

> 看真机日志：`adb shell run-as org.jmcomic.jmcomic cat files/state/jmcomic-qt/logs/<日期>.log`
> —— 竖屏适配、网格重排、返回键的证据都在应用自己的这份滚动日志里（`Log.*` 同时也会打到 logcat）。

> 踩过的坑：`wsl_collect_apk.sh` 如果在构建还没结束时运行，拷回来的是**上一版 APK**
> （现象：代码明明改了，真机日志里的行号和字符串却还是旧的）。所以先
> `wsl_wait_build.sh`，再 `wsl_collect_apk.sh`，最后用 `wsl_check_sync.sh` 验 APK 内的 `.pyc`。


### 9.1 为什么要两阶段补丁 buildozer.spec

`pyside6-android-deploy` 的 `buildozer.py` 把 `requirements` 写死为
`python3,shiboken6,PySide6`，且不暴露 minSdk / 自有 .so / 资源目录。它的
`Buildozer.initialize()` 在发现项目目录已有 `buildozer.spec` 时会**直接沿用**，
所以流程是：

```
pyside6-android-deploy --dry-run   # 生成 buildozer.spec + Qt recipe 目录 + jars
python tools/patch_buildozer_spec.py android/buildozer.spec ...   # 注入下面这些
pyside6-android-deploy             # 用补丁后的 spec 正式打包
```

注入内容：应用依赖清单、`android.api/minapi=34`、`android.add_libs_arm64_v8a`
（`libsr_qnn.so` + `libonnxruntime.so` + QNN 运行库进 APK 的 `lib/arm64-v8a/`）、
超分模型 `add_assets`、网络权限、`p4a.source_dir`（用本地已改镜像的 p4a）。

### 9.2 Android 上的依赖取舍（实测）

| 依赖 | 处理 |
| --- | --- |
| lxml / pillow / pycryptodome | p4a 有 recipe，正常编译（`tools/tool.py` 顶层 import lxml，缺了应用起不来） |
| bs4 / natsort / tqdm / pysmb / requests / webdavclient3 / pysocks 等 | 纯 python，p4a 用 pip 装（走清华镜像） |
| **jmcomic** | 自定义 recipe `android/recipes/jmcomic`，用 `--no-deps` 安装：它的依赖 `curl-cffi` 在 Android 上编不出来，装本体即可 |
| **curl_cffi** | 不进 requirements；由 `android/shims/curl_cffi` 垫片顶替（随 APK 作为 assets 打包，`main.py` 检测不到真库时加入 sys.path）。代价：没有 Chrome TLS 指纹 |
| smbprotocol / cryptography | 暂不打包（需要 Rust 交叉编译）；SMBv3 上传功能在 Android 上不可用 |

### 9.3 引擎自测结论（x86_64 宿主实测）

`host_test_sr_qnn.py` 用一个固定 `1×3×192×192 → 1×3×384×384` 的双线性 Resize 模型
当被测模型，逐项验证并全部通过：

* 模型表 41 个常量与界面下拉列表、`models.txt` 完全一致
* 300×200 图片 2x 超分（跨 2 个分块，192 的块 + 边缘补齐）输出 600×400，
  与 numpy 参考实现 **max diff = 0.5/255、mean = 0.20**，分块边界无额外突变 → 分块拼接正确
* `scale=1.5` → 450×300、目标尺寸模式 `600×400` 均正确
* 请求缺失模型时自动回退到可用模型
* `removeWaitProc` 丢弃排队任务、`remove` 取消运行中任务、非法图片/非法模型号被拒绝
* 这个测试实际抓出了一个真 bug：输入张量曾按 HWC 填充（ONNX 要 NCHW），修复后才与参考实现吻合


### 9.4 应用图标（启动器图标）

`pyside6-android-deploy --init` 生成 buildozer.spec 时，把 `icon.filename` 写死为
**PySide6 自带的** `PySide6/scripts/deploy_lib/pyside_icon.jpg`（256×256 JPEG），
所以默认装到手机上启动器显示的是 PySide 的 logo。修法是让补丁脚本把它换掉：

```bash
# wsl_build_apk.sh 里（补丁 buildozer.spec 之前）
ICON="$WORK/icon/app_icon.png"                          # 刻意放在 source.dir 之外
cp -f "$SRC/res/icon/logo_round.png" "$ICON"            # 与主窗口/托盘图标同一张图
python android/tools/patch_buildozer_spec.py ... --icon "$ICON"   # -> icon.filename
```

几点实测结论：

* p4a(`bootstraps/common/build/build.py`) 是**原样** `shutil.copy(icon, res/mipmap/icon.png)`，
  **不缩放、不校验尺寸**；清单模板里是 `android:icon="@mipmap/icon"`，所以给 512×512
  带 alpha 的 PNG 就行（`res/icon/logo_round.png` 正好是 512×512 RGBA，圆角外透明）。
* **用不了自适应图标**：p4a 的 `--icon-fg/--icon-bg` 要往 `res/mipmap-anydpi-v26/` 写 XML，
  但 `bootstrap=qt` 的 res 模板里**没有这个目录**，传了会直接 `FileNotFoundError`。
  `bootstrap=_sdl_common` 才有（可以对照 `p4a/pythonforandroid/bootstraps/_sdl_common/build/src/main/res/mipmap-anydpi-v26`）。
* 图标拷到 `$WORK/icon/` 而不是 `android/` 下：spec 里 `source.dir = .`（即 `src/android`），
  放进去会被 p4a 再打一份（457KB）进 `assets/private.tar`。
* 核对方式（不能比文件字节，aapt2 可能对 `res/` 下的 PNG 无损重编码）：

  ```bash
  python android/tools/probe_apk_icon.py android/JMComic-0.1-arm64-v8a-debug.apk res/icon/logo_round.png
  #   res/mipmap/icon.png: PNG 512x512 456970 字节
  #       与期望图: 尺寸相同=True 不同像素=0/262144 最大通道差=0
  #       结论: 是我们换上的图标(逐像素一致)
  aapt dump badging ...apk | grep icon
  #   application: label='JMComic' icon='res/mipmap/icon.png'
  ```

  换图标前同一个脚本给出的对照是 `res/mipmap/icon.png: JPEG 256x256 8157 字节`（PySide 默认图）。

### 9.5 android/tools 的约定：路径不写死、脚本分两档

所有脚本都不含本机绝对路径。公共路径集中在两个文件里，按需覆盖环境变量即可：

| 文件 | 给谁用 | 用法 |
| --- | --- | --- |
| `android/tools/env.sh` | bash 脚本 | 在 shebang 之后 `. "$(dirname "${BASH_SOURCE[0]}")/env.sh"` |
| `android/tools/env.ps1` | PowerShell 脚本 | 在 `param()` 之后 `. "$PSScriptRoot\env.ps1"` |

解析出来的变量（两边同名，可直接互换）：

| 变量 | 含义 | 默认值 |
| --- | --- | --- |
| `JM_REPO` / `$JmRepo` | 仓库根（脚本自己往上两级推出） | 自动定位 |
| `JM_WORK` | WSL 构建树 | `/root/jmcomic-build` |
| `JM_SDK` / `JM_NDK` | Android SDK / NDK | `$JM_WORK/android-sdk`、`.../ndk/26.1.10909125` |
| `JM_VENV` / `JM_VPY` | buildozer 宿主 venv / python | `$JM_WORK/venv311` |
| `JM_ADB` / `$JmAdb` | adb 可执行文件 | 先查 `PATH`，再查 `$ANDROID_HOME`、`~/Android/Sdk` |
| `JM_SERIAL` / `$JmSerial` | 目标设备串号 | `adb devices` 里第一个已授权设备 |
| `JM_USER` | WSL 非 root 用户（跑"降权回归"用） | `id -un 1000` |

所以"换一台机器"只需要：

```bash
export JM_WORK=/path/to/build-tree JM_SDK=/path/to/android-sdk JM_SERIAL=<序列号>
```

目录按"是否属于文档化的构建/验证流程"分成两档（判据见 `android/tools/README.md`）：

* `android/tools/` —— **入口脚本**：构建、同步、打包、校验、宿主回归、真机自检。
  不在文档里的脚本不会被保留在这一层。
* `android/tools/archive/` —— **移植过程的一次性排查脚本**，按历史原貌保留、只做了字符串脱敏
  （机器名/串号/绝对路径换成占位符），多数只跑过一次，**不保证可直接运行**。

`android/build_logs/` 是真机证据目录（抓回的日志/截图/配置），**已 gitignore、不入库**；
其中还含真机配置（账号、代理 IP）与下载样本，不要提交。



