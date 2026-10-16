# coding:utf-8
""" 触摸控件（滚动接管 QScroller + 滑动防误触） """
from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QAbstractItemView, QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QGraphicsView, QScroller, QScrollerProperties, QScrollBar, QSlider, QWidget
from tools.log import Log
from tools.mobile_ui_base import *  # noqa: F401,F403
from tools.mobile_ui_base import (_DescribeWidget, _GuardMode, _InPopup, _InTouchArea, _IsDescendant, _WidgetAlive)
from tools import mobile_ui



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
