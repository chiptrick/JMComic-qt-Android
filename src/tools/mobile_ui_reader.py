# coding:utf-8
""" 看图界面（工具菜单整宽 + 看图区触控：拖动滚动 / 双指缩放 / 点按三分区）

看图区的触控**完全在 QTouchEvent 上实现**，不再把触控合成为鼠标事件：
旧实现里"1 根手指"要自己合成 QMouseEvent 喂给场景(拖动/点按全靠 Qt 的鼠标链)，
现在 1 指拖动直接调用看图控件自己的滚动/翻页入口(ReadScroll.scrollValue，
和滚轮同一条路径)，1 指点按直接走三分区动作(弹菜单/半页滚动/翻页)，
2 指缩放沿用"手势中只做视图变换预览、抬手才整页重排"的方案。

**为什么要按 QEventPoint.id() 跨序列合并触点**：Qt 的多点触摸是"每个触点一个
目标控件"的，手指落在哪个窗口上，那个点就走哪条序列。看图区里滚动模式下
**相邻页**是嵌在视口上的真实子窗口(InitAllQLabel 把它们建成和视口一样大)，
两根手指常常一根落在图元上、一根落在相邻页的窗口上 —— 那是**两条独立的触摸
序列**，每条只有一个点。只看"这次事件里有几个点"永远等不到两个点，双指缩放
就完全不启动(真机现象：上下/左右/右左滚动模式下无法双指缩放)。所以这里把各条
序列的触点按 id 累积起来，够两个就进缩放。

1 指 -> 2 指 的转换：手上那次"拖动"直接作废(状态清掉)，缩放结束后剩下的手指
继续按"已吞掉"处理 —— 松手不能变成点按(否则会翻页/弹菜单)。

滚动模式下的 1 指拖动是**立即置值**(ReadScroll.DragScroll)，不套 200ms 补间：
手指到哪、图到哪。任何补间都会让滚动条值滞后于手指，抬手后还会继续飘并冲过
手指位置(原因与实测数据见 ReadScroll.DragScroll 的注释)。

翻页模式(单页/双页/等宽，非滚动)下的"滑动翻页"是**一次手势只翻一页**：
判定 = **翻页轴**上、以按下位置为基准的累计位移超过 TurnPageSlopPx，且滚动条
停在对应边界(和滚轮一致：页尾再往前 -> 下一页，页首再往后 -> 上一页)。翻页轴
按模式定：左右/右左的单页与双页是**横向**(ReadMode.isHorizontalPage)，等宽/
上下模式是纵向；轴在本手势第一次越过阈值时锁定，之后不再换轴。翻过页
之后本手势直接作废 —— 手指继续滑、甚至反方向滑都不再翻页，想继续翻必须重新
按下。这样一次滑动和"点按一下翻一页 / 滚轮一格翻一页"一一对应，不会一滑跳过
好几页(旧实现按每个 TouchUpdate 的增量判定，而翻页模式下滚动条一直停在边界，
一次长滑会连翻十几页)。滚动模式是连续滚动，没有这个锁，行为完全不变。
"""
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QEventPoint
from PySide6.QtWidgets import QApplication
from tools.log import Log
from tools.mobile_ui_base import *  # noqa: F401,F403
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
        # 覆盖了它，这里只补看图区自己的触控(拖动滚动 + 双指缩放 + 点按三分区)
        InstallReaderTouch(readView)
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


# 缩放的上下限(百分比，与工具栏滑块范围一致)
PinchMinPercent = 20
PinchMaxPercent = 500
# 抬手时百分比变化小于这个值就当没动(1px 的手指抖动不值得重排整页)
PinchStepPercent = 5


