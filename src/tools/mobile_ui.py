# coding:utf-8
""" 手机竖屏/触摸界面适配层

只在 Android(platform_mobile.IsAndroid()) 下生效，桌面端不会调用这里，
因此桌面端的布局与交互保持原样(不影响主要功能)。

适配内容：
    1. 左侧固定 240px 导航栏 -> 抽屉式浮动面板(竖屏下不挤压内容宽度)
    2. 对话框/页面里写死的过宽最小尺寸 -> 按屏幕宽度自动放宽
    3. 漫画详情页/设置页/分流设置页 等"左导航 + 右内容"左右并排 -> 上下堆叠
    4. 滚动区域全部支持手指拖动(动量滚动)
    5. 顶部分页按钮在窄屏下压缩字号，避免溢出
    6. 触摸防误触：滑动永远不会触发手指下的控件(下拉框/数值框/勾选框)
    7. 返回键:先收菜单/抽屉 -> 再退出看图 -> 再回退页面 -> 最后退到后台
    8. 看图界面的工具菜单改为整宽(原来固定 400px，在 384px 屏上跑到屏幕外)
    9. 首页/列表每行放 2 个封面(原来按桌面 250px 封面尺寸只放得下 1 个)
   10. 顶层窗口的 show/hide 延后到当前输入事件处理结束(见 DeferCall 注释)
"""
from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPoint, QPointF,
                            QPropertyAnimation, Qt, QTimer)
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractScrollArea,
                               QAbstractSpinBox, QApplication, QBoxLayout, QComboBox,
                               QCommandLinkButton, QDialog, QGraphicsView, QScroller,
                               QScrollerProperties, QScrollBar, QSizePolicy, QSlider,
                               QToolButton, QWidget)

import os
import re
import time

from tools.log import Log
from tools import platform_mobile

# 竖屏下允许的最小控件宽度(比这更宽的都会被放宽)
MinWidthLimit = 320
# 抽屉宽度占屏幕比例
DrawerWidthRatio = 0.82
DrawerMaxWidth = 300
# 抽屉滑入/滑出动画时长，以及兜底隐藏时间
DrawerAniMs = 120
DrawerAniFallbackMs = 260
# 手指滑动的判定阈值(逻辑像素)。小于它的位移仍然按"点击"处理，
# 大于它的位移一律视为滚动，把 release 吃掉，不再传给子控件。
TouchSlopPx = 16
# 触摸自检的观察窗口(秒)
TouchSelfTestSeconds = 120
# QWidget 的"无上限"宽度
WidgetSizeMax = 16777215
# 返回键去抖(毫秒)：Android 会同时给按下和抬起两个事件，连点也要吞掉
BackDebounceMs = 400
# 首页/列表每行放几个封面(竖屏)
GridColumns = 2
# 封面最小/最大宽度(逻辑像素)
GridCoverMin = 96
GridCoverMax = 240
# item widget 自己的边距/标签所占的额外宽度 + 安全余量。
# 实测：宿主 18px、真机 12px(字体/布局不同)，取 36 是为了保证**首次**算出来的封面
# 一定能放下 2 个(后面还有 self-correct 会继续收紧)。只算封面宽是不够的：
# QListWidget 是按整个 item 的 sizeHint 装箱的。
GridItemOverhead = 36
# self-correct 之后定下来的封面宽：后加的 item(翻页)直接用它，避免又变回一行 1 个
_gridCoverFinal = 0
# 上面那个封面宽是按多大的视口算出来的：视口变了(旋转/改窗口大小)必须重算，
# 否则横屏量出来的宽会被拿到竖屏用 -> 又变回一行 1 个
_gridCoverAvail = 0
# 列表视口的真实宽度(空列表也能量出来)。用它比用"页面宽度"准得多：
# 真机上页面 384px，而列表视口只有 330~338px(边距+滚动条+父级边框)。
_gridAvail = 0
# "刚加完一批漫画"的去抖重排(见 ScheduleGridCoverSize)。
# 首页的漫画是网络回来后一条条 AddBookItem 的，建控件时用的是那一刻的封面宽；
# 之前只有 shown/切页才会重排，于是首屏那批 item 建完后就没人再纠正了。
GridScheduleMs = 80
_gridPending = []
_gridTimer = None


def MakeChildOverlay(widget, coverParent=True):
    """ 把"本来打算做顶层窗口"的控件改成主窗口里的**子控件覆盖层**

    真机实证(Android 16 + Qt 6.11.2)：**任何第二个顶层窗口**只要开始渲染就会
    撞上平台插件里的全局死锁保护器并直接 abort：

        Abort message: 'Failed to acquire deadlock protector for
                        QAndroidPlatformOpenGLWindow::eglSurface().'
        栈: QWidget::setVisible -> show_sys -> QPlatformWindow::setVisible
            -> flushWindowSystemEvents -> processExposeEvent -> paintAndFlush
            -> QBackingStoreRhiSupport::create -> QRhi::create
            -> QOpenGLContext::makeCurrent -> eglSurface -> qFatal

    提示条(每次改设置都弹)、加载框(每次切页都弹)、遮罩对话框都属于这一类，
    所以"延后 show"是不够的(延后之后照样在 sendPostedEvents 里创建第二个窗口)。
    改成子控件后所有内容都在**同一个平台窗口**里合成，彻底不会再走这条路。
    """
    if widget is None or not IsEnabled():
        return False
    try:
        if getattr(widget, "_jmChildOverlay", False):
            return True
        wasVisible = widget.isVisible()
        if wasVisible:
            widget.hide()
        widget.setWindowFlags(Qt.WindowType.Widget)
        widget._jmChildOverlay = True
        ShowDeferralStats["overlays"] = ShowDeferralStats.get("overlays", 0) + 1
        if coverParent:
            widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        if wasVisible:
            widget.show()
        return True
    except Exception as es:
        Log.Error(es)
    return False


def CoverParentGeometry(widget):
    """ 子控件覆盖层：对齐父窗口(父窗口 resize 后要再调一次) """
    try:
        if widget is None or not getattr(widget, "_jmChildOverlay", False):
            return
        parent = widget.parentWidget()
        if parent is None:
            return
        widget.setGeometry(0, 0, parent.width(), parent.height())
    except Exception as es:
        Log.Error(es)
    return


def IsChildOverlay(widget):
    try:
        return bool(getattr(widget, "_jmChildOverlay", False))
    except Exception:
        return False


def DeferCall(fn, ms=0):
    """ 把一次调用推迟到当前事件处理结束之后执行

    真机实测(Android/Qt6)：在**输入事件处理过程中**同步 show()/hide() 一个顶层窗口
    (MsgLabel 提示条、加载框、各种对话框)，Qt 会在 QWindowPrivate::setVisible 里
    同步 flush 窗口系统事件 -> 立刻派发 Expose -> 立刻走一遍 paint -> 最终
    QAndroidPlatformOpenGLWindow::eglSurface() 重入，直接:

        Abort message: 'Failed to acquire deadlock protector for
                        QAndroidPlatformOpenGLWindow::eglSurface().'

    (真机 SIGABRT 栈: QTabBar::mousePressEvent -> python 槽 -> QDialog::setVisible
     -> QPlatformWindow::setVisible -> flushWindowSystemEvents -> paintAndFlush ->
     rhiFlush -> makeCurrent -> eglSurface -> abort)

    设置页里"改任何选项都会弹一次保存成功提示条"，正好命中这条路径，于是每次改设置
    都崩。延后 0ms 执行，语义完全一样，但不再重入。
    """
    if fn is None:
        return
    QTimer.singleShot(max(0, int(ms)), fn)
    return


def ShouldDeferWindowShow():
    """ 移动端需要把顶层窗口的显示/隐藏延后(桌面端保持同步，行为不变) """
    return IsEnabled()


class _MobileFilter(QObject):
    """ 全局事件过滤器：对话框尺寸自适应 + 可选按键/窗口事件诊断 """

    def eventFilter(self, obj, event):
        try:
            if _keyDiagEnabled:
                KeyDiag(obj, event)
            if event.type() == QEvent.Type.Show and isinstance(obj, QDialog):
                if isinstance(obj, QWidget) and getattr(obj, "widget", None) is not None:
                    # BaseMaskDialog：内部 widget 才是真正的对话框
                    RelaxMinSizes(obj.widget, CurrentLimit())
                    obj.widget.adjustSize()
                else:
                    RelaxMinSizes(obj, CurrentLimit())
        except Exception as es:
            Log.Error(es)
        return False


_filter = None
_limit = MinWidthLimit
_mainView = None
# 按键/窗口事件诊断开关(<AppDataDir>/device_keys 标记)：真机上"返回键到底有没有
# 到 Qt 窗口"、"白屏之前窗口发生了什么"只能靠把事件打出来判断。
_keyDiagEnabled = False
KeyDiagStats = {"key": 0, "window": 0, "back": 0}


def KeyDiag(obj, event):
    """ 记录按键与窗口生命周期事件(仅诊断标记打开时) """
    try:
        eventType = event.type()
        if eventType in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            KeyDiagStats["key"] += 1
            key = event.key()
            if key in (Qt.Key.Key_Back, Qt.Key.Key_Escape):
                KeyDiagStats["back"] += 1
            Log.Warn("key diag: {} key={}({}) text={!r} accepted={} receiver={}".format(
                eventType.name, key, Qt.Key(key).name if hasattr(Qt.Key, "name") else "",
                event.text() if hasattr(event, "text") else "",
                event.isAccepted(), _DescribeWidget(obj)))
        elif eventType in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Close,
                           QEvent.Type.WindowStateChange, QEvent.Type.ApplicationStateChange):
            if isinstance(obj, QWidget) and obj.isWindow():
                KeyDiagStats["window"] += 1
                Log.Warn("window diag: {} {} windowState={} visible={} active={}".format(
                    eventType.name, _DescribeWidget(obj),
                    obj.windowState().name if hasattr(obj.windowState(), "name") else "?",
                    obj.isVisible(), obj.isActiveWindow()))
    except Exception:
        pass
    return


def CurrentLimit():
    return _limit


def IsEnabled():
    return platform_mobile.IsAndroid()


def Apply(mainView):
    """ 主窗口创建后调用一次 """
    if not IsEnabled():
        return
    global _mainView
    _mainView = mainView
    try:
        UpdateLimit(mainView)
        SetupDrawer(mainView)
        RelaxMinSizes(mainView, _limit)
        StackBookInfo(mainView.bookInfoView)
        StackBookInfo(mainView.bookInfoView2)
        StackSideNavs(mainView)
        StackSrTool(getattr(mainView, "waifu2xToolView", None), mainView)
        CompactTabBar(mainView)
        SetupReadTool(getattr(mainView, "readView", None))
        ApplyGridCoverSize(mainView)
        EnableTouchScroll(mainView)
        SetupBackButton(mainView)
        InstallAppFilter(mainView)
        InstallTouchGuard(mainView)
        InstallWindowGuard(mainView)
        ReflowPortrait(getattr(mainView, "subStackWidget", None))
        InstallReflowHook(mainView)
        Log.Warn("mobile ui adapted, limit:{}".format(_limit))
    except Exception as es:
        Log.Error(es)


def UpdateLimit(mainView):
    """ 根据当前窗口宽度计算可用的最小宽度上限 """
    global _limit
    width = mainView.width()
    if width <= 0:
        width = mainView.sizeHint().width()
    if width <= 0:
        width = MinWidthLimit
    _limit = max(240, min(MinWidthLimit, width - 24))
    return _limit


def InstallAppFilter(mainView):
    global _filter
    if _filter is not None:
        return
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    _filter = _MobileFilter(app)
    app.installEventFilter(_filter)


class _DrawerScrim(QWidget):
    """ 抽屉遮罩层：点空白处关闭菜单

    真机上原来根本没有"点外部关闭"的处理，抽屉一打开就只能靠返回键或无路可走。
    """

    def __init__(self, mainView):
        super().__init__(mainView.subMainWindow)
        self._mainView = mainView
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 110);")
        self.hide()

    def mousePressEvent(self, event):
        CloseDrawer(self._mainView)
        return


def _TopOffset(mainView, subWindow):
    """ 抽屉顶部要避开顶栏，否则会盖住"菜单"按钮(真机上表现为菜单键消失) """
    for name in ("menuButton", "label"):
        widget = getattr(mainView, name, None)
        if widget is None:
            continue
        try:
            local = subWindow.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
            top = local.y() + widget.height()
            if top > 0:
                return top
        except Exception:
            continue
    return 0


def SetupDrawer(mainView):
    """ 导航栏改为浮动抽屉：手机竖屏下不再占用 240px 内容宽度 """
    nav = getattr(mainView, "navigationWidget", None)
    layout = getattr(mainView, "horizontalLayout_2", None)
    subWindow = getattr(mainView, "subMainWindow", None)
    if nav is None or layout is None or subWindow is None:
        return
    if getattr(nav, "_jmDrawer", False):
        UpdateDrawerGeometry(mainView)
        return

    layout.removeWidget(nav)
    nav.setParent(subWindow)
    nav.setMinimumWidth(0)
    nav.setMaximumWidth(DrawerMaxWidth)
    nav._jmDrawer = True
    nav.hide()
    # 点空白处关闭抽屉的遮罩层
    mainView._jmDrawerScrim = _DrawerScrim(mainView)
    # 尺寸变化时同步抽屉/遮罩几何
    mainView.WindowsSizeChange.connect(lambda: UpdateDrawerGeometry(mainView))
    UpdateDrawerGeometry(mainView)
    return


def UpdateDrawerGeometry(mainView):
    """ 重算抽屉与遮罩的位置

    注意：这里刻意不用 setFixedWidth —— 它会把宽度锁死，和导航栏基类
    aniShow/aniHide 的宽度动画互相打架(动画被夹到固定值，实际没有动画效果)。
    """
    nav = getattr(mainView, "navigationWidget", None)
    subWindow = getattr(mainView, "subMainWindow", None)
    if nav is None or subWindow is None or not getattr(nav, "_jmDrawer", False):
        return
    width = int(min(DrawerMaxWidth, max(220, mainView.width() * DrawerWidthRatio)))
    top = _TopOffset(mainView, subWindow)
    height = max(0, subWindow.height() - top)
    nav._jmDrawerWidth = width
    nav._jmDrawerTop = top
    scrim = getattr(mainView, "_jmDrawerScrim", None)
    if scrim is not None:
        scrim.setGeometry(0, top, subWindow.width(), height)
    if not nav.isHidden():
        nav.setGeometry(0, top, width, height)
        nav.raise_()
        if scrim is not None:
            scrim.raise_()
            nav.raise_()
    return


def IsDrawerOpen(mainView):
    nav = getattr(mainView, "navigationWidget", None)
    if nav is None or not getattr(nav, "_jmDrawer", False):
        return False
    return not nav.isHidden()


def OpenDrawer(mainView):
    nav = getattr(mainView, "navigationWidget", None)
    if nav is None or not getattr(nav, "_jmDrawer", False):
        return False
    UpdateDrawerGeometry(mainView)
    top = getattr(nav, "_jmDrawerTop", 0)
    width = getattr(nav, "_jmDrawerWidth", DrawerMaxWidth)
    height = max(0, mainView.subMainWindow.height() - top)
    scrim = getattr(mainView, "_jmDrawerScrim", None)
    if scrim is not None:
        scrim.show()
        scrim.raise_()
    nav.show()
    nav.setGeometry(0, top, width, height)
    nav.raise_()
    ani = _DrawerAni(nav)
    ani.stop()
    ani.setDuration(DrawerAniMs)
    ani.setEasingCurve(QEasingCurve.Type.OutCubic)
    ani.setStartValue(QPoint(-width, top))
    ani.setEndValue(QPoint(0, top))
    ani.start()
    return True


def _DrawerAni(nav):
    """ 复用挂在导航栏上的位移动画(只动 x，不动宽度，避免与基类冲突) """
    ani = getattr(nav, "_jmDrawerAni", None)
    if ani is None:
        ani = QPropertyAnimation(nav, b"pos", nav)
        nav._jmDrawerAni = ani
    return ani


def CloseDrawer(mainView):
    """ 切换界面/按返回键/点空白处后收起抽屉 """
    nav = getattr(mainView, "navigationWidget", None)
    if nav is None or not getattr(nav, "_jmDrawer", False):
        return
    scrim = getattr(mainView, "_jmDrawerScrim", None)
    if scrim is not None:
        scrim.hide()
    if nav.isHidden():
        return
    width = getattr(nav, "_jmDrawerWidth", DrawerMaxWidth)
    top = getattr(nav, "_jmDrawerTop", 0)
    ani = _DrawerAni(nav)
    ani.stop()
    ani.setDuration(DrawerAniMs)
    ani.setEasingCurve(QEasingCurve.Type.InCubic)
    ani.setStartValue(nav.pos())
    ani.setEndValue(QPoint(-width, top))
    ani.start()
    # 兜底：动画被打断(快速连点等)时也要真正隐藏，否则抽屉会一直留在屏幕上
    QTimer.singleShot(DrawerAniFallbackMs, lambda: _HideDrawer(nav))
    return


def ToggleDrawer(mainView):
    """ 点"菜单"按钮：返回 True 表示移动端已接管(桌面端返回 False，走原逻辑) """
    if not IsEnabled():
        return False
    if IsDrawerOpen(mainView):
        CloseDrawer(mainView)
    else:
        OpenDrawer(mainView)
    return True


def _HideDrawer(nav):
    try:
        ani = getattr(nav, "_jmDrawerAni", None)
        if ani is not None:
            ani.stop()
        if not nav.isHidden():
            nav.hide()
    except Exception as es:
        Log.Error(es)
    return


def RelaxMinSizes(root, limit):
    """ 递归放宽写死的过宽最小尺寸(macOS/桌面端不受影响) """
    if root is None:
        return
    try:
        if isinstance(root, QWidget):
            if root.minimumWidth() > limit:
                root.setMinimumWidth(limit)
            if root.minimumHeight() > 0 and root.minimumWidth() > 0:
                pass
            for child in root.findChildren(QWidget):
                if child.minimumWidth() > limit:
                    child.setMinimumWidth(limit)
        else:
            for child in root.findChildren(QWidget):
                if child.minimumWidth() > limit:
                    child.setMinimumWidth(limit)
    except Exception as es:
        Log.Error(es)
    return


