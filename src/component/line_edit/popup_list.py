# coding:utf-8
""" 输入框候选列表图层（搜索记录 / 提示词候选 / DOH 地址 / 获取地区）

两个输入框组件(`SearchLineEdit`、`TipLineEdit`)原来各自写了一份"输入框下方弹一个
Qt.ToolTip 独立窗口"的实现，三处问题一模一样：

    1. **Android 上点不动**：Qt.ToolTip 是**第二个顶层窗口**，平台侧不激活、不接收
       触摸事件 —— 手指落在列表上，事件其实给了下面那个窗口，`clicked` 永远不发。
       本项目里"第二个顶层窗口"还有 eglSurface 死锁 abort 的历史
       (见 mobile_ui_window.MakeChildOverlay)，所以手机端统一改成**主窗口里的子控件**。
    2. **宽度溢出**：`resize(max(500, self.width()), ...)` 把下限写死 500px，
       而竖屏逻辑宽只有 480(小屏 360~412) —— 右侧直接被切掉。
    3. **位置/高度没用屏幕夹紧**：高度恒为窗口一半，与条目数无关。

现在两端共用这一套几何：优先"和输入框同宽、贴着它下方、夹在宿主窗口内"，
桌面端保留原来的浮层窗口(窗口小的场景也不再多出屏幕)。

--- 2026-10-27 补充（"点得开但点不中"的收尾） ---------------------------------

`_OutsideHider` 原来是拿**事件的接收者**判断"点的是不是外面"：

    if obj is self.edit or self.widget.isAncestorOf(obj): 不算外面

手机端这条永远不成立 —— 触控事件投递到的是**宿主窗口**，不是弹层里的列表项，
于是手指落到弹层上的第一下就被判成"点到外面"，弹层当场收起，`clicked` 自然不发。
现在改成拿**触点的全局坐标**和两个矩形比：落点在弹层里 / 落点在输入框里都算里面。

另外补了开合动画：高度 + 位移用 `OutQuint`(200ms) 展开、`OutQuint`(120ms) 收起。
OutQuint 是单调缓出曲线，不会像 OutBack 那样冲过头被父控件裁掉，适合"从输入框
下面长出来"这种贴边生长的场景。

--- 2026-10-28 补充（IME 弹出后弹层不跟手 / 错位 / 被裁） ----------------------

Android 上点输入框会弹 IME，窗口被 adjustResize 缩短（分屏、小窗、旋转同理），
页面重新布局后输入框可能整体上移、被滚动条带着走；而弹层几何原来只在 Show 时
算了一次，于是停在旧位置：轻则和输入框错开，重则下半截落在可见窗口外
（搜索页搜索记录、登录页/代理设置里的 DOH、获取地区输入框都是这个毛病）。

现在弹层可见期间由 `_PopupTracker` 跟踪：

    * 输入框自己：Move / Resize / Hide / ParentChange / Destroy；
    * 宿主窗口与输入框的祖先链：Move / Resize / Show / Hide / WindowStateChange；
    * 祖先里每个 QAbstractScrollArea 的滚动条 valueChanged / rangeChanged
      （SmoothScrollBar 的滚动动画每一步都会发 valueChanged，不用轮询）；
    * 120ms 的兜底 QTimer（输入法/分屏改尺寸时，Qt 侧事件不一定按顺序来齐）。

命中后不做动画：直接按当前布局重算几何并**完整夹在宿主窗口 rect 内**；打开动画
还在跑时，如果目标位置没变就让它自己跑完（不打断、不闪），只有位置真的变了才
先停动画再即时落位。输入框被隐藏、滚出可视区（visibleRegion 为空）、宿主窗口
不可见时，弹层立即收起（不做收起动画，避免动画期间还停在错误位置）。
兜底定时器只在手机端启用，桌面端仍是原来的 ToolTip 浮层（桌面宿主缩放不会改变
它的坐标系，不需要跟踪）。

审计结论（2026-10-28）：全 src 里的浮动候选菜单只有 `SearchLineEdit` /
`TipLineEdit` 两处，都走本模块的 Install，没有第三处自绘/自管几何的输入框弹层；
`text_label.py:205` 的 `menu.popup` 是右键菜单，不是输入候选，不算在内。
"""
from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QEvent, QObject,
                            QPoint, QPropertyAnimation, QRect, QTimer, Qt)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QWidget

