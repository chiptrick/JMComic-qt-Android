import os
import re

from PySide6.QtCore import QStringListModel
from PySide6.QtGui import Qt
from PySide6.QtWidgets import QLineEdit, QWidget

from component.line_edit import popup_list
from config.setting import Setting
from interface.ui_line_edit_help_widget import Ui_LineEditHelp
from qt_owner import QtOwner
from tools.langconv import Converter
from tools.log import Log


class TipLineEdit(QLineEdit):
    """ 带候选名单的输入框(登录页 DoH 地址 / 代理地址 / 域名等)

    弹层与 SearchLineEdit 共用 component.line_edit.popup_list：手机端是主窗口里的
    子控件图层(原来的 Qt.ToolTip 顶层窗口在 Android 上点不动、宽度写死 500 会溢出)。
    """

    def __init__(self, parent=None):
        QLineEdit.__init__(self, parent)

        self.widget = QWidget()
        self.help = Ui_LineEditHelp()
        self.help.setupUi(self.widget)
        self.help.label.setText("")

        self.words = []
        self.model = QStringListModel(self)
        self.listView.setModel(self.model)
        self.listView.clicked.connect(self.SetText)
        popup_list.Install(self, self.widget, self.listView)

        self.isNotReload = False
        self.isShowSearch = True

        self.searchTag1 = "<font color=#232629>"
        self.searchTag2 = "</font>"

    @property
    def listView(self):
        return self.help.listView

    def SetWordData(self, data):
        self.words = data
        self.model.setStringList(data)

    def SetText(self, index):
        item = self.model.itemData(index)
        text = item.get(0)
        self.setText(text)
        return

    def keyReleaseEvent(self, ev):
        # print(ev.key())
        count = self.listView.model().rowCount()
        currentIndex = self.listView.currentIndex()
        if ev.key() == Qt.Key_Up:
            if count > 0:
                if currentIndex.row() < 0:
                    row = 0
                elif currentIndex.row() == 0:
                    row = count - 1
                else:
                    row = currentIndex.row() - 1 if currentIndex.row() > 0 else 0
                index = self.listView.model().index(row, 0)
                self.listView.setCurrentIndex(index)

        elif ev.key() == Qt.Key_Down:
            if count > 0:
                if currentIndex.row() < 0:
                    row = 0
                else:
                    row = currentIndex.row() + 1 if currentIndex.row() + 1 < count else 0
                index = self.listView.model().index(row, 0)
                self.listView.setCurrentIndex(index)

        if ev.key() == Qt.Key_Enter or ev.key() == Qt.Key_Return:
            currentIndex = self.listView.currentIndex()
            if currentIndex.row() >= 0:
                text = currentIndex.data()
                self.setText(text)
            self.Search()
        return QLineEdit.keyReleaseEvent(self, ev)

    def Search(self):
        text = self.text()
        QtOwner().OpenSearch(text)
        self.clearFocus()
        return

    def clearFocus(self) -> None:
        return QLineEdit.clearFocus(self)

    def focusInEvent(self, ev):
        # print("in")
        self.ShowListView()
        return QLineEdit.focusInEvent(self, ev)

    def focusOutEvent(self, ev):
        self.HideListView()
        return QLineEdit.focusOutEvent(self, ev)

    def HideListView(self):
        popup_list.Hide(self)

    def ShowListView(self):
        if not self.isShowSearch:
            return
        popup_list.Show(self)

    def CheckClick(self, pos):
        popup_list.CheckClick(self, pos)