class _ReaderTouch(QObject):
    """ 看图区触控：1 指拖动/点按，2 指缩放(全部在 QTouchEvent 上，不合成鼠标) """

    def __init__(self, view, readView, parent=None):
        super().__init__(parent)
        self._view = view
        self._readView = readView
        # {触点id: (本地坐标, 全局坐标)} —— 各条触摸序列按 id 合并(见模块注释)
        self._points = {}
        self._primary = None        # 驱动单指拖动/点按的那个触点 id
        self._pressPos = None       # 单指按下位置(全局，点按/拖动判定用)
        self._lastPos = None        # 上一次位置(全局，拖动位移用)
        self._dragging = False
        self._swallow = False       # 缩放之后剩下的手指直接吞掉(松手不许变点按)
        self._pinching = False
        # 翻页模式专用(见 _Scroll)：一次手势只翻一页
        # 横向/纵向各自累计，第一次越过阈值的那条轴被锁定(见 _Scroll)，之后不再换轴
        self._turnAccumX = 0.0      # 本手势横向累计位移(以按下位置为基准)
        self._turnAccumY = 0.0      # 本手势纵向累计位移(以按下位置为基准)
        self._turnAxis = None       # 本手势锁定的翻页轴：None / "x" / "y"
        self._turnFired = False     # 本手势是否已经翻过页(翻过即作废，抬手才重置)
        self._startDist = 0.0
        self._basePercent = 100
        self._ratio = 1.0
        self._liveRatio = 1.0
        self._carry = 0.0
        self._carryX = 0.0
        self._carryY = 0.0
        self.Touches = 0
        self.Drags = 0
        self.Scrolled = 0
        self.Cancels = 0
        self.LastDelta = 0
        self.Pinches = 0
        self.Turns = 0            # 翻页模式下滑动翻页的次数(一次手势最多 +1)
        self.LastPercent = 100

    def Reset(self):
        # 先撤掉预览用的视图变换(被打断时可能停在半缩放状态)
        self.ResetPreview()
        self._points.clear()
        self._primary = None
        self._pressPos = None
        self._lastPos = None
        self._dragging = False
        self._swallow = False
        self._pinching = False
        self._turnAccumX = 0.0
        self._turnAccumY = 0.0
        self._turnAxis = None
        self._turnFired = False
        self._startDist = 0.0
        self._ratio = 1.0
        self._carry = 0.0
        self._carryX = 0.0
        self._carryY = 0.0

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
            # 被打断(来电/系统手势)：这次手势作废，预览撤掉
            self.Cancels += 1
            self.Reset()
            return True
        if kind == 0:
            self.Touches += 1
        released = self._Merge(event)
        if kind == 2:
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
        # 单指阶段的位移跟踪(缩放一启动就不再走单指语义)
        if not self._pinching and len(self._points) <= 1 and not self._swallow:
            self._UpdateSingle(event, kind)
        for pid, endPos in released:
            if pid == self._primary:
                # 主触点松手：没拖动过 = 点按三分区(必须整只手都抬完才点按，
                # 另一根手指还在屏上/刚做过缩放时都不许变点按)
                if not self._dragging and not self._swallow and not self._pinching \
                        and not self._points:
                    self._Tap(endPos)
                self._primary = None
                self._dragging = False
                # 手势结束：翻页锁一起复位，下一次按下可以再翻一页
                self._turnAccumX = 0.0
                self._turnAccumY = 0.0
                self._turnAxis = None
                self._turnFired = False
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
                glob = QPointF(point.globalPosition())
                local = QPointF(point.position())
            except Exception:
                continue
            if state == QEventPoint.State.Released:
                if pid in self._points:
                    released.append((pid, glob))
                    del self._points[pid]
            else:
                self._points[pid] = (local, glob)
        return released

    def _UpdateSingle(self, event, kind):
        """ 单指语义：拖动滚动(点按判定在 OnTouch 的松手结算里) """
        # 找到(或认领)主触点
        if self._primary is None and self._points:
            pid = next(iter(self._points))
            self._primary = pid
            self._pressPos = self._points[pid][1]
            self._lastPos = self._pressPos
            self._dragging = False
            # 新的一次手势：翻页轴累计位移/翻页锁都从零开始
            self._turnAccumX = 0.0
            self._turnAccumY = 0.0
            self._turnAxis = None
            self._turnFired = False
        if self._primary is None:
            return
        point = self._points.get(self._primary)
        if point is None:
            return
        glob = point[1]
        if not self._dragging:
            if (glob - self._pressPos).manhattanLength() >= TouchSlopPx:
                self._dragging = True
                self.Drags += 1
                Log.Warn("reader touch: 开始拖动滚动")
        if self._dragging:
            dx = glob.x() - self._lastPos.x()
            dy = glob.y() - self._lastPos.y()
            self._lastPos = glob
            if dx or dy:
                self._Scroll(dx, dy)
        return

    def _Sync(self):
        """ 按当前活动触点数同步"拖动/缩放"状态 """
        count = len(self._points)
        if count >= 2:
            if not self._pinching:
                self.StartPinch()
            else:
                self.ApplyPinch()
            return
        if self._pinching:
            # 2 指 -> 1 指(或直接 0 指)：结算缩放。
            # 剩下的手指要吞掉 —— 否则松手会变成点按翻页
            self.FinishPinch()
            self._swallow = count > 0
            self._primary = None
            self._dragging = False
            return
        if count == 0:
            self._primary = None
            self._dragging = False
            self._swallow = False
            self._turnAccumX = 0.0
            self._turnAccumY = 0.0
            self._turnAxis = None
            self._turnFired = False
        return

    # -- 点按三分区 --------------------------------------------------------
    def _Tap(self, glob):
        """ 单指点按：和桌面端"鼠标点按三分区"同一套动作(见 read_graphics.eventFilter)

        放大状态下**不翻页**：手指想平移时常常只滑了十几像素(还在点按判定里)，
        一松手就翻页会把当前视角丢掉。菜单(上半屏)和半页滚动照旧。
        """
        view = self._view
        try:
            frame = view.frame
            if not frame.helpLabel.isHidden():
                frame.helpLabel.hide()
                return
            view.qtTool.CloseScrollAndTurn()
            local = view.mapFromGlobal(QPoint(int(glob.x()), int(glob.y())))
            zoomed = frame.scaleCnt != 0
            if local.x() <= view.width() // 3:
                if local.y() <= view.height() // 2:
                    view.readImg.ShowAndCloseTool()
                elif not zoomed:
                    view.ScrollLastPage()
            elif local.x() <= view.width() // 3 * 2:
                if local.y() <= view.height() // 2:
                    view.ScrollValue(-view.height() / 2)
                else:
                    view.ScrollValue(view.height() / 2)
            else:
                if local.y() <= view.height() // 2:
                    view.readImg.ShowAndCloseTool()
                elif not zoomed:
                    view.ScrollNextPage()
        except Exception as es:
            Log.Error(es)
        return

    # -- 拖动滚动 ----------------------------------------------------------
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
                # 必须走 DragScroll(直接置值)：ReadScroll.scrollValue 会给每个
                # TouchUpdate 套 200ms 补间动画，滚动条值永远追不上手指(实测
                # 600px/s 恒定落后十几像素)，抬手后还要再飘 200ms、并冲过手指
                # 位置一百多像素 —— 真机现象就是"滚动模式拖不动/滑过头"。
                #
                # 横向三种模式的手指方向各差一档(都是内容跟手，差别在排版)：
                #   左右滚动       手指左移 -> 值增大 -> 下一页
                #   右左滚动       页面从右往左排，手指左移仍是值增大，但铺开的是
                #                  "回看"页(前进 = 值减小；内容跟手本身就正确)
                #   右左滚动(正序)  取反：手指左移 -> 值减小 -> 下一页(和左右滚动一致)
                if upDown:
                    view.vScrollBar.DragScroll(step)
                elif initMode == ReadMode.RightLeftScroll2:
                    view.hScrollBar.DragScroll(-step)
                else:
                    view.hScrollBar.DragScroll(step)
                self.Scrolled += 1
                self.LastDelta = step
                return

            # 单页/双页：放大后**先平移**看图的其它部分(见 _Pan 的注释)
            if zoomed:
                self._Pan(dx, dy)
                return

            # 没放大：翻页模式 —— **一次手势只翻一页**(与点按/滚轮翻页一一对应)
            #
            # 旧实现按"每个 TouchUpdate 的增量"判定：翻页轴向上只要攒够 1px 且
            # 滚动条在边界就翻一页，而翻页模式下松手前滚动条一直停在边界(100%
            # 时 maximum 就是 0，首尾两个判定同时成立)，于是一次长滑会跟着每个
            # update 连翻十几页 —— 真机现象"轻轻一滑跳过好几张"。
            #
            # 判定(全部满足才翻，且翻完本手势作废)：
            #   1. 本手势还没翻过页：每根手指从按下到抬起最多翻一页，想继续翻
            #      必须重新按下(和点按一下翻一页、滚轮一格翻一页一致)；
            #   2. 在**翻页轴**上的累计位移超过 TurnPageSlopPx：
            #      左右/右左单页双页是**横向**轴(见 ReadMode.isHorizontalPage)，
            #      等宽/上下模式沿用纵向轴；
            #   3. 滚动条停在对应边界(和滚轮一致：页尾再往前 -> 下一页，
            #      页首再往后 -> 上一页；100% 时首尾是同一个位置，方向决定翻哪边)。
            #
            # 翻页轴在本手势第一次越过阈值时锁定，之后不再换轴(斜着滑也不会
            # 因为另一条轴后来居上而突然按另一个方向翻)。
            if self._turnFired:
                return
            horizontal = ReadMode.isHorizontalPage(initMode)
            self._turnAccumX += -dx
            self._turnAccumY += -dy
            if self._turnAxis is None:
                ax, ay = abs(self._turnAccumX), abs(self._turnAccumY)
                # 横向翻页模式里横向优先(左右滑动才是这类模式的"翻页"手势)；
                # 纵向手势保留为旧行为(以前只能上下滑翻页)，取位移更大的那条
                if horizontal and ax >= TurnPageSlopPx and ax >= ay:
                    self._turnAxis = "x"
                elif ay >= TurnPageSlopPx:
                    self._turnAxis = "y"
                elif horizontal and ax >= TurnPageSlopPx:
                    self._turnAxis = "x"
                else:
                    return
            if self._turnAxis == "x":
                accum, bar = self._turnAccumX, view.hScrollBar
            else:
                accum, bar = self._turnAccumY, view.vScrollBar
            if accum > 0:
                if abs(bar.value() - bar.maximum()) > 5:
                    return
                view.qtTool.NextPage()
            else:
                if bar.value() > 5:
                    return
                view.qtTool.LastPage()
            # 翻过页了：本手势直接作废(继续滑/反方向滑都不再翻)，抬手才重置
            self._turnFired = True
            self.Turns += 1
            self.Scrolled += 1
            self.LastDelta = int(accum)
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
            # 平移同样必须 1:1 跟手；notify=False：放大状态下平移绝不结算换页
            view.hScrollBar.DragScroll(stepX, notify=False)
            self.Scrolled += 1
            self.LastDelta = stepX
        self._carryY += -dy
        stepY = int(self._carryY)
        if stepY:
            self._carryY -= stepY
            view.vScrollBar.DragScroll(stepY, notify=False)
            self.Scrolled += 1
            self.LastDelta = stepY
        return

    # -- 双指缩放 ----------------------------------------------------------
    def StartPinch(self):
        """ 进入缩放态：手上的单指拖动作废(不滚动/不翻页/不点按) """
        self._pinching = True
        self._dragging = False
        self._primary = None
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


