# coding:utf-8
""" 看图界面（工具菜单整宽 + 看图区拖动滚动 + 双指缩放） """
from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QTimer
from PySide6.QtGui import QEventPoint, QMouseEvent
from PySide6.QtWidgets import QApplication
from tools.log import Log
from tools.mobile_ui_base import *  # noqa: F401,F403
from tools.mobile_ui_base import _EventLocalPos
from tools import mobile_ui




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
        # 覆盖了它，这里只补看图区自己的拖动滚动 + 双指缩放
        InstallReaderDrag(readView)
        InstallReaderPinch(readView)
        mobile_ui.EnableTouchScroll(readView)
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
        self.Cancels = 0
        self.LastDelta = 0

    def CancelPress(self):
        """ 取消当前这次"按下"(双指缩放开始时调用)

        双指开始时手上还按着一根手指：那次 press 已经发给场景了，如果直接松手会被
        当成"点按"(翻页/弹菜单)，而合成一次移动又会让图片真的滚一下(到边界还会触发
        翻页 —— 翻页会弹加载框，正好踩上"输入事件里 show 窗口"那个崩溃)。
        所以这里把状态改成"已拖动"：随后的 release 被吃掉，场景什么都收不到，
        不滚动、不翻页、不弹任何窗口。
        """
        if not self._pressed:
            return
        self._pressed = False
        self._dragging = True
        self.Cancels += 1
        return

    def eventFilter(self, obj, event):
        try:
            eventType = event.type()
            if eventType == QEvent.Type.MouseButtonPress:
                self._pressed = True
                self._dragging = False
                self._pressPos = _EventLocalPos(event)
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
            pos = _EventLocalPos(event)
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
    try:
        if readView is None or mobile_ui._readerDrag is not None:
            return
        view = getattr(getattr(readView, "frame", None), "scrollArea", None)
        if view is None:
            return
        target = view.viewport()
        if target is None:
            target = view
        mobile_ui._readerDrag = _ReaderDrag(view, view)
        target.installEventFilter(mobile_ui._readerDrag)
        Log.Warn("reader drag: 看图区拖动滚动已接管 ({})".format(type(target).__name__))
    except Exception as es:
        Log.Error(es)
    return


# ---------------------------------------------------------------------------
# 双指缩放
# ---------------------------------------------------------------------------
#
# 真机现象："看图页面无法通过双指放大缩小"。
#
# 根因：整条看图链路都建立在**鼠标事件**上 ——
#   * 拖动滚动：`_ReaderDrag`(`_ReaderDrag` 的 MouseButtonPress/MouseMove/Release)
#   * 点按三分区翻页/弹菜单：`read_graphics.eventFilter` 里的 GraphicsSceneMousePress/Release
# 而 Qt 只有在控件**不**接受触摸事件时才把触摸合成为鼠标事件，所以这里一旦
# `setAttribute(WA_AcceptTouchEvents)`，Qt 就不再合成鼠标事件，上面两套逻辑会一起失效。
#
# 因此本过滤器把"一根手指"的触摸序列**原样合成为鼠标事件**再发给视口(拖动/点按语义
# 一点都不变)，只把"两根手指"拦下来做缩放。这样：
#   * 1 指：与改造前完全一样(拖动滚动、点按翻页)
#   * 2 指：按两指距离比例缩放，落到和菜单"缩放"同一个入口(ScalePicture2)
#
# 1 指 -> 2 指(用户先落一根手指、再落第二根)时，按下事件已经发出去了，
# 如果直接松手就会被场景当成"点按"(误翻页/误弹菜单)。所以先合成一次
# PinchCancelPx 像素的移动再松手：拖动阈值(TouchSlopPx)与场景点按的 20px 判定
# 都会把它当拖动，那一下就不会被当成点按(屏幕上只偏移 25px，松手后可忽略)。

