# coding:utf-8
""" 看图界面（工具菜单整宽 + 看图区拖动滚动 + 双指缩放） """
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QTimer
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
        self._carryX = 0.0
        self._carryY = 0.0
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
                self._carryX = 0.0
                self._carryY = 0.0
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
            initMode = view.initReadMode
            upDown = ReadMode.isUpDown(initMode)
            try:
                zoomed = int(getattr(view, "scaleCnt", 0) or 0) != 0
            except Exception:
                zoomed = False

            if ReadMode.isScroll(initMode):
                # 滚动模式：**放大后两个方向都要能平移**
                # 滚动模式的缩放是视图变换，放大后图片横向/纵向都比视口大，
                # 只滚"当前轴"就永远看不到另一边 —— 真机现象：
                # "上下滚动模式双指放大后无法左右滑动查看图片其他部分"
                # (左右/右左滚动模式同理：放大后看不到上下)
                if zoomed:
                    self._Pan(dx, dy, flipX=(initMode == ReadMode.RightLeftScroll2))
                    return
                # 100%：只滚当前轴
                delta = -dy if upDown else -dx
                self._carry += delta
                step = int(self._carry)
                if step == 0:
                    return
                self._carry -= step
                if upDown:
                    view.vScrollBar.scrollValue(step)
                elif initMode == ReadMode.RightLeftScroll2:
                    view.hScrollBar.scrollValue(-step)
                else:
                    view.hScrollBar.scrollValue(step)
                self.Scrolled += 1
                self.LastDelta = step
                return

            # 单页/双页：放大后**先平移**看图的其它部分(见 _Pan 的注释)
            if zoomed:
                self._Pan(dx, dy)
                return

            # 没放大：滑到边界翻页(和滚轮一致)
            bar = view.vScrollBar if upDown else view.hScrollBar
            delta = -dy if upDown else -dx
            self._carry += delta
            step = int(self._carry)
            if step == 0:
                return
            self._carry -= step
            if step > 0 and abs(bar.value() - bar.maximum()) <= 5:
                view.qtTool.NextPage()
                return
            if step < 0 and bar.value() <= 5:
                view.qtTool.LastPage()
                return
            self.Scrolled += 1
            self.LastDelta = step
        except Exception as es:
            Log.Error(es)
        return

    def _Pan(self, dx, dy, flipX=False):
        """ **放大后**的双向平移

        以前这里只吃横向位移(纵向 dy 直接丢掉)，横向又因为放大后
        hScrollBar.maximum 一直是 0(ResetMaxNum 里那几行被注释掉了) 而永远
        被判成"在边界" -> 一滑就翻页。真机现象就是"双指缩放后左右滑动切页，
        没法看放大后的其它部分"。

        flipX：右左滚动的布局是从右往左排的，横向方向要和滚轮一致地取反。
        """
        view = self._view
        dx = -dx if flipX else dx
        self._carryX += -dx
        stepX = int(self._carryX)
        if stepX:
            self._carryX -= stepX
            view.hScrollBar.scrollValue(stepX)
            self.Scrolled += 1
            self.LastDelta = stepX
        self._carryY += -dy
        stepY = int(self._carryY)
        if stepY:
            self._carryY -= stepY
            view.vScrollBar.scrollValue(stepY)
            self.Scrolled += 1
            self.LastDelta = stepY
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
# 整条看图链路都建立在**鼠标事件**上 ——
#   * 拖动滚动：_ReaderDrag(MouseButtonPress/Move/Release)
#   * 点按三分区翻页/弹菜单：read_graphics.eventFilter 里的 GraphicsSceneMousePress/Release
# 而 Qt 只有在控件**不**接受触摸事件时才把触摸合成为鼠标事件，所以这里一旦
# setAttribute(WA_AcceptTouchEvents)，上面两套逻辑会一起失效。
#
# 因此本过滤器把"一根手指"的触摸序列**原样合成为鼠标事件**再发给视口(拖动/点按
# 语义一点都不变)，只把"两根手指"拦下来做缩放。
#
# **为什么要按 QEventPoint.id() 合并**：Qt 的多点触摸是"每个触点一个目标控件"的，
# 手指落在哪个窗口上，那个点就走哪条序列。看图区里滚动模式下**相邻页**是
# QGraphicsProxyWidget 里嵌的**真实子窗口**(InitAllQLabel 把它们建成和视口一样大)，
# 两根手指常常一根落在图元上、一根落在相邻页的窗口上 —— 那是**两条独立的触摸
# 序列**，每条只有一个点。只看"这次事件里有几个点"永远等不到两个点，双指缩放
# 就完全不启动(真机现象：上下/左右/右左滚动模式下无法双指缩放；单页模式整页
# 就是一个大窗口、两根手指都落在它身上，所以那边好使)。
# 所以这里把各条序列的触点按 id 累积起来，够两个就进缩放。
#
# 1 指 -> 2 指 时按下事件已经发出去了：直接松手会被场景当成"点按"(翻页/弹菜单)，
# 所以走 _ReaderDrag.CancelPress() 作废那次按下(release 被吃掉，不滚动也不翻页)。