def InstallReaderTouch(readView):
    """ 给看图区装上触控处理(移动端)：拖动滚动 + 双指缩放 + 点按三分区

    InstallReaderDrag/InstallReaderPinch 都汇到这里(旧接口名保留，
    宿主回归/真机自检引用的是 mobile_ui._readerDrag/_readerPinch)。
    """
    try:
        if readView is None or mobile_ui._readerDrag is not None:
            return
        view = getattr(getattr(readView, "frame", None), "scrollArea", None)
        if view is None:
            return
        target = view.viewport()
        if target is None:
            target = view
        touch = _ReaderTouch(view, readView, view)
        # 只有接受触摸事件才会收到 QTouchEvent(也顺带断掉 Qt 的触控->鼠标合成，
        # 看图区的拖动/点按全部由 _ReaderTouch 自己在触控上实现)
        target.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        target.installEventFilter(touch)
        mobile_ui._readerDrag = touch
        mobile_ui._readerPinch = touch
        Log.Warn("reader touch: 看图区触控已接管(拖动/双指缩放/点按三分区) ({})".format(
            type(target).__name__))
    except Exception as es:
        Log.Error(es)
    return


def InstallReaderDrag(readView):
    """ 旧接口名：看图区拖动滚动(现在是整套触控处理) """
    InstallReaderTouch(readView)
    return


def InstallReaderPinch(readView):
    """ 旧接口名：看图区双指缩放(现在是整套触控处理) """
    InstallReaderTouch(readView)
    return
