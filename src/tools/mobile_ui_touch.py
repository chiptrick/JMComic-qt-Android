# coding:utf-8
""" 触摸控件（滑动只有一处：QScroller 接管滚动 + 滑动防误触 + 分区标签条横划）

手指滑动在本文件里**只有一处实现** —— `_TouchGuard` 这个 App 级事件过滤器，
三种去向都由它派生：

    1. 滚动区域(QAbstractScrollArea) —— QScroller 接管手势(惯性/摩擦用 Qt 平台参数)
    2. 分区标签条(QTabBar)          —— 合成"逐像素滚轮事件"驱动(见 _TabBarScroll)
    3. 误触防护                     —— 同一个状态机：滑动过的 release 不交给控件

即"一次滑动只判定一次"：`TouchSlopPx` 之内算点按(原样重放给控件)，超过就是滑动。

为什么分区标签条要单独一条通道：`QTabBar` 只有两个 16x32 的滚动箭头，**没有**公开的
滚动偏移 API（scrollOffset 是私有成员），拖动也不认（QTabBar 没有拖动滚动的实现）。
唯一能按像素滚动它的入口是 `QTabBar::wheelEvent` 里的"像素滚动"分支：

    if (styleHint(SH_TabBar_AllowWheelScrolling))                 // 默认 true
        if (event->device()->capabilities() & Capability::PixelScroll)
            scrollOffset = qBound(0, scrollOffset - pixelDelta.x(), max);

平台自带的鼠标/触摸设备**没有** PixelScroll 能力（喂它只会走进 else 分支去"切标签"），
所以这里自造一个带 PixelScroll 的设备，把手指的位移换算成 pixelDelta 喂进去 ——
标签条就精确地按像素跟手滚动，样式/绘制/命中测试全还是 Qt 自己那套；松手再按手指
速度做惯性衰减(和 QScroller 同样的指数模型)。

滚动区域要 QScroller 接管才认手指(见 MakeScrollable)，而**滚动区域是会"后来才建"
出来的**：首页除"最新上传"以外的分区页是网络回来后由 IndexView.InitBack 逐个
AddTab 建的；详情页/设置页里的滚动区、看图工具菜单也一样。`EnableTouchScroll` 只在
窗口 Apply/OnShown 时跑一遍，那时这些控件还不存在 -> 它们从来没被接管，手指在上面
划就是"完全不动"(真机现象：首页只有最新上传能滑)。

所以接管这件事有**两半**，都在本文件：
    * `_ScrollWatcher`(App 级过滤器) —— 听 ChildAdded/ChildPolished，建立即接管
    * `_TouchGuard.OnPress` 里的 `_AdoptScrollArea` —— 手指按上去时兜底补装
"""
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QInputDevice, QMouseEvent, QPointingDevice, QWheelEvent
from PySide6.QtWidgets import QAbstractItemView, QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QGraphicsView, QScroller, QScrollerProperties, QScrollBar, QSlider, QWidget
from tools.log import Log
from tools.mobile_ui_base import *  # noqa: F401,F403
from tools.mobile_ui_base import (_DescribeWidget, _EventGlobalPos, _EventLocalPos, _GuardMode, _InPopup, _InTouchArea, _IsDescendant, _SelfAndChildren, _TabBarAncestor, _WidgetAlive)
from tools import mobile_ui


# ---------------------------------------------------------------------------
# 分区标签条横划：合成"逐像素滚轮事件"驱动 QTabBar
# ---------------------------------------------------------------------------

