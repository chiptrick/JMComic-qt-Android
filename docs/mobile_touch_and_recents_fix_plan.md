# 真机问题定位与修复方案（表格触控 / 搜索记录 / 后台任务）

> 面向 0.52 版本真机反馈的 4 个问题。全部结论都落到具体文件与行号，修复方案按"最小改动 + 同源逻辑一次收口"给出。
> 涉及的核心模块：`src/tools/mobile_ui_touch.py`（触控路由）、`src/tools/mobile_ui_base.py`（判定阈值/窗口类型）、
> `src/component/tab/base_table_widget.py`、`src/component/line_edit/*`、`android/java/org/jmcomic/SafService.java`、
> `android/tools/patch_android_manifest.py`。

## 落地状态（2026-10-26，0.53 构建）

四处问题**已全部按本文档实现**，并新增两个宿主回归。改动清单与验证结果见文末
「附录 B：落地清单」；真机验证项见「附录 C」。

---

## 问题 1　超分模型选择表 / 下载列表：滑动不跟手（轻微一滑就跳多行）

### 1.1 根因（主因）：QScroller 的计量单位是"滚动条值"，而表格默认是按"项"计的

`QScroller` 的滑动是这么闭环的（Qt 源码路径，与业务代码无关）：

```
手势位移(px) --QScrollEvent.contentPos--> QAbstractScrollArea::viewportEvent
                                           hbar->setValue(contentPos.x())
                                           vbar->setValue(contentPos.y())
```

也就是说 **一个手指像素 = 一个滚动条单位**。而 `QAbstractItemView` 的两个滚动模式默认都是
`ScrollPerItem`：

* `ScrollPerItem`　→ 滚动条值 = 行号/列号，`range = rowCount-1`，一个单位 = 一整行
* `ScrollPerPixel` → 滚动条值 = 像素，一个单位 = 1px

在 `ScrollPerItem` 下，`QAbstractScrollArea` 回报给 `QScrollPrepareEvent` 的
`contentPosRange` 只有"行数"这么大，`contentPos` 也是行号。于是手指滑 8px = 表格跳 8 行；
而且 `contentSize(行数) < viewportSize(像素)` 会让 QScroller 的越界/惯性计算彻底失真
（一甩就到尽头）。**这正是"轻微滑动即切换多行、且不可能 1:1 跟手"的机理。**

代码侧的直接证据：

| 位置 | 现状 | 问题 |
|---|---|---|
| `src/tools/mobile_ui_touch.py:1475-1487` `MakeScrollable()` | 只写了 `area.setVerticalScrollMode(ScrollPerPixel)` | **`setHorizontalScrollMode` 全仓库从未被设置过**（唯一的 `ui_book_info.py:423` 是书页列表，不是表格） |
| `src/component/tab/base_table_widget.py:15` | 只设垂直逐像素 | 水平仍是按列跳 |
| `src/interface/ui_sr_select_widget.py:41` | 裸 `QTableWidget`，连垂直都没设 | 全靠 `MakeScrollable` 兜底补垂直，水平必然按列跳 |
| `src/interface/ui_download.py:32` | 裸 `QTableWidget`（11 列），两个方向都没设 | 同上，问题最重 |

**为什么问题恰好在"左右滑动"上暴露**：这两个表的横向内容都超出竖屏，横向滚动才是主用方向——

* 超分模型选择表：`setting_sr_select_view.py:29-32` 固定列宽 `200+150+100+100 = 550px`，
  而真机逻辑宽只有 **480px**（`android/build_logs/waifu2x_page2.png` 实测），必然横向滚动；
* 下载列表：`download_view.py:42-83` 11 列，只有第 1 列 200px、第 2 列 300px 被显式设宽，
  其余列取默认 100px ⇒ 总宽 ≈ **1100px+**（还叠加竖表头约 30px），必须横向滚动才能看到右侧列。
  于是"轻轻一划就冲到最后一列、中间列永远停不住" = 既"不跟手"，又"信息看不全"。

### 1.2 次因：下载列表"信息显示不完整"还有排版自身的锅

1. 列宽按桌面尺寸写死/缺省（上表），竖屏下"标题｜状态｜进度"三列无法同屏；
2. `download_view.py:77-79` 先 `setSectionResizeMode(Stretch)` 再立刻改成 `Interactive`，
   Stretch 等于没生效，列宽全部退回默认值（这是典型的"以为自适应了其实没有"）；
3. 单元格无省略号策略声明、无 `setWordWrap(False)`，长标题会把行撑高/被硬裁；
4. `BaseTableWidget` 没有任何宽度约束（`setMinimumWidth`），父布局压缩时表格先溢出而不是压缩列。

### 1.3 修复方案

**P0（真正解决"不跟手"，一行级改动，覆盖所有表格）**

```python
# src/tools/mobile_ui_touch.py  MakeScrollable()
if isinstance(area, QAbstractItemView):
    # 逐像素滚动是 QScroller 能 1:1 跟手的前提：ScrollPerItem 下
    # 一个手指像素 = 一整行/一整列（见文件头说明）。垂直、水平都要设。
    area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    area.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
```

```python
# src/component/tab/base_table_widget.py  __init__
self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)   # 新增
```