from tools.log import Log


# 弹层最小宽度/最小高度(逻辑像素)
PopupMinWidth = 200
PopupMinHeight = 96
# 列表里预估的行高(取不到真实 sizeHintForRow 时用)
PopupRowHeight = 44
# 标题("搜索记录")+边距占掉的高度
PopupChromeHeight = 40
# 展开/收起动画时长(毫秒)与曲线
PopupOpenMs = 200
PopupCloseMs = 120
# 弹层可见期间的兜底重定位间隔(毫秒)。真机上 IME 开合/分屏改尺寸时，窗口事件与
# 布局事件不一定按期望顺序到达；120ms 一次的开销可以忽略，但足以兜住漏掉的事件。
PopupReanchorMs = 120
# 弹层与宿主窗口边缘至少留的像素(窗口小到放不下时这个值会按窗口自动缩小)
PopupMargin = 4


def _IsAndroid():
    try:
        from tools import platform_mobile
        return platform_mobile.IsAndroid()
    except Exception:
        return False


def _Clamp(value, low, high):
    """ 把 value 夹进 [low, high]；high 比 low 还小时以 low 为准(窗口极小的兜底) """
    if high < low:
        return low
    return max(low, min(value, high))


class _OutsideHider(QObject):
    """ 手指/鼠标点到弹层和输入框以外时收起弹层

    子控件图层不会抢焦点，所以原来的 `focusOutEvent -> hide()` 在手机上不再触发
    (触摸不经过焦点系统)，必须自己判"点的是谁"。

    **判的是触点的位置，不是事件的接收者**：手机端 TouchBegin 的接收者是宿主窗口，
    用它做 `isAncestorOf` 判断等于"按在弹层上也算点外面"（弹层刚出来就被自己收掉）。
    """

    def __init__(self, edit, widget, parent=None):
        super().__init__(parent)
        self.edit = edit
        self.widget = widget

    @staticmethod
    def _PressPos(event):
        """ 取触点的全局坐标(TouchBegin 用第一个点；鼠标用 globalPosition) """
        try:
            if event.type() == QEvent.Type.TouchBegin:
                points = event.points()
                if not points:
                    return None
                return points[0].globalPosition().toPoint()
            return event.globalPosition().toPoint()
        except Exception:
            return None

    def eventFilter(self, obj, event):
        try:
            if event.type() not in (QEvent.Type.TouchBegin, QEvent.Type.MouseButtonPress):
                return False
            if not isinstance(obj, QWidget):
                return False
            if not self.widget.isVisible():
                return False

            pos = self._PressPos(event)
            if pos is not None:
                if self.widget.rect().contains(self.widget.mapFromGlobal(pos)):
                    return False
                if self.edit.rect().contains(self.edit.mapFromGlobal(pos)):
                    return False
            else:
                # 拿不到坐标(合成事件/老版本)时退回接收者判断
                if obj is self.edit or obj is self.widget or self.widget.isAncestorOf(obj):
                    return False

            hide = getattr(self.edit, "HideListView", None)
            if callable(hide):
                hide()
        except Exception:
            pass
        return False


