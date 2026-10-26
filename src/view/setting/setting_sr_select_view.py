# coding:utf-8
from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import QApplication

from component.dialog.base_mask_dialog import BaseMaskDialog
from interface.ui_sr_select_widget import Ui_SrSelect


class SettingSrSelectView(BaseMaskDialog, Ui_SrSelect):
    """ 超分模型选择弹窗

    旧实现是 4 列定宽表格(200/150/100/100=550)，手机 480 逻辑宽下右侧列永远在屏外，
    只能靠 setColumnHidden 藏掉「耗时」列来凑宽度。现在列宽/分组/吸顶全部交给
    SrModelTable，这里只负责尺寸与「确定/关闭」。
    """
    Close = Signal(str)

    def __init__(self, parent=None, curModelName=""):
        BaseMaskDialog.__init__(self, parent)
        Ui_SrSelect.__init__(self)
        self.setupUi(self.widget)
        self.curModelName = curModelName or ""
        self.saveButton.clicked.connect(self._ClickButton)
        self.closeButton.clicked.connect(self.close)
        self._FitSize()
        self.tableWidget.SetCurrentModel(self.curModelName)
        # 让当前项居中要等布局跑完(宽高这时才是真的)
        QTimer.singleShot(0, self.tableWidget.ScrollToCurrent)

    def _FitSize(self):
        """ 尺寸夹到窗口内

        旧版 .ui 的 minimumWidth=500 会把整个弹窗顶出 480 宽的屏幕，表格再窄也没用。
        尺寸取父窗口(手机上是主窗口)，没有父窗口时退回当前活动窗口 —— 不要用
        QtOwner().owner：那会触发 main_view 的懒导入，那条链上有人 `from this import d`。
        """
        owner = self.parentWidget() or QApplication.activeWindow()
        width = owner.width() if owner is not None else 0
        height = owner.height() if owner is not None else 0
        if width <= 0:
            self.widget.resize(673, 560)
            return
        self.widget.setMinimumWidth(0)
        self.widget.setMaximumWidth(max(320, width - 16))
        dialogWidth = min(560, max(320, width - 16))
        dialogHeight = min(620, max(320, height - 96)) if height > 0 else 560
        self.widget.resize(dialogWidth, dialogHeight)

    def _ClickButton(self):
        modelName = self.tableWidget.SelectedModelName()
        if not modelName:
            return
        self.Close.emit(modelName)
        self.close()
