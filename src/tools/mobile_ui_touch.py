# coding:utf-8
""" 触摸控件（触控只认 QTouchEvent：QScroller 平滑滚动 + 原生点按激活 + 分区标签条横划）

**触控到此为止，不再把触控映射成鼠标操作**。旧实现是"Qt 先把触摸合成成鼠标、
我们再拦截/重放鼠标"(点按时重放 press+release，看图拖动靠吃鼠标 move)，
现在整条链路都搬到了触控事件上：

    1. 滚动区域(QAbstractScrollArea) —— QScroller 接管(TouchGesture)，Qt 原生
       平滑滚动：1:1 跟手、松手惯性/摩擦都是 Qt 自己的手感参数。滚动条在移动端
       直接置值(SmoothScrollBar 的 500ms 自定义缓动关掉)，不和 QScroller 抢手感。
    2. 点按激活 —— 扣住整个触控序列(接受 TouchBegin，Qt 就不再合成鼠标)，松手
       时位移不超过 TouchSlopPx 就走控件**自己的公开入口**激活：按钮 click()、
       下拉框 showPopup()、数值框 stepBy()、标签条 setCurrentIndex()、列表项走
       clicked/itemClicked 信号(应用自己接的那条链)。全程不构造 QMouseEvent。
    3. 分区标签条(QTabBar) —— 横划也交给 QScroller(TouchGesture)：识别、速度、
       惯性全是 Qt 原生平滑滚动；QScroller 发来的 QScrollEvent 增量只用来
       "致动" —— 喂给 QTabBar 唯一公开的逐像素输入路径(带 PixelScroll 能力的
       滚轮分支)。QTabBar 没有公开的滚动偏移 API，这是必需的最小翻译层。
    4. 滑块/滚动条/输入框(需要真鼠标按下语义的控件) —— 完全不插手：触控没人
       认领时由 Qt 自己合成鼠标(Qt::AA_SynthesizeMouseForUnhandledTouchEvents
       的原生兼容路径)，那是 Qt 的行为、不是我们的映射，拖把手/选文本照旧可用。
    5. 看图控件(QGraphicsView) —— 见 mobile_ui_reader，同样纯触控
       (拖动滚动/双指缩放/点按三分区都在 QTouchEvent 上实现)。

为什么点按也要扣住整个序列(而不是放它走 Qt 的合成)：Qt 对"没人认领的触控"会
**当场**合成鼠标按下(qguiapplication.cpp processTouchEvent，按事件逐个合成)，
而 QComboBox/QAbstractSpinBox 在 press 时就生效(弹列表/开始加减数值) ——
滚动起手那一下会被当成点击。旧实现靠"扣住合成出来的鼠标 press、点按时再重放"
解决；新实现直接在触控上判定(一次滑动只判定一次)：

    * 单指、位移 <= TouchSlopPx   -> 点按：走控件公开入口激活
    * 位移超阈值 / 多指            -> 滑动：什么都不激活，滚动交给 QScroller

和旧实现的差别：点按不再"重放鼠标 press+release"，而是调用控件自己的激活入口；
列表项点按走 clicked/itemClicked 信号(和 Qt 合成鼠标点击触发的是同一条应用逻辑)。
滑块/滚动条从"扣 release"改成完全不碰 —— 它们的按下语义只能由 Qt 原生合成提供，
而且 QScroller 拦下的滑动本就不会产生按下。

标签条为什么还留一小段"滚轮致动"：QTabBar 的 scrollOffset 是私有成员，唯一能
按像素滚动它的公开入口是 wheelEvent 里"设备带 PixelScroll 能力就按像素滚"那条
分支(平台自带设备没有这个能力)。分工是：手势/速度/惯性 = QScroller(Qt 原生
平滑滚动)，"把增量送进 QTabBar 自己的输入路径" = 这一小段致动。第一次摸到
标签条时仍自检一次(SelfCheck)：真机上要是这条致动不通，横划自动退化为"不滚"，
点按与两端箭头照旧。

滚动区域是会"后来才建"出来的(首页分区页是网络回来后 AddTab 建的；详情页/设置页
里的滚动区、看图工具菜单也一样)。接管这件事有两半：
    * `_ScrollWatcher`(App 级过滤器) —— 听 ChildAdded/ChildPolished，建立即接管
      (顺带接管新标签条的横划)
    * `_TouchRouter.OnTouch` 里的 `_AdoptScrollArea` —— 手指按上去时兜底补装
"""
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, QSizeF, Qt, QTimer
from PySide6.QtGui import (QEventPoint, QInputDevice, QPointingDevice, QScrollEvent,
                           QScrollPrepareEvent, QWheelEvent)
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView,
                               QAbstractScrollArea, QAbstractSpinBox, QApplication,
                               QComboBox, QGraphicsView, QLineEdit, QPlainTextEdit,
                               QScroller, QScrollerProperties, QScrollBar, QSlider,
                               QTabBar, QTextEdit, QWidget)