# 缩放的上下限(百分比，与工具栏滑块范围一致)
PinchMinPercent = 20
PinchMaxPercent = 500
# 抬手时百分比变化小于这个值就当没动(1px 的手指抖动不值得重排整页)
PinchStepPercent = 5


class _ReaderPinch(QObject):
    """ 看图区触摸：1 指合成为鼠标事件(拖动/点按)，2 指缩放 """

    def __init__(self, view, readView, parent=None):
        super().__init__(parent)
        self._view = view
        self._readView = readView
        self._target = None
        # {触点id: (本地坐标, 全局坐标)} —— 各条触摸序列按 id 合并(见模块注释)
        self._points = {}
        self._primary = None        # 正在驱动鼠标语义的那个触点
        self._swallow = False       # 缩放之后剩下的手指直接吞掉(否则松手变点按)
        self._pinching = False
        self._startDist = 0.0
        self._basePercent = 100
        self._ratio = 1.0
        self._liveRatio = 1.0
        self.Touches = 0
        self.Pinches = 0
        self.LastPercent = 100

    def Reset(self):
        # 先撤掉预览用的视图变换(被打断时可能停在半缩放状态)
        self.ResetPreview()
        self._points.clear()
        self._primary = None
        self._swallow = False
        self._pinching = False
        self._startDist = 0.0
        self._ratio = 1.0

    # -- 事件 --------------------------------------------------------------
    def eventFilter(self, obj, event):
        try:
            eventType = event.type()
            if eventType == QEvent.Type.TouchBegin:
                return self.OnTouch(event, 0)
            if eventType == QEvent.Type.TouchUpdate:
                return self.OnTouch(event, 1)
            if eventType == QEvent.Type.TouchEnd:
                return self.OnTouch(event, 2)
            if eventType == QEvent.Type.TouchCancel:
                return self.OnTouch(event, 3)
        except Exception as es:
            Log.Error(es)
            self.Reset()
        return False

    def OnTouch(self, event, kind):
        if kind == 3:
            # 被打断(来电/系统手势)：这次按下作废，预览撤掉
            self.CancelMouse()
            self.Reset()
            return True
        released = self._Merge(event)
        if kind == 0:
            self.Touches += 1
        elif kind == 2:
            # TouchEnd 一定意味着这条序列结束了：把这次事件里还没被清掉的点
            # 一并作废(个别平台最后一个点不带 Released 状态，留着会污染下一次手势)
            try:
                for point in event.points():
                    pid = point.id()
                    if pid in self._points:
                        released.append((pid, point.globalPosition()))
                        del self._points[pid]
            except Exception:
                pass
        for pid, glob in released:
            if pid == self._primary:
                # 主手指松开：给这次"按下"收尾(场景靠它判点按)
                self._Send(QEvent.Type.MouseButtonRelease, glob)
                self._primary = None
        self._Sync()
        return True

    def _Merge(self, event):
        """ 把这次事件里的触点合并进活动表，返回刚松开的 [(id, 全局坐标)] """
        released = []
        try:
            points = event.points()
        except Exception:
            return released
        for point in points:
            try:
                pid = point.id()
                state = point.state()
                glob = point.globalPosition()
                local = point.position()
            except Exception:
                continue
            if state == QEventPoint.State.Released:
                if pid in self._points:
                    released.append((pid, glob))
                    del self._points[pid]
            else:
                self._points[pid] = (local, glob)
        return released

    def _Sync(self):
        """ 按当前活动触点数同步"鼠标/缩放"状态 """
        count = len(self._points)
        if count >= 2:
            if not self._pinching:
                self.StartPinch()
            else:
                self.ApplyPinch()
            return
        if self._pinching:
            # 2 指 -> 1 指(或直接 0 指)：结算缩放。
            # 剩下的手指要吞掉 —— 否则它会被当成新的按下，松手就变"点按"翻页
            self.FinishPinch()
            self._swallow = count > 0
            if count == 0:
                self._primary = None
            return
        if count == 1:
            if self._swallow:
                return
            pid = next(iter(self._points))
            if self._primary is None:
                self._primary = pid
                self._Send(QEvent.Type.MouseButtonPress, self._points[pid][1])
            elif pid == self._primary:
                self._Send(QEvent.Type.MouseMove, self._points[pid][1])
            return
        # count == 0：这次触摸彻底结束
        self._primary = None
        self._swallow = False
        return

    # -- 缩放 --------------------------------------------------------------
    def StartPinch(self):
        """ 进入缩放态：把手上的那次"按下"作废(不滚动/不翻页) """
        self.CancelMouse()
        self._pinching = True
        self._startDist = self._PinchDist()
        self._basePercent = self.CurrentPercent()
        self._ratio = 1.0
        self.LastPercent = self._basePercent
        self.Pinches += 1
        try:
            mode = self._readView.qtTool.stripModel
        except Exception:
            mode = None
        Log.Warn("reader pinch: 开始双指缩放(base={}%, 模式={}, 距离={:.0f}, 触点数={})".format(
            self._basePercent, mode, self._startDist, len(self._points)))
        # 诊断：每个触点下面是什么控件(见模块注释里"两条序列"那段)
        self._LogFingers()
        return

    def _PinchDist(self):
        """ 两指距离(多于两点时取前两点) —— 必须用**全局坐标**：
        两根手指可能落在不同控件上，各自的本地坐标不可比 """
        points = list(self._points.values())
        if len(points) < 2:
            return 0.0
        dx = points[1][1].x() - points[0][1].x()
        dy = points[1][1].y() - points[0][1].y()
        return (dx * dx + dy * dy) ** 0.5

    def ApplyPinch(self):
        """ 缩放过程中只做**视图缩放预览**(QGraphicsView.scale)，抬手才真正重排

        为什么不能用 ScalePicture2 做实时缩放：它走 changeScale -> ShowImgAll，
        手指还在屏幕上时干这个，真机上就是卡住不动(还可能顺带触发重解码)。改成：
          * 手势中：`QGraphicsView.scale(step, step)` —— 只改绘制变换，不动图元，
            每帧几乎零成本，跟手
          * 抬手时：先 resetTransform() 复位，再按目标百分比走一次 ScalePicture2
            (整页重排只发生一次，且延后到事件循环外)
        """
        dist = self._PinchDist()
        if self._startDist <= 1.0:
            self._startDist = dist
            return
        if dist <= 1.0:
            return
        self._ratio = dist / self._startDist
        self.ApplyPreview(self._ratio)
        return

    def ApplyPreview(self, ratio):
        """ 按累计比例做视图缩放(只画，不重排) """
        view = self._view
        if view is None or not hasattr(view, "scale"):
            return
        try:
            target = max(PinchMinPercent / 100.0,
                         min(PinchMaxPercent / 100.0, max(0.05, ratio)))
            step = target / max(0.05, self._liveRatio)
            if abs(step - 1.0) < 0.01:
                return
            # 预览期间禁止"滚动值变化 -> 换页"(见 read_scroll.OnValueChange)
            view._jmPinchPreview = True
            view.scale(step, step)
            self._liveRatio = target
        except Exception as es:
            Log.Error(es)
        return

    def ResetPreview(self):
        """ 撤掉预览用的视图缩放(不碰 scaleCnt) """
        view = self._view
        if view is not None:
            try:
                view._jmPinchPreview = False
            except Exception:
                pass
        if abs(self._liveRatio - 1.0) < 0.001:
            return
        try:
            view.resetTransform()
        except Exception as es:
            Log.Error(es)
        self._liveRatio = 1.0
        return

    def FinishPinch(self):
        """ 抬手：撤掉预览，按目标百分比走一次真正的重排 """
        if not self._pinching:
            return
        self._pinching = False
        base = self._basePercent
        ratio = self._ratio if self._ratio > 0 else 1.0
        self.ResetPreview()
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
        self._liveRatio = 1.0
        return

    # -- 合成鼠标 ----------------------------------------------------------
    def CancelMouse(self):
        """ 作废手上这次"按下"

        改成"已拖动"状态后，随后的 release 会被 _ReaderDrag 吃掉 —— 不滚动、
        不翻页、不弹窗口(否则 1 指转 2 指那一下会被场景当成点按)。
        """
        if self._primary is None:
            return
        drag = mobile_ui._readerDrag
        if drag is not None and hasattr(drag, "CancelPress"):
            drag.CancelPress()
        point = self._points.get(self._primary)
        if point is not None:
            self._Send(QEvent.Type.MouseButtonRelease, point[1])
        self._primary = None
        return

    def _Send(self, eventType, glob):
        """ 合成鼠标事件发给视口(坐标从**全局**换算 —— 触点可能来自别的控件) """
        target = self._target
        if target is None or glob is None:
            return
        try:
            local = target.mapFromGlobal(QPoint(int(glob.x()), int(glob.y())))
            if eventType == QEvent.Type.MouseButtonRelease:
                buttons = Qt.MouseButton.NoButton
            else:
                buttons = Qt.MouseButton.LeftButton
            event = QMouseEvent(eventType, local, local, glob,
                                Qt.MouseButton.LeftButton, buttons,
                                Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(target, event)
        except Exception as es:
            Log.Error(es)
        return

    def _LogFingers(self):
        """ 诊断：记录每个触点下面的控件 """
        try:
            for pid in list(self._points.keys()):
                local, glob = self._points[pid]
                widget = QApplication.widgetAt(QPoint(int(glob.x()), int(glob.y())))
                Log.Warn("reader pinch: 触点 {} 在({:.0f},{:.0f}) 下面 = {}".format(
                    pid, glob.x(), glob.y(),
                    type(widget).__name__ if widget is not None else "None"))
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