def Install(edit, widget, listView):
    """ 把候选列表图层装到输入框上；返回状态字典(存在 edit._jmPopup) """
    mobile = _IsAndroid()
    state = {"widget": widget, "listView": listView, "mobile": mobile,
             "filter": None, "anim": None, "closing": False,
             "animating": False, "tracker": None, "host": None,
             # 打开那一刻输入框是否可见：真机上永远是可见的；宿主自检里有些输入框
             # 藏在折叠面板里，打开后不做"跟着隐藏"的收敛（保持旧行为）
             "shownVisible": False,
             # 锚点指纹：宿主尺寸 + 输入框在宿主里的位置 + 行数。兜底刷新/滚动
             # 事件里绝大多数帧都没变，先比指纹就能跳过整个几何重算。
             "anchorKey": None, "anchorRect": None,
             # 内容量测缓存：Show 时量一次，之后重定位/兜底刷新直接复用
             "rows": -1, "rowHeight": PopupRowHeight, "chrome": PopupChromeHeight,
             "listMax": 0, "contentHeight": 0, "listMaxSet": None}
    try:
        if mobile:
            # 子控件图层：不再是顶层窗口(见模块头)。objectName+样式表给一个边框，
            # 否则浮在页面上分不清边界(桌面端 ToolTip 窗口自带阴影/边框)
            widget.setWindowFlags(Qt.Widget)
            widget.setObjectName("jmPopupList")
            widget.setAttribute(Qt.WA_StyledBackground, True)
            # 只作用于这个弹层（不碰全局主题）：
            #   * 主题给 QListView 定了 padding-left:15px + 底部 2px 边框，弹层里会缩进一大截；
            #   * 行高按 26px 收紧，13 个地区才不会摊成几百像素的大长条。
            # 注意：不要在这里碰背景色 —— 主题是靠 QSS 上色的，palette(window) 在
            # 未设调色板的环境里会是浅灰，弹层直接变成白底白字。只改内边距/行高。
            widget.setStyleSheet(
                "QWidget#jmPopupList{border:1px solid palette(mid);}"
                "QListView{padding-left:4px;border:none;}"
                "QListView::item{min-height:24px;padding:1px 2px;}")
            widget.setMinimumHeight(0)
            widget.hide()
            listView.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            listView.setTextElideMode(Qt.ElideRight)
            listView.setUniformItemSizes(True)
            listView.setMinimumHeight(0)
            # 逐像素 + QScroller：列表才能 1:1 跟手滚动，也才会被触控路由当成
            # "已接管的滚动区域"来认领点按(见 mobile_ui_touch._InTouchArea)
            from tools import mobile_ui
            mobile_ui.MakeScrollable(listView)
            app = QApplication.instance()
            if app is not None:
                state["filter"] = _OutsideHider(edit, widget, app)
                app.installEventFilter(state["filter"])
        else:
            widget.setParent(edit, Qt.Popup)
            widget.setFocusProxy(edit)
            widget.setWindowFlags(Qt.ToolTip)
    except Exception as es:
        Log.Error(es)
    edit._jmPopup = state
    return state


def _StopAnim(state):
    anim = state.get("anim")
    state["anim"] = None
    state["animating"] = False
    if anim is None:
        return
    try:
        anim.stop()
    except Exception:
        pass


def _AnimateTo(widget, start, end, duration, state, onFinished=None):
    """ geometry 动画：OutQuint（缓出、单调，不会冲过头） """
    _StopAnim(state)
    try:
        anim = QPropertyAnimation(widget, b"geometry", widget)
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.OutQuint)
        anim.setStartValue(start)
        anim.setEndValue(end)
        state["animating"] = True

        def _Done():
            state["animating"] = False
            if onFinished is not None:
                onFinished()

        anim.finished.connect(_Done)
        widget.setGeometry(start)
        anim.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
        state["anim"] = anim
        return anim
    except Exception as es:
        Log.Error(es)
        state["animating"] = False
        widget.setGeometry(end)
        return None


def _MeasureMobileContent(state):
    """ 量一次内容量：行高 / 列表高度 / 列表上方的标题与添加行高度

    这些值只和候选条数、标题/添加行是否显示有关，跟窗口尺寸无关 —— 量一次缓存，
    之后每次重定位直接复用，120ms 的兜底刷新才足够便宜。
    """
    widget = state["widget"]
    listView = state["listView"]
    rows = 0
    model = listView.model()
    if model is not None:
        rows = model.rowCount()
    rowHeight = listView.sizeHintForRow(0) if rows > 0 else 0
    if rowHeight <= 0:
        rowHeight = PopupRowHeight
    # 1) 先松开上一次给列表设的高度上限，否则下面量出来的 sizeHint 会被它夹住
    try:
        listView.setMaximumHeight(16777215)
    except Exception:
        pass
    # 2) QListView 的 sizeHint 是固定默认值(256x192)，不是内容高 ——
    #    用"整体 sizeHint 减去列表 sizeHint"反推标题/添加行/边距占的高度
    try:
        chrome = max(0, widget.sizeHint().height() - listView.sizeHint().height())
    except Exception:
        chrome = PopupChromeHeight
    # 3) 列表只留"刚好放下这些行"的高度；+12 是边框/viewport 余量
    #    (实测 list 与 viewport 差 10px)，否则最后一行会被切一条并顶出滚动条
    listMax = max(48, rows * rowHeight + 12)
    state["rows"] = rows
    state["rowHeight"] = rowHeight
    state["chrome"] = chrome
    state["listMax"] = listMax
    state["contentHeight"] = max(PopupMinHeight, listMax + chrome)
    # 强制下一次套用新的最大高度
    state["listMaxSet"] = None