**P0 配套：把"裸表格"统一收口**
新增 `mobile_ui.MakeItemViewsPixelScroll(root)`：遍历 `root`（含自己）下所有
`QAbstractItemView`，补齐两个方向的 `ScrollPerPixel`，并在
`mobile_ui_hooks.Apply / OnShown`、`mobile_ui_touch._ScrollWatcher.Flush` 三处调用，
保证**后建**的表（模型选择弹窗、批量超分页、DoH 页、NAS 页）也一次覆盖，避免"改了 A 漏了 B"。

**P1：移动端表格排版（解决"信息显示不完整"）**

新增 `mobile_ui_layout.FitTablesForPortrait(available)`（Apply/OnShown 里调用）：

1. 关键列 `ResizeToContents` 且 `setMaximumSectionSize` 上限（如 160px）；
   主信息列（下载列表的"名称"、模型表的"模型名"）设 `Stretch`，吃掉剩余宽度；
2. 竖屏下**隐藏低优先级列**（下载列表：时间 / 速度 / 转换耗时；超分表：耗时），
   通过长按行菜单或"详情"查看，保证"标题+状态+进度"同屏；
3. `table.setTextElideMode(Qt.ElideRight)`、`setWordWrap(False)`、`setHorizontalScrollBarPolicy(AsNeeded)`；
4. 表格 `setMinimumWidth(0)` + `horizontalHeader().setMinimumSectionSize(48)`，让它能在窄屏压缩。

**P2：手感微调（需实测确认，非根因）**
`_TuneScroller()` 里补三条：`DragStartDistance`（默认 0.005m，高 DPI 下可能等价几十像素，
会出现"手指动了表格没动"）、`MaximumVelocity`、`DecelerationFactor`。
注意它与 `TouchSlopPx = 16`（`mobile_ui_base.py:19`）的点击/滑动判定要协调：
`DragStartDistance` 应 ≤ `TouchSlopPx`，否则 16~40px 的小幅滑动既不算点按也不滚动，手感发死。

### 1.4 改动文件

| 文件 | 改动 |
|---|---|
| `src/tools/mobile_ui_touch.py` | `MakeScrollable()` 补 `setHorizontalScrollMode`；新增 `MakeItemViewsPixelScroll()`；`_TuneScroller()` 手感参数 |
| `src/component/tab/base_table_widget.py` | 补水平逐像素 |
| `src/tools/mobile_ui_hooks.py` | Apply/OnShown 调 `MakeItemViewsPixelScroll` + `FitTablesForPortrait` |
| `src/tools/mobile_ui_touch.py`（`_ScrollWatcher.Flush`） | 新表建出来时补逐像素 + 排版 |
| `src/tools/mobile_ui_layout.py` | 新增 `FitTablesForPortrait()` |
| `src/view/download/download_view.py` | 列宽改自适应 + 竖屏隐藏列；去掉无效的 Stretch 调用 |
| `src/view/setting/setting_sr_select_view.py` | 列宽改"名称 Stretch + 其余按内容"，并夹到屏宽内 |

---

## 问题 2　表格单击漂移，命中不到目标位置

### 2.1 根因 A（决定性）：`indexAt()` 用错了坐标系

`src/tools/mobile_ui_touch.py:420-424`：

```python
local = view.mapFromGlobal(QPoint(...))     # ← 表格自身坐标系（含表头/边框）
index = view.indexAt(local)                 # ← 但 QAbstractItemView::indexAt 要的是
                                            #    **viewport 坐标系**
```

Qt 文档明确：`QAbstractItemView::indexAt(point)` 的点是"视图视口坐标"
（内部就是 `rowAt(point) / columnAt(point)`，直接吃视口坐标）。

于是命中点被平移了 **水平表头高度（默认 25px）+ 边框 + 竖直表头宽度（约 30px）**：

* 超分模型表行高 `23px`（`ui_sr_select_widget.py:64`），表头 25px ⇒ **点第 2 行命中第 1 行**；
* 竖直表头把 x 平移了约 30px ⇒ 列也整体错位 1 列。

这是"漂移"的确定性来源（每次偏移量相同），不是抖动、不是精度问题。

### 2.2 根因 B（放大误差）：点按用的是"松手点"而不是"按下点"

`_finalize()`（`mobile_ui_touch.py:1030-1082`）里 `_Activate(widget, pos)` /
`_ActivateSpin(widget, pos)` 传的是**松手位置**。而判定阈值 `TouchSlopPx = 16`，
意味着松手点允许离按下点最多 16px。对 23px 行高的表格来说，这已经是**大半行**：

* 按下在第 3 行、松手在第 4 行 ⇒ 命中第 4 行；
* 用户的直觉是"我点的是第 3 行"。

Qt 原生鼠标是 `press` 时定 `pressedIndex`、`release` 只做确认，所以正确做法是用按下点。

### 2.3 修复方案

```python
# mobile_ui_touch.py  _ActivateItemView()
def _ActivateItemView(view, globalPos):
    # indexAt 吃的是 **视口** 坐标，表格自身坐标会多算 "水平表头 + 边框 + 竖直表头"
    viewport = view.viewport() if view.viewport() is not None else view
    local = viewport.mapFromGlobal(QPoint(int(globalPos.x()), int(globalPos.y())))
    index = view.indexAt(local)
    ...
```

