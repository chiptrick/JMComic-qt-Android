# coding:utf-8
""" 看图视口（Vulkan 合成）

QGraphicsView 的视口本来就是普通 QWidget：QPainter 先画进后备存储，再由 Qt 的 QRhi
把后备存储上传/合成到屏幕。Vulkan 加速打开时（见 tools/vulkan_accel.py），这最后一跳
由 Vulkan 后端承担，所以视口**不需要**像旧的 GL 视口那样自己持有图形上下文
—— 也就没有 EGL/GL surface 的生命周期问题（Android 上第二个 surface 会撞平台插件的
全局死锁保护器，见 tools/mobile_ui_base 的说明）。

因此这个类的职责只有两条：
  1) 作为"加速已开启"的视口标记，并保持与 QAbstractScrollArea 默认视口**完全相同**的
     背景设置（Qt 的默认视口在 QAbstractScrollAreaPrivate::init 里是
     backgroundRole=Base + autoFillBackground=true；换成自定义视口后这两项不会自动
     继承，必须自己设回来，否则画不到的地方会出现残影）；
  2) 给日志和诊断一个查询"当前用的什么后端"的出口。

绘制内容仍由 QGraphicsView 负责（drawBackground + pixmap 图元），与不加速时是
同一条路径，所以显示效果一致。
"""

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QWidget

from tools import vulkan_accel


class ReadVulkan(QWidget):
    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.setObjectName("readVulkanViewport")
        # 与 QAbstractScrollArea 默认视口一致(见类注释)，保证换视口后画面不变
        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)

    @staticmethod
    def IsAccelerated():
        """ 本次进程是否真的跑在 Vulkan 上（环境变量没生效时为 False） """
        return vulkan_accel.IsActive()

    @staticmethod
    def GetBackendName():
        return vulkan_accel.GetBackendName()

    @staticmethod
    def GetStatus():
        return vulkan_accel.GetStatus()
