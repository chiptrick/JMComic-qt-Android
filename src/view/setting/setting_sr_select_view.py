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
        # 每次打开都会 new 一个新弹窗（见 QtOwner.OpenSrSelectModel），父窗口又是主窗口，
        # 不主动销毁的话它连同 40+ 行表格会一直挂着 —— 反复开关几次后越用越钝
        self.closed.connect(self.deleteLater)
        self._FitSize()
        self.tableWidget.SetCurrentModel(self.curModelName)
        if not self.tableWidget.DetectionOk():
            # 探测不可信时列表退回了"全部模型"，必须说清楚，否则用户会以为都能用
            self.label.setText("未检测到可用的超分引擎，已列出全部模型（需引擎可用才能生效）")
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
            self.widget.setFixedSize(673, 560)
            return
        # 必须 setFixedSize：widget 在 mask 弹窗的 QVBoxLayout 里，resize() 会被布局
        # 覆盖回 sizeHint —— 真机上就出现"弹窗只有巴掌大、列表只露 4 行"(截图反馈)。
        dialogWidth = min(560, max(320, width - 16))
        dialogHeight = min(660, max(360, int(height * 0.86))) if height > 0 else 560
        self.widget.setFixedSize(dialogWidth, dialogHeight)

    def _ClickButton(self):
        modelName = self.tableWidget.SelectedModelName()
        if modelName:
            self.Close.emit(modelName)
        # 一个都没选中（当前模型不在可用列表里、又没有点选）时不要卡在弹窗里：
        # 直接关掉，设置保持原样。原来这里是 return，用户点「确定」毫无反应。
        self.close()