```python
# mobile_ui_touch.py  _finalize()
press = seq["press"]          # 点按的命中一律用按下点（与 Qt 原生鼠标一致）
...  desc = _ActivateSpin(widget, press)
...  desc = _Activate(widget, press)
```

（`input` 通道已经用的是 `seq["press"]`，`_FocusInput` 也一样 —— 这块原本就是对的，
说明"按下点命中"在项目里已有正确范例，只是 view/spin 两条通道漏了。）

### 2.4 同类逻辑排查结论

全仓库 `indexAt()` 共 5 处，**只有 1 处坐标空间错误**：

| 位置 | 来源坐标 | 结论 |
|---|---|---|
| `tools/mobile_ui_touch.py:424` | `view.mapFromGlobal` → 表格坐标 | ❌ **错**（本次修复） |
| `view/download/download_view.py:273` | `customContextMenuRequested(pos)` | ✅ 该信号由 viewport 发出，pos 就是视口坐标 |
| `view/tool/local_read_all_view.py:119` | 同上 | ✅ |
| `view/nas/nas_view.py:281` | 同上 | ✅ |
| `component/list/comic_list_widget.py:118` | 同上 | ✅ |

`_Activate()` 里另外两处命中用的是 `mapFromGlobal` + 控件自身 API，坐标系正确：
`QTabBar.tabAt(local)`（控件坐标）、`_SpinBoxStepAt()` 用 `style.subControlRect`（控件坐标），无需改。

---

## 问题 3　搜索记录：内容超出显示范围 + 点不动

### 3.1 根因 A：搜索记录弹层是一个**独立顶层窗口**（Qt.ToolTip）

`src/component/line_edit/search_line_edit.py:30-42`：

```python
self.widget = QWidget()
self.help.setupUi(self.widget)            # 里面是 "搜索记录" 标签 + QListView
self.widget.setParent(self, Qt.Popup)     # 先当 Popup
self.widget.setWindowFlags(Qt.ToolTip)    # 再改成 ToolTip（顶层窗口）
```

后果（本项目已经踩过的同一类坑，见 `mobile_ui_window.MakeChildOverlay` 的注释）：

1. **Android 上 ToolTip 窗口不激活、不接收触摸**：点它，触摸事件落在下面的主窗口上，
   列表 `clicked` 永远不会触发 ⇒ "搜索记录点不动"；
2. 即便触摸到了，`focusOutEvent`（`:165-168`）会**无条件 `hide()`** 弹层 —— 手指刚落下弹层就没了；
3. 它是**第二个顶层窗口**，正是 `MakeChildOverlay` 注释里记录的
   `eglSurface() deadlock protector` 崩溃路径（本文件侥幸没崩，但风险同源）。

顺带一个**判定漏洞**：`mobile_ui_base._InPopup()`（`:201-215`）只认
`WindowType_Mask == Qt.Popup`，**ToolTip 不算弹窗**，所以这条路径既没被"弹窗豁免"保护，
也不在 `_InTouchArea`（`:133-140`，祖先里没有 `_jmTouchScroll`）之内 ⇒
触控路由两头都不管，只能指望 Qt 合成鼠标，而合成鼠标又到不了这个窗口。

### 3.2 根因 B：几何硬编码 + 没做屏幕夹紧

`search_line_edit.py:181-185`：

```python
self.widget.resize(max(500, self.width()), QtOwner().owner.height() // 2)
```

* 宽度下限写死 **500px**，真机逻辑宽 480（小屏 360~412dp）⇒ **必然右侧溢出屏幕**，
  "内容超出显示范围"就是这一句；
* 高度恒为**窗口一半**，与条目数量无关（一条记录也占半屏，看着像"内容区超出"）；
* 没有 `x/y` 夹紧，`x` 直接取输入框全局左边，宽 500 就冲出右边界。

### 3.3 根因 C：多挂了一次布局，留下一个游离的 `QLabel("asdasdasdasd")`

`search_line_edit.py:40-42`：

```python
self.qLabel = QLabel("asdasdasdasd")
self.hLayout = QHBoxLayout(self.widget)   # widget 里已经有 setupUi 建的 verticalLayout_2
self.hLayout.addWidget(self.qLabel)
```

`setLayout` 被第二次调用时 Qt 只会打印 "already has a layout" 并失败，但 `addWidget`
仍会把 `qLabel` 挂到 widget 上（默认几何 (0,0)）⇒ 弹层左上角可能叠出一段
`asdasdasdasd` 文字，进一步挤占/遮挡内容。这是历史调试残留，必须删掉。

### 3.4 修复方案

把弹层从"独立 ToolTip 顶层窗口"改成**主窗口内的子控件图层**（与 `BaseMaskDialog`
在 Android 上的做法一致）：