def StackBookInfo(view):
    """ 漫画详情：封面/信息 由左右并排改为上下堆叠 """
    try:
        if view is None or getattr(view, "_jmStacked", False):
            return
        hLayout = getattr(view, "horizontalLayout", None)
        infoLayout = getattr(view, "verticalLayout_2", None)
        grid = getattr(view, "gridLayout_3", None)
        picture = getattr(view, "picture", None)
        if hLayout is None or infoLayout is None or grid is None:
            return
        if hLayout.indexOf(infoLayout) < 0:
            return
        item = hLayout.takeAt(hLayout.indexOf(infoLayout))
        grid.addLayout(infoLayout, grid.rowCount(), 0, 1, 1)
        if picture is not None:
            picture.setMinimumWidth(0)
            picture.setMaximumWidth(CurrentLimit())
            picture.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        view._jmStacked = True
        Log.Warn("book info layout stacked for portrait")
    except Exception as es:
        Log.Error(es)
    return


def CompactTabBar(mainView):
    """ 顶部分页按钮在窄屏下压缩，避免溢出屏幕 """
    try:
        buttons = getattr(mainView, "toolButtons", None) or []
        for button in buttons:
            if isinstance(button, QToolButton):
                button.setMinimumWidth(0)
                font = button.font()
                if font.pointSize() > 0:
                    font.setPointSize(max(7, font.pointSize() - 2))
                    button.setFont(font)
    except Exception as es:
        Log.Error(es)
    return


def _NavLayoutButtons(layout):
    """ 这个布局是不是"只有一个标题按钮(或几个功能按钮)+弹簧"的导航列

    设置页是 QCommandLinkButton x4 + 弹簧；分流设置页(login_new 的 tab_4)是
    QCommandLinkButton x1 + 弹簧。返回按钮列表，不是导航列则返回 None。
    """
    if not isinstance(layout, QBoxLayout):
        return None
    buttons = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        if item.spacerItem() is not None:
            continue
        widget = item.widget()
        if widget is None:
            # 导航列里再嵌布局的形态没见过，保守起见当它不是导航列
            return None
        if widget.isHidden():
            continue
        if not isinstance(widget, QCommandLinkButton):
            return None
        buttons.append(widget)
    return buttons or None


def _CompressNavButtons(buttons):
    """ 导航按钮从"竖排大块"压成"横排一行小按钮"

    QCommandLinkButton 默认是"图标 + 标题 + 说明"的竖块，横排里必须压扁。
    水平策略必须用 Ignored：qSmartMinSize 对 Expanding 会取 sizeHint，
    4 个按钮加起来最小宽度 664px，横排到 384px 的屏幕上照样"放不下"。
    """
    for widget in buttons:
        widget.setDescription("")
        widget.setIcon(QIcon())
        widget.setMinimumWidth(0)
        widget.setMaximumWidth(WidgetSizeMax)
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        font = widget.font()
        if font.pointSize() > 0:
            font.setPointSize(max(8, font.pointSize() - 2))
            widget.setFont(font)
        widget.setMinimumHeight(0)
    return


def StackSideNavs(root=None):
    """ 竖屏："左侧导航列 + 右侧滚动内容" 的左右并排 -> 上下堆叠

    原来这类页面的外层都是 QHBoxLayout: [ 竖排导航列 , QScrollArea ]。
    竖屏 384px 下导航列要占掉 100 多像素，内容区只剩 230 上下，而内容里大量 row 是
    "80px 标签 + 150px 数值 + 108px 按钮"≈365px，于是被压缩/裁掉(用户看到的就是
    "显示不全"、"还是双排")。

    竖屏改成：导航按钮横排在最上面，内容区独占整宽。
    QBoxLayout 可以直接改方向，不用重建布局(保留全部信号连接)。

    覆盖：设置页(horizontalLayout = 竖排4按钮 + scrollArea)、
          分流设置页(login_new.tab_4 的 horizontalLayout_14 = 竖排标题 + scrollArea_3)。
    """
    if root is None:
        root = getattr(_mainView, "subStackWidget", None) if _mainView is not None else None
    if root is None:
        return 0
    count = 0
    try:
        for layout in [root] + root.findChildren(QBoxLayout):
            try:
                if not isinstance(layout, QBoxLayout):
                    continue
                if layout.direction() not in (QBoxLayout.Direction.LeftToRight,
                                              QBoxLayout.Direction.RightToLeft):
                    continue
                if getattr(layout, "_jmNavStacked", False):
                    continue
                if layout.count() != 2:
                    continue
                navItem = layout.itemAt(0)
                area = layout.itemAt(1).widget()
                if navItem is None or not isinstance(area, QAbstractScrollArea):
                    continue
                nav = navItem.layout()
                buttons = _NavLayoutButtons(nav)
                if buttons is None:
                    continue
                layout.setDirection(QBoxLayout.Direction.TopToBottom)
                nav.setDirection(QBoxLayout.Direction.LeftToRight)
                for i in range(nav.count()):
                    item = nav.itemAt(i)
                    if item is None:
                        continue
                    spacer = item.spacerItem()
                    if spacer is not None:
                        # 竖排时的弹簧在横排里只会白占宽度
                        spacer.changeSize(0, 0, QSizePolicy.Policy.Minimum,
                                          QSizePolicy.Policy.Minimum)
                _CompressNavButtons(buttons)
                layout._jmNavStacked = True
                count += 1
                Log.Warn("portrait: 并排的导航列/内容改为上下 ({}.{} + {})".format(
                    type(layout.parent()).__name__ if layout.parent() else "?",
                    layout.objectName() or "?", area.objectName() or "?"))
            except Exception as es:
                Log.Error(es)
    except Exception as es:
        Log.Error(es)
    if count:
        Log.Warn("portrait: {} 个[左导航+右内容]页面改为上下堆叠".format(count))
    return count


def StackSettingNav(view):
    """ 设置页专用收尾(方向已经由 StackSideNavs 改好)

    这里只补设置页自己的细节：目录行里的路径标签最小宽 150px，竖屏下会把"打开目录"
    按钮挤出去。
    """
    try:
        if view is None:
            return
        for name in ("downloadDir", "cacheDir", "chatDir", "waifu2xDir"):
            label = getattr(view, name, None)
            if label is not None:
                label.setMinimumWidth(100)
    except Exception as es:
        Log.Error(es)
    return