from tools.log import Log
from tools.mobile_ui_base import *  # noqa: F401,F403
from tools.mobile_ui_base import (_DescribeWidget, _InPopup, _InTouchArea, _IsDescendant,
                                  _SelfAndChildren, _TabBarAncestor, _WidgetAlive)
from tools import mobile_ui


# ---------------------------------------------------------------------------
# 分区标签条横划：QScroller 接管(手势/惯性)，QScrollEvent 增量致动到像素滚轮路径
# ---------------------------------------------------------------------------

class _TabSwipe(QObject):
    """ 标签条横划：QScroller(TouchGesture) + 增量致动(模块头有分工说明)

    保留旧实现的统计面(Begins/Feeds/Flings/LastScrolled/Running)给宿主回归与
    真机日志；惯性不再自己算 —— 速度/摩擦/衰减全是 QScroller 的。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bar = None            # 当前手势的标签条
        self._fingerDown = False
        self._engaged = False       # 这次手势里 QScroller 的 ScrollPrepare 到过没有
        self._startOffset = 0
        self._device = None
        self._carry = 0.0
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

    @staticmethod
    def MaxOffset(bar):
        """ 标签条最多能滚多远(px) """
        try:
            if bar is None or bar.count() <= 0:
                return 0
            return max(0, bar.tabRect(bar.count() - 1).right() + 8 - bar.width())
        except Exception:
            return 0

    def Running(self):
        """ 惯性还在滚吗(QScroller 离手后仍处于 Scrolling) """
        if self._fingerDown:
            return False
        scroller = self._Scroller()
        return scroller is not None and scroller.state() != QScroller.State.Inactive

    def Engaged(self):
        """ 这次手势 QScroller 有没有接管(没有就走直接致动兜底) """
        return self._engaged

    def _Scroller(self):
        bar = self._bar
        if bar is None or not _WidgetAlive(bar):
            return None
        try:
            return QScroller.scroller(bar)
        except Exception:
            return None

    # -- 手势生命周期(由 _TouchRouter 调) ---------------------------------
    def Attach(self, bar):
        """ 让一个标签条支持横划(接管一次；致动自检不过就只留点按/箭头) """
        if bar is None or getattr(bar, "_jmTabSwipe", False):
            return False
        bar._jmTabSwipe = True
        # 触控路由要能看到这个标签条上的 QTouchEvent
        bar.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        if bar.count() <= 1:
            return False
        if not self.SelfCheck(bar):
            return False
        try:
            QScroller.grabGesture(bar, QScroller.ScrollerGestureType.TouchGesture)
            props = QScroller.scroller(bar).scrollerProperties()
            props.setScrollMetric(QScrollerProperties.ScrollMetric.HorizontalOvershootPolicy,
                                  QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
            props.setScrollMetric(QScrollerProperties.ScrollMetric.VerticalOvershootPolicy,
                                  QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
            QScroller.scroller(bar).setScrollerProperties(props)
        except Exception as es:
            Log.Error(es)
            return False
        return True

    def NoteBegin(self, bar):
        """ 一根手指落到标签条上：开始一次横划手势 """
        self._bar = bar
        self._fingerDown = True
        self._engaged = False
        self._startOffset = self.Offset(bar)
        self._carry = 0.0
        self.Begins += 1

    def NoteEnd(self, bar):
        """ 手指离屏：结算这次手势，返回跟手期间滚了多少像素 """
        self._fingerDown = False
        self.LastScrolled = self.Offset(bar) - self._startOffset
        scroller = self._Scroller()
        if scroller is not None and scroller.state() == QScroller.State.Scrolling:
            # 松手后 QScroller 进入惯性(ScrollerGesture 的 fling)
            self.Flings += 1
        return self.LastScrolled

    def Stop(self):
        """ 停住惯性(新的手指落下/手势作废时) """
        scroller = self._Scroller()
        if scroller is not None:
            try:
                scroller.stop()
            except Exception:
                pass
        self._fingerDown = False
        self._engaged = False

    # -- QScroller -> QTabBar 致动 ----------------------------------------
    def OnPrepare(self, bar, event):
        """ QScrollPrepareEvent：把标签条的滚动范围报给 QScroller """
        self._bar = bar
        self._engaged = True
        maxOffset = self.MaxOffset(bar)
        try:
            event.setContentSize(QSizeF(bar.width() + maxOffset, bar.height()))
            event.setViewportRect(QRectF(bar.rect()))
            event.setContentPos(QPointF(self.Offset(bar), 0))
            event.accept()
        except Exception as es:
            Log.Error(es)
            return False
        return True

    def OnScroll(self, bar, event):
        """ QScrollEvent：把这一帧的增量喂进 QTabBar 自己的像素滚动路径

        contentPos 正向 = 往后滚 = 内容往左(偏移增大)；而 Feed(delta>0) 表示
        "内容往右"，所以要取反。
        """
        try:
            delta = -event.contentPosDelta().x()
            if delta:
                self.Feed(bar, delta)
            event.accept()
        except Exception as es:
            Log.Error(es)
            return False
        return True

    # -- 致动 --------------------------------------------------------------
    @staticmethod
    def PixelDevice():
        """ 自造一个"能报像素滚动"的输入设备

        只有 capabilities() 会被 QTabBar::wheelEvent 读到(像素滚动分支)，不参与
        平台的真实输入。这是把增量送进 QTabBar 公开输入路径的**内部致动**，
        不是把用户触控映射成鼠标/滚轮操作。
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

        返回 False 表示"喂进去了但偏移没动"(到两端尽头，或致动通道不通)。
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
        """ 第一次摸到这个标签条时验一次"像素滚轮致动到底推不推得动它"

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
            Log.Warn("portrait: 标签条横划用 QScroller+像素滚轮致动(自检通过)")
        else:
            Log.Warn("portrait: 标签条横划致动自检失败(像素滚轮推不动标签条, 只剩点按与两端箭头)")
        return ok


# ---------------------------------------------------------------------------
# 点按激活：走控件自己的公开入口(不构造任何输入事件)
# ---------------------------------------------------------------------------

def _ActivateItemView(view, globalPos):
    """ 项视图点按：选中 + 走 clicked/itemClicked 信号(应用自己接的激活链) """
    try:
        local = view.mapFromGlobal(QPoint(int(globalPos.x()), int(globalPos.y())))
        index = view.indexAt(local)
        if not index.isValid():
            # 点在空白处：和真实点击一样"取消选中"
            try:
                view.selectionModel().clear()
                view.setCurrentIndex(index)
            except Exception:
                pass
            return None
        view.setCurrentIndex(index)
        view.clicked.emit(index)
        getItem = getattr(view, "itemFromIndex", None)
        if callable(getItem) and hasattr(view, "itemClicked"):
            item = getItem(index)
            if item is not None:
                view.itemClicked.emit(item)
        # 双击(两次点按)走 doubleClicked —— 合成鼠标时代由 Qt 自己拼，现在自己判
        now = time.monotonic()
        last = getattr(view, "_jmLastTap", None)
        view._jmLastTap = (now, QPointF(globalPos))
        if last is not None and (now - last[0]) * 1000.0 <= QApplication.doubleClickInterval() \
                and (QPointF(globalPos) - last[1]).manhattanLength() <= TouchSlopPx * 2:
            view._jmLastTap = None
            view.doubleClicked.emit(index)
    except Exception as es:
        Log.Error(es)
    return _DescribeWidget(view)


def _Activate(widget, globalPos):
    """ 点按激活：按就近原则走控件**自己的公开入口**，返回被激活的控件描述

    不构造 QMouseEvent —— click()/showPopup()/stepBy()/setCurrentIndex()/
    clicked 信号就是这些控件公开的"被点了一下"入口。
    """
    node = widget
    while node is not None and _WidgetAlive(node):
        try:
            if isinstance(node, QAbstractButton):
                # 勾选框/单选/按钮/工具按钮(含标签条两端的滚动箭头)
                node.click()
                return _DescribeWidget(node)
            if isinstance(node, QComboBox):
                try:
                    if node.view().isVisible():
                        node.hidePopup()
                    else:
                        node.showPopup()
                except Exception:
                    node.showPopup()
                return _DescribeWidget(node)
            if isinstance(node, QAbstractSpinBox):
                # 上半屏 +1、下半屏 -1(和它自己的鼠标按下语义一致)
                local = node.mapFromGlobal(QPoint(int(globalPos.x()), int(globalPos.y())))
                node.stepBy(1 if local.y() < node.height() / 2 else -1)
                return _DescribeWidget(node)
            if isinstance(node, QTabBar):
                local = node.mapFromGlobal(QPoint(int(globalPos.x()), int(globalPos.y())))
                index = node.tabAt(local)
                if index >= 0:
                    node.setCurrentIndex(index)
                return _DescribeWidget(node)
            if isinstance(node, QAbstractItemView):
                return _ActivateItemView(node, globalPos)
            toggle = getattr(node, "Toggle", None)
            if callable(toggle):
                # 自定义控件自己的公开激活入口(如 SwitchButton.Toggle)
                toggle()
                return _DescribeWidget(node)
        except Exception as es:
            Log.Error(es)
            return None
        node = node.parentWidget()
    return None


# ---------------------------------------------------------------------------
# 触控路由：App 级事件过滤器，把每一次手指操作判定一次(点按/滑动/标签条横划)
# ---------------------------------------------------------------------------

class _TouchRouter(QObject):
    """ App 级事件过滤器：只处理 QTouchEvent/QScrollEvent，不再拦截/重放鼠标

    序列判定：
        * TouchBegin  -> 认领(接受触控，Qt 不再合成鼠标)，记录按下点
        * TouchUpdate -> 记录位移；超过 TouchSlopPx 标记为滑动
        * TouchEnd    -> 滑动：什么都不激活；点按：走 _Activate
        * 多指        -> 整个手势都按滑动处理(双指缩放/系统手势，不许变点击)

    "native" 模式(滑块/滚动条/输入框/弹窗/已接管滚动区之外)完全不入表、
    不接受事件 —— Qt 自己的未消费触控->鼠标合成路径原样生效。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._seqs = {}            # 触点id -> 手势状态(只有"接管"的序列才入表)
        self._multi = False        # 当前手势出现过第二根手指
        self._dryMarks = {}        # dry 模式按下去重(同一 TouchBegin 会在父级链上重复投递)
        self._tabSwipe = _TabSwipe(self)
        self._busy = False         # 激活控件期间防重入
        self.Presses = 0
        self.Drags = 0
        self.Suppressed = 0
        self.Replayed = 0          # 点按被激活的次数(统计名沿用旧版)
        self.LastSuppressed = ""
        self.LastReplayed = ""
        self.DryRun = False
        self.Enabled = True

    # -- 状态 --------------------------------------------------------------
    def Reset(self):
        for seq in self._seqs.values():
            self._UnwatchScroller(seq)
        self._seqs.clear()
        self._multi = False
        self._dryMarks.clear()
        return

    def TabScrollStats(self):
        """ 标签条横划的计数/参数(给宿主回归与真机日志看) """
        return self._tabSwipe

    def TabSwipeAttach(self, bar):
        return self._tabSwipe.Attach(bar)

    # -- 事件 --------------------------------------------------------------
    def eventFilter(self, obj, event):
        if not self.Enabled or self._busy:
            return False
        try:
            eventType = event.type()
            if eventType == QEvent.Type.TouchBegin or eventType == QEvent.Type.TouchUpdate \
                    or eventType == QEvent.Type.TouchEnd or eventType == QEvent.Type.TouchCancel:
                return self.OnTouch(obj, event)
            if eventType == QEvent.Type.ScrollPrepare:
                return self.OnScrollPrepare(obj, event)
            if eventType == QEvent.Type.Scroll:
                return self.OnScroll(obj, event)
        except Exception as es:
            Log.Error(es)
            self.Reset()
        return False

    def OnScrollPrepare(self, obj, event):
        if not isinstance(obj, QTabBar) or not getattr(obj, "_jmTabSwipe", False):
            return False
        return self._tabSwipe.OnPrepare(obj, event)

    def OnScroll(self, obj, event):
        if not isinstance(obj, QTabBar) or not getattr(obj, "_jmTabSwipe", False):
            return False
        return self._tabSwipe.OnScroll(obj, event)

    # -- 触控序列 ----------------------------------------------------------
    @staticmethod
    def _DeepAt(obj, point):
        """ 从 obj 顺着触点位置往下找最深的子控件(不依赖屏幕坐标，主机/真机都稳)

        坐标一律用 globalPosition() 换算：position() 只在 Qt 自己投递时才是
        "接收控件本地坐标"，测试合成的 QEventPoint 未必填了它。
        """
        try:
            glob = point.globalPosition()
            pos = obj.mapFromGlobal(QPoint(int(glob.x()), int(glob.y())))
        except Exception:
            return obj
        node = obj
        while True:
            try:
                child = node.childAt(pos)
            except Exception:
                break
            if child is None:
                break
            pos = child.mapFrom(node, pos)
            node = child
        while node is not None and not node.isEnabled():
            node = node.parentWidget()
        return node if node is not None else obj

    @staticmethod
    def _Classify(widget):
        """ 手指下的控件该走哪条通道

        "activate" -> 点按激活(按钮/下拉框/数值框/标签条)
        "tabbar"   -> 同 activate，但滑动改成"横划滚动标签条"(QScroller)
        "view"     -> 项视图/滚动区内容：滑动不许变成点击，点按走信号链
        "reader"   -> 看图控件(有自己的触控处理，这里完全不插手)
        "native"   -> 需要真鼠标按下语义的控件(滑块/滚动条/输入框)：
                      不认领触控，Qt 原生"未消费触控->鼠标"合成照常工作
        """
        node = widget
        while node is not None:
            if isinstance(node, QGraphicsView):
                return "reader"
            if isinstance(node, QTabBar):
                return "tabbar" if node.count() > 1 else "activate"
            if isinstance(node, QAbstractButton):
                if isinstance(node.parentWidget(), QTabBar):
                    return "tabbar"
                return "activate"
            if isinstance(node, QComboBox):
                return "activate"
            if isinstance(node, QAbstractSpinBox):
                return "activate"
            if isinstance(node, (QSlider, QScrollBar)):
                return "native"
            if isinstance(node, (QTextEdit, QPlainTextEdit)):
                return "native"
            if isinstance(node, QLineEdit):
                if not isinstance(node.parentWidget(), (QComboBox, QAbstractSpinBox)):
                    return "native"
                # 数值框/下拉框内部的输入行，继续往上交给它们判
            if isinstance(node, QAbstractItemView):
                return "view"
            if getattr(node, "_jmTouchScroll", False):
                return "view"
            node = node.parentWidget()
        return "native"

    def OnTouch(self, obj, event):
        eventType = event.type()
        if eventType == QEvent.Type.TouchCancel:
            self._tabSwipe.Stop()
            self.Reset()
            return False
        try:
            points = list(event.points())
        except Exception:
            return False

        # 1) 新触点：判定通道(同一次 TouchBegin 会在父级链上重复投递几次，
        #    已在表里的触点直接跳过；dry 模式按时间窗去重)
        for point in points:
            try:
                if point.state() != QEventPoint.State.Pressed:
                    continue
                pid = point.id()
            except Exception:
                continue
            if pid in self._seqs:
                continue
            if self.DryRun:
                now = time.monotonic()
                self._dryMarks = {k: v for k, v in self._dryMarks.items()
                                  if now - v < 0.5}
                if pid in self._dryMarks:
                    continue
                self._dryMarks[pid] = now
            self.OnPress(obj, point, event)

        # 2) 位移跟踪 / 松手结算
        handled = bool(self._seqs)
        for point in points:
            seq = self._seqs.get(point.id())
            if seq is None:
                continue
            try:
                state = point.state()
                pos = QPointF(point.globalPosition())
            except Exception:
                continue
            if state == QEventPoint.State.Released:
                self.OnRelease(seq, pos)
                handled = True
            else:
                self.OnMove(seq, pos)
                handled = True
        return handled

    def OnPress(self, obj, point, event):
        try:
            pos = QPointF(point.globalPosition())
        except Exception:
            return
        if self._seqs:
            # 第二根手指：整个手势都不再当点按(并入表里一起吞掉)
            self._multi = True
        else:
            # 新的一根手指落下就该停住上一次的标签条惯性(和原生滚动一致)
            self._tabSwipe.Stop()
        # 兜底：后来才建出来的滚动区域(见模块头)第一次被手指按到时就地补装
        widget = self._DeepAt(obj, point)
        if widget is not None:
            _AdoptScrollArea(widget)
        if _InPopup(obj) or _InPopup(widget):
            return
        mode = self._Classify(widget)
        if mode == "reader":
            # 看图控件有自己的触控处理(mobile_ui_reader)
            return
        if mode != "tabbar":
            # 只管"已接管手指滚动"的区域里的控件(和旧守卫同作用域)：
            # 区域外的按钮/输入框完全交给 Qt 原生行为
            if not _InTouchArea(widget):
                return
        if mode == "native":
            return
        if self.DryRun:
            # 只记录不接管(不接受触控)：让 Qt 的原生合成照常发生，用来复现旧问题
            self.Presses += 1
            Log.Warn("touch[dry]: 本该接管 {} ({})".format(_DescribeWidget(widget), mode))
            return
        seq = {"id": point.id(), "widget": widget, "mode": mode, "press": pos,
               "last": pos, "moved": False, "bar": None, "conn": None}
        if mode == "tabbar":
            bar = _TabBarAncestor(widget) if not isinstance(widget, QTabBar) else widget
            if bar is None:
                return
            seq["bar"] = bar
            self._tabSwipe.NoteBegin(bar)
        else:
            # QScroller 认领手势后会把后续 TouchUpdate 吞掉(手势过滤器先于应用过滤器)，
            # 位移就再从 scroller 状态观察一路：进过 Dragging/Scrolling 就算滑动过
            self._WatchScroller(seq, widget)
        self._seqs[point.id()] = seq
        self.Presses += 1
        try:
            event.accept()
        except Exception:
            pass
        return

    def _WatchScroller(self, seq, widget):
        try:
            node = widget
            area = None
            while node is not None:
                if isinstance(node, QAbstractScrollArea) and getattr(node, "_jmTouchScroll", False):
                    area = node
                    break
                node = node.parentWidget()
            if area is None:
                return
            target = area.viewport() if area.viewport() is not None else area
            scroller = QScroller.scroller(target)
            owner = self

            def OnState(state, _seq=seq, _owner=owner):
                if state != QScroller.State.Inactive and state != QScroller.State.Pressed:
                    _owner._MarkMoved(_seq)

            scroller.stateChanged.connect(OnState)
            seq["conn"] = (scroller, OnState)
        except Exception:
            return

    def _UnwatchScroller(self, seq):
        conn = seq.get("conn")
        seq["conn"] = None
        if conn is None:
            return
        try:
            scroller, callback = conn
            scroller.stateChanged.disconnect(callback)
        except Exception:
            pass
        return

    def _MarkMoved(self, seq):
        """ 标记"这次手势滑动过"(所有判定点共用，Drags 只数一次) """
        if seq.get("moved"):
            return
        seq["moved"] = True
        self.Drags += 1
        return

    def OnMove(self, seq, pos):
        if not seq["moved"] and (pos - seq["press"]).manhattanLength() > TouchSlopPx:
            self._MarkMoved(seq)
        if seq["mode"] == "tabbar" and seq["bar"] is not None:
            if not self._tabSwipe.Engaged():
                # QScroller 没接管这条手势时的直接致动兜底(平台/样式差异保险)
                self._tabSwipe.Feed(seq["bar"], pos.x() - seq["last"].x())
        seq["last"] = pos
        return

    def OnRelease(self, seq, pos):
        self._seqs.pop(seq["id"], None)
        try:
            self._UnwatchScroller(seq)
            self._finalize(seq, pos)
        finally:
            if not self._seqs:
                self._multi = False
        return

    def _finalize(self, seq, pos):
        mode = seq["mode"]
        widget = seq["widget"]
        # 滑动判定三保险：跟踪到的位移 / 松手位置离按下点 / QScroller 活过没有
        # (QScroller 认领会吞掉中途的 TouchUpdate，后两条兜住这种情况)
        if (pos - seq["press"]).manhattanLength() > TouchSlopPx:
            self._MarkMoved(seq)
        if self._multi or seq["moved"]:
            # 滑动(或多指)：什么都不激活 —— 滚动由 QScroller 自己完成
            self.Suppressed += 1
            self.LastSuppressed = _DescribeWidget(widget)
            if mode == "tabbar" and seq["bar"] is not None:
                scrolled = self._tabSwipe.NoteEnd(seq["bar"])
                Log.Warn("touch: 标签条横划 {}px -> 已滚 {}px(惯性 {} 次), 未切分区".format(
                    int((pos - seq["press"]).x()), scrolled, self._tabSwipe.Flings))
            else:
                Log.Warn("touch: 滑动松手未触发控件 {}".format(self.LastSuppressed))
            return
        if mode == "tabbar" and seq["bar"] is not None:
            self._tabSwipe.NoteEnd(seq["bar"])
        # 点按：走控件自己的公开入口
        self._busy = True
        try:
            desc = _Activate(widget, pos)
        finally:
            self._busy = False
        if desc:
            self.Replayed += 1
            self.LastReplayed = desc
            Log.Warn("touch: 点按激活 {}".format(desc))
        return


