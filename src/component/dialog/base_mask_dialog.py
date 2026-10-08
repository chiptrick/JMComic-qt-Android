# coding:utf-8
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (QDialog, QGraphicsDropShadowEffect,
                               QGraphicsOpacityEffect, QWidget, QSpacerItem, QSizePolicy, QVBoxLayout, QApplication)

from tools import mobile_ui, platform_mobile


class BaseMaskDialog(QDialog):
    """ 带遮罩的对话框抽象基类 """
    closed = Signal()

    def __init__(self, parent):
        #QDialog.__init__(self, parent=parent)
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)
        self.windowMask = QWidget(self)
        # 蒙版中间的对话框，所有小部件以他为父级窗口
        self.widget = QWidget(self, objectName='centerWidget')
        self.setWindowFlags(Qt.FramelessWindowHint|Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.setAttribute(Qt.WA_QuitOnClose, False)
        if platform_mobile.IsAndroid():
            # 手机端做成主窗口里的子控件覆盖层：Android + Qt6.11 上第二个顶层窗口
            # 一渲染就撞 eglSurface() 的死锁保护器 abort(见 mobile_ui.MakeChildOverlay)。
            # 这类对话框(登录/收藏夹/模型选择/目录选择/DoH…)都是"盖满主窗口的遮罩"，
            # 本来就适合做子控件。
            mobile_ui.MakeChildOverlay(self)
        if self.parent() is not None:
            self.setGeometry(self.parent().geometry())
        self.windowMask.resize(self.size())

        self.windowMask.setStyleSheet('background:rgba(255, 255, 255, 0.6)')
        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)
        self.vBoxLayout.addItem(self.verticalSpacer)
        self.vBoxLayout.addWidget(self.widget, 0, Qt.AlignHCenter)
        self.verticalSpacer2 = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)
        self.vBoxLayout.addItem(self.verticalSpacer2)

        self.__setShadowEffect()

    def show(self):
        """ 子控件模式下：对齐父窗口 + 抬到最上层 """
        if mobile_ui.IsChildOverlay(self):
            parent = self.parentWidget()
            if parent is not None:
                self.setGeometry(0, 0, parent.width(), parent.height())
        QDialog.show(self)
        if mobile_ui.IsChildOverlay(self):
            self.raise_()

    def reject(self):
        self.close()

    def closeEvent(self, arg__1) -> None:
        self.closed.emit()
        arg__1.accept()

    def __setShadowEffect(self):
        """ 添加阴影 """
        shadowEffect = QGraphicsDropShadowEffect(self.widget)
        shadowEffect.setBlurRadius(50)
        shadowEffect.setOffset(0, 5)
        self.widget.setGraphicsEffect(shadowEffect)

    def showEvent(self, e):
        """ 淡入 """
        opacityEffect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(opacityEffect)
        opacityAni = QPropertyAnimation(opacityEffect, b'opacity', self)
        opacityAni.setStartValue(0)
        opacityAni.setEndValue(1)
        opacityAni.setDuration(200)
        opacityAni.setEasingCurve(QEasingCurve.InSine)
        opacityAni.finished.connect(opacityEffect.deleteLater)
        opacityAni.start()
        super().showEvent(e)

    # def closeEvent(self, e):
    #     """ 淡出 """
    #     self.widget.setGraphicsEffect(None)
    #     opacityEffect = QGraphicsOpacityEffect(self)
    #     self.setGraphicsEffect(opacityEffect)
    #     opacityAni = QPropertyAnimation(opacityEffect, b'opacity', self)
    #     opacityAni.setStartValue(1)
    #     opacityAni.setEndValue(0)
    #     opacityAni.setDuration(100)
    #     opacityAni.setEasingCurve(QEasingCurve.OutCubic)
    #     opacityAni.finished.connect(self.deleteLater)
    #     opacityAni.start()
    #     e.ignore()