def _AnchorKey(edit, state):
    """ 便宜的锚点指纹：宿主尺寸 + 输入框在宿主里的位置/大小 + 候选行数

    弹层重排的触发源里，窗口滚动条动画每帧都会发 valueChanged：绝大多数帧
    指纹都没变，先比指纹可以跳过整个几何重算（代价是两次 mapTo + 整数比较）。
    """
    try:
        host = edit.window()
        if host is None:
            return None
        bottomLeft = edit.mapTo(host, QPoint(0, edit.height()))
        rows = state.get("rows", -1)
        model = state["listView"].model()
        if model is not None:
            rows = model.rowCount()
        return (id(host), host.width(), host.height(),
                bottomLeft.x(), bottomLeft.y(), edit.width(), edit.height(), rows)
    except Exception:
        return None


def _ComputeMobileRect(edit, state, measure=False):
    """ 手机端几何：贴着输入框下方/上方，整个矩形夹进宿主窗口(不吃掉最后一像素)

    返回值是相对宿主窗口的 QRect；宿主/输入框暂时不可用时返回 None。
    注意这里**不做**"输入框是否隐藏/滚出可视区"的判定（那属于 Reanchor 的收起逻辑），
    因为宿主自检里存在"面板折叠时也调用 Show"的旧用例。
    """
    widget = state["widget"]
    listView = state["listView"]
    host = edit.window()
    if host is None:
        return None
    state["host"] = host
    if widget.parentWidget() is not host:
        widget.setParent(host)

    # 行数变了(比如搜索记录新增)才重量，否则复用缓存
    if not measure:
        model = listView.model()
        if model is not None and model.rowCount() != state.get("rows", -1):
            measure = True
    if measure or state.get("contentHeight", 0) <= 0:
        _MeasureMobileContent(state)

    hostW = max(1, host.width())
    hostH = max(1, host.height())
    # 边距按宿主短边收缩：150px 的小窗也留得下弹层；再小就贴边
    margin = min(PopupMargin, max(0, min(hostW, hostH) // 8))

    # 输入框左下角在宿主里的位置(祖先滚动/布局变化都会直接反映到 mapTo 结果上)
    bottomLeft = edit.mapTo(host, QPoint(0, edit.height()))
    editTop = bottomLeft.y() - edit.height()
    editLeft = bottomLeft.x()

    # 宽度：不窄于输入框、不窄于最小宽，但整个弹层必须留在宿主内
    maxW = max(1, hostW - margin * 2)
    width = max(edit.width(), PopupMinWidth)
    width = max(1, min(width, maxW))
    x = _Clamp(editLeft, margin, hostW - margin - width)

    # 高度：先按内容高，再夹到宿主高度（宿主很小时压缩高度、让列表内部滚动）
    maxH = max(1, hostH - margin * 2)
    contentHeight = state["contentHeight"]
    height = min(contentHeight, maxH)
    height = max(height, min(PopupMinHeight, maxH))
    height = max(1, min(height, maxH))

    # 上方/下方各自最多能放多高（2px 是弹层与输入框之间的间隙）
    spaceBelow = hostH - margin - (editTop + edit.height()) - 2
    spaceAbove = editTop - margin - 2

    # 上下都放不下完整内容时，先把高度收缩到空间较大的那一侧 ——
    # 真机极端小窗 + IME 会把窗口压得很矮（wm size 900x1600 + adjustResize 剩约
    # 222dp 高），不先收缩的话最后夹 y 只能把弹层压回输入框上，看起来就像"弹层
    # 没跟着输入框走"。
    if spaceBelow < height and spaceAbove < height:
        side = max(spaceBelow, spaceAbove)
        if side > 0:
            squeezed = min(height, max(side, min(PopupMinHeight, maxH)))
            if squeezed < height:
                height = max(1, squeezed)
                # 每次展开最多记一条：真机上用来核对窗口被 IME 压小后弹层贴的是哪侧
                if not state.get("squeezeLogged"):
                    state["squeezeLogged"] = True
                    try:
                        Log.Warn(
                            "弹层上下空间不足，收缩高度贴边: 宿主={}x{} 输入框=({},{},{},{}) 上={} 下={} -> 高={}"
                            .format(hostW, hostH, editLeft, editTop,
                                    edit.width(), edit.height(),
                                    spaceAbove, spaceBelow, height))
                    except Exception:
                        pass

    listMax = state["listMax"]
    overflow = contentHeight - height
    if overflow > 0:
        listMax = max(48, listMax - overflow)
    listMax = max(1, min(listMax, maxH))
    if state.get("listMaxSet") != listMax:
        try:
            listView.setMaximumHeight(listMax)
        except Exception:
            pass
        state["listMaxSet"] = listMax

    # 下方优先；下方不够、上方更大就翻上去；最后整体夹进宿主 —— 宿主极小时
    # 允许贴边，但绝不出现"半截在可见窗口外"
    if spaceBelow >= height or spaceBelow >= spaceAbove:
        y = editTop + edit.height() + 2
    else:
        y = editTop - height - 2
    y = _Clamp(y, margin, hostH - margin - height)
    return QRect(x, y, width, height)


def _ComputeDesktopRect(edit, state):
    """ 桌面端几何：输入框下方的浮层窗口，完整夹进屏幕可用区域 """
    bottomLeft = edit.mapToGlobal(QPoint(0, edit.height()))
    editTop = bottomLeft.y() - edit.height()
    editLeft = bottomLeft.x()
    screen = QGuiApplication.screenAt(bottomLeft) or QGuiApplication.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
    else:
        available = QRect(bottomLeft.x(), bottomLeft.y(), 1920, 1080)
    margin = min(PopupMargin, max(0, min(available.width(), available.height()) // 8))
    maxW = max(1, available.width() - margin * 2)
    width = max(edit.width(), 320)
    width = max(1, min(width, maxW))
    x = _Clamp(editLeft, available.x() + margin,
               available.right() - margin - width)
    maxH = max(1, available.height() - margin * 2)
    height = max(PopupMinHeight, available.height() // 3)
    height = max(1, min(height, maxH))
    spaceBelow = available.bottom() - margin - bottomLeft.y() - 8
    spaceAbove = editTop - available.top() - margin - 2
    if spaceBelow >= height or spaceBelow >= spaceAbove:
        y = bottomLeft.y()
    else:
        y = editTop - height - 2
    y = _Clamp(y, available.top() + margin,
               available.bottom() - margin - height)
    return QRect(x, y, width, height)


def _DetachTracker(state):
    tracker = state.get("tracker")
    if tracker is None:
        return
    try:
        tracker.Detach()
    except Exception:
        pass


def _AttachTracker(edit, state):
    tracker = state.get("tracker")
    if tracker is None:
        tracker = _PopupTracker(edit, state)
        state["tracker"] = tracker
    tracker.Attach()


def _HideInstant(edit):
    """ 输入框已隐藏 / 滚出可视区 / 宿主窗口不可见：立刻收起，不做收起动画

    收起动画期间弹层还停在旧几何上，这时候它已经没有可见的锚点了，继续动画
    只会在错误位置停留 120ms，所以这里直接 hide()。
    """
    state = getattr(edit, "_jmPopup", None)
    if state is None or state["widget"] is None:
        return
    _DetachTracker(state)
    _StopAnim(state)
    try:
        state["widget"].hide()
    except Exception:
        pass
    state["closing"] = False


def _MobileShouldHide(edit, state):
    """ 弹层可见期间：输入框/宿主是不是已经不该再显示弹层了 """
    try:
        host = edit.window()
        if host is None or not host.isVisible():
            return True
        if not state.get("shownVisible"):
            # 打开时输入框本来就不可见(宿主自检里的折叠面板/程序化调用)：
            # 保持旧行为，不做可见性收敛，否则这些用例的弹层会被立刻收掉
            return False
        if not edit.isVisible():
            return True
        # 滚出可视区：visibleRegion 已经被祖先 viewport 裁空
        if edit.visibleRegion().isEmpty():
            return True
    except Exception:
        return True
    return False


class _PopupTracker(QObject):
    """ 弹层可见期间盯着"会让弹层跑偏"的所有几何变化（手机端专用）

    监听对象在 Show 时挂上、Hide 时摘掉：
      * 输入框本身：Move / Resize / Hide / ParentChange / Destroy；
      * 宿主窗口与输入框的祖先链：Move / Resize / Show / Hide / WindowStateChange；
      * 祖先里每个 QAbstractScrollArea 的滚动条 valueChanged / rangeChanged
        （SmoothScrollBar 的滚动动画每一步都会发 valueChanged，不用轮询）；
      * 120ms 兜底 QTimer：真机上输入法/系统改窗口尺寸时，Qt 事件不一定齐。

    事件不直接重排，而是用 QTimer(0) 合并到下一轮事件循环 —— 一次布局调整常伴随
    几十个 Move/Resize，合并后只算一次。`busy` 防递归（重排本身也可能触发事件）。
    """

    def __init__(self, edit, state):
        super().__init__(QApplication.instance())
        self.edit = edit
        self.state = state
        self.widgets = []      # 已装事件过滤器的 QWidget
        self.widgetIds = set()
        self.scrollBars = []   # [(bar, valueConn, rangeConn)]
        self.scrollBarIds = set()
        self.busy = False
        self.timer = QTimer(self)
        self.timer.setInterval(PopupReanchorMs)
        self.timer.timeout.connect(self.OnTimer)
        # 合并同一轮事件循环里的多次 Move/Resize：单次 0ms 定时器
        self.defer = QTimer(self)
        self.defer.setSingleShot(True)
        self.defer.setInterval(0)
        self.defer.timeout.connect(self._OnDeferred)
        try:
            # 输入框销毁时把弹层也带走（eventFilter 里的 Destroy 在部分平台收不到）
            edit.destroyed.connect(self._OnEditDestroyed)
        except Exception:
            pass

    # ---------------- 挂载/摘除 ----------------
    def Attach(self):
        try:
            if self.edit is None:
                return
            self._Watch(self.edit)
            window = self.edit.window()
            if window is not None:
                self._Watch(window)
            parent = self.edit.parentWidget()
            while parent is not None:
                self._Watch(parent)
                if parent is window or parent.isWindow():
                    break
                parent = parent.parentWidget()
            self._WatchScrollAreas()
            if not self.state["widget"].isHidden():
                self.timer.start()
        except Exception as es:
            Log.Error(es)

    def Detach(self):
        self.timer.stop()
        self.defer.stop()
        for widget in self.widgets:
            try:
                widget.removeEventFilter(self)
            except Exception:
                pass
        self.widgets = []
        self.widgetIds = set()
        for bar, valueConn, rangeConn in self.scrollBars:
            try:
                bar.valueChanged.disconnect(valueConn)
            except Exception:
                pass
            try:
                bar.rangeChanged.disconnect(rangeConn)
            except Exception:
                pass
        self.scrollBars = []
        self.scrollBarIds = set()

    def _Watch(self, widget):
        if widget is None:
            return
        key = id(widget)
        if key in self.widgetIds:
            return
        self.widgetIds.add(key)
        self.widgets.append(widget)
        try:
            widget.installEventFilter(self)
        except Exception:
            pass

    def _WatchScrollAreas(self):
        widget = self.edit
        while widget is not None:
            if isinstance(widget, QAbstractScrollArea):
                self._WatchScrollArea(widget)
            if widget.isWindow():
                break
            widget = widget.parentWidget()

    def _WatchScrollArea(self, area):
        bars = []
        try:
            bars.append(area.verticalScrollBar())
            bars.append(area.horizontalScrollBar())
        except Exception:
            pass
        for bar in bars:
            if bar is None:
                continue
            key = id(bar)
            if key in self.scrollBarIds:
                continue
            self.scrollBarIds.add(key)
            try:
                valueConn = bar.valueChanged.connect(self.ScheduleReorder)
                rangeConn = bar.rangeChanged.connect(self.ScheduleReorder)
            except Exception:
                continue
            self.scrollBars.append((bar, valueConn, rangeConn))

    # ---------------- 事件 ----------------
    def ScheduleReorder(self, *args):
        if self.busy or self.state.get("tracker") is not self:
            return
        try:
            if self.state.get("closing"):
                return
            widget = self.state.get("widget")
            if widget is None or widget.isHidden():
                return
            if not self.defer.isActive():
                self.defer.start()
        except Exception:
            pass

    def _OnDeferred(self):
        if self.state.get("tracker") is not self:
            return
        # 事件型重排：位置真的变了就停掉开合动画，立刻落位（不做动画、不闪）
        self._Reorder(force=True)

    def OnTimer(self):
        if self.state.get("tracker") is not self:
            self.timer.stop()
            return
        widget = self.state.get("widget")
        if widget is None or widget.isHidden():
            self.timer.stop()
            return
        # 兜底型重排：展开动画还在跑就让它跑完，不跟它抢 geometry
        self._Reorder(force=False)

    def _Reorder(self, force):
        if self.busy:
            return
        state = self.state
        if state.get("tracker") is not self or self.edit is None:
            return
        if state.get("closing"):
            return
        widget = state.get("widget")
        if widget is None or widget.isHidden():
            return
        if state.get("animating") and not force:
            return
        self.busy = True
        try:
            host = self.edit.window()
            if host is not state.get("host"):
                state["host"] = host
                self.Attach()
            Reanchor(self.edit)
        except Exception as es:
            Log.Error(es)
        finally:
            self.busy = False

    def eventFilter(self, obj, event):
        try:
            if self.state.get("tracker") is not self or self.edit is None:
                return False
            eventType = event.type()
            if eventType == QEvent.Type.Destroy:
                if obj is self.edit:
                    self._OnEditDestroyed()
                return False
            if eventType == QEvent.Type.Hide:
                # 输入框/宿主窗口被藏起来：没有可见锚点了，立刻收起
                if obj is self.edit or obj is self.edit.window():
                    _HideInstant(self.edit)
                    return False
            if eventType in (QEvent.Type.Move, QEvent.Type.Resize,
                             QEvent.Type.Show, QEvent.Type.Hide,
                             QEvent.Type.WindowStateChange,
                             QEvent.Type.ParentChange):
                self.ScheduleReorder()
        except Exception:
            pass
        return False

    def _OnEditDestroyed(self, *args):
        state = self.state
        if state.get("tracker") is not self:
            return
        state["tracker"] = None
        self.edit = None
        try:
            self.Detach()
        except Exception:
            pass
        widget = state.get("widget")
        if widget is not None:
            state["widget"] = None
            try:
                widget.hide()
                widget.deleteLater()
            except Exception:
                pass
        self.deleteLater()


def Reanchor(edit):
    """ 布局变了：按当前几何重新摆放弹层（无动画）；不该显示时直接收起

    由 `_PopupTracker` 在宿主窗口/输入框/祖先/滚动条变化时调用，也导出给宿主
    自检和"外壳自己知道布局变了"的调用方。返回新的 QRect（没在显示时返回 None）。
    """
    state = getattr(edit, "_jmPopup", None)
    if state is None or state["widget"] is None:
        return None
    widget = state["widget"]
    try:
        if state.get("closing") or widget.isHidden():
            return None
        if state["mobile"]:
            if _MobileShouldHide(edit, state):
                _HideInstant(edit)
                return None
            # 先比锚点指纹：宿主/输入框/行数都没变就直接返回缓存矩形
            key = _AnchorKey(edit, state)
            if key is not None and key == state.get("anchorKey"):
                rect = state.get("anchorRect")
                if rect is not None and widget.geometry() == rect:
                    return rect
            rect = _ComputeMobileRect(edit, state)
            state["anchorKey"] = key
            state["anchorRect"] = rect
        else:
            rect = _ComputeDesktopRect(edit, state)
        if rect is None:
            _HideInstant(edit)
            return None
        if widget.geometry() != rect:
            # 开合动画的目标没变：让它自己跑完，别打断（避免闪一下）
            anim = state.get("anim")
            if state.get("animating") and anim is not None:
                try:
                    if anim.endValue() == rect:
                        return rect
                except Exception:
                    pass
            _StopAnim(state)
            widget.setGeometry(rect)
        return rect
    except Exception as es:
        Log.Error(es)
        return None


def Show(edit):
    """ 在输入框下方显示候选列表(几何全部夹在宿主范围内) """
    state = getattr(edit, "_jmPopup", None)
    if state is None:
        return False
    widget = state["widget"]
    if widget is None:
        return False
    if not widget.isHidden() and not state.get("closing"):
        return False
    state["closing"] = False
    try:
        if state["mobile"]:
            host = edit.window()
            if host is None:
                return False
            if widget.parentWidget() is not host:
                widget.setParent(host)
            # 打开这一刻输入框是否可见：真机永远可见；宿主自检里折叠面板内的
            # 输入框不可见，打开后不按可见性收敛（保持旧行为）
            state["shownVisible"] = edit.isVisible()
            state["host"] = host
            state["squeezeLogged"] = False
            rect = _ComputeMobileRect(edit, state, measure=True)
            if rect is None:
                return False
            state["anchorKey"] = _AnchorKey(edit, state)
            state["anchorRect"] = rect
            widget.show()
            widget.raise_()
            if state.get("animate", True):
                # 从 2px 高长出来：贴住输入框上沿，视觉上就是"从框下面展开"
                start = QRect(rect.x(), rect.y(), rect.width(), 2)
                _AnimateTo(widget, start, rect, PopupOpenMs, state)
            else:
                widget.setGeometry(rect)
            _AttachTracker(edit, state)
        else:
            # 桌面：仍然是输入框下方的浮层，但不许伸出屏幕
            rect = _ComputeDesktopRect(edit, state)
            if rect is None:
                return False
            widget.setGeometry(rect)
            widget.show()
        return True
    except Exception as es:
        Log.Error(es)
    return False


def Hide(edit):
    state = getattr(edit, "_jmPopup", None)
    if state is None:
        return
    widget = state["widget"]
    try:
        if widget is None or (widget.isHidden() and not state.get("closing")):
            return
        state["closing"] = True
        # 收起动画期间不再跟踪布局：弹层已经在往回收，重排只会让动画抖
        _DetachTracker(state)
        if not state["mobile"] or not state.get("animate", True):
            _StopAnim(state)
            widget.hide()
            state["closing"] = False
            return
        rect = widget.geometry()
        end = QRect(rect.x(), rect.y(), rect.width(), 2)

        def _Finish():
            try:
                widget.hide()
            except Exception:
                pass
            state["closing"] = False

        _AnimateTo(widget, rect, end, PopupCloseMs, state, _Finish)
    except Exception as es:
        Log.Error(es)


def IsHidden(edit):
    state = getattr(edit, "_jmPopup", None)
    if state is None or state["widget"] is None:
        return True
    try:
        return state["widget"].isHidden() or bool(state.get("closing"))
    except Exception:
        return True


def CheckClick(edit, pos):
    """ 页面别处被点了一下：收起弹层(桌面端由 MainView.mousePressEvent 调)

    注意不能只靠 `clearFocus()`：手机端子控件图层不抢焦点，输入框可能本来就没焦点，
    clearFocus() 是空操作，focusOutEvent 也就不会来(原来"点了别处弹层还在"的一个来源)。
    """
    if IsHidden(edit):
        return
    Hide(edit)
    clear = getattr(edit, "clearFocus", None)
    if callable(clear):
        clear()