# 需要触控路由"认领"的点按类控件：让它们收到 QTouchEvent
# (否则 TouchBegin 只会在它们的**父级**上投递，扣不住 press 语义，
#  Qt 的 focus-follow 也认不出手指下的控件)
_TapClassWidgets = (QAbstractButton, QComboBox, QAbstractSpinBox, QTabBar)


def MarkTapClass(widget):
    """ 给点按类控件打开触控接收(幂等，建出来就打一次) """
    try:
        widget.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
    except Exception:
        pass
    return


def InstallTouchGuard(mainView):
    """ 装上全局触控路由(只在移动端)：点按激活 + 滑动防误触 + 标签条横划 """
    if not IsEnabled() or mobile_ui._touchGuard is not None:
        return
    app = QApplication.instance()
    if app is None:
        return
    mobile_ui._touchGuard = _TouchRouter(app)
    app.installEventFilter(mobile_ui._touchGuard)
    # 现存控件就地接管(后建的由 _ScrollWatcher 负责)
    try:
        for bar in _SelfAndChildren(mainView, QTabBar):
            mobile_ui._touchGuard.TabSwipeAttach(bar)
        for cls in (QAbstractButton, QComboBox, QAbstractSpinBox):
            for widget in _SelfAndChildren(mainView, cls):
                MarkTapClass(widget)
    except Exception as es:
        Log.Error(es)
    return