```python
class SearchLineEdit(QLineEdit):
    def __init__(...):
        ...
        self.widget.setWindowFlags(Qt.Widget)      # 不再是顶层窗口
        # 删除 qLabel / 第二次 QHBoxLayout
        self.listView.clicked.connect(self.SetText)
        self.listView.setUniformItemSizes(False)
        self.listView.setTextElideMode(Qt.ElideRight)

    def ShowListView(self):
        host = self.window()                        # 主窗口；子控件图层随它缩放
        self.widget.setParent(host)
        # 位置：输入框正下方（用 mapTo 换算，不再 mapToGlobal 绕一圈）
        topLeft = self.mapTo(host, QPoint(0, self.height()))
        # 宽度：与输入框同宽，且夹在窗口内
        width = max(240, min(self.width(), host.width() - topLeft.x() - 4))
        # 高度：按内容自适应，最多占窗口下半屏
        rows = min(self.listView.model().rowCount(), 8)
        contentH = rows * 44 + 40
        height = max(120, min(contentH, host.height() - topLeft.y() - 8))
        self.widget.setGeometry(topLeft.x(), topLeft.y(), width, height)
        self.widget.raise_()
        self.widget.show()
        mobile_ui.MakeScrollable(self.listView)     # 逐像素 + QScroller（问题 1 同源）
```

要点：

* 子控件图层 → 触控路由能"看见"它：`_Classify` 判成 `view`，`_InTouchArea` 因为
  `listView` 自己带 `_jmTouchScroll` 而成立，抬手走 `_ActivateItemView`（问题 2 修好后
  坐标正确）⇒ `clicked` → `SetText` → `setText` + `Search()` 正常生效；
* 不再依赖 `focusOutEvent` 隐藏（图层不抢焦点），改为"点主窗口其它地方 / 切页 / 滚动时隐藏"
  （由 `main_view.mousePressEvent` 已有的 `CheckClick()` 入口 + `HideListView()` 触发即可）；
* 桌面端行为保持不变（仍然是同一个 `widget`，只是不再作为顶层弹窗）。

### 3.5 同类逻辑排查结论

| 位置 | 现状 | 结论 |
|---|---|---|
| `component/line_edit/search_line_edit.py:30-42,176-186` | ToolTip 顶层窗 + 500px 下限 + 游离 QLabel | ❌ 本次修复（问题 3 本体） |
| `component/line_edit/tip_line_edit.py:21-31,115-125` | **完全相同**的三处问题（登录页 DoH 地址 / 代理地址输入框的候选列表） | ❌ 同样需要修，建议抽成一个公共 `PopupListOverlay` 基类，两处共用 |
| `component/label/msg_label.py:28-29` | `Qt.Window|Qt.Tool` 顶层提示条 | ⚠️ 只读提示，不接收触摸；已有 `DeferCall` 延后 show 保护，暂不动（若要彻底消掉第二顶层窗口，也应改子控件图层） |
| `component/dialog/base_mask_dialog.py:24-29` | 已用 `MakeChildOverlay` 改子控件 | ✅ 正确范例，直接复用其思路 |
| `mobile_ui_base._InPopup()` | 只认 `Qt.Popup`，`ToolTip` 不算 | ⚠️ 修好弹层后不再依赖它；但建议补上 `ToolTip`，避免以后再踩 |

---

## 问题 4　按 HOME 后多任务里没有这个应用（但后台仍在跑）

### 4.1 根因：SAF 选择器的 Intent 把 `EXCLUDE_FROM_RECENTS` 打到了**主任务**上

`android/java/org/jmcomic/SafService.java:185-203`：

```java
Intent intent = new Intent(SafService.this, SafPickActivity.class);
intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
        | Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS   // ← 问题在这
        | Intent.FLAG_ACTIVITY_NO_ANIMATION);
startActivity(intent);
```

而 `SafPickActivity` 在清单里**没有声明自己的 taskAffinity**（`patch_android_manifest.py:57-62`
只给了 `process=":saf"`、`theme`、`excludeFromRecents`、`configChanges`；它的 Java 注释
`SafPickActivity.java:23` 写着"taskAffinity=\"\""，但清单里实际并没有），
于是它继承应用默认 affinity（包名）= **和主 QtActivity 同一个任务**。

`FLAG_ACTIVITY_NEW_TASK` + 同 affinity 的结果是"**复用已有任务**"，而
`FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS` 会作用到落进去的这个任务上 ⇒
**整个应用任务被标记为 excludeFromRecents，从此不出现在多任务列表**，
但进程、Service（`stopWithTask="false"`）、Python 线程都还在跑 —— 与现象完全吻合。

触发条件极低：首次启动 `SavePath` 为空会弹下载目录选择（`main_view.py:393-396`），
走的就是 SAF tree picker ⇒ **绝大多数用户第一次用完就已经中招**。

### 4.2 修复方案

1. **清单**：给 `SafPickActivity` 补上独立 taskAffinity（与它自己的注释一致），
   让 `NEW_TASK` 真的开一个新任务，`excludeFromRecents` 只影响这个一次性任务：

```xml
<!-- android/tools/patch_android_manifest.py  ComponentsXml -->
<activity android:name="org.jmcomic.SafPickActivity"
          android:exported="false"
          android:process=":saf"
          android:taskAffinity=""                        <!-- 新增：独立任务 -->
          android:theme="@android:style/Theme.Translucent.NoTitleBar"
          android:excludeFromRecents="true"
          android:configChanges="orientation|screenSize|keyboardHidden|uiMode" />
```

> 该文件已有 `BlockRe` "整段替换"逻辑，改 `ComponentsXml` 后下次 `wsl_build_apk.sh`
> 会把模板里的旧块整体换掉（注释里记录过"只改属性不改块会残留旧写法"的坑），无需手工改模板。

