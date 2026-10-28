import os
import re

from PySide6.QtCore import QEvent, QStringListModel, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QPushButton, QToolButton,
                               QWidget)

from component.line_edit import popup_list
from config.setting import Setting
from interface.ui_line_edit_help_widget import Ui_LineEditHelp
from qt_owner import QtOwner
from tools.langconv import Converter
from tools.log import Log


class TipLineEdit(QLineEdit):
    """ 带候选名单的输入框(登录页 DOH 地址 / 获取地区)

    弹层与 SearchLineEdit 共用 component.line_edit.popup_list：手机端是主窗口里的
    子控件图层(原来的 Qt.ToolTip 顶层窗口在 Android 上点不动、宽度写死 500 会溢出)。

    2026-10-27 补的两件事：
      1. **点得开**：`focusInEvent` 只在"从没焦点变成有焦点"时触发，而触控路由
         `_FocusInput()` 在输入框已聚焦时直接返回 —— 第二次点同一个框，弹层再也不出现。
         现在多了 `Popover()` 公开入口（点按/抬手都会调），已聚焦也能开。
      2. **能自定义**：`EnableAddRow()` 在列表底部加「＋ 添加 XXX」一栏；点它之前
         是个灰按钮(不会触发输入)，点开才换成真输入框 + ✓/✕，✓ 校验通过后写回
         候选列表并应用到当前输入框。
    """

    wordSelected = Signal(str)   # 从候选里选了一项（写回输入框之后发）
    wordAdded = Signal(str)      # 通过「添加」一栏新增了一项

    def __init__(self, parent=None):
        QLineEdit.__init__(self, parent)

        self.widget = QWidget()
        self.help = Ui_LineEditHelp()
        self.help.setupUi(self.widget)
        # 标题默认不占位（这之前是个空 QLabel，弹层顶上会空一大块）
        self.help.label.setText("")
        self.help.label.setVisible(False)

        self.words = []
        self.model = QStringListModel(self)
        self.listView.setModel(self.model)
        self.listView.clicked.connect(self.SetText)
        popup_list.Install(self, self.widget, self.listView)

        self.isNotReload = False
        self.isShowSearch = True

        self.searchTag1 = "<font color=#232629>"
        self.searchTag2 = "</font>"

        # 「添加」一栏（EnableAddRow 之后才有控件）
        self.addRow = None
        self.addButton = None
        self.addEdit = None
        self.addOk = None
        self.addNo = None
        self.addValidator = None

    @property
    def listView(self):
        return self.help.listView

    # ---------------- 候选数据 ----------------
    def SetPopupCaption(self, text):
        """ 弹层顶部的小标题（空字符串 = 不显示） """
        text = text or ""
        self.help.label.setText(text)
        self.help.label.setVisible(bool(text))

    def _ExtraHeight(self):
        """ 弹层里「列表之外」的那部分高度（标题 + 添加行） """
        extra = 0
        try:
            if self.help.label.isVisible():
                extra += max(16, self.help.label.sizeHint().height())
            if self.addRow is not None:
                extra += max(28, self.addRow.sizeHint().height())
        except Exception:
            pass
        return extra

    def SetWordData(self, data):
        self.words = list(data or [])
        self.model.setStringList(self.words)

    def AddWord(self, text, front=True):
        """ 往候选里加一条(去重，默认放最前面)，并刷新列表 """
        text = (text or "").strip()
        if not text:
            return False
        if text in self.words:
            self.words.remove(text)
        if front:
            self.words.insert(0, text)
        else:
            self.words.append(text)
        self.model.setStringList(self.words)
        return True

    def SetText(self, index):
        item = self.model.itemData(index)
        text = item.get(0)
        if not text:
            return
        self.setText(text)
        # 选完就收起：否则弹层会盖住下面几行，用户容易以为没生效
        self.HideListView()
        self.wordSelected.emit(text)
        return

    # ---------------- 键盘 ----------------
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
                self.wordSelected.emit(text)
            self.Search()
        return QLineEdit.keyReleaseEvent(self, ev)

    def Search(self):
        text = self.text()
        QtOwner().OpenSearch(text)
        self.clearFocus()
        return

    def clearFocus(self) -> None:
        return QLineEdit.clearFocus(self)

    # ---------------- 弹层开合 ----------------
    def focusInEvent(self, ev):
        # print("in")
        self.ShowListView()
        return QLineEdit.focusInEvent(self, ev)

    def focusOutEvent(self, ev):
        # 焦点跑去「添加」一栏的输入框时不能收（那是弹层自己的子控件）
        if self._FocusInPopup():
            return QLineEdit.focusOutEvent(self, ev)
        self.HideListView()
        return QLineEdit.focusOutEvent(self, ev)

    def mouseReleaseEvent(self, ev):
        # 已聚焦时再点一下也要能重新展开（focusInEvent 不会再触发）
        if ev.button() == Qt.MouseButton.LeftButton:
            self.Popover()
        return QLineEdit.mouseReleaseEvent(self, ev)

    def _FocusInPopup(self):
        try:
            if self.widget is None:
                return False
            focused = self.widget.window().focusWidget()
            if focused is None:
                return False
            return focused is self.widget or self.widget.isAncestorOf(focused)
        except Exception:
            return False

    def HideListView(self):
        popup_list.Hide(self)

    def ShowListView(self):
        if not self.isShowSearch:
            return
        popup_list.Show(self)

    def Popover(self, event=None):
        """ 点按输入框的开合入口（手机端触控路由 / 桌面端鼠标都会走到这里） """
        if not self.isShowSearch or not self.isEnabled():
            return
        if popup_list.IsHidden(self):
            self.ShowListView()

    def CheckClick(self, pos):
        popup_list.CheckClick(self, pos)

    # ---------------- 「添加」一栏 ----------------
    def EnableAddRow(self, caption="添加", placeholder="", validator=None):
        """ 在候选列表底部加一栏「＋ 添加 XXX」

        caption   —— 按钮文案（如「添加 DOH 地址」）
        validator —— 校验函数，返回 True 才允许保存

        未点「＋」之前这里是个**按钮**（不是输入框）：手机上点按钮一定能激活，
        而"灰掉的输入框"点下去既不会聚焦、也拿不到触摸，等于点不动。
        """
        if self.addRow is not None:
            return self.addRow
        try:
            row = QWidget(self.widget)
            row.setObjectName("jmAddRow")
            # 行高固定：按钮态和编辑态切换时弹层高度不变（否则列表会被挤一下）
            row.setFixedHeight(36)
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 1, 0, 1)
            lay.setSpacing(4)

            button = QPushButton("+  " + caption, row)
            button.setObjectName("jmAddButton")
            button.setFlat(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(34)
            lay.addWidget(button)

            edit = QLineEdit(row)
            edit.setPlaceholderText(placeholder or caption)
            edit.setFixedHeight(30)
            edit.hide()
            lay.addWidget(edit, 1)

            # 用 √ / × 而不是 ✓ / ✕：后者要靠符号字体，部分安卓机型会渲染成方块
            ok = QToolButton(row)
            ok.setText("√")
            ok.setFixedSize(30, 30)
            ok.hide()
            lay.addWidget(ok)

            no = QToolButton(row)
            no.setText("×")
            no.setFixedSize(30, 30)
            no.hide()
            lay.addWidget(no)

            self.help.verticalLayout_2.addWidget(row)

            button.clicked.connect(self._UnlockAdd)
            ok.clicked.connect(self._CommitAdd)
            no.clicked.connect(self._CancelAdd)

            self.addRow = row
            self.addButton = button
            self.addEdit = edit
            self.addOk = ok
            self.addNo = no
            self.addValidator = validator
            return row
        except Exception as es:
            Log.Error(es)
        return None

    def _UnlockAdd(self):
        """ 点「＋」：按钮换成真输入框，并把焦点/输入法交给它 """
        try:
            self.addButton.hide()
            self.addEdit.clear()
            self.addEdit.show()
            self.addOk.show()
            self.addNo.show()
            self.addEdit.setFocus(Qt.MouseFocusReason)
            try:
                method = QGuiApplication.inputMethod()
                if method is not None and not method.isVisible():
                    method.show()
            except Exception:
                pass
        except Exception as es:
            Log.Error(es)

    def _CancelAdd(self):
        try:
            self.addEdit.clear()
            self.addEdit.hide()
            self.addOk.hide()
            self.addNo.hide()
            self.addButton.show()
            self.setFocus(Qt.MouseFocusReason)
        except Exception as es:
            Log.Error(es)

    def _CommitAdd(self):
        try:
            text = (self.addEdit.text() or "").strip()
            if not text or (self.addValidator is not None and not self.addValidator(text)):
                self._FlashAdd()
                return
            self.AddWord(text)
            self._CancelAdd()
            self.setText(text)
            self.HideListView()
            self.wordSelected.emit(text)
            self.wordAdded.emit(text)
            # 走既有的"编辑完成"链：保存设置 + 触发校验
            self.editingFinished.emit()
        except Exception as es:
            Log.Error(es)

    def _FlashAdd(self):
        """ 校验失败闪一下红边（弹层里没有空间放提示文案） """
        try:
            self.addEdit.setStyleSheet(
                "QLineEdit{border:1px solid #d9534f;border-radius:2px;}")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(900, self._ClearAddStyle)
        except Exception:
            pass

    def _ClearAddStyle(self):
        try:
            self.addEdit.setStyleSheet("")
        except Exception:
            pass
