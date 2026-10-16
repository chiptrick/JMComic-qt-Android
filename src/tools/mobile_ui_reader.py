# coding:utf-8
""" 看图界面（工具菜单整宽 + 看图区拖动滚动） """
from PySide6.QtCore import QEvent, QObject
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
        # 覆盖了它，这里只补看图区自己的拖动滚动
        InstallReaderDrag(readView)
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
        self.LastDelta = 0

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