class _TabBarScroll(QObject):
    """ 把手指横划换算成"逐像素滚轮事件"喂给标签条(模块头有为什么这么做) """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bar = None
        self._device = None
        self._lastX = None
        self._lastMoveAt = 0.0
        self._lastTickAt = 0.0
        self._velocity = 0.0
        # 不足 1 像素的余量：滚轮事件只认整数像素，慢速拖动不能每帧都丢掉小数
        self._carry = 0.0
        # 速度估计的累计器(见 Move 里为什么不能直接 dx/dt)
        self._accDx = 0.0
        self._accDt = 0.0
        self._startOffset = 0
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, int(TabFlingIntervalMs)))
        self._timer.timeout.connect(self.OnTick)
        self.Begins = 0
        self.Feeds = 0
        self.Flings = 0
        self.LastDelta = 0
        self.LastScrolled = 0

    # -- 状态 --------------------------------------------------------------
    @staticmethod
    def Offset(bar):
        """ 标签条当前滚到哪了(px)。没有偏移 API，只能从 tabRect 反推 """
        try:
            if bar is None or bar.count() <= 0:
                return 0
            return -bar.tabRect(0).x()
        except Exception:
            return 0

    def Stop(self):
        self._timer.stop()
        self._bar = None
        self._lastX = None
        self._velocity = 0.0
        self._carry = 0.0
        self._accDx = 0.0
        self._accDt = 0.0
        return

    def Running(self):
        """ 惯性还在滚吗 """
        return self._bar is not None

    def Begin(self, bar, x):
        """ 手指在标签条上开始横划(x = 手指**按下**的位置，第一次位移由调用方补喂) """
        self.Stop()
        if bar is None or bar.count() <= 1:
            return False
        self._bar = bar
        self._lastX = x
        self._lastMoveAt = time.monotonic()
        self._startOffset = self.Offset(bar)
        self.Begins += 1
        if not self.SelfCheck(bar):
            # 这条通道在这台机器上推不动标签条(样式/设备能力不同)：
            # 别装成在滚，点按与两端箭头照旧
            self.Stop()
            return False
        return True

    def Move(self, x):
        """ 手指移动：位移直接换算成滚动量(1:1 跟手) """
        bar = self._bar
        if bar is None or self._lastX is None:
            return
        dx = x - self._lastX
        self._lastX = x
        now = time.monotonic()
        dt = now - self._lastMoveAt
        self._lastMoveAt = now
        # 速度估计：位移和时间先**攒够一个窗口**再算。安卓会把一帧里的多条触摸事件
        # 合到同一次投递里(dt≈0)，直接 dx/dt 会算出天量速度 -> 一松手就冲到尽头。
        self._accDx += dx
        self._accDt += dt
        if self._accDt >= TabVelocityWindowMs / 1000.0:
            self.UpdateVelocity()
        self.Feed(bar, dx)
        return

    def UpdateVelocity(self):
        """ 用攒下的位移/时间更新一次速度(指数平滑)，见 Move 的注释 """
        if self._accDt <= 0.0:
            return
        self._velocity = 0.4 * (self._accDx / self._accDt) + 0.6 * self._velocity
        self._accDx = 0.0
        self._accDt = 0.0
        return

    def End(self):
        """ 松手：按手指速度做惯性(指数衰减)，返回这次总共滚了多少像素 """
        bar = self._bar
        if bar is None:
            self.LastScrolled = 0
            return 0
        idleMs = (time.monotonic() - self._lastMoveAt) * 1000.0
        if idleMs <= TabFlingStopGapMs:
            # 松手前攒着的那点位移也算进来(最后一次可能还没攒够一个窗口)
            self.UpdateVelocity()
            velocity = self._velocity
        else:
            velocity = 0.0
        self.LastScrolled = self.Offset(bar) - self._startOffset
        if abs(velocity) < TabFlingMinVelocity:
            self.Stop()
            return self.LastScrolled
        self._velocity = max(-TabFlingMaxVelocity, min(TabFlingMaxVelocity, velocity))
        self._lastTickAt = time.monotonic()
        self.Flings += 1
        self._timer.start()
        return self.LastScrolled

    def OnTick(self):
        """ 惯性帧：速度按 TabFlingDecay^(秒) 衰减，到头了或慢下来就停 """
        bar = self._bar
        if bar is None:
            self.Stop()
            return
        now = time.monotonic()
        dt = now - self._lastTickAt
        self._lastTickAt = now
        if dt <= 0.0:
            return
        moved = self.Feed(bar, self._velocity * dt)
        self._velocity *= TabFlingDecay ** dt
        if not moved or abs(self._velocity) < TabFlingMinVelocity:
            self.Stop()
        return

    # -- 驱动 --------------------------------------------------------------
    @staticmethod
    def PixelDevice():
        """ 自造一个"能报像素滚动"的输入设备

        只有 `capabilities()` 会被读到(见模块头)，不参与平台的真实输入。
        """
        return QPointingDevice("jm-tabbar-strip", 0, QInputDevice.DeviceType.TouchScreen,
                               QPointingDevice.PointerType.Finger,
                               QInputDevice.Capability.PixelScroll, 10, 0)

    def Device(self):
        if self._device is None:
            self._device = self.PixelDevice()
        return self._device

    def Feed(self, bar, delta):
        """ 让标签条滚 delta 像素(delta>0 = 内容往右)。

        返回 False 表示"喂进去了但偏移没动"(到两端尽头，或这条通道不通)。
        """
        self._carry += delta
        step = int(self._carry)
        if step == 0:
            return True
        self._carry -= step
        before = self.Offset(bar)
        try:
            pos = bar.rect().center()
            event = QWheelEvent(QPointF(pos), QPointF(bar.mapToGlobal(pos)),
                                QPoint(step, 0), QPoint(0, 0),
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                Qt.ScrollPhase.ScrollUpdate, False,
                                Qt.MouseEventSource.MouseEventNotSynthesized, self.Device())
            QApplication.sendEvent(bar, event)
        except Exception as es:
            Log.Error(es)
            return False
        self.Feeds += 1
        self.LastDelta = step
        return self.Offset(bar) != before

    def SelfCheck(self, bar):
        """ 第一次摸到这个标签条时验一次"合成的像素滚轮到底推不推得动它"

        各平台/样式的 styleHint(SH_TabBar_AllowWheelScrolling) 或设备能力可能不同；
        真机上要是还滑不动，这一行日志能直接指出是不是这条通道没通。
        """
        cached = getattr(bar, "_jmTabWheel", None)
        if cached is not None:
            return cached
        ok = False
        try:
            before = self.Offset(bar)
            delta = -TabSelfCheckPx
            self.Feed(bar, delta)
            if self.Offset(bar) == before:
                # 左边到底了(偏移已经是 0)就试另一个方向
                delta = TabSelfCheckPx
                self.Feed(bar, delta)
            ok = self.Offset(bar) != before
            if ok:
                # 把自检挪走的那几像素挪回原位(喂刚才那个位移的**反**方向)
                self.Feed(bar, -delta)
        except Exception as es:
            Log.Error(es)
        bar._jmTabWheel = ok
        if ok:
            Log.Warn("portrait: 标签条横划用逐像素滚轮驱动(自检通过)")
        else:
            Log.Warn("portrait: 标签条横划自检失败(合成滚轮推不动标签条, 只剩点按与两端箭头)")
        return ok