# 缩放的上下限(百分比，与工具栏滑块范围一致)
PinchMinPercent = 20
PinchMaxPercent = 500
# 抬手时百分比变化小于这个值就当没动(1px 的手指抖动不值得重排整页)
PinchStepPercent = 5


def _TouchPoints(event):
    """ 取出这次触摸事件里**还按着**的点 [(本地坐标, 全局坐标), ...] """
    points = []
    try:
        for point in event.points():
            try:
                if point.state() == QEventPoint.State.Released:
                    continue
            except Exception:
                pass
            points.append((point.position(), point.globalPosition()))
    except Exception:
        pass
    return points


def _Distance(points):
    """ 两指距离(多于两点时取前两点) """
    if len(points) < 2:
        return 0.0
    dx = points[1][0].x() - points[0][0].x()
    dy = points[1][0].y() - points[0][0].y()
    return (dx * dx + dy * dy) ** 0.5


class _ReaderPinch(QObject):
    """ 看图区触摸：1 指合成为鼠标事件(拖动/点按)，2 指缩放 """

    def __init__(self, view, readView, parent=None):
        super().__init__(parent)
        self._view = view
        self._readView = readView
        self._target = None
        self._mouseDown = False
        self._lastPos = None
        self._pinching = False
        self._startDist = 0.0
        self._basePercent = 100
        self._ratio = 1.0
        self.Touches = 0
        self.Pinches = 0
        self.LastPercent = 100

    def Reset(self):
        self._mouseDown = False
        self._lastPos = None
        self._pinching = False
        self._startDist = 0.0
        self._ratio = 1.0

    # -- 事件 --------------------------------------------------------------
    def eventFilter(self, obj, event):
        try:
            eventType = event.type()
            if eventType == QEvent.Type.TouchBegin:
                return self.OnBegin(event)
            if eventType == QEvent.Type.TouchUpdate:
                return self.OnUpdate(event)
            if eventType in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
                return self.OnEnd(event, eventType == QEvent.Type.TouchCancel)
        except Exception as es:
            Log.Error(es)
            self.Reset()
        return False

    def OnBegin(self, event):
        points = _TouchPoints(event)
        self.Touches += 1
        if len(points) >= 2:
            self.StartPinch(points)
            return True
        if self._pinching and points:
            # 缩放中途又落了一根手指：继续缩放，别退回鼠标语义
            return True
        if len(points) == 1:
            self._mouseDown = True
            self._lastPos = points[0][0]
            self._Send(QEvent.Type.MouseButtonPress, points[0])
            return True
        return False

    def OnUpdate(self, event):
        points = _TouchPoints(event)
        if len(points) >= 2:
            if not self._pinching:
                self.StartPinch(points)
            else:
                self.ApplyPinch(points)
            return True
        if self._pinching:
            return True
        if self._mouseDown and points:
            self._lastPos = points[0][0]
            self._Send(QEvent.Type.MouseMove, points[0])
            return True
        return False

    def OnEnd(self, event, cancelled):
        points = _TouchPoints(event)
        pinching = self._pinching
        if self._mouseDown and not cancelled:
            pos = points[0] if points else None
            if pos is None and self._lastPos is not None:
                pos = (self._lastPos, self._lastPos)
            if pos is not None:
                self._Send(QEvent.Type.MouseButtonRelease, pos)
        if cancelled and self._mouseDown:
            self._Send(QEvent.Type.MouseButtonRelease,
                       (self._lastPos or QPointF(0, 0), self._lastPos or QPointF(0, 0)))
        if pinching and not cancelled:
            # 抬手才真正应用缩放(见 ApplyPinch 的注释)
            self.FinishPinch()
        self.Reset()
        return True

    # -- 缩放 --------------------------------------------------------------
    def StartPinch(self, points):
        """ 进入缩放态：把手上那次"按下"作废(不滚动/不翻页，见 _ReaderDrag.CancelPress) """
        if self._mouseDown:
            drag = mobile_ui._readerDrag
            if drag is not None and hasattr(drag, "CancelPress"):
                drag.CancelPress()
            local = self._lastPos or points[0][0]
            self._Send(QEvent.Type.MouseButtonRelease, (local, points[0][1]))
            self._mouseDown = False
        self._pinching = True
        self._startDist = _Distance(points)
        self._basePercent = self.CurrentPercent()
        self._ratio = 1.0
        self.LastPercent = self._basePercent
        self.Pinches += 1
        Log.Warn("reader pinch: 开始双指缩放(base={}%)".format(self._basePercent))
        return

    def ApplyPinch(self, points):
        """ 缩放过程中**只记比例**，不重排图形

        以前这里每动 5% 就调一次 ScalePicture2 —— 那会走 changeScale -> 整页重排
        (几十张图重新定位)，手指还在屏幕上时做这个，真机直接卡住(C 侧 qnn/图像线程
        也被拖慢)。改成抬手时算一次、下一轮事件循环再应用：既不卡，也不会在输入
        事件处理里改布局。
        """
        if self._startDist <= 1.0:
            self._startDist = _Distance(points)
            return
        dist = _Distance(points)
        if dist <= 1.0:
            return
        self._ratio = dist / self._startDist
        return

    def FinishPinch(self):
        """ 抬手：算出目标百分比，延后一拍应用(见 ApplyPinch 的注释) """
        if not self._pinching:
            return
        base = self._basePercent
        ratio = self._ratio if self._ratio > 0 else 1.0
        percent = int(round(base * ratio))
        percent = max(PinchMinPercent, min(PinchMaxPercent, percent))
        if abs(percent - base) < PinchStepPercent:
            return
        self.LastPercent = percent
        QTimer.singleShot(0, lambda: self.ScaleTo(percent))
        Log.Warn("reader pinch: 应用缩放 {}% -> {}%".format(base, percent))
        return

    def CurrentPercent(self):
        """ 当前缩放百分比(来自 scaleCnt：scaleCnt=0 -> 100%) """
        try:
            scaleCnt = int(getattr(getattr(self._readView, "frame", None), "scaleCnt", 0))
        except Exception:
            scaleCnt = 0
        return max(PinchMinPercent, min(PinchMaxPercent, 100 + scaleCnt * 10))

    def ScaleTo(self, percent):
        """ 走和菜单"缩放"完全相同的入口(滑块 -> ScalePicture) """
        try:
            tool = getattr(self._readView, "qtTool", None)
            if tool is None:
                return
            tool.ScalePicture2(percent)
        except Exception as es:
            Log.Error(es)
        return

    # -- 合成鼠标 ----------------------------------------------------------
    def _Send(self, eventType, pos):
        target = self._target
        if target is None:
            return
        local, glob = pos
        if eventType == QEvent.Type.MouseButtonRelease:
            buttons = Qt.MouseButton.NoButton
        else:
            buttons = Qt.MouseButton.LeftButton
        try:
            event = QMouseEvent(eventType, local, local, glob,
                                Qt.MouseButton.LeftButton, buttons,
                                Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(target, event)
        except Exception as es:
            Log.Error(es)
        return


def InstallReaderPinch(readView):
    """ 给看图区装上双指缩放(移动端) """
    try:
        if readView is None or mobile_ui._readerPinch is not None:
            return
        view = getattr(getattr(readView, "frame", None), "scrollArea", None)
        if view is None:
            return
        target = view.viewport()
        if target is None:
            target = view
        pinch = _ReaderPinch(view, readView, view)
        pinch._target = target
        # 只有接受触摸事件才会收到 QTouchEvent；代价是 Qt 不再合成鼠标事件，
        # 由 _ReaderPinch 自己合成(见模块注释)
        target.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        target.installEventFilter(pinch)
        mobile_ui._readerPinch = pinch
        Log.Warn("reader pinch: 双指缩放已接管 ({})".format(type(target).__name__))
    except Exception as es:
        Log.Error(es)
    return
