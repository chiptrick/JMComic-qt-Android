import os
import time

from PySide6.QtCore import Qt, QPoint, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup, QRectF, Property
from PySide6.QtGui import QPen, QPainterPath, QPainter, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFileDialog

from tools import mobile_ui, platform_mobile
from tools.log import Log


class MsgLabel(QWidget):
    BackgroundColor = QColor(195, 195, 195)
    BorderColor = QColor(150, 150, 150)

    ShowMsgTick = {}

    def __init__(self, *args, **kwargs):
        super(MsgLabel, self).__init__(*args, **kwargs)
        if platform_mobile.IsAndroid():
            # 手机端必须做成**子控件**：Android + Qt6.11 上第二个顶层窗口一渲染就
            # 撞 eglSurface() 的死锁保护器直接 abort(设置页每改一项都会弹这个提示条，
            # 真机上表现为"改设置必崩")。详见 tools/mobile_ui.MakeChildOverlay。
            mobile_ui.MakeChildOverlay(self, coverParent=False)
            # 提示条不该抢触摸：它盖在页面上，但要点得到下面的控件
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        else:
            self.setWindowFlags(
                Qt.Window | Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setMinimumWidth(200)
        self.setMinimumHeight(48)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 16)
        self.label = QLabel(self)
        layout.addWidget(self.label)
        self.animationGroup = QParallelAnimationGroup(self)
        self.opacityAnimation = None
        self.moveAnimation = None

    def setText(self, text):
        self.label.setText(text)

    def text(self):
        return self.label.text()

    def stop(self):
        self.hide()
        self.animationGroup.stop()
        self.animationGroup.clear()
        self.opacityAnimation = None
        self.moveAnimation = None
        self.close()

    def ShowNow(self):
        QWidget.show(self)
        parent = self.parent()
        if parent is None:
            return
        if mobile_ui.IsChildOverlay(self):
            # 子控件：坐标是相对父窗口的(父窗口的 geometry().x/y() 是它在自己父级里的位置，
            # 拿来做偏移会把提示条推到屏幕外)
            x = 0
            y = 0
            self.raise_()
        else:
            x = parent.geometry().x()
            y = parent.geometry().y()
        x2 = parent.size().width()
        y2 = parent.size().height()
        startPos = QPoint(x+int(x2/2)-int(self.width()/2), y+int(y2/2))
        endPos = QPoint(x+int(x2/2)-int(self.width()/2), y+int(y2/2)-self.height()*3-5)
        self.move(startPos)
        # 初始化动画
        self.initAnimation(startPos, endPos)

    def show(self):
        # Android 上如果它还是**顶层窗口**(桌面端/异常兜底)，从输入事件处理里同步 show
        # 会让 Qt 在 eglSurface() 上重入并直接 abort('Failed to acquire deadlock
        # protector')；延到当前事件处理结束再 show，行为不变、不再重入。
        # 手机端已经把它做成子控件了(见 __init__)，子控件不需要延后。
        if mobile_ui.ShouldDeferWindowShow() and not mobile_ui.IsChildOverlay(self):
            mobile_ui.DeferCall(self.ShowNow)
            return
        self.ShowNow()

    def initAnimation(self, startPos, endPos):
        # 透明度动画
        opacityAnimation = QPropertyAnimation(self, b"opacity")
        opacityAnimation.setStartValue(1.0)
        opacityAnimation.setEndValue(0.0)
        # 设置动画曲线
        opacityAnimation.setEasingCurve(QEasingCurve.InQuad)
        opacityAnimation.setDuration(3000)  # 在4秒的时间内完成
        # 往上移动动画
        moveAnimation = QPropertyAnimation(self, b"pos")
        moveAnimation.setStartValue(startPos)
        moveAnimation.setEndValue(endPos)
        moveAnimation.setEasingCurve(QEasingCurve.InQuad)
        moveAnimation.setDuration(4000)  # 在5秒的时间内完成
        # 并行动画组（目的是让上面的两个动画同时进行）
        self.animationGroup.addAnimation(opacityAnimation)
        self.animationGroup.addAnimation(moveAnimation)
        self.animationGroup.finished.connect(self.close)  # 动画结束时关闭窗口
        self.animationGroup.start()
        self.opacityAnimation = opacityAnimation
        self.moveAnimation = moveAnimation

    def paintEvent(self, event):
        super(MsgLabel, self).paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # 抗锯齿

        rectPath = QPainterPath()  # 圆角矩形

        height = self.height() - 8  # 往上偏移8
        rectPath.addRoundedRect(QRectF(0, 0, self.width(), height), 5, 5)
        x = self.width() / 5 * 4
        # 边框画笔
        painter.setPen(QPen(self.BorderColor, 1, Qt.SolidLine,
                            Qt.RoundCap, Qt.RoundJoin))
        # 背景画刷
        painter.setBrush(self.BackgroundColor)
        # 绘制形状
        painter.drawPath(rectPath)

    def windowOpacity(self):
        return super(MsgLabel, self).windowOpacity()

    def setWindowOpacity(self, opacity):
        super(MsgLabel, self).setWindowOpacity(opacity)

    opacity = Property(float, windowOpacity, setWindowOpacity)

    def ShowMsg(self, text):
        self.stop()
        self.setText(text)
        self.setStyleSheet("color:black")
        self.show()

    @staticmethod
    def ShowMsgEx(owner, text):
        msgTick = MsgLabel.ShowMsgTick.get(owner.__class__.__name__, 0)
        CurTick = int(time.time())
        if msgTick >= CurTick:
            return
        data = MsgLabel(owner)
        data.setText(text)
        data.setStyleSheet("color:black")
        data.show()
        MsgLabel.ShowMsgTick[owner.__class__.__name__] = CurTick

    def ShowError(self, text):
        self.stop()
        self.setText(text)
        self.setStyleSheet("color:red")
        self.show()

    @staticmethod
    def ShowErrorEx(owner, text):
        msgTick = MsgLabel.ShowMsgTick.get(owner.__class__.__name__, 0)
        CurTick = int(time.time())
        if msgTick >= CurTick:
            return
        data = MsgLabel(owner)
        data.setText(text)
        data.setStyleSheet("color:red")
        data.show()
        MsgLabel.ShowMsgTick[owner.__class__.__name__] = CurTick

    @staticmethod
    def OpenPicture(self, path="."):
        try:
            # Android 上不能用 QFileDialog(会弹一个回不来的顶层窗口，应用直接卡死)，
            # 走应用内的选择器；桌面端仍原样用 QFileDialog，返回值形状一致
            from tools import mobile_file_dialog
            filename = mobile_file_dialog.GetOpenFileName(
                self, "Open Image", path, "Image Files(*.jpg *.png)")
            if filename and len(filename) > 1:
                name = filename[0]
                picFormat = filename[1]
                baseName = os.path.basename(name)
                if baseName[-3:] == "png":
                    picFormat = "png"
                elif baseName[-3:] == "jpg":
                    picFormat = "jpeg"
                elif baseName[-4:] == "webp":
                    picFormat = "webp"
                elif baseName[-3:] == "gif":
                    picFormat = "gif"
                else:
                    return None, None, None

                if os.path.isfile(name):
                    self.cachePath = os.path.dirname(name)

                    f = open(name, "rb")
                    data = f.read()
                    f.close()
                    return data, name, picFormat
                return None, None, None
        except Exception as ex:
            Log.Error(ex)
            return None, None, None