2. **Intent**：去掉 `FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS`（双保险；即使 affinity 配错，
   也不会再把主任务踢出多任务）。

3. **验证**（改前/改后各跑一次，3 分钟）：

```bash
adb shell dumpsys activity recents | grep -i -A3 jmcomic   # 看有没有 Record
adb shell dumpsys activity activities | grep -iE "excludeFromRecents|taskAffinity|jmcomic"
# 复现路径：启动 → 首次选下载目录(SAF) → 按 HOME → 看多任务里应用卡片是否还在
```

### 4.3 同类逻辑排查结论

| 位置 | 现状 | 结论 |
|---|---|---|
| `SafService.java:194-203` `StartPicker()` | `NEW_TASK + EXCLUDE_FROM_RECENTS` | ❌ 本次修复（根因） |
| `SafService.java:246-249` `Open()` | `NEW_TASK` + URI 授权（打开文件管理器） | ✅ 无 recents 相关 flag，不动 |
| `patch_android_manifest.py:53-63` | 缺 `taskAffinity=""` | ❌ 本次补齐 |
| `SafPickActivity.java:23` 注释 | 声称有 `taskAffinity=""`，实际没有 | ⚠️ 注释与实现不一致（本 bug 的成因之一），修完对齐 |
| 应用内其它 `startActivity` | 全仓库仅 SafService 一处（`grep startActivity` 已确认） | ✅ 无遗漏 |

### 4.4 次因（同一现象的另一条路径，需一并知晓）

若用户是**连按两次返回键**退出过（`mobile_ui_window.QuitAppAndCleanup` → `app.quit()`），
Python 主线程结束后 Activity 可能已不再属于任何任务，而 `:saf` 进程 / 后台线程仍存活
⇒ 同样是"后台还在跑、多任务里没有"。这条与 HOME 无关，但排查同类反馈时要区分开
（判据：`adb shell dumpsys activity activities | grep -i "Hist #"` 里有没有主 Activity）。

---

## 问题 4 复诊（0.53 → 0.54）：一次被证伪的假设

### 4.5 复诊（0.53 → 0.54，**已被 4.8 的真机实测证伪**）：曾误判为 SurfaceView

1. **任务本身是干净的**（用 aapt2 反查 0.53 的 AndroidManifest 确认）：
   主 Activity `org.kivy.android.PythonActivity` 既没有 `excludeFromRecents`，
   affinity 就是默认的 `A=<uid>:org.jmcomic.jmcomic`（历史 logcat 里的 TaskInfo 也印证），
   `launchMode=singleTask`，没有任何"不进多任务"的声明。
2. **Qt 侧也不动任务**：把 PySide6 6.12 的整套 Android jar 解包、
   对全部 class 反查 `finishAndRemoveTask` / `setExcludeFromRecents` /
   `EXCLUDE_FROM_RECENTS` / `moveTaskToBack` / `setTaskDescription` —— **零命中**；
   `QtActivityBase.onStop()` 里只有 `super.onStop()` + `QtNative.setApplicationState(4)`。
   而 p4a 的 `PythonActivity.onDestroy()` 会 `killProcess`，进程还活着就说明 Activity 没被销毁。
3. ⇒ 任务在、Activity 在、进程在，**缺的只是"画面"**：系统抓任务快照时拿不到像素。

**根因**：Qt 默认用 **SurfaceView** 承载整个 Qt 窗口
（`qandroidplatformwindow.cpp`：单窗口时选 `SurfaceContainer::SurfaceView`）。
SurfaceView 的内容画在一块**独立的 Surface** 上，**不属于 View 树**，
而 Android 的任务快照 / 截屏 / 多任务预览是按 **View 层级**合成抓取的 ——
抓不到这块独立 Surface，于是整张卡片是全黑（表现为"没有本应用的后台视图"）。
仓库里上一次排查留下的 `android/build_logs/repro_home.png` 是一张全黑图，正是同一现象。

旁证：视频/相机类应用"最近任务缩略图一块黑"是同一机制；
Qt 6.10+ 为此提供了 `QT_ANDROID_SURFACE_CONTAINER_TYPE` 覆盖容器类型
（`qEnvironmentVariableIntValue`，**0=SurfaceView、1=TextureView**），
TextureView 通过 SurfaceTexture 把画面合成进 View 树，快照/截屏都拿得到。

### 4.6 修复

1. **`android/main.py`**：新增 `ApplySurfaceContainer()`，在 `QApplication` **之前**
   把 `QT_ANDROID_SURFACE_CONTAINER_TYPE` 默认设为 `1`（TextureView）；该变量在窗口
   初始化时只读一次，晚设无效。`<AppDataDir>/sr_env.txt` 里写同名键可覆盖
   （想退回 SurfaceView 就写 `QT_ANDROID_SURFACE_CONTAINER_TYPE=0`）。
   `DumpDiagnostics` 会把实际取值打进启动日志。
