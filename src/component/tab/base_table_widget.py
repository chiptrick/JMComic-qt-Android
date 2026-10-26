from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QListWidget, QAbstractItemView, QScroller, QTableWidget

from component.scroll.smooth_scroll_bar import SmoothScrollBar
from config.setting import Setting
from qt_owner import QtOwner
from task.qt_task import QtTaskBase
from tools.str import Str


class BaseTableWidget(QTableWidget):
    def __init__(self, parent):
        QTableWidget.__init__(self, parent)
        # 两个方向都必须逐像素：QScroller 的手势位移是直接当"滚动条值"用的，
        # 默认的 ScrollPerItem 下 1 个手指像素 = 一整行/一整列
        # (真机现象：轻微一滑表格就跳好几行，见 docs/mobile_touch_and_recents_fix_plan.md)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.ForwardButton:
            # QtOwner().SwitchWidgetNext()
            event.ignore()
        elif event.button() == Qt.BackButton:
            event.ignore()
            # QtOwner().SwitchWidgetLast()
        return QTableWidget.mousePressEvent(self, event)