# ---------------------------------------------------------------------------
# 滑动防误触 + 分区标签条横划(同一个状态机)
# ---------------------------------------------------------------------------

class _TouchGuard(QObject):
    """ App 级事件过滤器：把每一次手指滑动判定一次(点按/滑动/标签条横划) """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._widget = None
        self._bar = None
        self._pressPos = None
        self._localPos = None
        self._globalPos = None
        self._mode = "slide"
        self._dragging = False
        self._dragPx = 0
        self._undo = None
        self._replaying = False
        self._tabScroll = _TabBarScroll(self)
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
        self._bar = None
        self._pressPos = None
        self._localPos = None
        self._globalPos = None
        self._mode = "slide"
        self._dragging = False
        self._dragPx = 0
        self._undo = None
        return

    def TabScrollStats(self):
        """ 标签条横划的计数/参数(给宿主回归与真机日志看) """
        return self._tabScroll

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
                return bool(self.OnMove(obj, event))
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
        if _InPopup(obj):
            return False
        # 兜底：后来才建出来的滚动区域(见模块头)第一次被手指按到时就地补装 QScroller。
        # 放在判定模式之前 —— 装上之后 _InTouchArea 才算"在已接管区域里"，
        # 连带"滑动不误触"也一起生效(否则新页面里滑动还会误点上控件)。
        _AdoptScrollArea(obj)
        # 新的手指落下就该停住上一次的标签条惯性(和原生滚动一致)
        self._tabScroll.Stop()
        mode = _GuardMode(obj)
        if mode == "tabbar":
            # 标签条一般不在"已接管手指滚动"的区域里，不套 _InTouchArea 那个限制
            bar = _TabBarAncestor(obj)
            if bar is None:
                return False
            self._bar = bar
        elif not _InTouchArea(obj):
            return False
        self._widget = obj
        self._pressPos = _EventGlobalPos(event)
        self._localPos = _EventLocalPos(event)
        self._globalPos = _EventGlobalPos(event)
        self._mode = mode
        if self._pressPos is None:
            return False
        if mode == "slide":
            self._undo = self._Snapshot(obj)
        self.Presses += 1
        # "tap" 类控件连 press 都不能让它看到：下拉框会在 press 时弹出来，
        # 数值框会在 press 时开始自动重复(而且只认 release 停)；
        # 标签条也在 press 时就把手指底下的标签切成当前分区(横划会白跑一次网络请求)
        return mode in ("tap", "tabbar") and not self.DryRun

    def OnMove(self, obj, event):
        if self._widget is None or self._pressPos is None:
            return
        pos = _EventGlobalPos(event)
        if pos is None:
            return
        if self._dragging:
            if self._mode == "tabbar":
                self._dragPx = pos.x() - self._pressPos.x()
                self._tabScroll.Move(pos.x())
                return True
            return
        if (pos - self._pressPos).manhattanLength() < TouchSlopPx:
            return
        self._dragging = True
        self.Drags += 1
        # press 阶段就已经生效的控件(滑块/滚动条/被放过 press 的控件)，在这里回滚
        self.Undo()
        if self._mode == "tabbar":
            self._dragPx = pos.x() - self._pressPos.x()
            # 从**按下**的位置起算：别让这 TouchSlopPx 的死区把手指头 16px 位移吃掉
            if self._tabScroll.Begin(self._bar, self._pressPos.x()):
                self._tabScroll.Move(pos.x())
            return True
        return

    def OnRelease(self, obj, event):
        widget, dragging, dry = self._widget, self._dragging, self.DryRun
        mode = self._mode
        local, glob = self._localPos, self._globalPos
        dragPx = self._dragPx
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
            if mode == "tabbar":
                # 松手后按速度继续滚(惯性)，这一下 release 不给标签条(否则会切分区)
                scrolled = self._tabScroll.End()
                Log.Warn("touch guard: 标签条横划 {}px -> 标签条滚 {}px(惯性 {} 次), 未传给 {}".format(
                    int(dragPx), scrolled, self._tabScroll.Flings, self.LastSuppressed))
                return True
            self._tabScroll.Stop()
            Log.Warn("touch guard: 拦下滑动误触 release, 未传给 {}".format(self.LastSuppressed))
            return True
        self._tabScroll.Stop()
        if mode not in ("tap", "tabbar"):
            # press 已经放过去了，正常点击交给控件自己处理
            return False
        if dry:
            Log.Warn("touch guard[dry]: 本该重放一次点按 {}".format(_DescribeWidget(widget)))
            return False
        # 点按：press 被扣住了，这里补一次完整的点击(分区标签条也由此切分区)
        if not _WidgetAlive(widget):
            return True
        try:
            self.Replay(widget, local, glob)
        except Exception as es:
            Log.Error(es)
        return True