2. **`src/tools/mobile_ui_hooks.InstallAppStateHook()`**（`Apply` 里安装）：
   - `ApplicationInactive`（≈onPause，画面还在）→ `repaint()` 把当前这一帧推出去，
     保证系统抓快照时拿到的是"当前这一屏"；
   - `ApplicationActive` → `OnShown()` 重排 + 强制重绘（顺带修"从多任务切回来黑屏"）；
   - 每次状态变化打 `appState: ...` 一行日志，真机上一眼分清"进了后台"还是"被销毁重来"。

### 4.7 取证工具（下次真机一条命令定性）

```bash
bash android/tools/check_recents.sh          # 按 HOME 切后台之后再跑
```
输出分 5 段：Activity 栈里有没有 `Task{...#N A=...:org.jmcomic.jmcomic}`、
`dumpsys activity recents` 里有没有记录与 `thumbnailStatus/hasValidSnapshot`、
有没有 `excludeFromRecents`、进程是否还活着、
以及 `qt.qpa.window ... using surface container type` 与 `appState:` 日志。
判读口径写在脚本末尾：
- 有任务 + 快照空 → 渲染容器问题（0.54 起默认 TextureView）
- 连任务都没有 → 任务被移除/被排除（查 ROM 后台策略）
- 进程没了 → 被杀（查 logcat FATAL）

---

## 问题 4 三诊（0.55/0.56，真机 adb 实测）：根因是"首帧之前被抓快照"

> 4.1-4.3（任务被 `EXCLUDE_FROM_RECENTS` 排除）、4.5（SurfaceView 不被快照）两条结论
> **都已被真机实测证伪/推翻**：0.53、0.54 上问题依旧。下面是这轮用 adb + 截图定位到的真机制。

### 4.8 真机取证（vivo V2463A / Android 16 / OriginOS 16）

| 检查 | 结果 | 结论 |
|---|---|---|
| `dumpsys activity recents` | `Recent #N: Task{#60286 A=10380:org.jmcomic.jmcomic}`，`isForceExcludedFromRecents=false`、`autoRemoveRecents=false`、`mHasBeenVisible=true` | 任务在多任务列表里，**没被排除** |
| `dumpsys activity activities` | `Task{...#60286 ... sz=1}`，其它应用（微信/设置/健康）并列 | 任务正常存活 |
| `dumpsys window windows` | `mHasSurface=true`、`fl=` 里**没有** `FLAG_SECURE`、`mViewVisibility` 与其它应用一致（后台都是 `0x8`） | 窗口没问题，"后台 GONE"是所有应用共有的，不是差异点 |
| `dumpsys activity top` 控件树 | `QtTextureView{... 0,0-1440,2953}` | 0.54 的容器切换**生效了**，问题不在 SurfaceView |
| `dumpsys SurfaceFlinger --list` | 只有 `Window:...PythonActivity` 与 `ActivityRecord...`，**无 `SurfaceView[...]` 图层** | 同上 |
| 多任务截图（正常使用后按 HOME） | 卡片里是**完整应用画面** | 平时是好的 |
| 多任务截图（**启动后 ~2s 内按 HOME**） | 卡片是**纯白空卡**；再等 15s 依旧空白 | ★ 复现：抓到了"Qt 还没画第一帧"的窗口 |

### 4.9 真机制

Android 在应用**离开前台那一刻**抓任务快照，抓的是窗口里的最后一帧；
`TaskSnapshotController` 抓完就缓存，**这一帧是空白就一直是空白**，除非再走一次
"前台 → 后台"。

本应用冷启时，窗口已经由系统显示（`am start -W` 的 `Displayed` 只要 **209~305ms**），
但 Qt 的首帧要等 Python 把 **`EnsureModels()` / `sr_backend.InstallQnnCompat()` /
`start.InitSrEngine()` / `DumpDiagnostics("startup")`** 全跑完才出来 —— 真机实测
**第 1 秒屏幕仍是纯白**。用户在这段时间按 HOME（刚点开就切走，很常见），
快照就是白块，之后多任务里永远是白块 ⇒ 用户看到"缺少本应用的后台视图"。

### 4.10 修复（0.55/0.56）

1. **把首帧提前**(`src/start.py` + `android/main.py`)：`Run()` 新增 `afterShow` 回调，
   `main.show()` 之后先 `app.processEvents()` 把首帧真正送出去，再跑
   `EnsureModels / InstallQnnCompat / InitSrEngine / DumpDiagnostics`（都在
   `Main.Init()` 之前，`config.CanWaifu2x` 的时序不变）。
   真机实测：**第 1 秒就已经是应用画面/启动图**（修复前第 1 秒是白屏）。
2. **窗口背景兜底**(`android/tools/patch_android_manifest.py`)：给 Activity 主题补
   `android:windowBackground` → `res/drawable/jm_window_bg.xml`（深色 `#141414` +
   180dp 居中应用图标）。万一还是抓在首帧之前，卡片上也是"应用启动图"，不再是白块。
   主题模板与 bootstrap 的 `res/drawable` 都由构建脚本幂等写入。
3. 保留 0.54 的 `InstallAppStateHook`（`ApplicationInactive` 刷一帧、
   `ApplicationActive` 重排重绘）与 0.53 的任务属性修复（都无害，且后者防止
   `EXCLUDE_FROM_RECENTS` 再落到主任务上）。

### 4.11 真机验证结果（0.55 / 0.56，已完成）