def TouchGuardStats():
    if mobile_ui._touchGuard is None:
        return None
    return mobile_ui._touchGuard


def TabBarOffset(bar):
    """ 标签条当前滚到哪了(px)。QTabBar 没有偏移 API，只能从 tabRect 反推 """
    return _TabSwipe.Offset(bar)


# ---------------------------------------------------------------------------
# 滚动区域：QScroller 接管手指拖动(所有滚动区域共用这一个入口)
# ---------------------------------------------------------------------------

def MakeScrollable(area):
    """ 让一个滚动区域支持手指拖动滚动(QScroller 平滑滚动) + 逐像素滚动

    返回 True 表示"这一次真的接管了"(首次)；已经接管过/看图控件返回 False。
    """
    if area is None or isinstance(area, QGraphicsView):
        # 看图界面有自己的一套触控处理(mobile_ui_reader)，不接管
        return False
    if getattr(area, "_jmTouchScroll", False):
        return False
    target = area.viewport() if area.viewport() is not None else area
    # 触控路由要能在视口这一层看到/认领 QTouchEvent(见 _TouchRouter)
    target.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
    QScroller.grabGesture(target, QScroller.ScrollerGestureType.TouchGesture)
    if isinstance(area, QAbstractItemView):
        # 只有项视图有 setVerticalScrollMode；QPlainTextEdit/QTextEdit 本身已是逐像素
        area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    # QScroller 要 1:1 跟手：SmoothScrollBar 的自定义缓动(500ms OutQuint)会让
    # "滚动条实际值"滞后于手指，也叠掉了 QScroller 自己的惯性手感 —— 移动端关掉，
    # 跟手/惯性完全交给 Qt 原生平滑滚动
    for bar in (area.horizontalScrollBar(), area.verticalScrollBar()):
        setSmooth = getattr(bar, "SetSmooth", None)
        if callable(setSmooth):
            setSmooth(False)
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
    """ App 级事件过滤器：**后来才建出来的**滚动区域/标签条自动接管

    真机现象：首页除"最新上传"以外的分区列表完全不能滑动(见模块头)。
    建立即接管是这里唯一要干的事；至于为什么不当场扫、要延迟一拍：
    ChildAdded 是 QWidget 构造函数里发给父控件的，那会儿新控件的 Python 子类
    还没构造完(属性/重写都还没挂上) —— 攒起来用 0ms 定时器推到下一轮事件循环，
    那时控件已经完整，扫出来的结果才靠得住。

    和 _TouchRouter.OnTouch 里的 _AdoptScrollArea 是一件事的两半：这一半"建出来就接管"，
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
        # 只看滚动区域/标签条/点按类控件自己：普通容器不用管 —— 它里面真装了这些，
        # 那个控件建出来时也会各发一次 ChildAdded(漫画 item 那种叶子控件一天几百个，
        # 不筛会白扫)
        if not isinstance(child, (QAbstractScrollArea,) + _TapClassWidgets):
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
        guard = mobile_ui._touchGuard
        for widget in pending:
            if not _WidgetAlive(widget):
                continue
            if isinstance(widget, QTabBar):
                if guard is not None:
                    guard.TabSwipeAttach(widget)
                else:
                    MarkTapClass(widget)
                continue
            if isinstance(widget, _TapClassWidgets):
                MarkTapClass(widget)
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
        Log.Warn("portrait: 后建滚动区域/标签条自动接管已开启(分区页/详情页/工具菜单等)")
    mobile_ui._scrollWatcher.Adopted += EnableTouchScroll(mainView)
    return mobile_ui._scrollWatcher


def ScrollWatcherStats():
    """ 给宿主回归与真机自检看：新滚动了几个、扫了几轮 """
    if mobile_ui._scrollWatcher is None:
        return None
    return mobile_ui._scrollWatcher.Stats()