def InstallTouchGuard(mainView):
    """ 装上全局的滑动守卫(只在移动端)：防误触 + 分区标签条横划 """
    if not IsEnabled() or mobile_ui._touchGuard is not None:
        return
    app = QApplication.instance()
    if app is None:
        return
    mobile_ui._touchGuard = _TouchGuard(app)
    app.installEventFilter(mobile_ui._touchGuard)
    return


def TouchGuardStats():
    if mobile_ui._touchGuard is None:
        return None
    return mobile_ui._touchGuard


def TabBarOffset(bar):
    """ 标签条当前滚到哪了(px)。QTabBar 没有偏移 API，只能从 tabRect 反推 """
    return _TabBarScroll.Offset(bar)


# ---------------------------------------------------------------------------
# 滚动区域：QScroller 接管手指拖动(所有滚动区域共用这一个入口)
# ---------------------------------------------------------------------------

def MakeScrollable(area):
    """ 让一个滚动区域支持手指拖动滚动(QScroller) + 逐像素滚动

    返回 True 表示"这一次真的接管了"(首次)；已经接管过/看图控件返回 False。
    """
    if area is None or isinstance(area, QGraphicsView):
        # 看图界面有自己的一套拖动/翻页逻辑，不接管
        return False
    if getattr(area, "_jmTouchScroll", False):
        return False
    target = area.viewport() if area.viewport() is not None else area
    QScroller.grabGesture(target, QScroller.ScrollerGestureType.TouchGesture)
    if isinstance(area, QAbstractItemView):
        # 只有项视图有 setVerticalScrollMode；QPlainTextEdit/QTextEdit 本身已是逐像素
        area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    _TuneScroller(target)
    area._jmTouchScroll = True
    return True