| 场景 | 修复前 | 修复后 |
|---|---|---|
| 冷启第 1 秒的屏幕 | 纯白（截图 47KB） | 深色启动图（截图 562KB~1.8MB） |
| **启动 2s 内按 HOME**（原复现路径） | **纯白空卡，且 15s 后依旧空白** | 启动图（深色 + 居中图标），卡片有内容 |
| 正常使用 8s 后按 HOME | — | 应用真实界面（顶栏/标签页/加载中吉祥物） |
| 正常使用 18s（封面已加载）后按 HOME | — | 应用首页**完整画面**（封面/标题/更新时间都在） |

`bash android/tools/check_recents.sh` 可作为后续回归取证。

### 4.12 仍存在的客观限制

- 卡片内容取的是"离开前台那一帧"，所以**切换瞬间的过渡画面会被定格**（可见残影），
  这是系统行为，应用侧只能保证"有内容、是真画面"。
- 若某次仍看到空白卡片：切回应用再按一次 HOME 就会刷新（快照按"前台→后台"重抓）。

> 上面 4.1-4.3 的结论（`EXCLUDE_FROM_RECENTS` 把主任务踢出多任务）**被真机证伪**：
> 0.53 已把该 flag 去掉并给 SafPickActivity 加了独立 `taskAffinity=""`，问题依旧。
> 结论要按下面这条重写。

## 附：同类逻辑总表（一次收口清单）

| # | 模块 | 现状 | 结论 |
|---|---|---|---|
| 1 | `MakeScrollable()` 只补垂直逐像素 | 全仓库无 `setHorizontalScrollMode` | 问题 1 根因，必修 |
| 2 | `BaseTableWidget` 只补垂直 | 同上 | 必修 |
| 3 | 裸 `QTableWidget`：`ui_sr_select_widget` / `ui_download` / `ui_doh_dns:29` / `ui_nas:41` | 两个方向都按项 | 由 `MakeItemViewsPixelScroll` 统一兜底 |
| 4 | 裸 `QListWidget`：`ui_favorite_fold:48` / `ui_forbid_words:59` / `ui_nas:81` / `ui_line_edit_help_widget:33` | 垂直按项（靠 MakeScrollable 补） | 同上；后两个是"列表类弹层"，见问题 3 |
| 5 | `BaseListWidget:24-33` | 垂直逐像素 ✅、水平按项 | 列表单列，横向不触发；`tag_list_widget:20-23` 已显式补水平 ✅ |
| 6 | `ui_book_info:422-423` eps 列表 | 两个方向逐像素 | ✅ 正确范例（说明作者知道要设，只是没推广） |
| 7 | `_ActivateItemView` 的 `indexAt` 坐标系 | 用表格坐标 | 问题 2 根因，必修 |
| 8 | `_finalize` 用松手点命中 | activate/spin 两条通道 | 问题 2 次因，必修 |
| 9 | 其余 4 处 `indexAt`（右键菜单） | viewport 坐标 | ✅ 无需改 |
| 10 | `search_line_edit` / `tip_line_edit` 的 ToolTip 弹层 | 独立顶层窗 + 500px 下限 + 游离 label | 问题 3 根因，必修 |
| 11 | `_InPopup()` 不认 `ToolTip` | 判定漏洞 | 建议补（防复发） |
| 12 | `SafService.StartPicker` 的 `EXCLUDE_FROM_RECENTS` | 打到主任务 | 问题 4 根因，必修 |
| 13 | `SmoothScrollBar` 500ms 自定义缓动 vs QScroller | 已由 `SetSmooth(False)` 关闭 | ✅ 仅对"已接管"区域生效；未接管的弹窗内列表仍可能双缓动（问题 3 修复时注意） |

## 回归建议（沿用仓库既有宿主回归风格）

新增 2 个 `android/tools/host_test_*.py`（对照 `host_test_tap_gate.py` 的写法，
用 `QTouchEvent` 直接喂事件，不依赖真机）—— **均已实现并通过**：

1. `host_test_table_touch.py`（4 组）：A 滚动计量单位（含"改回 ScrollPerItem 就会
   按行跳"的反证）；B 点按命中（含"旧坐标算法确实错位"的反证 + 端到端触控路由）；
   C 逐像素兜底幂等；D 竖屏列宽（11 列 → 一屏装下、标题列拿到剩余宽度）。
2. `host_test_search_popup.py`（4 组）：A 子控件图层 + 几何不溢出；B 点记录写回输入框
   （真触控 + 触控路由）；C 点别处自动收起；D 桌面端仍走原浮层且不伸出屏幕。

---

## 附录 B：落地清单（0.53）