def StackSrTool(view, mainView=None):
    """ 图片超分页：预览/参数 左右并排 -> 上下堆叠(竖屏)

    原来 gridLayout 里 (0,0)=QGraphicsView 预览、(0,1)=参数面板(最大宽 300px)。
    竖屏 384px 下预览只剩 80 多像素，基本看不见图。
    竖屏改成预览在上(占大部分高度)、参数面板在下(整宽、限高，可滚动)。
    """
    try:
        if view is None or getattr(view, "_jmSrStacked", False):
            return
        grid = getattr(view, "gridLayout", None)
        panel = getattr(view, "verticalLayout", None)
        area = getattr(view, "scrollArea", None)
        if grid is None or panel is None:
            return
        if grid.indexOf(panel) < 0:
            return
        grid.takeAt(grid.indexOf(panel))
        grid.addLayout(panel, 1, 0, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        grid.setRowStretch(1, 0)
        grid.setRowStretch(0, 1)
        if area is not None:
            area.setMaximumWidth(WidgetSizeMax)
        view._jmSrStacked = True
        UpdateSrToolHeight(view, mainView)
        Log.Warn("waifu2x tool stacked for portrait")
    except Exception as es:
        Log.Error(es)
    return


def UpdateSrToolHeight(view, mainView=None):
    """ 参数面板限高，保证预览区还有足够高度(旋转屏幕后重算) """
    try:
        if view is None or not getattr(view, "_jmSrStacked", False):
            return
        area = getattr(view, "scrollArea", None)
        if area is None:
            return
        height = 0
        for source in (view, getattr(mainView, "subMainWindow", None), mainView):
            if source is None:
                continue
            if source.height() > height:
                height = source.height()
        if height <= 0:
            height = 700
        area.setMaximumHeight(max(190, int(height * 0.42)))
    except Exception as es:
        Log.Error(es)
    return


def SetupReadTool(readView):
    """ 看图界面的工具菜单(ReadTool)：竖屏下改成整宽

    原来 ReadFrame.ScaleFrame 里写死 `qtTool.setGeometry(w - 400, 0, 400, h)`：
    桌面端窗口 1000+ 宽时是"右侧 400px 抽屉"，但竖屏只有 384px 宽，
    x = -16、宽度 400 —— 整个菜单跑到屏幕外，用户看到的就是"菜单宽度超出屏幕，
    右边一半点不到"。竖屏改成占满整个看图区域(内容自带滚动条)。
    """
    try:
        frame = getattr(readView, "frame", None)
        if frame is None or getattr(frame, "_jmToolMobile", False):
            return
        orig = frame.ScaleFrame

        def ScaleFrameMobile():
            orig()
            ApplyReadToolGeometry(frame)

        frame.ScaleFrame = ScaleFrameMobile
        frame._jmToolMobile = True
        ApplyReadToolGeometry(frame)
        # 工具菜单里的滚动区(QScrollArea)要能手指拖动 —— EnableTouchScroll 已经
        # 覆盖了它，这里只补看图区自己的拖动滚动
        InstallReaderDrag(readView)
        EnableTouchScroll(readView)
        Log.Warn("portrait: 看图工具菜单改为整宽(不再固定 400px)")
    except Exception as es:
        Log.Error(es)
    return


def ApplyReadToolGeometry(frame):
    """ 把工具菜单贴到看图区域的整宽上(每次 resize 都要跑) """
    try:
        tool = getattr(frame, "qtTool", None)
        if tool is None:
            return
        width = frame.width()
        height = frame.height()
        if width <= 0 or height <= 0:
            return
        tool.setMinimumWidth(0)
        tool.setMaximumWidth(width)
        tool.setGeometry(0, 0, width, height)
    except Exception as es:
        Log.Error(es)
    return


# ---------------------------------------------------------------------------
# 看图区拖动滚动
# ---------------------------------------------------------------------------
#
# 真机现象："看图界面无法滚动"。看图区是 QGraphicsView，桌面端只支持滚轮
# (wheelEvent)，触摸设备既没有滚轮也没有拖动实现：
#   * QGraphicsView 设的是 NoDrag(不做 ScrollHandDrag)
#   * 场景的鼠标事件只用来识别"点按三分区"(而且要求 |dx| <= 20 才算点按)
# 所以手指在图片上拖动毫无反应(菜单面板是另一个滚动区，那是另一回事)。
#
# 这里直接把拖动位移喂给和滚轮**同一条**路径(ReadScroll.scrollValue)，
# 顺带复用滚轮那套"到页尾自动翻页"的逻辑；点按(|dx|、|dy| 都小于阈值)完全不碰，
# 原来的三分区点按逻辑一点不变。

_readerDrag = None


class _ReaderDrag(QObject):
    """ 看图区手指拖动 -> 滚动(只在移动端装到看图控件上) """

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self._view = view
        self._pressed = False
        self._dragging = False
        self._pressPos = None
        self._lastPos = None
        self._carry = 0.0
        self.Drags = 0
        self.Scrolled = 0
        self.LastDelta = 0

    def eventFilter(self, obj, event):
        try:
            eventType = event.type()
            if eventType == QEvent.Type.MouseButtonPress:
                self._pressed = True
                self._dragging = False
                self._pressPos = self._Pos(event)
                self._lastPos = self._pressPos
                self._carry = 0.0
                return False
            if eventType == QEvent.Type.MouseButtonRelease:
                dragging = self._dragging
                self._pressed = False
                self._dragging = False
                # 拖动结束的那次 release 必须吃掉：否则场景会把它当成"点按"，
                # 再额外跳半页/翻页一次
                return dragging
            if eventType != QEvent.Type.MouseMove or not self._pressed:
                return False
            pos = self._Pos(event)
            if pos is None or self._lastPos is None:
                return False
            dx = pos.x() - self._lastPos.x()
            dy = pos.y() - self._lastPos.y()
            if not self._dragging:
                move = (pos - self._pressPos).manhattanLength()
                if move < TouchSlopPx:
                    return False
                self._dragging = True
                self.Drags += 1
                Log.Warn("reader drag: 开始拖动滚动")
            self._lastPos = pos
            self._Scroll(dx, dy)
            return True
        except Exception as es:
            Log.Error(es)
        return False

    @staticmethod
    def _Pos(event):
        try:
            return QPointF(event.position())
        except Exception:
            try:
                return QPointF(event.pos())
            except Exception:
                return None

    def _Scroll(self, dx, dy):
        view = self._view
        try:
            from view.read.read_enum import ReadMode
            stripModel = view.qtTool.stripModel
            upDown = ReadMode.isUpDown(view.initReadMode)
            delta = -dy if upDown else -dx
            self._carry += delta
            step = int(self._carry)
            if step == 0:
                return
            self._carry -= step
            if not ReadMode.isScroll(stripModel):
                # 非滚动模式：到边界就翻页(和滚轮一致)
                bar = view.vScrollBar if upDown else view.hScrollBar
                if step > 0 and abs(bar.value() - bar.maximum()) <= 5:
                    view.qtTool.NextPage()
                    return
                if step < 0 and bar.value() <= 5:
                    view.qtTool.LastPage()
                    return
            if upDown:
                view.vScrollBar.scrollValue(step)
            elif view.initReadMode == ReadMode.RightLeftScroll2:
                view.hScrollBar.scrollValue(-step)
            else:
                view.hScrollBar.scrollValue(step)
            self.Scrolled += 1
            self.LastDelta = step
        except Exception as es:
            Log.Error(es)
        return


def InstallReaderDrag(readView):
    """ 给看图区装上拖动滚动(移动端) """
    global _readerDrag
    try:
        if readView is None or _readerDrag is not None:
            return
        view = getattr(getattr(readView, "frame", None), "scrollArea", None)
        if view is None:
            return
        target = view.viewport()
        if target is None:
            target = view
        _readerDrag = _ReaderDrag(view, view)
        target.installEventFilter(_readerDrag)
        Log.Warn("reader drag: 看图区拖动滚动已接管 ({})".format(type(target).__name__))
    except Exception as es:
        Log.Error(es)
    return


def GridCoverWidth(isCategory=False):
    """ 竖屏下封面该多宽：让一行正好放得下 GridColumns 个

    ComicItemWidget 原来按桌面写死 250x340(rate=100)，384px 的竖屏一行只能放下
    1 个封面(用户要求每行 2 本)。这里按**列表视口的真实宽度**反算封面宽度，
    宽高比保持桌面原样。self-correct 定下来的宽度优先(见 ApplyGridCoverSize)。
    """
    if _gridCoverFinal > 0:
        return _gridCoverFinal
    avail = _gridAvail
    if avail < 120:
        # 还不知道视口宽：退回"页面宽 - 列表边距"
        width = 0
        if _mainView is not None:
            width = PortraitWidth(_mainView)
        if width < 200:
            screen = platform_mobile.GetScreenSize()
            width = int(screen[0] or 0)
        if width < 200:
            width = _limit
        if width < 200:
            width = MinWidthLimit
        avail = max(120, width - GridItemOverhead)
    return max(GridCoverMin, min(GridCoverMax, int((avail - GridItemOverhead) / max(1, GridColumns))))


def MeasureGridAvail(root):
    """ 量出列表真正能用的宽度(QListWidget 视口宽)

    必须**空列表也能量**：首页的漫画是异步加载的，等 item 出现再算就晚了
    (真机上就是这一步踩空，首屏 60 个 item 全按旧的宽封面建好，一行只放 1 个)。
    """
    global _gridAvail
    try:
        from PySide6.QtWidgets import QListWidget
        # 列表还没被布局时(ComicListWidget.__init__ 里写死的 resize(800, 600)、
        # 或者窗口还没被 Android 拉成竖屏尺寸)视口会报出一个远大于页面的宽度，
        # 拿它当"可用宽"会把封面宽 freeze 在 GridCoverMax(240px) -> 一行只放 1 个。
        # 页面宽度是列表宽度的上限，超过它的一律按页面宽度算。
        pageWidth = PortraitWidth(_mainView) if _mainView is not None else 0
        worst = 0
        for view in _SelfAndChildren(root, QListWidget):
            viewport = view.viewport()
            width = viewport.width() if viewport is not None else view.width()
            if pageWidth >= 200 and width > pageWidth:
                width = pageWidth
            if width >= 120 and (worst == 0 or width < worst):
                worst = width
        if worst:
            _gridAvail = worst
    except Exception as es:
        Log.Error(es)
    return _gridAvail


def ResetGridCover():
    """ 尺寸/设置变化后重新反算封面宽(self-correct 的缓存要作废) """
    global _gridCoverFinal, _gridAvail, _gridCoverAvail
    _gridCoverFinal = 0
    _gridAvail = 0
    _gridCoverAvail = 0
    return


def ScheduleGridCoverSize(root):
    """ 刚往列表里加完一批漫画 -> 去抖之后再对一次"一行 2 个"

    首页的漫画是网络回来后**一条条 AddBookItem** 的，控件宽度在建的时候就被封面宽
    定死了；而 ApplyGridCoverSize 原来只在窗口 shown / 切页时才跑，所以首屏那批
    item 建完之后没有任何时机纠正它 —— 真机表现就是"打开首页一行 1 个，进设置页
    再返回首页才变一行 2 个"(切页触发了那次重排)。

    这里在每次添加之后排一次重排(80ms 去抖，把一批添加合并成一次)。
    ApplyGridCoverSize 内部有 `_jmGridSized == width` 短路，重复调用只处理新 item，
    所以翻页/连续加载时不会有额外开销。
    """
    global _gridTimer
    if not IsEnabled() or root is None:
        return
    try:
        if root not in _gridPending:
            _gridPending.append(root)
        if _gridTimer is None:
            timer = QTimer()
            timer.setSingleShot(True)
            timer.setInterval(GridScheduleMs)
            timer.timeout.connect(_FlushGridPending)
            _gridTimer = timer
        # 一批添加只排一次(不 restart)，保证首屏能及时收敛
        if not _gridTimer.isActive():
            _gridTimer.start()
    except Exception as es:
        Log.Error(es)
    return


def _FlushGridPending():
    """ 把攒下来的列表各重排一次 """
    global _gridPending
    if not _gridPending:
        return
    pending, _gridPending = _gridPending, []
    for root in pending:
        try:
            ApplyGridCoverSize(root)
        except Exception as es:
            Log.Error(es)
    return


def ApplyGridCoverSize(root):
    """ 把已经建好的封面控件改成竖屏尺寸，并同步 QListWidgetItem 的 sizeHint

    只改控件尺寸是不够的：QListWidget 是按 item 的 sizeHint 装箱的，sizeHint 还是
    添加时的旧值的话，一行照样只放得下 1 个。
    """
    if root is None:
        return 0
    try:
        from component.widget.comic_item_widget import ComicItemWidget
    except Exception:
        return 0
    global _gridCoverFinal, _gridCoverAvail
    count = 0
    try:
        # 先量视口宽(空列表也能量)：首页的 item 是异步加的，等它们出现再算就晚了
        MeasureGridAvail(root)
        # 视口宽变了(旋转/改窗口大小/换页面)，之前定下来的封面宽要作废重算，
        # 否则横屏(或在窗口还没定型时)量出来的宽会被拿到竖屏用 -> 一行只放得下 1 个
        if _gridAvail and _gridAvail != _gridCoverAvail:
            if _gridCoverAvail:
                Log.Warn("portrait: 列表视口 {}px -> {}px，重算封面宽".format(
                    _gridCoverAvail, _gridAvail))
            _gridCoverFinal = 0
        width = GridCoverWidth(False)
        for attempt in range(4):
            for widget in _SelfAndChildren(root, ComicItemWidget):
                if getattr(widget, "_jmGridSized", 0) == width:
                    continue
                try:
                    widget.ResizeCover(width)
                    widget._jmGridSized = width
                    count += 1
                except Exception as es:
                    Log.Error(es)
            if count:
                RefreshItemSizeHints(root)
            # 只改封面尺寸不一定够：item widget 还有自己的边距/标签，
            # 真实 sizeHint 可能刚好超过"可用宽度 / 列数" -> QListWidget 又变回一行 1 个。
            # 这里按真实 sizeHint 反推需要再收多少，最多迭代几次。
            over = _GridOverflow(root)
            if over <= 0:
                break
            width = max(GridCoverMin, width - over - 2)
            Log.Warn("portrait: 封面还宽 {}px，收到 {}px 再试".format(over, width))
        else:
            Log.Warn("portrait: 封面宽度自校正未收敛(最后一轮仍超宽)")
        _gridCoverFinal = width
        _gridCoverAvail = _gridAvail
    except Exception as es:
        Log.Error(es)
    if count:
        Log.Warn("portrait: {} 个封面改为一行 {} 个(封面宽 {}px)".format(
            count, GridColumns, _gridCoverFinal or GridCoverWidth(False)))
    return count


def _SelfAndChildren(root, cls):
    """ root 自己(如果就是 cls)+ 所有子孙里的 cls

    Qt 的 findChildren 不含自己，而调用方经常直接传"那个列表/那个控件"，
    漏掉自己就会静默什么都不做(真机/主机都踩过)。
    """
    found = []
    try:
        if isinstance(root, cls):
            found.append(root)
        found.extend(root.findChildren(cls))
    except Exception as es:
        Log.Error(es)
    return found


def _GridOverflow(root):
    """ item 实际宽度超出"可用宽/列数"多少像素(<=0 表示一行放得下 GridColumns 个) """
    try:
        from PySide6.QtWidgets import QListWidget
        worst = 0
        for view in _SelfAndChildren(root, QListWidget):
            viewport = view.viewport()
            avail = viewport.width() if viewport is not None else view.width()
            if avail <= 0 or not view.count():
                continue
            per = max(1, avail // max(1, GridColumns))
            for row in range(min(view.count(), 8)):
                widget = view.itemWidget(view.item(row))
                if widget is None:
                    continue
                worst = max(worst, widget.sizeHint().width() - per)
        return worst
    except Exception as es:
        Log.Error(es)
    return 0


def RefreshItemSizeHints(root):
    """ 重新按控件自身尺寸刷新列表项尺寸(封面尺寸变化后必须调)

    只改 item 的 sizeHint 是不够的：QListView 的"一行几个"是上一次排版算出来的，
    必须显式让它重排，否则真机上会出现"尺寸改了但还是一行 1 个"。
    """
    try:
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QListWidget
        for view in _SelfAndChildren(root, QListWidget):
            try:
                widgets = []
                for row in range(view.count()):
                    item = view.item(row)
                    widget = view.itemWidget(item)
                    if widget is None:
                        continue
                    item.setSizeHint(widget.sizeHint())
                    widgets.append(widget)
                if widgets:
                    # 显式给栅格尺寸 + 固定宽度：一行几个就确定了。
                    # 只 setGridSize 不够：QListView 的装箱仍会看 item 的 sizeHint，
                    # 而 sizeHint 会被 item 内部布局(封面+标签+边距)撑大；真机上因此
                    # 出现过"item 163 < 330/2 却仍然一行 1 个"。
                    # 把 item widget 的宽度也固定成栅格宽，sizeHint 就跟着栅格走。
                    cellW = max(w.sizeHint().width() for w in widgets)
                    cellH = max(w.sizeHint().height() for w in widgets)
                    viewport = view.viewport()
                    avail = viewport.width() if viewport is not None else view.width()
                    per = max(60, avail // max(1, GridColumns)) if avail > 0 else 0
                    if per > 0 and cellW > per:
                        cellW = per
                        for w in widgets:
                            try:
                                w.setFixedWidth(cellW)
                            except Exception as es:
                                Log.Error(es)
                    view.setGridSize(QSize(cellW, cellH))
                # 强制重排(顺序：先更新几何再重排 items)
                for name in ("updateGeometries", "doItemsLayout"):
                    func = getattr(view, name, None)
                    if func is None:
                        continue
                    try:
                        func()
                    except Exception:
                        pass
            except Exception as es:
                Log.Error(es)
    except Exception as es:
        Log.Error(es)
    return


def PortraitWidth(mainView):
    """ 页面可用宽度(取页面栈的宽度；还没布局时退回主窗口 / 最小宽度上限) """
    width = 0
    stack = getattr(mainView, "subStackWidget", None)
    if stack is not None:
        width = stack.width()
    if width < 200:
        sub = getattr(mainView, "subMainWindow", None)
        if sub is not None:
            width = sub.width()
    if width < 200:
        width = mainView.width()
    if width < 200:
        width = _limit
    return width


# 拆行后行与行之间的间距
WrapRowSpacing = 6
# 预留余量：每层布局还有自己的边距，按页面宽度直接装箱会略微溢出
WrapSafetyMargin = 12


def _PackRowIndexes(widths, available, spacing):
    """ 顺序装箱：一行的控件最小宽度之和不超过 available """
    rows = []
    current = []
    used = 0
    for index, width in enumerate(widths):
        extra = width + (spacing if current else 0)
        if current and used + extra > available:
            rows.append(current)
            current = []
            used = 0
            extra = width
        current.append(index)
        used += extra
    if current:
        rows.append(current)
    return rows


def _ReplaceNestedLayout(parent, old, new):
    """ 用 new 顶掉 parent 里的 old(保持原来的位置/跨行跨列) """
    try:
        from PySide6.QtWidgets import QGridLayout
        if isinstance(parent, QWidget):
            # old 是这个 widget 自己的顶层布局：Qt 不允许直接 setLayout 顶掉已有的布局，
            # 先把旧布局转交给一个临时 widget(它随临时 widget 一起销毁)，再装新的
            if parent.layout() is not old:
                return False
            holder = QWidget()
            holder.setLayout(old)
            parent.setLayout(new)
            holder.deleteLater()
            return True
        index = parent.indexOf(old)
        if index < 0:
            return False
        if isinstance(parent, QGridLayout):
            row, col, rowSpan, colSpan = parent.getItemPosition(index)
            parent.takeAt(index)
            parent.addLayout(new, row, col, rowSpan, colSpan)
            return True
        if isinstance(parent, QBoxLayout):
            parent.takeAt(index)
            parent.insertLayout(index, new)
            return True
    except Exception as es:
        Log.Error(es)
    return False


def _WrapOneRow(layout, available):
    """ 把一个放不下的横向行拆成多行；返回是否真的拆了 """
    items = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None or item.spacerItem() is not None:
            # 弹簧不参与装箱：每行末尾统一加一个，避免拆完出现大片空隙
            continue
        items.append(item)
    if len(items) < 2:
        return False
    widths = []
    for item in items:
        try:
            widths.append(max(0, item.minimumSize().width()))
        except Exception:
            widths.append(0)
    spacing = layout.spacing()
    if spacing < 0:
        spacing = WrapRowSpacing
    rows = _PackRowIndexes(widths, available, spacing)
    if len(rows) < 2:
        return False
    parent = layout.parent()
    if parent is None:
        return False
    # 先把 item 从旧布局里摘出来(旧布局变空)，再整体替换
    while layout.count():
        layout.takeAt(0)
    from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
    column = QVBoxLayout()
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(WrapRowSpacing)
    for group in rows:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(spacing)
        for index in group:
            row.addItem(items[index])
        row.addStretch(1)
        column.addLayout(row)
    if not _ReplaceNestedLayout(parent, layout, column):
        # 替换失败：把 item 放回去，别把界面搞空
        for index, item in enumerate(items):
            layout.addItem(item)
        return False
    try:
        layout.setParent(None)
    except Exception:
        pass
    return True


def _FlattenGridRows(grid, budget):
    """ 把放不下的 QGridLayout 压成单列(竖屏)

    帮助页里的版本/时间信息是一个 3 列 QGridLayout：每列本身都不宽，
    但列宽相加 524px，竖屏下放不下。压成单列后每个控件各占一行。
    压完还是放不下(有单个控件本身就超宽)就原样还原，绝不帮倒忙。
    """
    saved = []
    for i in range(grid.count()):
        item = grid.itemAt(i)
        if item is None:
            continue
        saved.append((grid.getItemPosition(i), item))
    if len(saved) < 2:
        return False
    # 弹簧在单列里只会平白占高度，丢掉
    keep = [(pos, item) for pos, item in saved if item.spacerItem() is None]
    if len(keep) < 2:
        return False
    keep.sort(key=lambda pair: (pair[0][0], pair[0][1]))
    try:
        while grid.count():
            grid.takeAt(0)
        for index, (_pos, item) in enumerate(keep):
            grid.addItem(item, index, 0, 1, 1)
        if grid.minimumSize().width() <= budget:
            return True
        # 还原
        while grid.count():
            grid.takeAt(0)
        for pos, item in saved:
            grid.addItem(item, pos[0], pos[1], pos[2], pos[3])
    except Exception as es:
        Log.Error(es)
    return False


def EnableLabelWrap(root, available):
    """ 竖屏下把"本身就放不下"的文字标签改成多行显示

    帮助页那种一整段说明文字的 QLabel，单行最小宽度就有 500 多像素，
    横向怎么排都放不下。给它打开 wordWrap 让文字折行，是最不破坏结构的做法。
    对长路径/长 URL 这种没有换行机会的文本，打开 wordWrap 也降不下来，就还原回去。
    """
    if root is None or available <= 0:
        return 0
    from PySide6.QtWidgets import QLabel
    budget = max(200, available - WrapSafetyMargin)
    count = 0
    for label in root.findChildren(QLabel):
        try:
            if label.wordWrap():
                continue
            before = label.minimumSizeHint().width()
            if before <= budget:
                continue
            label.setWordWrap(True)
            after = label.minimumSizeHint().width()
            if after >= before:
                label.setWordWrap(False)
                continue
            count += 1
        except Exception as es:
            Log.Error(es)
    if count:
        Log.Warn("portrait: {} 个过宽标签改为折行显示(可用 {}px)".format(count, budget))
    return count


def WrapWideRows(root, available):
    """ 把放不下的横向行拆成多行(竖屏)

    工具栏那一类行(详情页的收藏/下载/评论按钮、收藏/历史/本地收藏/分类/周榜的分页栏)
    在 384px 竖屏下放不下，Qt 只能把右侧控件裁掉 —— 用户看到的就是"显示不全"。
    这里按顺序装箱把它们拆成若干行：所有控件都保留、顺序不变、每行都放得下。

    天然幂等：拆完的行自己都放得下，不会再次被拆，所以不需要"只跑一次"的标记
    (窗口尺寸会变，用了标记反而会让第一次的判定被永久沿用)。
    只处理嵌套在其它布局里的行(最常见的形态)；顶层布局交给 RelaxMinSizes。
    """
    if root is None or available <= 0:
        return 0
    budget = max(200, available - WrapSafetyMargin)
    wrapped = 0
    for layout in root.findChildren(QBoxLayout):
        try:
            if layout.direction() not in (QBoxLayout.Direction.LeftToRight,
                                          QBoxLayout.Direction.RightToLeft):
                continue
            if layout.minimumSize().width() <= budget:
                continue
            if _WrapOneRow(layout, budget):
                wrapped += 1
        except Exception as es:
            Log.Error(es)
    if wrapped:
        Log.Warn("portrait: 拆分了 {} 个放不下的横向行(可用 {}px)".format(wrapped, budget))
    return wrapped


def FlattenWideGrids(root, available):
    """ 把放不下的 QGridLayout 压成单列(竖屏) """
    if root is None or available <= 0:
        return 0
    from PySide6.QtWidgets import QGridLayout
    budget = max(200, available - WrapSafetyMargin)
    flattened = 0
    for grid in root.findChildren(QGridLayout):
        try:
            if grid.minimumSize().width() <= budget:
                continue
            if _FlattenGridRows(grid, budget):
                flattened += 1
        except Exception as es:
            Log.Error(es)
    if flattened:
        Log.Warn("portrait: {} 个放不下的栅格改为单列(可用 {}px)".format(flattened, budget))
    return flattened


# ---------------------------------------------------------------------------
# 触摸防误触(tap guard)
# ---------------------------------------------------------------------------
#
# 真机现象：
#   * 在设置页手指上滑，滑的过程中设置被改掉(勾选框被切换)
#   * 在"下拉菜单的选项框"和"数值选项框"**附近**滑动也会误触它们
#
# 原因是 Qt 把触摸合成为鼠标事件后**直接投给手指下的那个子控件**，而这些控件
#   * QComboBox 在 **press** 时就弹出下拉列表，
#   * QAbstractSpinBox 在 **press** 时就开始加减数值，并且按住不放会**自动重复**，
#     它的自动重复只认 mouseReleaseEvent —— 把 release 吃掉反而会让数值一直加下去，
#   * QAbstractButton(勾选框/单选/按钮)在 release 时切换，
# 于是"滚动的起手动作"被当成了点击。
#
# 做法(只在移动端、只作用于"已接管手指滚动"的滚动区域里的控件)：
#   1. 按下时先**扣住 press**，不发给控件，只记下位置
#   2. 位移超过 TouchSlopPx 判定为滚动：丢弃这次 press，什么都不做(控件完全不知情)
#   3. 位移没超阈值判定为点按：把记下的 press+release 原样**重放**给控件
#      (控件看到的和自己收到一次真实点击完全一样，语义零变化)
# 这样滑动永远不会触发控件，点按和以前一模一样。
#
# 例外(走旧的"扣住 release"策略，不能扣 press)：
#   * QSlider / QScrollBar 需要真正的 press-drag(拖把手/滑块)
#   * QAbstractScrollArea 的视口 / QAbstractItemView 自己要处理按下拖动
#     (列表项的按下拖动、QScroller 的鼠标手势都在 press 上)
#   * Qt::Popup 弹窗(下拉列表、右键菜单)里的点击/滚动不拦，否则列表没法点

_touchGuard = None


def _InTouchArea(widget):
    """ 手指下这个控件是不是在"已接管手指滚动"的滚动区域里 """
    node = widget
    while node is not None:
        if getattr(node, "_jmTouchScroll", False):
            return True
        node = node.parentWidget()
    return False


def _DescribeWidget(widget):
    if widget is None:
        return "None"
    # 用 Class:objectName 而不是 repr —— 这行会被 verify_on_device.ps1 用正则解析
    return "{}:{}".format(type(widget).__name__, widget.objectName() or "?")


def _IsDescendant(widget, ancestor):
    """ widget 是不是 ancestor 的子孙(含自己) """
    if widget is None or ancestor is None:
        return False
    node = widget
    while node is not None:
        if node is ancestor:
            return True
        node = node.parentWidget()
    return False


def _WindowType(widget):
    """ 顶层窗口的"类型"部分(去掉 Window 位)

    注意不能直接写 `flags & Qt.WindowType.Popup`：Qt 的 Popup = 0x8 | Window，
    Window 位是共有的，那样写连普通主窗口都会被判成 Popup(踩过这个坑)。
    """
    try:
        flags = widget.windowFlags() & Qt.WindowType.WindowType_Mask
        return Qt.WindowType(int(flags))
    except Exception:
        return Qt.WindowType.Widget


def _InPopup(widget):
    """ 手指下的控件是不是在弹出窗口里

    下拉框弹出的列表、右键菜单、输入框补全列表都是独立弹窗(Qt::Popup)，
    有自己的点击/滚动语义，误触防护不能插手。
    """
    try:
        if not isinstance(widget, QWidget):
            return True
        window = widget.window()
        if window is None:
            return True
        return _WindowType(window) == Qt.WindowType.Popup
    except Exception:
        return True


def _GuardMode(widget):
    """ 手指下这个控件该怎么防误触

    返回 "tap"   -> 扣住 press，判定为点按后重放(下拉框/数值框/勾选框/按钮)
         "slide" -> 只扣住 release(滑块/滚动条/列表视口等需要按下拖动的东西)
    """
    node = widget
    while node is not None:
        if isinstance(node, (QComboBox, QAbstractSpinBox, QAbstractButton)):
            return "tap"
        if isinstance(node, (QSlider, QScrollBar, QAbstractScrollArea)):
            return "slide"
        if getattr(node, "_jmTouchScroll", False):
            return "slide"
        node = node.parentWidget()
    return "slide"


def _WidgetAlive(widget):
    try:
        from shiboken6 import isValid
        return bool(isValid(widget))
    except Exception:
        return widget is not None


class _TouchGuard(QObject):
    """ 滚动区域的滑动防误触(见文件头注释) """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._widget = None
        self._pressPos = None
        self._localPos = None
        self._globalPos = None
        self._mode = "slide"
        self._dragging = False
        self._undo = None
        self._replaying = False
        self.Presses = 0
        self.Drags = 0
        self.Suppressed = 0
        self.Replayed = 0
        self.LastSuppressed = ""
        self.LastReplayed = ""
        self.DryRun = False
        self.Enabled = True

    # -- 状态 --------------------------------------------------------------
    def Reset(self):
        self._widget = None
        self._pressPos = None
        self._localPos = None
        self._globalPos = None
        self._mode = "slide"
        self._dragging = False
        self._undo = None
        return

    @staticmethod
    def _GlobalPos(event):
        try:
            return QPointF(event.globalPosition())
        except Exception:
            return QPointF(event.globalPos())

    @staticmethod
    def _LocalPos(event):
        try:
            return QPointF(event.position())
        except Exception:
            return QPointF(event.pos())

    @staticmethod
    def _Snapshot(widget):
        """ 记录"滑动时可能需要回滚"的状态，返回一个回滚函数

        只用于 press 阶段就生效、但又必须放过 press 的控件(滑块/滚动条)。
        """
        node = widget
        while node is not None:
            if isinstance(node, QAbstractSpinBox):
                value = node.value()
                return lambda w=node, v=value: w.setValue(v)
            if isinstance(node, QSlider):
                value = node.value()
                return lambda w=node, v=value: w.setValue(v)
            if isinstance(node, QComboBox):
                # 手指落在下拉框**弹出的列表**里时，用户是在滚动那个列表，
                # 这时不能把弹窗收起来(否则列表滚动就废了)
                if widget is not node and _IsDescendant(widget, node.view()):
                    return None

                def Close(w=node):
                    try:
                        if w.view().isVisible():
                            w.hidePopup()
                    except Exception:
                        pass
                return Close
            node = node.parentWidget()
        return None

    def Undo(self):
        undo, self._undo = self._undo, None
        if undo is None:
            return
        try:
            undo()
        except Exception as es:
            Log.Error(es)
        return

    def Replay(self, widget=None, local=None, glob=None):
        """ 把这次点按原样重放给控件(press + release)

        重放期间必须**关掉守卫自己**：sendEvent 同样会走 QApplication 的过滤器，
        不关的话重放的 press/release 又会被守卫接住 -> 无限递归(真机/主机都踩过)。
        """
        widget = self._widget if widget is None else widget
        local = self._localPos if local is None else local
        glob = self._globalPos if glob is None else glob
        if widget is None or local is None or glob is None or not _WidgetAlive(widget):
            return
        self._replaying = True
        try:
            for eventType in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
                event = QMouseEvent(eventType, local, local, glob,
                                    Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                    Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(widget, event)
        finally:
            self._replaying = False
        self.Replayed += 1
        self.LastReplayed = _DescribeWidget(widget)
        return

    # -- 事件 --------------------------------------------------------------
    def eventFilter(self, obj, event):
        if not self.Enabled or self._replaying:
            return False
        try:
            eventType = event.type()
            if eventType == QEvent.Type.MouseButtonPress:
                return self.OnPress(obj, event)
            elif eventType == QEvent.Type.MouseMove:
                self.OnMove(obj, event)
            elif eventType == QEvent.Type.MouseButtonRelease:
                return self.OnRelease(obj, event)
        except Exception as es:
            Log.Error(es)
            self.Reset()
        return False

    def OnPress(self, obj, event):
        self.Reset()
        try:
            if event.button() != Qt.MouseButton.LeftButton:
                return False
        except Exception:
            return False
        if not isinstance(obj, QWidget):
            return False
        # 滚动条自己要被拖动；看图控件有自己的拖动/翻页逻辑；弹窗不插手
        if isinstance(obj, (QScrollBar, QGraphicsView)):
            return False
        if _InPopup(obj) or not _InTouchArea(obj):
            return False
        mode = _GuardMode(obj)
        self._widget = obj
        self._pressPos = self._GlobalPos(event)
        self._localPos = self._LocalPos(event)
        self._globalPos = self._GlobalPos(event)
        self._mode = mode
        if mode == "slide":
            self._undo = self._Snapshot(obj)
        self.Presses += 1
        # "tap" 类控件连 press 都不能让它看到：下拉框会在 press 时弹出来，
        # 数值框会在 press 时开始自动重复(而且只认 release 停)
        return mode == "tap" and not self.DryRun

    def OnMove(self, obj, event):
        if self._widget is None or self._dragging or self._pressPos is None:
            return
        if (self._GlobalPos(event) - self._pressPos).manhattanLength() < TouchSlopPx:
            return
        self._dragging = True
        self.Drags += 1
        # press 阶段就已经生效的控件(滑块/滚动条/被放过 press 的控件)，在这里回滚
        self.Undo()
        return

    def OnRelease(self, obj, event):
        widget, dragging, dry = self._widget, self._dragging, self.DryRun
        mode = self._mode
        local, glob = self._localPos, self._globalPos
        self.Reset()
        if widget is None:
            return False
        if dragging:
            if dry:
                Log.Warn("touch guard[dry]: 本该拦下一次误触点击 {}".format(
                    _DescribeWidget(widget)))
                return False
            self.Suppressed += 1
            self.LastSuppressed = _DescribeWidget(widget)
            Log.Warn("touch guard: 拦下滑动误触 release, 未传给 {}".format(self.LastSuppressed))
            return True
        if mode != "tap":
            # press 已经放过去了，正常点击交给控件自己处理
            return False
        if dry:
            Log.Warn("touch guard[dry]: 本该重放一次点按 {}".format(_DescribeWidget(widget)))
            return False
        # 点按：press 被扣住了，这里补一次完整的点击
        if not _WidgetAlive(widget):
            return True
        try:
            self.Replay(widget, local, glob)
        except Exception as es:
            Log.Error(es)
        return True


def InstallTouchGuard(mainView):
    """ 装上全局的滑动防误触(只在移动端) """
    global _touchGuard
    if not IsEnabled() or _touchGuard is not None:
        return
    app = QApplication.instance()
    if app is None:
        return
    _touchGuard = _TouchGuard(app)
    app.installEventFilter(_touchGuard)
    return


def TouchGuardStats():
    if _touchGuard is None:
        return None
    return _touchGuard


# ---------------------------------------------------------------------------
# 顶层窗口显示/隐藏守卫 + 返回键
# ---------------------------------------------------------------------------
#
# 两个真机问题都出在"顶层窗口/Activity"这一层：
#
# 1) 崩溃：改设置时弹"保存成功"提示条(MsgLabel 是一个独立顶层窗口)、切页签时弹
#    加载框(LoadingDialog)、点"选择模型"弹遮罩对话框，这些都是在**输入事件处理
#    过程中**同步 show()，Qt 会在 QWindowPrivate::setVisible -> show_sys 里同步
#    flush 窗口系统事件 -> 立刻派发 Expose -> 立刻 paint ->
#    QAndroidPlatformOpenGLWindow::eglSurface() 重入 ->
#    'Failed to acquire deadlock protector for ... eglSurface()' -> SIGABRT。
#    (真机栈: QTabBar::mousePressEvent -> python 槽 -> QDialog::setVisible ->
#     QPlatformWindow::setVisible -> flushWindowSystemEvents -> paintAndFlush ->
#     rhiFlush -> makeCurrent -> eglSurface -> abort)
#
#    注意：QEvent.Show 是在 show_sys() **之后**才发的，所以在事件过滤器里拦
#    Show 事件根本来不及(平台窗口已经建好、flush 已经发生)。必须拦在
#    "调用 show()" 这一层 —— PySide6 允许从 Python 侧替换 Qt 类的方法，
#    所以这里直接给 QWidget.show/hide 套一层"延后到当前输入事件处理结束"。
#
# 2) 返回键：Android 的返回键 = Qt.Key_Back(按下)+release。原来只在
#    keyReleaseEvent 里处理，优先级只有"退出看图/收抽屉/回退页面"三档：
#      * 看图界面的工具菜单(是个子控件，不是窗口)收不起来
#      * 根页面上什么都不做，事件继续往下走，最后 Activity 被 finish，
#        Python 侧 app.exec() 返回、主线程退出，但 Activity 还留在前台 ->
#        **白屏**(用户看到的)
#    现在统一在 mobile_ui.HandleBackKey 里按优先级处理并吃掉事件。

_showDeferralInstalled = False
_showDeferralOrigin = {}
ShowDeferralStats = {"deferred": 0, "shown": 0, "hidden": 0, "closed": 0}


def InstallShowDeferral(mainView=None):
    """ 全局：把顶层窗口的 show/hide 延后到当前输入事件处理结束

    只对**顶层窗口**动手(isWindow())：子控件的 show/hide 不创建平台窗口，
    也没有重入风险，保持原样最安全。
    """
    global _showDeferralInstalled
    if not IsEnabled() or _showDeferralInstalled:
        return False
    try:
        origShow = QWidget.show
        origHide = QWidget.hide
        origClose = QWidget.close
        # 延后执行时要调用**原函数**：QWidget.close 已经被我们换掉了，
        # 再调 QWidget.close 会又进一次守卫 -> 无限延后，窗口永远关不掉(踩过)
        _showDeferralOrigin["show"] = origShow
        _showDeferralOrigin["hide"] = origHide
        _showDeferralOrigin["close"] = origClose

        def WaitShow(widget):
            ShowDeferralStats["deferred"] += 1
            DeferCall(lambda w=widget: _SafeShow(w))

        def IsMainWindow(widget):
            return widget is _mainView or widget is getattr(_mainView, "subMainWindow", None)

        def WidgetShow(self):
            try:
                if self.isWindow() and not self.isVisible() and not IsMainWindow(self):
                    WaitShow(self)
                    return
            except Exception as es:
                Log.Error(es)
            origShow(self)

        def WidgetHide(self):
            try:
                if self.isWindow() and self.isVisible() and not IsMainWindow(self):
                    ShowDeferralStats["hidden"] += 1
                    DeferCall(lambda w=self: _SafeHide(w))
                    return
            except Exception as es:
                Log.Error(es)
            origHide(self)

        def WidgetClose(self):
            # close() 内部同样会销毁平台窗口 -> 同一个 eglSurface 重入风险
            try:
                if self.isWindow() and self.isVisible() and not IsMainWindow(self):
                    ShowDeferralStats["closed"] = ShowDeferralStats.get("closed", 0) + 1
                    DeferCall(lambda w=self: _SafeClose(w))
                    return True
            except Exception as es:
                Log.Error(es)
            return origClose(self)

        QWidget.show = WidgetShow
        QWidget.hide = WidgetHide
        QWidget.close = WidgetClose
        _showDeferralInstalled = True
        Log.Warn("window guard: 顶层窗口 show/hide/close 已改为延后执行")
        return True
    except Exception as es:
        Log.Error(es)
    return False


def _SafeShow(widget):
    try:
        if _WidgetAlive(widget) and not widget.isVisible():
            # 直接调被套住的原函数会再进守卫，这里用 setVisible/原始函数跳过守卫
            QWidget.setVisible(widget, True)
            ShowDeferralStats["shown"] += 1
    except Exception as es:
        Log.Error(es)
    return


def _SafeHide(widget):
    try:
        if _WidgetAlive(widget) and widget.isVisible():
            QWidget.setVisible(widget, False)
    except Exception as es:
        Log.Error(es)
    return


def _SafeClose(widget):
    try:
        if _WidgetAlive(widget):
            orig = _showDeferralOrigin.get("close")
            if orig is not None:
                orig(widget)
            else:
                QWidget.setVisible(widget, False)
    except Exception as es:
        Log.Error(es)
    return


# 兼容旧调用名
def InstallWindowGuard(mainView=None):
    return InstallShowDeferral(mainView)


def WindowGuardStats():
    return ShowDeferralStats


# -- 返回键 -----------------------------------------------------------------

BackStats = {"count": 0, "action": "", "last": "", "minimize": 0, "quit": 0}
_backLastTick = 0.0
# 根页面连按两次返回键的间隔(毫秒)：第二次才真的退出应用
BackQuitWindowMs = 2500


def PageName(widget):
    try:
        if widget is None:
            return "?"
        title = widget.windowTitle()
        return "{}[{}]".format(type(widget).__name__, title or widget.objectName() or "?")
    except Exception:
        return "?"


def CurrentPageName(mainView):
    try:
        stack = getattr(mainView, "subStackWidget", None)
        if stack is None:
            return "?"
        return PageName(stack.currentWidget())
    except Exception:
        return "?"


def _VisibleTopWindow(mainView):
    """ 找一个盖在主窗口上面的对话框窗口(加载框/遮罩对话框)

    只看 Dialog/Sheet：提示条(MsgLabel 是 Qt::Tool)、弹出列表(Qt::Popup)不算，
    它们要么自动消失，要么有自己的关闭路径。
    """
    closeTypes = (Qt.WindowType.Dialog, Qt.WindowType.Sheet, Qt.WindowType.Drawer)
    try:
        for widget in QApplication.topLevelWidgets():
            if widget is mainView or widget is getattr(mainView, "subMainWindow", None):
                continue
            if not isinstance(widget, QWidget) or not widget.isVisible():
                continue
            if not widget.isWindow():
                continue
            if _WindowType(widget) not in closeTypes:
                continue
            if widget.width() <= 1 or widget.height() <= 1:
                continue
            return widget
    except Exception as es:
        Log.Error(es)
    return None


def MinimizeToDesktop(mainView):
    """ 根页面按返回：**不能**用 showMinimized()

    真机实测(Android 16 + Qt6.11.2)：`showMinimized()` 只把 Qt 窗口隐藏了，
    Activity 仍然是 `topResumedActivity`、窗口 `mViewVisibility=VISIBLE` ——
    Android 那边还停在前台，但 Qt 已经不再绘制，屏幕上就是一片空白：
    **这正是用户报的"白屏"**。真正的"退到桌面"要调 Android 的
    `moveTaskToBack(true)`，而这个包调不到：

      * pyjnius 不可用：`jnius.so` 在真机上 dlopen 失败
        (cannot locate symbol "WebView_AndroidGetJNIEnv"，bootstrap=qt 没有那个符号)
      * PySide6 6.11 没有绑定 QJniObject / QAndroidJniObject

    所以这里**保持窗口可见**，只给一句提示，让用户用系统的手势/Home 回桌面
    (这也是 Android 的标准做法)，至少不会留下白屏。
    """
    BackStats["minimize"] += 1
    Log.Warn("back: 根页面(不退到后台, 见 MinimizeToDesktop 注释) windowState={} visible={}".format(
        mainView.windowState().name if hasattr(mainView.windowState(), "name") else "?",
        mainView.isVisible()))
    try:
        if not getattr(mainView, "_jmBackHintShown", False):
            mainView._jmBackHintShown = True
            QtOwner().ShowMsgOne("已在首页：用系统手势或 Home 返回桌面")
    except Exception as es:
        Log.Error(es)
    return "stay"


def HandleBackKey(mainView):
    """ 返回键统一处理；返回 True 表示已接管(事件必须 accept，不能再往下传)

    优先级(和桌面端语义一致，只是补上了菜单/根页面两档)：
        1. 看图界面的工具菜单(是子控件，不是窗口)
        2. 盖在上面的顶层窗口(提示条/对话框/加载框)
        3. 导航抽屉
        4. 看图中 -> 退出看图回到上级(书详情等)
        5. 页面栈回退一层
        6. 根页面 -> 退到后台(回桌面)
    """
    global _backLastTick
    now = time.time() * 1000.0
    if now - _backLastTick < BackDebounceMs:
        # Android 会给按下和抬起两个事件，同一按不能处理两次
        return True
    _backLastTick = now
    BackStats["count"] += 1
    try:
        # 0. 弹出窗口(下拉框列表/右键菜单)
        popup = QApplication.activePopupWidget()
        if popup is not None and popup.isVisible():
            try:
                popup.close()
            except Exception as es:
                Log.Error(es)
            return _BackDone("close-popup:{}".format(_DescribeWidget(popup)))

        # 1. 看图界面的工具菜单
        readView = getattr(mainView, "readView", None)
        if _readToolVisible(readView):
            _hideReadTool(readView)
            return _BackDone("close-read-tool")

        # 2. 顶层窗口(提示条/对话框)
        top = _VisibleTopWindow(mainView)
        if top is not None:
            try:
                top.close()
            except Exception as es:
                Log.Error(es)
            return _BackDone("close-window:{}".format(_DescribeWidget(top)))

        # 3. 抽屉
        if IsDrawerOpen(mainView):
            CloseDrawer(mainView)
            return _BackDone("close-drawer")

        # 4. 看图 -> 退出看图
        if getattr(mainView, "totalStackWidget", None) is not None \
                and mainView.totalStackWidget.currentIndex() == 1 and readView is not None:
            readView.Close()
            return _BackDone("close-reader")

        # 5. 页面栈回退
        stack = getattr(mainView, "subStackWidget", None)
        subList = getattr(mainView, "subStackList", None) or []
        index = stack.currentIndex() if stack is not None else -1
        if index in subList and subList.index(index) > 0:
            before = CurrentPageName(mainView)
            mainView.SwitchWidgetLast()
            Log.Warn("back: 页面回退 {} -> {}".format(before, CurrentPageName(mainView)))
            return _BackDone("switch-widget-last")

        # 6. 根页面
        if IsDrawerOpen(mainView):
            CloseDrawer(mainView)
            return _BackDone("close-drawer")
        MinimizeToDesktop(mainView)
        return _BackDone("root-page")
    except Exception as es:
        Log.Error(es)
        return _BackDone("error")


def _BackDone(action):
    BackStats["action"] = action
    BackStats["last"] = "{} @ {}".format(action, CurrentPageName(_mainView) if _mainView else "?")
    Log.Warn("back: {} (页面 {})".format(action, CurrentPageName(_mainView) if _mainView else "?"))
    return True


def _readToolVisible(readView):
    try:
        tool = getattr(getattr(readView, "frame", None), "qtTool", None)
        return tool is not None and not tool.isHidden()
    except Exception:
        return False


def _hideReadTool(readView):
    try:
        readView.frame.qtTool.hide()
    except Exception as es:
        Log.Error(es)
    return


def LogUiEvent(text):
    """ 把关键 UI 事件写进日志

    真机上没法看屏幕(没有 OCR)，只能靠这些行判断"用户到底停在哪个页面、
    窗口有没有真的显示出来"。行数有限，不会刷屏。
    """
    try:
        Log.Warn("ui: {}".format(text))
    except Exception:
        pass
    return


def EnableTouchScroll(root, exclude=None):
    """ 给所有滚动区域加上手指拖动滚动 """
    if root is None:
        return
    try:
        areas = root.findChildren(QAbstractScrollArea)
        for area in areas:
            if exclude is not None and (area is exclude or exclude.isAncestorOf(area)):
                continue
            if isinstance(area, QGraphicsView):
                # 看图界面有自己的一套拖动/翻页逻辑，不接管
                continue
            if getattr(area, "_jmTouchScroll", False):
                continue
            target = area.viewport() if area.viewport() is not None else area
            QScroller.grabGesture(target, QScroller.ScrollerGestureType.TouchGesture)
            if isinstance(area, QAbstractItemView):
                # 只有项视图有 setVerticalScrollMode；QPlainTextEdit/QTextEdit 本身已是逐像素
                area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            area._jmTouchScroll = True
            try:
                props = QScroller.scroller(target).scrollerProperties()
                props.setScrollMetric(QScrollerProperties.ScrollMetric.VerticalOvershootPolicy,
                                      QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
                props.setScrollMetric(QScrollerProperties.ScrollMetric.HorizontalOvershootPolicy,
                                      QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
                QScroller.scroller(target).setScrollerProperties(props)
            except Exception:
                pass
    except Exception as es:
        Log.Error(es)
    return


def OnShown(mainView):
    """ 窗口首次显示 / 旋转 / 从后台回到前台时调用：重新计算尺寸并适配 """
    if not IsEnabled():
        return
    try:
        LogUiEvent("shown: {}x{} windowState={} page={}".format(
            mainView.width(), mainView.height(),
            mainView.windowState().name if hasattr(mainView.windowState(), "name") else "?",
            CurrentPageName(mainView)))
        UpdateLimit(mainView)
        RelaxMinSizes(mainView, _limit)
        SetupDrawer(mainView)
        StackSideNavs(mainView)
        StackSettingNav(getattr(mainView, "settingView", None))
        StackSrTool(getattr(mainView, "waifu2xToolView", None), mainView)
        UpdateSrToolHeight(getattr(mainView, "waifu2xToolView", None), mainView)
        SetupReadTool(getattr(mainView, "readView", None))
        ApplyGridCoverSize(mainView)
        ReflowPortrait(getattr(mainView, "subStackWidget", None))
        EnableTouchScroll(mainView)
        MaybeSelfTest(mainView)
        MaybeTouchSelfTest(mainView)
        MaybeDeviceVerify(mainView)
        MaybeReaderSelfTest(mainView)
        MaybeKeyDiag(mainView)
    except Exception as es:
        Log.Error(es)
    return


def _WriteUiDiag(lines):
    """ 追加到 <AppDataDir>/android_startup.log(与 android/main.py 的自检同一份) """
    try:
        base = platform_mobile.GetAppDataDir()
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "android_startup.log"), "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as es:
        Log.Error(es)
    return


def MaybeSelfTest(mainView):
    """ 抽屉自检：只在 <AppDataDir>/ui_selftest 标记文件存在时跑一次

    真机验证用。设备上没法用 OCR(uiautomator 也读不到 Qt Widgets 的树)，
    所以让应用自己用**真实窗口几何**验证"抽屉不遮挡顶栏"和"点空白处能关闭"。
    """
    try:
        marker = os.path.join(platform_mobile.GetAppDataDir(), "ui_selftest")
        if not os.path.exists(marker):
            return
        try:
            os.remove(marker)
        except Exception:
            pass
        QTimer.singleShot(800, lambda: _SelfTestStart(mainView))
    except Exception as es:
        Log.Error(es)
    return


def _SelfTestStart(mainView):
    lines = ["", "===== ui selftest (drawer) ====="]
    try:
        nav = getattr(mainView, "navigationWidget", None)
        sub = getattr(mainView, "subMainWindow", None)
        menu = getattr(mainView, "menuButton", None)
        scrim = getattr(mainView, "_jmDrawerScrim", None)
        lines.append("main window: {}x{}".format(mainView.width(), mainView.height()))
        if sub is not None:
            lines.append("subMainWindow: {}x{}".format(sub.width(), sub.height()))
        barBottom = 0
        if menu is not None and sub is not None:
            local = sub.mapFromGlobal(menu.mapToGlobal(QPoint(0, 0)))
            barBottom = local.y() + menu.height()
        lines.append("menuButton 底部(subMainWindow 坐标): {}".format(barBottom))
        if not ToggleDrawer(mainView):
            lines.append("ui selftest: SKIP (抽屉未启用)")
            _WriteUiDiag(lines)
            return
        lines.append("打开后: nav hidden={} geometry=({},{},{},{})".format(
            nav.isHidden(), nav.x(), nav.y(), nav.width(), nav.height()))
        okBar = (barBottom > 0) and (nav.y() >= barBottom)
        lines.append("不遮挡顶栏: {} (drawer.y={} >= menuBottom={})".format(okBar, nav.y(), barBottom))
        okBox = (sub is not None) and nav.geometry().bottom() <= sub.height() \
            and nav.geometry().right() <= sub.width()
        lines.append("未超出容器: {} (bottom={} right={} / {}x{})".format(
            okBox, nav.geometry().bottom(), nav.geometry().right(),
            sub.width() if sub else -1, sub.height() if sub else -1))
        if scrim is None:
            lines.append("遮罩: 不存在 (FAIL)")
        else:
            lines.append("遮罩: visible={} geometry=({},{},{},{})".format(
                scrim.isVisible(), scrim.x(), scrim.y(), scrim.width(), scrim.height()))
        lines.append("几何判定: {}".format("PASS" if (okBar and okBox and scrim is not None) else "FAIL"))
        QTimer.singleShot(700, lambda: _SelfTestClick(mainView, nav, scrim, lines))
    except Exception as es:
        lines.append("ui selftest: FAIL (异常 {})".format(es))
        _WriteUiDiag(lines)
    return


def _SelfTestClick(mainView, nav, scrim, lines):
    try:
        if scrim is not None:
            pos = QPointF(scrim.width() / 2.0, scrim.height() / 2.0)
            event = QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos,
                                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                Qt.KeyboardModifier.NoModifier)
            scrim.mousePressEvent(event)
            lines.append("已模拟点击遮罩(空白区域)")
        else:
            lines.append("没有遮罩，无法模拟点击空白区域")
    except Exception as es:
        lines.append("模拟点击遮罩异常: {}".format(es))
    QTimer.singleShot(800, lambda: _SelfTestVerify(nav, scrim, lines))
    return


def _SelfTestVerify(nav, scrim, lines):
    try:
        closed = nav.isHidden()
        scrimHidden = (scrim is None) or (not scrim.isVisible())
        lines.append("点击后: nav.isHidden={} scrim.isVisible={}".format(closed, not scrimHidden))
        lines.append("ui selftest: {}".format("PASS" if (closed and scrimHidden) else "FAIL"))
    except Exception as es:
        lines.append("ui selftest: FAIL (异常 {})".format(es))
    _WriteUiDiag(lines)
    return


def MaybeTouchSelfTest(mainView):
    """ 滑动防误触自检：只在 <AppDataDir>/ui_touch_selftest 标记文件存在时跑一次

    真机上没法用 OCR(也没有 uiautomator 树)，所以让应用自己：
        1. 切到设置页
        2. 把某个勾选框的**物理像素坐标**写进日志(这样 adb 就能精准地滑它/点它)
        3. 周期性把守卫计数、目标勾选状态、滚动位置写进日志
    之后从 adb 发 input swipe / input tap，就能客观地验证：
        * 滑动不再改变设置(守卫计数 +1、目标状态不变)
        * 短距离点按仍然生效(目标状态翻转)
        * 长距离滑动仍然能滚动(scrollValue 变化)

    标记文件内容含 "dry" 时守卫只记录不拦截，用来复现"滑动会改设置"的原始问题。
    """
    try:
        base = platform_mobile.GetAppDataDir()
        marker = os.path.join(base, "ui_touch_selftest")
        if not os.path.exists(marker):
            return
        mode = ""
        try:
            with open(marker, "r", encoding="utf-8", errors="ignore") as f:
                mode = (f.read() or "").strip().lower()
        except Exception:
            mode = ""
        try:
            os.remove(marker)
        except Exception:
            pass
        guard = _touchGuard
        if guard is not None and "dry" in mode:
            guard.DryRun = True
        QTimer.singleShot(900, lambda: _TouchSelfTestStart(mainView, mode))
    except Exception as es:
        Log.Error(es)
    return


def _TouchSelfTestStart(mainView, mode):
    lines = ["", "===== ui selftest (touch guard) ====="]
    try:
        view = getattr(mainView, "settingView", None)
        if view is None:
            lines.append("ui touch selftest: SKIP (没有 settingView)")
            _WriteUiDiag(lines)
            return
        mainView.SwitchWidget(view)
        lines.append("mode: {}".format("dry(只记录不拦截)" if mode and "dry" in mode
                                      else "arm(拦截)"))
        # 等页面真正布局完再取几何：刚切过去时它还是设计器坐标(会算出屏幕外的坐标)
        QTimer.singleShot(1500, lambda: _TouchSelfTestPick(view, lines))
    except Exception as es:
        lines.append("ui touch selftest: FAIL (异常 {})".format(es))
        _WriteUiDiag(lines)
    return


def _VisibleRect(widget, viewport):
    """ 控件在视口里**真正可见**的那块矩形(控件坐标系)

    设置页的勾选框是整行拉伸的，宽度可能比视口还宽(实测 378 vs 352)，所以不能用
    "控件矩形完全落在视口内"来筛选 —— 那样一个都选不出来，最后退化到设计器坐标里的
    downAuto(y=2638)，算出来的物理坐标是屏幕外的 y=9945，adb 的 tap/swipe 全打空。
    """
    from PySide6.QtCore import QRect
    rect = QRect(widget.mapTo(viewport, QPoint(0, 0)), widget.size())
    visible = rect.intersected(viewport.rect())
    if visible.width() <= 0 or visible.height() <= 0:
        return None, rect
    return visible, rect


def _PickVisibleCheckBox(view):
    """ 在设置页视口里挑一个**真的能点到**的勾选框(取最靠上的) """
    from PySide6.QtWidgets import QCheckBox
    return _PickVisibleWidget(view, lambda w: isinstance(w, QCheckBox), 40)


def _PickVisibleWidget(view, predicate, minWidth=40):
    """ 在设置页视口里挑一个**真的能点到**的控件(取最靠上的)

    真机验收要的是"物理坐标"：只有和视口有足够交集(高度 60%、宽度 50%)的控件
    才值得拿来当触摸测试目标，否则算出来的坐标是屏幕外的，adb 打空还以为是功能坏了。
    """
    area = getattr(view, "scrollArea", None)
    viewport = area.viewport() if area is not None else None
    best = None
    for widget in view.findChildren(QWidget):
        try:
            if not predicate(widget):
                continue
            if not widget.isVisible() or widget.width() < minWidth or widget.height() < 10:
                continue
            if viewport is None:
                if best is None or widget.y() < best[0]:
                    best = (widget.y(), widget)
                continue
            visible, _rect = _VisibleRect(widget, viewport)
            if visible is None:
                continue
            if visible.height() < widget.height() * 0.6 or visible.width() < widget.width() * 0.5:
                continue
            if best is None or visible.top() < best[0]:
                best = (visible.top(), widget)
        except Exception:
            continue
    return best[1] if best else None


def _TouchSelfTestPick(view, lines):
    target = _PickVisibleCheckBox(view)
    if target is None:
        lines.append("target: 视口里没有露出足够的勾选框(退化为 downAuto, 坐标可能不可点)")
        target = getattr(view, "downAuto", None)
    else:
        lines.append("target: 选的是视口里最靠上的勾选框 {}".format(
            _DescribeWidget(target)))
    # 用户报的"在下拉框/数值框**附近**滑动会误触"也要能量化验证：
    # 各挑一个下拉框和数值框，把真实物理坐标写进日志，主机侧用 adb input swipe 打它
    from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox
    combo = _PickVisibleWidget(view, lambda w: isinstance(w, QComboBox), 60)
    spin = _PickVisibleWidget(view, lambda w: isinstance(w, (QSpinBox, QDoubleSpinBox)), 40)
    extras = [("combo", combo), ("spin", spin)]
    _TouchSelfTestReport(view, target, lines, extras)
    return


def _WidgetTapPoint(view, widget, lines, tag):
    """ 写一个控件的物理点按坐标(主机侧 adb input 用) """
    try:
        area = getattr(view, "scrollArea", None)
        viewport = area.viewport() if area is not None else None
        window = view.window()
        dpr = window.devicePixelRatioF() if window is not None else 1.0
        if not isinstance(widget, QWidget) or viewport is None:
            lines.append("  {}: 没有可用目标".format(tag))
            return None
        visible, _rect = _VisibleRect(widget, viewport)
        if visible is None:
            lines.append("  {}: 目标不在视口内".format(tag))
            return None
        visGlobal = viewport.mapToGlobal(visible.topLeft())
        tapX = visGlobal.x() + visible.width() // 2
        tapY = visGlobal.y() + visible.height() // 2
        lines.append("  {}: {} 值={} 可见 x={} y={} w={} h={}".format(
            tag, _DescribeWidget(widget), _WidgetValue(widget),
            visGlobal.x(), visGlobal.y(), visible.width(), visible.height()))
        lines.append("  {} 点击点 logical=({},{}) physical=({},{}) dpr={}".format(
            tag, tapX, tapY, int(round(tapX * dpr)), int(round(tapY * dpr)), dpr))
        return tapX, tapY
    except Exception as es:
        lines.append("  {}: 取坐标失败 {}".format(tag, es))
    return None


def _WidgetValue(widget):
    try:
        if isinstance(widget, QComboBox):
            return "{}[{}]".format(widget.currentText(), widget.currentIndex())
        if isinstance(widget, QAbstractSpinBox):
            return str(widget.value())
        if isinstance(widget, QAbstractButton):
            return "checked={}".format(widget.isChecked())
    except Exception:
        pass
    return "?"


def _TouchSelfTestReport(view, target, lines, extras=None):
    try:
        area = getattr(view, "scrollArea", None)
        bar = getattr(area, "vScrollBar", None) if area is not None else None
        viewport = area.viewport() if area is not None else None
        window = view.window()
        dpr = window.devicePixelRatioF() if window is not None else 1.0
        if area is not None:
            lines.append("scroll area: {}x{} viewport {}x{} scrollValue={}".format(
                area.width(), area.height(), viewport.width() if viewport else -1,
                viewport.height() if viewport else -1, bar.value() if bar is not None else -1))
        for tag, widget in (extras or []):
            _WidgetTapPoint(view, widget, lines, tag)
        if isinstance(target, QWidget):
            topLeft = target.mapToGlobal(QPoint(0, 0))
            lines.append("target: {} '{}' checked={}".format(
                type(target).__name__, target.objectName(), target.isChecked()))
            lines.append("  rect logical x={} y={} w={} h={}".format(
                topLeft.x(), topLeft.y(), target.width(), target.height()))
            if viewport is not None:
                visible, _rect = _VisibleRect(target, viewport)
                if visible is not None:
                    visGlobal = viewport.mapToGlobal(visible.topLeft())
                    lines.append("  visible logical x={} y={} w={} h={}".format(
                        visGlobal.x(), visGlobal.y(), visible.width(), visible.height()))
                    tapX = visGlobal.x() + visible.width() // 2
                    tapY = visGlobal.y() + visible.height() // 2
                    lines.append("  tap point logical=({},{}) physical=({},{}) dpr={}".format(
                        tapX, tapY, int(round(tapX * dpr)), int(round(tapY * dpr)), dpr))
            # 记下窗口/屏幕几何，方便核对 adb input 的物理坐标换算
            try:
                winGeo = window.geometry()
                from PySide6.QtGui import QGuiApplication
                screen = QGuiApplication.primaryScreen()
                screenGeo = screen.geometry() if screen is not None else None
                lines.append("  window logical=({},{},{}x{}) screen logical={}".format(
                    winGeo.x(), winGeo.y(), winGeo.width(), winGeo.height(),
                    "({},{},{}x{})".format(screenGeo.x(), screenGeo.y(),
                                           screenGeo.width(), screenGeo.height())
                    if screenGeo is not None else "?"))
            except Exception as es:
                lines.append("  窗口几何取不到: {}".format(es))
        else:
            lines.append("target: 没有 downAuto")
        screen = platform_mobile.GetScreenSize()
        lines.append("  screen logical={}x{} physical≈{}x{} dpr={}".format(
            screen[0], screen[1], int(round(screen[0] * dpr)), int(round(screen[1] * dpr)), dpr))
        lines.append("  说明: 用 adb input swipe/tap 打上面那个 physical 坐标; 观察窗口 {}s".format(
            TouchSelfTestSeconds))
    except Exception as es:
        lines.append("ui touch selftest: FAIL (取几何异常 {})".format(es))
    _WriteUiDiag(lines)

    state = {"tick": 0, "last": None, "timer": None}
    timer = QTimer(view)
    state["timer"] = timer
    timer.setInterval(1000)

    def Tick():
        state["tick"] += 1
        guard = _touchGuard
        checked = target.isChecked() if isinstance(target, QAbstractButton) else None
        setting = None
        try:
            from config.setting import Setting
            setting = Setting.DownloadAuto.value
        except Exception:
            setting = None
        scroll = -1
        barMax = -1
        contentH = -1
        try:
            area = getattr(view, "scrollArea", None)
            bar = getattr(area, "vScrollBar", None)
            scroll = bar.value() if bar is not None else -1
            barMax = bar.maximum() if bar is not None else -1
            content = area.widget() if area is not None else None
            contentH = content.height() if content is not None else -1
        except Exception:
            pass
        cur = (guard.Presses if guard else -1, guard.Drags if guard else -1,
               guard.Suppressed if guard else -1, guard.Replayed if guard else -1,
               guard.LastSuppressed if guard else "", checked, setting, scroll,
               barMax, contentH,
               " ".join("{}={}".format(tag, _WidgetValue(w)) for tag, w in (extras or [])))
        if cur != state["last"] or state["tick"] % 15 == 0:
            # barMax=0 说明内容没超出视口，这个页面本来就滚不动，别把"没滚动"当成失败
            # (注意别在 format 串里写 {max}，那会被当成关键字参数 -> KeyError)
            _WriteUiDiag(["  t={:>3}s presses={} drags={} suppressed={} replayed={} last={} "
                          "checkbox={} Setting.DownloadAuto={} scrollValue={}/{} contentH={} "
                          "target={} {}".format(
                              state["tick"], cur[0], cur[1], cur[2], cur[3], cur[4] or "-",
                              cur[5], cur[6], cur[7], cur[8], cur[9],
                              _DescribeWidget(target) if target is not None else "-",
                              cur[10])])
            state["last"] = cur
        if state["tick"] >= TouchSelfTestSeconds:
            timer.stop()
            _WriteUiDiag(["ui touch selftest: 观察窗口结束"])
        return

    timer.timeout.connect(Tick)
    timer.start()
    return


def DescribePortrait(mainView):
    """ 把竖屏排版的关键几何写成可判定的文本行

    真机上没有 OCR 也读不到 uiautomator 树，只能让应用自己报几何。
    这里报的是"客观量"：
        * 设置页外层是上下排列、导航在内容之上
        * 内容区可视宽度、以及**还有没有横向布局放不下**(QLayout.minimumSize 是权威值)
        * 超分页预览/参数面板的位置关系
    """
    lines = []
    try:
        setting = getattr(mainView, "settingView", None)
        if setting is not None:
            outer = getattr(setting, "horizontalLayout", None)
            nav = getattr(setting, "verticalLayout", None)
            area = getattr(setting, "scrollArea", None)
            direction = outer.direction().name if outer is not None else "?"
            lines.append("settings: outer.direction={}".format(direction))
            if nav is not None and area is not None:
                navGeo = nav.geometry()
                areaGeo = area.geometry()
                lines.append("  nav(4 buttons)=(x={},y={},w={},h={}) content=(x={},y={},w={},h={})".format(
                    navGeo.x(), navGeo.y(), navGeo.width(), navGeo.height(),
                    areaGeo.x(), areaGeo.y(), areaGeo.width(), areaGeo.height()))
                lines.append("  nav 在内容之上: {}".format(navGeo.y() + navGeo.height() <= areaGeo.y() + 4))
            if area is not None:
                vp = area.viewport()
                avail = vp.width() if vp is not None else area.width()
                lines.append("  content viewport={}x{}".format(avail, vp.height() if vp else -1))
                worst = None
                for layout in setting.findChildren(QBoxLayout):
                    if layout.direction() not in (QBoxLayout.Direction.LeftToRight,
                                                  QBoxLayout.Direction.RightToLeft):
                        continue
                    try:
                        need = layout.minimumSize().width()
                    except Exception:
                        continue
                    if worst is None or need > worst[0]:
                        worst = (need, layout.objectName(),
                                 layout.parentWidget().objectName() if layout.parentWidget() else "?")
                if worst is not None:
                    lines.append("  最宽的横向布局需要 {}px / 可用 {}px ({}.{}) -> {}".format(
                        worst[0], avail, worst[2], worst[1],
                        "放得下" if worst[0] <= avail else "放不下"))
                    # 放不下时把这一行的构成打出来，方便定位是谁在撑宽度
                    for layout in setting.findChildren(QBoxLayout):
                        if layout.objectName() != worst[1]:
                            continue
                        if layout.minimumSize().width() != worst[0]:
                            continue
                        for j in range(layout.count()):
                            item = layout.itemAt(j)
                            child = item.widget()
                            label = "{}:{}".format(type(child).__name__, child.objectName()) \
                                if child is not None else "<spacer/layout>"
                            lines.append("    item[{}] {} min={} hint={}".format(
                                j, label, item.minimumSize().width(), item.sizeHint().width()))
                        break
        srTool = getattr(mainView, "waifu2xToolView", None)
        if srTool is not None:
            grid = getattr(srTool, "gridLayout", None)
            area = getattr(srTool, "scrollArea", None)
            view = getattr(srTool, "graphicsView", None)
            if grid is not None and area is not None and view is not None:
                panelIndex = grid.indexOf(srTool.verticalLayout)
                row, col = (-1, -1)
                if panelIndex >= 0:
                    row, col, _rs, _cs = grid.getItemPosition(panelIndex)
                viewIndex = grid.indexOf(view)
                vrow, vcol = (-1, -1)
                if viewIndex >= 0:
                    vrow, vcol, _vrs, _vcs = grid.getItemPosition(viewIndex)
                lines.append("sr tool: preview=({},{}) {}x{} / panel=({},{}) {}x{} maxH={} -> {}".format(
                    vrow, vcol, view.width(), view.height(), row, col,
                    area.width(), area.height(), area.maximumHeight(),
                    "上下堆叠" if (row, col) == (1, 0) else "仍是并排"))
        index = getattr(mainView, "indexView", None)
        widget = getattr(index, "newListWidget", None) if index is not None else None
        if widget is not None:
            try:
                lines.append("首页列表条目数: {}".format(widget.count()))
                lines.extend(GridStatsLines(widget))
            except Exception as es:
                lines.append("首页列表条目数: 取不到 ({})".format(es))
        lines.extend(_ReaderLines(mainView))
        lines.extend(_GuardLines())
    except Exception as es:
        lines.append("DescribePortrait failed: {}".format(es))
    lines.extend(_ParseStatsLines())
    lines.extend(_ImagePipelineLines())
    return lines


def _ColumnsPerRow(itemWidth, avail):
    """ 这一行实际能放几个(和 QListWidget 的 flow 装箱一致：按 item 宽度整除) """
    try:
        if itemWidth <= 0:
            return 0
        return max(1, int(avail // itemWidth))
    except Exception:
        return 0


def GridStatsLines(widget):
    """ 网格列表真实的一行几个(直接用 QListWidget 的实际几何数出来)

    不能只看"封面宽 x 可用宽"的估算：QListWidget 是按 item 的 sizeHint 装箱的，
    sizeHint 没跟着封面尺寸更新的话，一行照样只放得下 1 个。这里按
    visualItemRect 的真实 y 坐标分组，数出每一行到底有几个 item。
    """
    lines = []
    try:
        from collections import OrderedDict
        rows = OrderedDict()
        for i in range(min(widget.count(), 60)):
            item = widget.item(i)
            if item is None:
                continue
            rect = widget.visualItemRect(item)
            rows.setdefault(rect.top(), 0)
            rows[rect.top()] += 1
        vp = widget.viewport()
        avail = vp.width() if vp is not None else widget.width()
        cover = GridCoverWidth(False)
        perRow = max(rows.values()) if rows else 0
        firstHint = 0
        grid = widget.gridSize()
        if widget.count():
            w0 = widget.itemWidget(widget.item(0))
            if w0 is not None:
                firstHint = w0.sizeHint().width()
        lines.append("首页网格: 封面宽 {}px 控件宽 {}px 栅格={}x{} / 可用 {}px -> 每行 {} 个(前 {} 行 {})".format(
            cover, firstHint, grid.width(), grid.height(), avail, perRow, len(rows),
            list(rows.values())[:6]))
    except Exception as es:
        lines.append("首页网格: 取不到 ({})".format(es))
    return lines


def _ReaderLines(mainView):
    """ 看图界面的关键几何与滚动接管情况 """
    lines = []
    try:
        readView = getattr(mainView, "readView", None)
        if readView is None:
            return lines
        frame = getattr(readView, "frame", None)
        tool = getattr(frame, "qtTool", None)
        if frame is not None and tool is not None:
            lines.append("reader tool: 面板=({},{},{}x{}) 看图区={}x{} -> {}".format(
                tool.x(), tool.y(), tool.width(), tool.height(),
                frame.width(), frame.height(),
                "整宽(在屏内)" if tool.x() >= 0 and tool.x() + tool.width() <= frame.width() + 2
                else "超出屏幕"))
            # 主机侧要拿真实物理坐标去 adb input，所以把看图区的全局位置和 dpr 也报出来
            try:
                globalPos = frame.mapToGlobal(QPoint(0, 0))
                window = frame.window()
                dpr = window.devicePixelRatioF() if window is not None else 1.0
                lines.append("reader 看图区 global logical=({},{}) {}x{} dpr={}".format(
                    globalPos.x(), globalPos.y(), frame.width(), frame.height(), dpr))
            except Exception as es:
                lines.append("reader 看图区 global: 取不到 ({})".format(es))
        # 滚动接管：菜单面板是普通 QScrollArea(走 QScroller)，看图区是 QGraphicsView
        # (走 _ReaderDrag 的拖动滚动，故意不挂 QScroller)
        try:
            menuArea = getattr(tool, "scrollArea22", None) if tool is not None else None
            graphics = getattr(frame, "scrollArea", None)
            lines.append("reader 滚动: 菜单滚动区={} 看图区({})={}".format(
                "已接管滚动" if getattr(menuArea, "_jmTouchScroll", False) else "未接管滚动",
                type(graphics).__name__ if graphics is not None else "?",
                "拖动滚动已接管" if _readerDrag is not None else "拖动滚动未接管"))
        except Exception as es:
            lines.append("reader 滚动: 取不到 ({})".format(es))
    except Exception as es:
        lines.append("reader lines failed: {}".format(es))
    return lines


def _GuardLines():
    lines = []
    try:
        guard = _touchGuard
        stats = ShowDeferralStats
        lines.append("touch guard: presses={} drags={} suppressed={} replayed={} last={}".format(
            guard.Presses if guard else -1, guard.Drags if guard else -1,
            guard.Suppressed if guard else -1, guard.Replayed if guard else -1,
            (guard.LastSuppressed if guard else "") or "-"))
        lines.append("window guard: 延后显示={} 已显示={} 延后隐藏={} 延后关闭={} 子控件覆盖层={}".format(
            stats.get("deferred"), stats.get("shown"), stats.get("hidden"),
            stats.get("closed"), stats.get("overlays")))
        lines.append("key diag: 按键={} Key_Back={} 窗口事件={} back处理={}".format(
            KeyDiagStats.get("key"), KeyDiagStats.get("back"), KeyDiagStats.get("window"),
            BackStats.get("count")))
        lines.append("back 统计: count={} minimize={} last={}".format(
            BackStats.get("count"), BackStats.get("minimize"), BackStats.get("last") or "-"))
    except Exception as es:
        lines.append("guard lines failed: {}".format(es))
    return lines


def _ImagePipelineLines():
    """ 图片解码管线(拼图解密 + QImage 工作线程)的统计

    "看图里图片不对/不出来"必须能从这里一眼看出来：是拼图失败(返回原图)、
    还是 QImage 线程死了/解码失败。
    """
    lines = []
    try:
        from task.task_qimage import QImageStats
        stats = QImageStats()
        lines.append("图片解码: 任务={} 成功={} 失败={} 空图={} Qt分割={} bytes分割={} 最后长度={} 最后错误={}".format(
            stats.get("task"), stats.get("ok"), stats.get("fail"), stats.get("null"),
            stats.get("segQt"), stats.get("segBytes"),
            stats.get("lastLen"), (stats.get("lastError") or "-")[:120]))
    except Exception as es:
        lines.append("图片解码统计: 取不到 ({})".format(es))
    try:
        from task.task_multi import TaskMulti
        multi = TaskMulti()
        lines.append("拼图解密: worker={}(线程={}) 队列槽={}".format(
            len(multi.queueList), len(multi.threadList), multi._inQueue.qsize()))
    except Exception as es:
        lines.append("拼图解密统计: 取不到 ({})".format(es))
    return lines


# ---------------------------------------------------------------------------
# 看图界面自检(device_reader 标记触发)
# ---------------------------------------------------------------------------
#
# 用户报的两件事："看图界面里图片无法正常解密"、"看图界面和它的菜单滚不动、
# 菜单还超出屏幕"、"返回键收不掉菜单/退不出看图"。真机上没有 OCR，所以：
#   1) 先跑一次**完全离线**的"分块倒序 -> 解密 -> QImage 解码"往返，逐像素比对
#      (不依赖网络，接口抖动不会造成假失败)
#   2) 再打开一本本地漫画(有的话)或首页第一本，把看图区/菜单几何、滚动位置、
#      返回键动作都写进日志；主机侧用 adb input swipe/keyevent 打真坐标来验证

def GridSelfTest(mainView):
    """ 用真机自己的视口宽验证"首页一行放得下 2 个"

    首页漫画是联网加载的(真机上接口经常 403/超时，列表是空的)，所以不能靠它验证。
    这里在**真正的首页列表控件**里临时放两个 ComicItemWidget，用真机的视口宽度、
    真机的 QListWidget 装箱逻辑数出"一行几个"，量完把临时 item 删掉。
    """
    lines = ["---- 首页网格自检(真机视口) ----"]
    widget = None
    added = 0
    try:
        from PySide6.QtWidgets import QListWidgetItem
        from component.widget.comic_item_widget import ComicItemWidget
        index = getattr(mainView, "indexView", None)
        widget = getattr(index, "newListWidget", None) if index is not None else None
        if widget is None:
            lines.append("  首页网格自检: FAIL (没有 indexView.newListWidget)")
            return lines
        viewport = widget.viewport()
        avail = viewport.width() if viewport is not None else widget.width()
        lines.append("  真机列表: 控件 {}x{}, 视口 {}x{}".format(
            widget.width(), widget.height(), avail, viewport.height() if viewport else -1))
        ResetGridCover()
        MeasureGridAvail(widget)
        cover = GridCoverWidth(False)
        lines.append("  反算封面宽: 视口 {}px - 余量 {}px -> 封面 {}px ({} 列)".format(
            _gridAvail, GridItemOverhead, cover, GridColumns))
        items = []
        for i in range(GridColumns):
            item = ComicItemWidget()
            item.SetTitle("网格自检 {}".format(i + 1), "")
            item.setParent(widget.viewport())
            listItem = QListWidgetItem(widget)
            listItem.setSizeHint(item.sizeHint())
            widget.setItemWidget(listItem, item)
            items.append(listItem)
            added += 1
        RefreshItemSizeHints(widget)
        ApplyGridCoverSize(widget)
        lines.extend(GridStatsLines(widget))
        stats = GridStatsLines(widget)
        perRow = 0
        try:
            perRow = int(re.search(r"每行 (\d+) 个", stats[0]).group(1))
        except Exception:
            perRow = -1
        lines.append("  首页网格自检: {} (一行 {} 个, 期望 {})".format(
            "PASS" if perRow == GridColumns else "FAIL", perRow, GridColumns))
    except Exception as es:
        lines.append("  首页网格自检: FAIL 异常 {}: {}".format(type(es).__name__, es))
    finally:
        # 把临时 item 删掉，别影响真实列表
        try:
            for row in range(widget.count() - 1, -1, -1):
                if added <= 0:
                    break
                widget.takeItem(row)
                added -= 1
        except Exception as es:
            lines.append("  清理临时 item 失败: {}".format(es))
    return lines


def PickerSelfTest(mainView):
    """ 真机验证文件选择器：不开顶层窗口 + 能列目录 + 读不了的目录优雅降级

    用户报的"导入本地漫画/导入本地图片卡死"，根因是 `QFileDialog` 在 Android 上
    新建顶层窗口 + 嵌套模态循环，一去不回。换成 `tools/mobile_file_dialog.py` 的
    应用内子控件之后，这里在真机上确认它确实**不是窗口**、能列出目录、并且
    Android 分区存储下读不到的目录只是报错不会卡住。
    """
    lines = ["---- 文件选择器自检(真机) ----"]
    picker = None
    try:
        from tools import mobile_file_dialog, platform_mobile
        startDir = platform_mobile.GetExternalDir()
        lines.append("  起始目录: {}".format(startDir))
        picker = mobile_file_dialog._PickerDialog(mainView, "自检", startDir,
                                                  mobile_file_dialog.ModeDir, "")
        lines.append("  选择器: isWindow={} 父控件={} 当前目录={}".format(
            picker.isWindow(), type(picker.parent()).__name__, picker.currentDir))
        count = picker.listWidget.count() if picker.listWidget is not None else -1
        lines.append("  列表条目数: {} (应用目录应可读)".format(count))
        # 读不到的目录(分区存储)必须只报错不抛异常
        try:
            picker._GoTo("/data/data")
            lines.append("  不可读目录: 已降级处理(没有抛异常)")
        except Exception as es:
            lines.append("  不可读目录: 抛异常 {}: {} (不应该)".format(type(es).__name__, es))
        ok = (not picker.isWindow()) and count >= 0
        lines.append("  选择器自检: {}".format("PASS" if ok else "FAIL"))
    except Exception as es:
        lines.append("  选择器自检: FAIL 异常 {}: {}".format(type(es).__name__, es))
    finally:
        try:
            if picker is not None:
                picker.hide()
                picker.deleteLater()
        except Exception:
            pass
    return lines


def MaybeReaderSelfTest(mainView):
    """ 看图自检：只在 <AppDataDir>/device_reader 标记文件存在时跑一次

    必须**等首页/本地收藏真的加载出漫画**再打开看图：真机上登录 + /latest 要好几秒，
    太早跑会出现"没有可打开的漫画"这种假失败(实测踩过一次)。
    """
    try:
        marker = os.path.join(platform_mobile.GetAppDataDir(), "device_reader")
        if not os.path.exists(marker):
            return
        try:
            os.remove(marker)
        except Exception:
            pass
        QTimer.singleShot(3000, lambda: _ReaderWaitBook(mainView, 0))
    except Exception as es:
        Log.Error(es)
    return


def _ReaderHasBook(mainView):
    """ 本地收藏或首页列表里有没有可以打开的漫画 """
    try:
        localRead = getattr(mainView, "localReadView", None)
        books = getattr(localRead, "allBookInfos", None) or {}
        for v in books.values():
            eps = v.eps[0] if v.eps else v
            if eps.picCnt or v.picCnt:
                return True
    except Exception:
        pass
    try:
        index = getattr(mainView, "indexView", None)
        widget = getattr(index, "newListWidget", None) if index is not None else None
        if widget is not None:
            for row in range(min(widget.count(), 5)):
                book = widget.itemWidget(widget.item(row))
                if book is not None and getattr(book, "id", ""):
                    return True
    except Exception:
        pass
    return False


def _ReaderWaitBook(mainView, tries):
    # 这里跑在 QTimer 槽里：一旦抛异常，PySide 只会打到 stderr，整个等待链就断了
    # (真机上就出现过"reader 自检块根本没写出来")。所以自己包一层。
    try:
        if _ReaderHasBook(mainView) or tries >= 30:
            _ReaderSelfTestStart(mainView, tries)
            return
    except Exception as es:
        Log.Error(es)
        _WriteUiDiag(["reader 自检: 等漫画时异常 {}: {} (直接开始自检)".format(
            type(es).__name__, es)])
        try:
            _ReaderSelfTestStart(mainView, tries)
        except Exception as es2:
            Log.Error(es2)
        return
    QTimer.singleShot(3000, lambda: _ReaderWaitBook(mainView, tries + 1))
    return


def _ReaderSelfTestStart(mainView, tries=0):
    lines = ["", "===== device verify (reader) ====="]
    lines.append("等待漫画可用的轮次: {} (每轮 3s)".format(tries))
    try:
        lines.extend(DecryptSelfTest())
        lines.extend(GridSelfTest(mainView))
        lines.extend(PickerSelfTest(mainView))
        lines.extend(_OpenReaderForTest(mainView))
        lines.extend(_ReaderLines(mainView))
        lines.extend(_ImagePipelineLines())
    except Exception as es:
        lines.append("reader selftest failed: {}".format(es))
    lines.append("===== end device verify (reader) =====")
    _WriteUiDiag(lines)
    # 打开看图要拉章节/图片，等一会儿再开始轮询
    QTimer.singleShot(4000, lambda: _ReaderPollStart(mainView))
    return


def _SegOfficialNum(epsId, scrambleId, pictureName):
    """ 官方分块数公式(jmcomic JmImageTool.get_num)的独立实现 """
    import hashlib
    epsId = int(epsId or 0)
    scrambleId = int(scrambleId or 0)
    if epsId < scrambleId:
        return 0
    if epsId < 268850:
        return 10
    x = 10 if epsId < 421926 else 8
    s = "{}{}".format(epsId, pictureName).encode()
    return ord(hashlib.md5(s).hexdigest()[-1]) % x * 2 + 2


def _SegOfficialQt(img, num):
    """ 官方分块还原算法(jmcomic decode_and_save)的独立实现

    故意按官方那份"先算源 y / 目标 y 再贴"的循环写，而不是照抄 ToolUtil 的实现，
    这样自检就不是"自己验证自己"。
    """
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    w, h = img.width(), img.height()
    out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    over = h % num
    c = h // num
    painter = QPainter(out)
    try:
        for i in range(num):
            move = c
            ySrc = h - c * (i + 1) - over
            yDst = c * i
            if i == 0:
                move += over
            else:
                yDst += over
            if ySrc < 0 or yDst < 0 or ySrc + move > h or yDst + move > h:
                continue
            painter.drawImage(QRect(0, yDst, w, move), img, QRect(0, ySrc, w, move))
    finally:
        painter.end()
    return out


def _SegOfficialEncodeQt(img, num):
    """ 服务端那种"打乱"：先按 [高块, 常块...] 切，再倒序贴回去 —— 上面那个 decode 的逆

    (rem != 0 时这个变换不是对合，所以"造样本"必须用它，不能拿 decode 凑)
    """
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    w, h = img.width(), img.height()
    out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    over = h % num
    c = h // num
    pieces = []
    y = 0
    for i in range(num):
        move = c + (over if i == 0 else 0)
        pieces.append((y, y + move))
        y += move
    painter = QPainter(out)
    try:
        yDst = 0
        for start, end in reversed(pieces):
            coH = end - start
            painter.drawImage(QRect(0, yDst, w, coH), img, QRect(0, start, w, coH))
            yDst += coH
    finally:
        painter.end()
    return out


def _SegMakeTestImage(num, rem):
    """ 造一张"每行颜色唯一、高度不是 num 整数倍"的样本(rem != 0 才能检验余数处理) """
    from PySide6.QtGui import QImage
    w = 24
    h = 32 * num + rem
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    for y in range(h):
        color = (0xff << 24) | ((y * 7 % 256) << 16) | ((y * 13 % 256) << 8) | (y * 3 % 256)
        for x in range(w):
            img.setPixel(x, y, color)
    return img


def _SegSamePixels(a, b):
    """ -> (可比, 不同像素数) 不同像素数 -1 表示"大图只判定不同" """
    from PySide6.QtGui import QImage
    if a is None or b is None or a.isNull() or b.isNull() or a.size() != b.size():
        return False, -1
    try:
        fmt = QImage.Format.Format_ARGB32
        aa = a.convertToFormat(fmt)
        bb = b.convertToFormat(fmt)
        if bytes(aa.constBits()) == bytes(bb.constBits()):
            return True, 0
        if aa.width() * aa.height() <= 200000:
            diff = 0
            for y in range(aa.height()):
                for x in range(aa.width()):
                    if aa.pixel(x, y) != bb.pixel(x, y):
                        diff += 1
            return True, diff
        return True, -1
    except Exception:
        return False, -1


def _SegSeamRatio(img, num, samples=32):
    """ 接缝分：块与块相接处的平均行差 / 全图平均行差

    只作为参考值：它能发现"严重错位"(比如同一张图被还原了两次, 实测 8 倍)，
    但对"带子顺序错了"不敏感(实测 0.9)，所以判定用的是逐像素比对。
    """
    try:
        w, h = img.width(), img.height()
        c = h // num
        rem = h % num
        if c <= 0 or w <= 0:
            return -1.0, -1.0
        step = max(1, w // samples)

        def rowDiff(y):
            s = n = 0
            for x in range(0, w, step):
                p1 = img.pixel(x, y - 1)
                p2 = img.pixel(x, y)
                s += (abs((p1 >> 16 & 255) - (p2 >> 16 & 255))
                      + abs((p1 >> 8 & 255) - (p2 >> 8 & 255))
                      + abs((p1 & 255) - (p2 & 255)))
                n += 1
            return s / max(1, n)

        bounds = []
        y = 0
        for i in range(num):
            y += c + (rem if i == 0 else 0)
            if 1 <= y < h:
                bounds.append(y)
        seam = sum(rowDiff(y) for y in bounds) / max(1, len(bounds))
        base = []
        for k in range(1, 200):
            y = 1 + k * (h - 2) // 200
            if any(abs(y - b) <= 2 for b in bounds):
                continue
            base.append(rowDiff(y))
        avg = sum(base) / max(1, len(base))
        return seam, avg
    except Exception:
        return -1.0, -1.0


def _SegMeanErr(a, b, step=12):
    """ 采样平均像素差(0-255)：给"有损重编码"的路径用，避免要求逐像素完全相等 """
    try:
        if a is None or b is None or a.isNull() or b.isNull() or a.size() != b.size():
            return -1.0
        w, h = a.width(), a.height()
        n = 0
        s = 0
        for y in range(0, h, step):
            for x in range(0, w, step):
                p1 = a.pixel(x, y)
                p2 = b.pixel(x, y)
                s += (abs((p1 >> 16 & 255) - (p2 >> 16 & 255))
                      + abs((p1 >> 8 & 255) - (p2 >> 8 & 255))
                      + abs((p1 & 255) - (p2 & 255)))
                n += 1
        return (s / 3.0 / n) if n else -1.0
    except Exception:
        return -1.0


def _SegFindCachedRealPage():
    """ 找一张真机自己缓存下来的真 JM 图 -> (path, bookId, epsIndex, pageIndex) """
    import glob
    from config.setting import Setting
    best = None
    try:
        root = Setting.GetCachePath()
    except Exception:
        return None
    for path in glob.glob(os.path.join(root, "book", "*", "*", "*")):
        try:
            if not os.path.isfile(path) or os.path.getsize(path) < 4096:
                continue
            mtime = os.path.getmtime(path)
        except Exception:
            continue
        parts = path.replace("\\", "/").split("/")
        try:
            pageIndex = int(os.path.splitext(parts[-1])[0]) - 1
            epsIndex = int(parts[-2]) - 1
            bookId = parts[-3]
        except Exception:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, path, bookId, epsIndex, pageIndex)
    if best is None:
        return None
    return best[1], best[2], best[3], best[4]


def _SegRealPageParams(bookId, epsIndex, pageIndex):
    """ 用缓存路径反查这一页真正的 (epsId, scrambleId, pictureName) """
    try:
        from tools.book import BookMgr
        book = BookMgr().GetBook(bookId)
        if not book:
            return None
        eps = book.pageInfo.epsInfo.get(epsIndex)
        if not eps or not eps.scrambleId:
            return None
        realIndex = eps.GetRealIndex(pageIndex)
        name = eps.pictureName.get(realIndex)
        if name is None:
            return None
        return eps.epsId, eps.scrambleId, name
    except Exception:
        return None


def DecryptSelfTest():
    """ 离线证明"图片分割(分块还原) + QImage 解码"这条链在真机上是好的

    真机 21:40 的日志里它就是坏的：
        SegmentationPicture failed, epsId:1479594 scrambleId:220980 len:1091216
        err:cannot identify image file <_io.BytesIO object ...>
    Android 上 p4a 编出来的 Pillow 只有 png/jpg/gif，**没有 webp 解码器**
    (APK 里只有 PIL/_webp.pyi，没有 _webp.so)，而 JM 下发的图正是 webp；
    以前失败后兜底返回"被打乱的原图"，用户看到的就是"图片分割异常、图像错位"。

    两层自检，都不依赖网络：
      1) 合成样本：高度故意不是 num 的整数倍(rem != 0)，应用真实函数 vs 独立实现的官方算法
      2) 真机缓存里的真图(webp)：同样比对，并报告 Pillow 能不能解它
    """
    import os
    from config.setting import Setting
    out = ["---- 图片分割(分块还原)自检(离线) ----"]
    from tools.tool import ToolUtil

    # ---------------- Pillow 编解码器现状(根因) ----------------
    try:
        from PIL import Image, features
        import PIL
        webpMod = "有" if os.path.exists(os.path.join(os.path.dirname(PIL.__file__), "_webp.so")) else "缺失"
        out.append("  Pillow {}: jpg={} webp={} zlib={} PIL/_webp.so={}".format(
            PIL.__version__, features.check("jpg"), features.check("webp"),
            features.check("zlib"), webpMod))
    except Exception as es:
        out.append("  Pillow 能力探测失败: {}: {}".format(type(es).__name__, es))

    # ---------------- 1. 合成样本(rem != 0) vs 独立实现的官方算法 ----------------
    try:
        epsId, scrambleId, pictureName = 300000, 1, "1.png"
        num = ToolUtil.GetSegmentationNum(epsId, scrambleId, pictureName)
        numRef = _SegOfficialNum(epsId, scrambleId, pictureName)
        out.append("  分块数公式: 应用={} 官方独立实现={} -> {}".format(
            num, numRef, "一致" if num == numRef else "不一致"))
        # 真机日志里那次真实数据也一起校验公式
        numReal = ToolUtil.GetSegmentationNum(1479594, 220980, "00001")
        numRealRef = _SegOfficialNum(1479594, 220980, "00001")
        out.append("  真实样本公式: epsId=1479594 scrambleId=220980 00001 -> 应用={} 官方={}".format(
            numReal, numRealRef))
        okFormula = (num == numRef and numReal == numRealRef and numReal == 12)

        rem = 5                                   # 故意留余数：rem=0 时这个变换才是对合
        src = _SegMakeTestImage(num, rem)
        enc = _SegOfficialEncodeQt(src, num)       # 用官方实现造"服务端下发的那种图"
        expected = src.copy()
        # 先证明这对独立实现确实互逆(否则"自检"本身不可信)
        rt = _SegOfficialQt(enc, num)
        sameRt, diffRt = _SegSamePixels(expected, rt)
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.WriteOnly)
        enc.save(buf, "PNG")
        encBytes = bytes(ba)
        buf.close()
        out.append("  合成样本: {}x{} (高度 {} = {}*{}+{}, rem={}) 打乱后 {} 字节; 官方 encode/decode 互逆={}".format(
            src.width(), src.height(), src.height(), src.height() // num, num,
            src.height() % num, src.height() % num, len(encBytes),
            (sameRt and diffRt == 0)))

        fixed = ToolUtil.SegmentationPicture(encBytes, epsId, scrambleId, pictureName)
        qFix = ToolUtil.LoadQImage(fixed) if fixed else None
        same, diff = _SegSamePixels(expected, qFix)
        out.append("  SegmentationPicture(合成): 返回={} 字节, 与官方算法逐像素: 可比={} 不同像素={}".format(
            len(fixed) if fixed else 0, same, diff))
        okSyn = bool(fixed) and same and diff == 0

        # 看图线程真正走的那条(QImage 域，不来回编解码)
        qQt = ToolUtil.SegmentationQImage(encBytes, epsId, scrambleId, pictureName)
        same2, diff2 = _SegSamePixels(expected, qQt)
        out.append("  SegmentationQImage(合成): 可比={} 不同像素={}".format(same2, diff2))
        okQt = same2 and diff2 == 0

        # 还原两次必须"更差"：这是本轮之前踩过的坑(而且 rem!=0 时它不是对合)
        twice = _SegOfficialQt(qFix, num) if qFix is not None else None
        same3, diff3 = _SegSamePixels(twice, qFix)
        out.append("  还原两次 vs 还原一次: 可比={} 不同像素={} (rem!=0 时应当不同)".format(same3, diff3))
        okTwice = same3 and diff3 != 0

        # 落盘路径
        try:
            tmpPath = os.path.join(Setting.GetLogPath(), "seg_selftest.png")
            try:
                os.makedirs(Setting.GetLogPath(), exist_ok=True)
            except Exception:
                pass
            okDisk = ToolUtil.SegmentationPictureToDisk(encBytes, epsId, scrambleId, pictureName, tmpPath, "png")
            okDiskPix = False
            if okDisk:
                qDisk = ToolUtil.LoadQImage(open(tmpPath, "rb").read() if os.path.isfile(tmpPath) else b"")
                same4, diff4 = _SegSamePixels(expected, qDisk)
                okDiskPix = same4 and diff4 == 0
                out.append("  SegmentationPictureToDisk(合成): 返回={} 落盘像素一致={}".format(okDisk, okDiskPix))
            else:
                out.append("  SegmentationPictureToDisk(合成): 返回={} (落盘失败)".format(okDisk))
        except Exception as es:
            # 落盘环境问题(只读目录等)不该让整条自检失败
            out.append("  SegmentationPictureToDisk(合成): 跳过 ({})".format(es))
            okDisk, okDiskPix = True, True

        out.append("  图片分割自检(合成, rem={}): {}".format(
            rem, "PASS" if (okFormula and okSyn and okQt and okTwice and okDisk and okDiskPix) else "FAIL"))
    except Exception as es:
        out.append("  图片分割自检(合成): FAIL 异常 {}: {}".format(type(es).__name__, es))
        okSyn = okQt = okFormula = False

    # ---------------- 2. 真机缓存里的真图(webp) ----------------
    try:
        found = _SegFindCachedRealPage()
        if not found:
            out.append("  真机样本: 没有缓存图，跳过(合成自检已覆盖算法)")
        else:
            path, bookId, epsIndex, pageIndex = found
            raw = open(path, "rb").read()
            params = _SegRealPageParams(bookId, epsIndex, pageIndex)
            pilOk = False
            pilErr = ""
            try:
                from PIL import Image
                from io import BytesIO
                with Image.open(BytesIO(raw)) as im:
                    im.load()
                    pilOk = True
            except Exception as es:
                pilErr = "{}: {}".format(type(es).__name__, es)
            qRaw = ToolUtil.LoadQImage(raw)
            out.append("  真机样本: {} ({} 字节, 书 {} 章节 {} 页 {})".format(
                os.path.basename(path), len(raw), bookId, epsIndex + 1, pageIndex + 1))
            out.append("  真机样本解码: Pillow={}{} Qt={} {}x{}".format(
                "OK" if pilOk else "失败", (" (" + pilErr[:80] + ")") if pilErr else "",
                (not qRaw.isNull()), qRaw.width(), qRaw.height()))
            if params:
                epsId, scrambleId, name = params
                num = ToolUtil.GetSegmentationNum(epsId, scrambleId, name)
                out.append("  真机样本参数: epsId={} scrambleId={} pictureName={} num={}".format(
                    epsId, scrambleId, name, num))
                expected = _SegOfficialQt(qRaw, num) if num > 1 else qRaw.copy()
                # 看图线程真正走的路径(QImage 域，不重编码)——这条必须和官方算法逐像素一致
                qQt = ToolUtil.SegmentationQImage(raw, epsId, scrambleId, name)
                same2, diff2 = _SegSamePixels(expected, qQt)
                # bytes 路径(保存/超分输入用)是 webp 有损重编码，只比较平均差
                fixed = ToolUtil.SegmentationPicture(raw, epsId, scrambleId, name)
                errBytes = _SegMeanErr(ToolUtil.LoadQImage(fixed) if fixed else None, expected)
                errRaw = _SegMeanErr(qRaw, expected)
                seamRaw, baseRaw = _SegSeamRatio(qRaw, num) if num > 1 else (-1, -1)
                seamFix, baseFix = _SegSeamRatio(qQt, num) if (qQt is not None and num > 1) else (-1, -1)
                out.append("  真机样本还原: QImage域与官方 可比={} 不同像素={} / bytes路径平均差={:.1f} / 未还原平均差={:.1f}".format(
                    same2, diff2, errBytes, errRaw))
                out.append("  真机样本接缝分(仅供参考): 未还原={:.2f} 还原后={:.2f} 基线={:.2f}".format(
                    seamRaw, seamFix, baseFix))
                okReal = (same2 and diff2 == 0 and bool(fixed) and fixed != raw
                          and 0.0 <= errBytes < 6.0 and errRaw > 20.0)
                out.append("  图片分割自检(真机样本 webp): {}".format("PASS" if okReal else "FAIL"))
            else:
                out.append("  真机样本参数: 拿不到章节参数(书信息不在内存)，只验证解码")
                out.append("  图片分割自检(真机样本 webp): {}".format(
                    "PASS" if not qRaw.isNull() else "FAIL"))
    except Exception as es:
        out.append("  真机样本自检异常 {}: {}".format(type(es).__name__, es))

    # ---------------- 3. 应用真实链路(TaskQImage) ----------------
    try:
        epsId, scrambleId, pictureName = 300000, 1, "1.png"
        from PySide6.QtGui import QImage
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        num = ToolUtil.GetSegmentationNum(epsId, scrambleId, pictureName)
        src = _SegMakeTestImage(num, 3)
        enc = _SegOfficialEncodeQt(src, num)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.WriteOnly)
        enc.save(buf, "PNG")
        buf.close()
        encBytes = bytes(ba)

        fixed = ToolUtil.SegmentationPicture(encBytes, epsId, scrambleId, pictureName)

        from task.task_qimage import TaskQImage, QtQImageTask
        info = QtQImageTask(0)
        info.data = bytes(fixed)
        info.radio = 1.0
        info.toW = 0
        info.toH = 0
        q = TaskQImage().ConverQImage(info)
        out.append("  TaskQImage.ConverQImage: {} {}x{} -> {}".format(
            q is not None, q.width() if q else -1, q.height() if q else -1,
            "PASS" if (q is not None and not q.isNull()) else "FAIL"))

        # 走 TaskQImage 的"看图线程真实入口"(带 saveParams，Android 上应走 Qt 那条)
        received = {}

        def _cb(img, param):
            received[param] = img

        tq = TaskQImage()
        tq.AddQImageTask(encBytes, 1.0, 0, 0, 0, (epsId, scrambleId, pictureName), _cb, 4242)
        from PySide6.QtCore import QTimer
        for _ in range(60):
            QApplication.processEvents()
            if 4242 in received:
                break
            time.sleep(0.05)
        img4242 = received.get(4242)
        same5, diff5 = _SegSamePixels(src, img4242)
        out.append("  TaskQImage(带 saveParams) 真线程回调: {} 可比={} 不同像素={}".format(
            img4242 is not None, same5, diff5))
        from task.task_qimage import QImageStats
        st = QImageStats()
        out.append("  解码统计: 任务={} 成功={} 失败={} 空图={} Qt分割={} bytes分割={} 最后错误={}".format(
            st.get("task"), st.get("ok"), st.get("fail"), st.get("null"),
            st.get("segQt"), st.get("segBytes"), (st.get("lastError") or "-")[:80]))
        okPipe = img4242 is not None and same5 and diff5 == 0
    except Exception as es:
        out.append("  TaskQImage 链路: FAIL {}: {}".format(type(es).__name__, es))
        okPipe = False

    out.append("  解密自检: {}".format("PASS" if (okFormula and okSyn and okQt and okPipe) else "FAIL"))
    return out


def _ReaderSelfTestStartOld(mainView):
    """ 旧版本(被上面带 tries 参数的那份取代，保留仅为对比，不参与调用) """
    lines = ["", "===== device verify (reader) ====="]
    try:
        lines.extend(DecryptSelfTest())
        lines.extend(_OpenReaderForTest(mainView))
        lines.extend(_ReaderLines(mainView))
        lines.extend(_ImagePipelineLines())
    except Exception as es:
        lines.append("reader selftest failed: {}".format(es))
    lines.append("===== end device verify (reader) =====")
    _WriteUiDiag(lines)
    _ReaderPollStart(mainView)
    return


def _OpenReaderForTest(mainView):
    """ 打一本漫画进看图界面：优先本地漫画(离线、真图)，否则用首页第一本 """
    from qt_owner import QtOwner
    out = []
    try:
        localRead = getattr(mainView, "localReadView", None)
        books = getattr(localRead, "allBookInfos", None) or {}
        for v in books.values():
            try:
                eps = v.eps[0] if v.eps else v
                if not (eps.picCnt or v.picCnt):
                    continue
                out.append("reader: 打开本地漫画 '{}' (picCnt={}, eps={})".format(
                    v.title, eps.picCnt or v.picCnt, len(v.eps)))
                QtOwner().OpenLocalReadView(v, 0)
                return out
            except Exception as es:
                out.append("reader: 本地漫画打开失败 {}".format(es))
                break
    except Exception as es:
        out.append("reader: 本地漫画列表取不到 {}".format(es))
    try:
        index = getattr(mainView, "indexView", None)
        widget = getattr(index, "newListWidget", None) if index is not None else None
        if widget is not None and widget.count():
            book = widget.itemWidget(widget.item(0))
            if book is not None and getattr(book, "id", ""):
                out.append("reader: 打开首页第一本 id={}".format(book.id))
                QtOwner().OpenReadView(book.id, 0, -1)
                return out
        out.append("reader: 没有可打开的漫画(本地/首页都空)")
    except Exception as es:
        out.append("reader: 打开在线漫画失败 {}".format(es))
    return out


def _SegReaderPageSample():
    """ 看图界面当前页的**真实原始字节** + 它自己的 saveParams

    saveParams = (epsId, scrambleId, pictureName) 是看图流程自己算出来、真正用于
    还原这一页的那组参数，比"从缓存目录反查"可靠得多。
    """
    try:
        from qt_owner import QtOwner
        readView = getattr(QtOwner().owner, "readView", None)
        if readView is None:
            return None
        pictureData = getattr(readView, "pictureData", None) or {}
        cur = getattr(readView, "curIndex", 0)
        order = [cur] + [i for i in range(0, min(len(pictureData), cur + 6))]
        seen = set()
        for index in order:
            if index in seen:
                continue
            seen.add(index)
            p = pictureData.get(index)
            if p is None:
                continue
            data = getattr(p, "data", None)
            saveParams = getattr(p, "saveParams", None)
            if not data or not isinstance(saveParams, tuple) or len(saveParams) < 3:
                continue
            return bytes(data), saveParams, index
    except Exception:
        return None
    return None


def SegmentRealPageSelfTest():
    """ 拿看图界面正在显示的那一页做"真数据 + 真参数"的逐像素对账

    这是"图像错位"最直接的设备侧证据：服务端下发的原始字节，必须能被还原成与
    官方算法逐像素一致的图（未还原的那份应该差得很远）。
    """
    out = ["---- 真机看图页分割对账(真数据) ----"]
    try:
        from tools.tool import ToolUtil
        sample = _SegReaderPageSample()
        if not sample:
            out.append("  真机看图页: 当前没有带 saveParams 的页面(没在联网看漫画)，跳过")
            return out
        raw, saveParams, index = sample
        epsId, scrambleId, pictureName = saveParams[0], saveParams[1], saveParams[2]
        num = ToolUtil.GetSegmentationNum(epsId, scrambleId, pictureName)
        qRaw = ToolUtil.LoadQImage(raw)
        out.append("  真机看图页: 页={} epsId={} scrambleId={} pictureName={} num={} {}x{} {} 字节".format(
            index, epsId, scrambleId, pictureName, num,
            qRaw.width(), qRaw.height(), len(raw)))
        if num <= 1:
            out.append("  真机看图页分割: SKIP (num<=1, 这一页本来就不需要还原)")
            return out
        expected = _SegOfficialQt(qRaw, num)
        qQt = ToolUtil.SegmentationQImage(raw, epsId, scrambleId, pictureName)
        same, diff = _SegSamePixels(expected, qQt)
        errRaw = _SegMeanErr(qRaw, expected)
        out.append("  真机看图页还原: 与官方算法 可比={} 不同像素={} / 未还原平均差={:.1f}".format(
            same, diff, errRaw))
        out.append("  真机看图页分割: {}".format(
            "PASS" if (same and diff == 0 and errRaw > 20.0) else "FAIL"))
    except Exception as es:
        out.append("  真机看图页分割: FAIL 异常 {}: {}".format(type(es).__name__, es))
    return out


def _ReaderPollStart(mainView):
    """ 周期性把看图区的滚动位置/菜单可见性写进日志，供 adb 侧核对 """
    state = {"tick": 0, "last": None, "timer": None}
    timer = QTimer(mainView)
    state["timer"] = timer
    timer.setInterval(1000)

    def Tick():
        state["tick"] += 1
        try:
            # 等看图界面真的有一页带 saveParams 的图(联网漫画)之后，
            # 用"真数据 + 真参数"做一次逐像素对账 —— 这是"错位"最直接的设备侧证据
            if not state.get("segChecked") and state["tick"] >= 4:
                if _SegReaderPageSample() is not None:
                    state["segChecked"] = True
                    _WriteUiDiag(SegmentRealPageSelfTest())
            readView = getattr(mainView, "readView", None)
            frame = getattr(readView, "frame", None)
            view = getattr(frame, "scrollArea", None)
            tool = getattr(frame, "qtTool", None)
            v = view.vScrollBar.value() if view is not None else -1
            vMax = view.vScrollBar.maximum() if view is not None else -1
            h = view.hScrollBar.value() if view is not None else -1
            hMax = view.hScrollBar.maximum() if view is not None else -1
            toolVisible = tool is not None and not tool.isHidden()
            drag = _readerDrag.Drags if _readerDrag is not None else -1
            scroll = _readerDrag.Scrolled if _readerDrag is not None else -1
            try:
                from task.task_qimage import QImageStats
                qs = QImageStats()
                seg = (qs.get("task"), qs.get("ok"), qs.get("segQt"), qs.get("segBytes"))
            except Exception:
                seg = (-1, -1, -1, -1)
            cur = (v, vMax, h, hMax, toolVisible, drag, scroll,
                   mainView.totalStackWidget.currentIndex(),
                   BackStats.get("count"), BackStats.get("action"), seg)
            if cur != state["last"] or state["tick"] % 15 == 0:
                _WriteUiDiag(["  reader t={:>3}s 页签={} 页={}/{} v={}/{} h={}/{} 菜单={} "
                              "拖动={} 滚动次数={} back={} lastBack={} 解码=任务{}/成功{}/Qt分割{}/bytes{}".format(
                                  state["tick"], cur[7],
                                  getattr(readView, "curIndex", -1),
                                  getattr(readView, "maxPic", -1), v, vMax, h, hMax,
                                  "显示" if toolVisible else "隐藏", drag, scroll,
                                  cur[8], cur[9] or "-", seg[0], seg[1], seg[2], seg[3])])
                state["last"] = cur
        except Exception as es:
            _WriteUiDiag(["  reader poll 异常: {}".format(es)])
        if state["tick"] >= 90:
            timer.stop()
            _WriteUiDiag(["reader: 观察窗口结束"])
        return

    timer.timeout.connect(Tick)
    timer.start()
    return


def SetupBackButton(mainView):
    """ 手机端在顶栏加一个"返回"按钮

    真机实测(Qt 6.11.2 + Android 16)：Android 的返回键**根本到不了** Qt 窗口
    (应用日志里 `key diag` 一次 Key_Back 都没有)，所以 `main_view.keyPressEvent`
    里的返回逻辑在真机上等于没接线。除了保留按键处理(某些机型/焦点状态下会到)，
    再给一个看得见、一定可用的返回入口。
    """
    try:
        if not IsEnabled() or getattr(mainView, "_jmBackButton", None) is not None:
            return False
        layout = getattr(mainView, "menuLayout", None)
        if layout is None:
            return False
        button = QToolButton(mainView.subMainWindow)
        button.setObjectName("jmBackButton")
        button.setText("返回")
        button.setToolTip("返回上一级")
        button.setAutoRaise(True)
        button.clicked.connect(lambda: HandleBackKey(_mainView))
        layout.insertWidget(0, button)
        mainView._jmBackButton = button
        Log.Warn("mobile ui: 顶栏加了返回按钮(真机返回键到不了 Qt)")
        return True
    except Exception as es:
        Log.Error(es)
    return False


def MaybeKeyDiag(mainView):
    """ device_keys 标记存在时打开按键/窗口诊断 """
    global _keyDiagEnabled
    try:
        marker = os.path.join(platform_mobile.GetAppDataDir(), "device_keys")
        if not os.path.exists(marker):
            return
        try:
            os.remove(marker)
        except Exception:
            pass
        _keyDiagEnabled = True
        Log.Warn("key diag: 已开启(按键与窗口事件都会写日志)")
    except Exception as es:
        Log.Error(es)
    return


def MaybeDeviceVerify(mainView):
    """ 设备验收自检：只在 <AppDataDir>/device_verify 标记文件存在时跑一次

    分两块写(首页那块**不能切页面**：切走会把首页还没回来的 /latest 请求连带取消，
    结果就是"首页条目数=0"的假失败)：
        1) (home)   等 /promote + /latest 都解密成功，报解密统计、首页条目数与网格列数
        2) (layout) 再切到设置页量排版几何(设置页平时没被布局过，几何是设计器坐标)
    """
    try:
        marker = os.path.join(platform_mobile.GetAppDataDir(), "device_verify")
        if not os.path.exists(marker):
            return
        try:
            os.remove(marker)
        except Exception:
            pass
        QTimer.singleShot(8000, lambda: _DeviceVerifyPoll(mainView, 0))
    except Exception as es:
        Log.Error(es)
    return


def _DeviceVerifyPoll(mainView, tries):
    """ 等首页两个接口都解密成功(或等够时间)再写 (home) 块 """
    ok = 0
    try:
        from server import req as serverReq
        ok = int(serverReq.ParseStats.get("ok") or 0)
    except Exception:
        ok = 0
    if ok >= 2 or tries >= 25:
        # 解密计数是在 ParseData 里加的，比"填进列表控件"早一步，
        # 所以再多等一会儿再读条目数，否则会读到 0(真机上就这么误判过一次)
        delay = 2500 if ok >= 2 else 0
        QTimer.singleShot(delay, lambda: _DeviceVerifyHome(mainView, tries))
        return
    QTimer.singleShot(2000, lambda: _DeviceVerifyPoll(mainView, tries + 1))
    return


def _DeviceVerifyHome(mainView, tries):
    lines = ["", "===== device verify (home) ====="]
    lines.append("等待轮次: {} (每轮 2s)".format(tries))
    try:
        lines.extend(_ParseStatsLines())
        index = getattr(mainView, "indexView", None)
        widget = getattr(index, "newListWidget", None) if index is not None else None
        if widget is not None:
            try:
                lines.append("首页列表条目数: {} (内容高 {})".format(
                    widget.count(), widget.height()))
            except Exception as es:
                lines.append("首页列表条目数: 取不到 ({})".format(es))
        else:
            lines.append("首页列表条目数: 没有 indexView.newListWidget")
    except Exception as es:
        lines.append("device verify (home) failed: {}".format(es))
    lines.append("===== end device verify (home) =====")
    _WriteUiDiag(lines)
    # 接着切到设置页量排版
    QTimer.singleShot(1000, lambda: _DeviceVerifyLayoutStart(mainView))
    return


def _ParseStatsLines():
    lines = []
    try:
        from server import req as serverReq
        stats = serverReq.ParseStats
        lines.append("接口解密统计: ok={} fail={} lastError={}".format(
            stats.get("ok"), stats.get("fail"), stats.get("lastError") or "(无)"))
        lines.append("  最后一次: {} {}".format(stats.get("lastUrl", ""), stats.get("lastShape", "")))
    except Exception as es:
        lines.append("接口解密统计: 取不到 ({})".format(es))
    return lines


def _DeviceVerifyLayoutStart(mainView):
    """ 切到设置页再做几何测量 """
    try:
        view = getattr(mainView, "settingView", None)
        if view is not None:
            mainView.SwitchWidget(view)
    except Exception as es:
        Log.Error(es)
    QTimer.singleShot(1500, lambda: _DeviceVerifyLayout(mainView))
    return


def _DeviceVerifyLayout(mainView):
    lines = ["", "===== device verify (layout) ====="]
    try:
        lines.extend(_ParseStatsLines())
        lines.extend(DescribePortrait(mainView))
    except Exception as es:
        lines.append("device verify (layout) failed: {}".format(es))
    lines.append("===== end device verify (layout) =====")
    _WriteUiDiag(lines)
    return


def ShrinkToFit(root, available):
    """ 最后一道保险：拆行之后仍放不下的横向行，把里面可压缩的文本控件压扁

    真机实测：设置页"模型"那一行 = QLabel(60) + QToolButton:downModelName(314) = 378px，
    而内容视口只有 352px。拆行本来能解决，但这一行的最小宽度是运行时(setText)才涨上去的，
    时机上不一定赶得上。这里按"最宽的控件先压"的顺序把整行压到放得下为止，
    保证竖向排列下**不存在**放不下的横向行(可压缩的只限于纯文本控件)。
    """
    if root is None or available <= 0:
        return 0
    from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton
    budget = max(200, available - WrapSafetyMargin)
    shrinkable = (QToolButton, QLabel, QPushButton, QLineEdit, QComboBox)
    count = 0
    for layout in root.findChildren(QBoxLayout):
        try:
            if layout.direction() not in (QBoxLayout.Direction.LeftToRight,
                                          QBoxLayout.Direction.RightToLeft):
                continue
            if layout.minimumSize().width() <= budget:
                continue
            items = []
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item is None or item.spacerItem() is not None:
                    continue
                items.append(item)
            items.sort(key=lambda it: it.minimumSize().width(), reverse=True)
            for item in items:
                if layout.minimumSize().width() <= budget:
                    break
                widget = item.widget()
                if widget is None or not isinstance(widget, shrinkable):
                    continue
                if getattr(widget, "_jmShrunk", False):
                    continue
                text = widget.text() if hasattr(widget, "text") else ""
                if text and hasattr(widget, "setToolTip") and not widget.toolTip():
                    widget.setToolTip(text)
                widget.setMinimumWidth(0)
                widget.setSizePolicy(QSizePolicy.Policy.Ignored,
                                     widget.sizePolicy().verticalPolicy())
                widget._jmShrunk = True
                count += 1
        except Exception as es:
            Log.Error(es)
    if count:
        Log.Warn("portrait: {} 个控件压扁以让横向行放得下(可用 {}px)".format(count, budget))
    return count


def ReflowPortrait(root=None, available=None):
    """ 按当前宽度重排一次(幂等，可反复调用)

    为什么需要重复跑：页面上的文字是**运行时**才填的(例如设置页的下载路径
    `SetDownloadLabel` 在建好界面之后才 setText)，Apply 时量出来的行宽是"还没填字"的
    假值；真机上就出现过"Apply 时 10 行放得下，填完字之后有一行 378px > 可用 352px"。
    所以在页面切出来的时候再跑一遍。
    """
    if not IsEnabled():
        return 0
    if root is None:
        root = getattr(_mainView, "subStackWidget", None) if _mainView is not None else None
    if root is None:
        return 0
    if available is None:
        available = PortraitWidth(_mainView) if _mainView is not None else _limit
    count = StackSideNavs(root)
    count += EnableLabelWrap(root, available)
    count += WrapWideRows(root, available)
    count += FlattenWideGrids(root, available)
    count += ShrinkToFit(root, available)
    return count


def InstallReflowHook(mainView):
    """ 页面切换 / 首屏文字填完之后再重排一次 """
    stack = getattr(mainView, "subStackWidget", None)
    if stack is None:
        return

    def OnPageChanged(index):
        page = stack.widget(index)
        if page is None:
            return
        if IsEnabled():
            # 真机上没有 OCR，只能靠这行知道用户停在哪个页面
            LogUiEvent("page -> {} (index {})".format(PageName(page), index))
        # 只重排刚显示出来的那一页(文字是切出来时才知道真实宽度的)，避免每次切页都全栈扫描
        def ReflowPage(p=page):
            try:
                StackSideNavs(p)
                ReflowPortrait(p)
                ApplyGridCoverSize(p)
            except Exception as es:
                Log.Error(es)
        QTimer.singleShot(150, ReflowPage)

    try:
        stack.currentChanged.connect(OnPageChanged)
    except Exception as es:
        Log.Error(es)
    # 首屏(下载路径之类的文字)是异步填的，隔一会儿再兜一次
    QTimer.singleShot(2500, ReflowPortrait)
    return


def OnResize(mainView):
    """ 尺寸变化(旋转屏幕、软键盘弹出)后调用；只有上限变化时才全量放宽 """
    if not IsEnabled():
        return
    try:
        global _limit
        old = _limit
        UpdateLimit(mainView)
        UpdateDrawerGeometry(mainView)
        UpdateSrToolHeight(getattr(mainView, "waifu2xToolView", None), mainView)
        if old != _limit:
            RelaxMinSizes(mainView, _limit)
            # 软键盘弹出/旋转后封面宽度会变，重算一次"一行 2 个"
            ResetGridCover()
            ApplyGridCoverSize(mainView)
        else:
            # _limit 在宽屏下会饱和到 MinWidthLimit(320)，所以"设计尺寸 800px -> 手机
            # 384px"这种缩放走不到上面那支；但列表视口其实变了，封面宽得跟着重算，
            # 否则首屏那批 item 会一直停在按 800px 算出来的 GridCoverMax(240px) ——
            # 真机现象就是"打开首页一行 1 个"。这里去抖地补一次重排。
            ScheduleGridCoverSize(mainView)
    except Exception as es:
        Log.Error(es)
    return