def _TuneScroller(target):
    """ 滚动区域统一的手感参数(越界回弹关掉：竖屏下回弹会把相邻页面露出来) """
    try:
        props = QScroller.scroller(target).scrollerProperties()
        props.setScrollMetric(QScrollerProperties.ScrollMetric.VerticalOvershootPolicy,
                              QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        props.setScrollMetric(QScrollerProperties.ScrollMetric.HorizontalOvershootPolicy,
                              QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        QScroller.scroller(target).setScrollerProperties(props)
    except Exception:
        pass
    return


def EnableTouchScroll(root, exclude=None):
    """ 给 root **自己**(含子孙)的滚动区域加上手指拖动滚动，返回新接管的个数

    root 自己也要算(findChildren 不含自己)：调用方经常直接把"那个列表/那个页面"传进来，
    漏掉自己就会静默什么都不做(真机/主机都踩过)。
    """
    count = 0
    if root is None:
        return count
    try:
        for area in _SelfAndChildren(root, QAbstractScrollArea):
            if exclude is not None and (area is exclude or exclude.isAncestorOf(area)):
                continue
            if MakeScrollable(area):
                count += 1
    except Exception as es:
        Log.Error(es)
    return count


def _AdoptScrollArea(widget):
    """ 从 widget 往上找最近的滚动区域，没接管过就补装一次

    手指落在列表项/标签这种子控件上时，往上找才是那个真正要滚的滚动区域。
    最近的一个就是答案：再往上的外层滚动区由它自己的手指事件负责，不用管。
    返回这一次新接管的区域(没接管/不需要则 None)。
    """
    node = widget
    while node is not None:
        if isinstance(node, QAbstractScrollArea):
            # 命中最近的一个就收工(它是看图控件时 MakeScrollable 自然返回 False)
            return node if MakeScrollable(node) else None
        node = node.parentWidget()
    return None


def TouchScrollAreas(root):
    """ root(含自己)里的滚动区域清单，给宿主回归/真机自检用 """
    return [area for area in _SelfAndChildren(root, QAbstractScrollArea)]


class _ScrollWatcher(QObject):
    """ App 级事件过滤器：**后来才建出来的**滚动区域自动装上 QScroller

    真机现象：首页除"最新上传"以外的分区列表完全不能滑动(见模块头)。
    建立即接管是这里唯一要干的事；至于为什么不当场扫、要延迟一拍：
    ChildAdded 是 QWidget 构造函数里发给父控件的，那会儿新控件的 Python 子类
    还没构造完(属性/重写都还没挂上) —— 攒起来用 0ms 定时器推到下一轮事件循环，
    那时控件已经完整，扫出来的结果才靠得住。

    和 _TouchGuard.OnPress 里的 _AdoptScrollArea 是一件事的两半：这一半"建出来就接管"，
    那一半"万一漏了，手指按上去时兜底"。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.Flush)
        self.Seen = 0
        self.Scans = 0
        self.Adopted = 0

    def eventFilter(self, obj, event):
        try:
            eventType = event.type()
            if eventType != QEvent.Type.ChildAdded and eventType != QEvent.Type.ChildPolished:
                return False
            child = event.child()
        except Exception:
            return False
        # 只看滚动区域自己：普通容器不用管 —— 它里面真装了滚动区域，那个区域建出来时
        # 也会各发一次 ChildAdded(漫画 item 那种叶子控件一天几百个，不筛会白扫)
        if not isinstance(child, QAbstractScrollArea):
            return False
        self.Seen += 1
        self._pending.append(child)
        if len(self._pending) > ScrollWatchMaxPending:
            del self._pending[:len(self._pending) - ScrollWatchMaxPending]
        if not self._timer.isActive():
            self._timer.start()
        return False

    def Flush(self):
        pending, self._pending = self._pending, []
        self.Scans += 1
        for widget in pending:
            if not _WidgetAlive(widget):
                continue
            self.Adopted += EnableTouchScroll(widget)
        return

    def Stats(self):
        return {"seen": self.Seen, "scans": self.Scans, "adopted": self.Adopted,
                "pending": len(self._pending)}


def InstallScrollWatcher(mainView):
    """ 装上"后建的滚动区域自动接管"监听(只在移动端)，并顺手扫一遍当前的

    Apply/OnShown 都会调；单例，重复调用只是多扫一遍(幂等)。
    """
    if not IsEnabled():
        return None
    app = QApplication.instance()
    if app is None:
        return None
    if mobile_ui._scrollWatcher is None:
        mobile_ui._scrollWatcher = _ScrollWatcher(app)
        app.installEventFilter(mobile_ui._scrollWatcher)
        Log.Warn("portrait: 后建滚动区域自动接管已开启(分区页/详情页/工具菜单等)")
    mobile_ui._scrollWatcher.Adopted += EnableTouchScroll(mainView)
    return mobile_ui._scrollWatcher


def ScrollWatcherStats():
    """ 给宿主回归与真机自检看：新滚动了几个、扫了几轮 """
    if mobile_ui._scrollWatcher is None:
        return None
    return mobile_ui._scrollWatcher.Stats()