| 文件 | 改动 |
|---|---|
| `src/tools/mobile_ui_touch.py` | `MakeScrollable()` 补 `setHorizontalScrollMode(ScrollPerPixel)`；新增 `MakeItemViewsPixelScroll()` 并在 `EnableTouchScroll()` 里先跑一遍；`_ActivateItemView()` 改用 `viewport()` 坐标；`_finalize()` 的 spin/activate 命中改用手按下点 |
| `src/tools/mobile_ui_base.py` | `_InPopup()` 把 `Qt.ToolTip` 也算作弹窗（防"候选列表被当普通控件认领"） |
| `src/tools/mobile_ui_layout.py` | 新增 `FitTableForPortrait()` / `FitTablesForPortrait()`（列宽策略、隐藏低价值列、ElideRight、压缩表头下限）；`ReflowPortrait()` 末尾调用 |
| `src/tools/mobile_ui_window.py` | `_MobileFilter` 增加 `ClampInnerWidth()`：遮罩对话框内容宽度不超过窗口（Show 时夹宽 + adjustSize，Resize 时只夹宽，避免递归） |
| `src/component/tab/base_table_widget.py` | 补水平逐像素 |
| `src/component/line_edit/popup_list.py`（新） | 候选列表图层：手机端子控件图层 + 桌面端原 ToolTip 浮层，几何统一夹紧；`_OutsideHider` 负责点别处收起 |
| `src/component/line_edit/search_line_edit.py` | 改用 `popup_list`；删掉 `QLabel("asdasdasdasd")` + 第二次 `QHBoxLayout`；`HideListView/ShowListView/CheckClick` 转发 |
| `src/component/line_edit/tip_line_edit.py` | 同上（DoH 地址 / 代理地址 / 域名候选列表） |
| `src/view/download/download_view.py` | 竖屏列策略：隐藏 id/时间/速度/转换章节/转换耗时，标题列 Stretch |
| `src/view/download/download_all_view.py` | 竖屏列策略：隐藏分类，名称列 Stretch |
| `src/view/download/download_some_view.py` | 竖屏列策略：标题列 Stretch，其余压窄 |
| `src/view/setting/setting_sr_select_view.py` | 竖屏列策略（隐藏"耗时"）+ 对话框内容宽度夹到窗口内 |
| `android/java/org/jmcomic/SafService.java` | 去掉 `FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS` |
| `android/tools/patch_android_manifest.py` | `SafPickActivity` 加 `android:taskAffinity=""`（独立任务） |
| `android/java/org/jmcomic/SafPickActivity.java` | 注释与实现对齐（说明 taskAffinity 为什么必须） |
| `android/main.py` | 新增 `ApplySurfaceContainer()`：默认 `QT_ANDROID_SURFACE_CONTAINER_TYPE=1`（TextureView，见 4.5），取值写进启动诊断 |
| `src/tools/mobile_ui_hooks.py` | 新增 `InstallAppStateHook()`：进后台刷最后一帧 / 回前台重排重绘 / `appState:` 日志 |
| `android/tools/check_recents.sh`（新） | 多任务取证：任务在不在、快照状态、是否被排除、进程存活、渲染容器类型 |
| `src/start.py`（0.55） | `Run()` 新增 `afterShow` 回调：`main.show()` 之后先 `processEvents()` 把首帧送出去，再跑重活（见 4.10） |
| `android/main.py`（0.55） | 新增 `DeferredStartup()`：`EnsureModels` / `InstallQnnCompat` / `InitSrEngine` / `DumpDiagnostics` 全部挪到首帧之后 |
| `android/tools/patch_android_manifest.py`（0.55/0.56） | 给 Activity 主题补 `android:windowBackground`→`@drawable/jm_window_bg`；幂等写入 bootstrap 的 `res/drawable`（深色 + 180dp 居中图标） |

宿主回归：`host_test_table_touch.py`、`host_test_search_popup.py`、`host_test_app_state.py` 全绿；
`host_test_tap_gate / input_focus / spin_focus / text_select / sr_layout / widget_guard_audit` 无回归。
`smoke_test_android.py` 在本机有 3 处**历史遗留红点**（HelpView 横向溢出 372>366、
封面宽超 4px、封面宽缓存断言），已在**未改动的 HEAD** 上复现同样失败（本机字体度量与 CI
基线不同），与本轮改动无关。

## 附录 C：真机验证清单（0.53）

1. 设置 → 看图 → 选择模型：表格横向慢慢滑，内容应 1:1 跟随；只剩"模型名/算法/描述"三列且都在屏内。
2. 下载页：轻扫表格不再"跳行"，纵向/横向都跟手；可见列=标题/下载进度/章节/状态/转换进度/转换状态
   （时间/速度/转换耗时已隐藏），标题过长显示省略号。
3. 表格里点第 N 行：选中/高亮就是第 N 行（不再差一行）；点第 2 列不再落到第 3 列。
4. 搜索框点进去：搜索记录弹层不超出屏幕、能看到"搜索记录"标题；点某条记录 → 输入框变成该记录并立即搜索。
5. **多任务界面**（0.56 真机已验）：
   a. 正常用一会儿 → HOME → 多任务卡片显示**应用当前界面**；
   b. 点开应用**立刻**（1~2s 内）按 HOME → 卡片显示**启动图**（深色+图标），不再是白块；
   c. 若某次仍是空白卡片：切回应用再按一次 HOME 即刷新（快照按"前台→后台"重抓）。
   异常时跑 `bash android/tools/check_recents.sh`，按脚本末尾判读口径定位
   （任务在不在 / 快照是否为空 / 进程是否存活 / 渲染容器类型）。
   想临时退回 SurfaceView：在 `<AppDataDir>/sr_env.txt` 写 `QT_ANDROID_SURFACE_CONTAINER_TYPE=0`
   （注意：0.54 的实测表明容器类型不是本问题的成因，改它不影响多任务画面）。

