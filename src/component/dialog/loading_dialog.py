from PySide6 import QtWidgets, QtCore
from PySide6.QtCore import QTimer
from PySide6.QtGui import Qt
from PySide6.QtWidgets import QGridLayout

from component.label.gif_group_label import GifGroupLabel
from component.label.gif_label import GifLabel
from config.setting import Setting
from tools import mobile_ui, platform_mobile


class LoadingDialog(QtWidgets.QDialog):
    def __init__(self, owner):
        super(self.__class__, self).__init__(owner)
        self.gridLayout = QGridLayout(self)
        self.setWindowFlag(QtCore.Qt.FramelessWindowHint)
        self.setWindowFlag(QtCore.Qt.Dialog)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        if platform_mobile.IsAndroid():
            # 手机端做成主窗口里的子控件：Android + Qt6.11 上第二个顶层窗口一渲染就
            # 撞 eglSurface() 的死锁保护器 abort(切页/加载都会弹它)。
            # 顺便不再用 ApplicationModal：子控件的模态在 Qt 里无效，干脆让它别挡触摸。
            mobile_ui.MakeChildOverlay(self, coverParent=False)
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.label = GifGroupLabel(self)
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.gridLayout.addWidget(self.label, 0, 0, 1, 1)

        self.timer = QTimer(self.label)
        self.timer.setInterval(100)
        self.label.Init()
        self.label.resize(250, 250)
        self.cnt = 0
        self.closeCnt = 50
        self.timer.timeout.connect(self.UpdatePic)
        self.resize(250, 250)

    def show(self) -> None:
        self.timer.start()
        self.closeCnt = 10 * Setting.ApiTimeOut.GetIndexV()
        self.cnt = 0
        self.CenterInParent()
        super(self.__class__, self).show()
        if mobile_ui.IsChildOverlay(self):
            self.raise_()

    def CenterInParent(self):
        """ 子控件模式下没有窗口管理器帮我们居中，自己摆到父窗口中间 """
        try:
            if not mobile_ui.IsChildOverlay(self):
                return
            parent = self.parentWidget()
            if parent is None:
                return
            width = min(self.width(), parent.width())
            height = min(self.height(), parent.height())
            self.setGeometry(max(0, (parent.width() - width) // 2),
                             max(0, (parent.height() - height) // 2), width, height)
        except Exception as es:
            from tools.log import Log
            Log.Error(es)
        return

    def close(self):
        self.timer.stop()
        super(self.__class__, self).close()

    def UpdatePic(self):
        self.cnt += 1
        self.label.ShowNextPixMap()
        if self.cnt >= self.closeCnt:
            self.close()
        pass
