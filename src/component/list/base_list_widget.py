from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QListWidget, QAbstractItemView

from component.scroll.smooth_scroll_bar import SmoothScrollBar
from qt_owner import QtOwner
from task.qt_task import QtTaskBase
from tools.str import Str


class BaseListWidget(QListWidget, QtTaskBase):
    def __init__(self, parent):
        QListWidget.__init__(self, parent)
        QtTaskBase.__init__(self)
        self.page = 1
        self.pages = 1
        # self.verticalScrollBar().valueChanged.connect(self.OnMove)
        self.isLoadingPage = False
        self.LoadCallBack = None
        self.OpenBack = None
        self.LikeBack = None
        self.KillBack = None
        self.parentId = -1
        self.vScrollBar = SmoothScrollBar()
        self.vScrollBar.setOrientation(Qt.Vertical)
        self.setVerticalScrollBar(self.vScrollBar)
        # 翻页(滚到底加载下一页)挂 C++ 级的 valueChanged：
        # 移动端是 QScroller(C++) 直接改滚动条值，不会走 Python 覆写的 setValue，
        # 纯 Python 信号 MoveEvent 在触控滚动下不会发 —— 挂它会让移动端"加载更多"静默失效。
        self.verticalScrollBar().valueChanged.connect(self.OnActionTriggered)

        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(30)
        # self.timer = QTimer()
        # self.timer.setInterval(1000)
        # self.timer.timeout.connect(self.TimeOut)

        self.wheelStatus = True
        self.lastClick = 0
        self.lastIndex = -1
        self.doubleClickType = 0

    # def event(self, e) -> bool:
    #     print(e)
    #     return QListWidget.event(self, e)

    def ClearWheelEvent(self):
        pass
        # self.vScrollBar.stop()

    def SetWheelStatus(self, status):
        self.wheelStatus = status

    def wheelEvent(self, arg__1) -> None:
        if not self.wheelStatus:
            return
        self.vScrollBar.ScrollValue(-arg__1.angleDelta().y())

    def OnActionTriggered(self):
        if self.isLoadingPage:
            return
        if self.page >= self.pages:
            return
        if self.verticalScrollBar().sliderPosition() == self.verticalScrollBar().maximum():
            self.ClearWheelEvent()
            self.isLoadingPage = True
            if self.LoadCallBack:
                self.LoadCallBack()

    def UpdatePage(self, page, pages):
        self.page = page
        self.pages = pages
        self.UpdateState()

    def UpdateMaxPage(self, pages):
        self.pages = pages

    def UpdateState(self, isLoading=False):
        self.isLoadingPage = isLoading

    def GetPageStr(self):
        return Str.GetStr(Str.Page) + ": " + str(self.page) + "/" + str(self.pages)

    def clear(self) -> None:
        QListWidget.clear(self)

        # 防止异步加载时，信息错乱
        self.ClearTask()
        if self.vScrollBar:
            self.vScrollBar.ResetValue(0)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.ForwardButton:
            # QtOwner().SwitchWidgetNext()
            event.ignore()
        elif event.button() == Qt.BackButton:
            event.ignore()
            # QtOwner().SwitchWidgetLast()
        return QListWidget.mousePressEvent(self, event)