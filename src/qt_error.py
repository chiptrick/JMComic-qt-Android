import sys
import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyle, QErrorMessage, QLabel, QCheckBox, QPushButton


def showError(message, app):
    app.setQuitOnLastWindowClosed(True)
    # 设置内置错误图标
    app.setWindowIcon(app.style().standardIcon(QStyle.SP_MessageBoxCritical))
    w = QErrorMessage()
    w.finished.connect(lambda _: app.quit)
    w.resize(600, 400)
    # 去掉右上角?
    w.setWindowFlags(w.windowFlags() & ~Qt.WindowContextHelpButtonHint)
    w.setWindowTitle(w.tr('Error'))
    # 隐藏图标、勾选框、按钮
    w.findChild(QLabel, '').setVisible(False)
    w.findChild(QCheckBox, '').setVisible(False)
    w.findChild(QPushButton, '').setVisible(False)
    w.showMessage(escape(message))
    app.exec()


def IsAndroid():
    try:
        from tools import platform_mobile
        return bool(platform_mobile.IsAndroid())
    except Exception:
        return False


def ShowAndroidError(message):
    """ Android 下把运行期未捕获异常显示成主窗口里的**子控件**提示条(MsgLabel)

    真机实证(Android 16 + Qt6.11.2)：任何**第二个顶层窗口**一开始渲染就会撞平台
    插件里的全局死锁保护器并直接 abort：

        Abort message: 'Failed to acquire deadlock protector for
                        QAndroidPlatformOpenGLWindow::eglSurface().'
        栈: QWidget::setVisible -> show_sys -> QWindowPrivate::setVisible
            -> flushWindowSystemEvents -> processExposeEvent -> paintAndFlush
            -> QBackingStoreRhiSupport::create -> QRhi::create
            -> QOpenGLContext::makeCurrent -> eglSurface -> qFatal

    MsgLabel / LoadingDialog / 遮罩对话框都已经改成主窗口内的子控件覆盖层，运行期
    错误框是最后一处顶层窗口：以前任何一个没被捕获的 python 异常(滑块/网络/解析
    回调都可能抛)都会被这里弹出的顶层 QErrorMessage 变成**整个应用闪退**。现在改走
    同一套子控件提示条，异常只提示不再崩溃。

    另外 sys.excepthook 也会被工作线程用到(threading.excepthook 会转调它)，在那个
    线程里创建/操作 QWidget 同样会 abort，所以非主线程只记日志(调用方已记过)，
    绝不碰 GUI。
    """
    try:
        if threading.current_thread() is not threading.main_thread():
            return False
        lines = [line.strip() for line in (message or "").splitlines() if line.strip()]
        text = lines[-1] if lines else "程序异常(详见日志)"
        from qt_owner import QtOwner
        owner = QtOwner().owner
        if owner is None:
            return False
        from component.label.msg_label import MsgLabel
        MsgLabel.ShowErrorEx(owner, text)
        return True
    except Exception:
        return False


def showError2(message, app):
    # app.setQuitOnLastWindowClosed(True)
    # # 设置内置错误图标
    # app.setWindowIcon(app.style().standardIcon(QStyle.SP_MessageBoxCritical))
    if IsAndroid():
        # Android: 见 ShowAndroidError 注释，绝不新建顶层窗口(否则未捕获异常=闪退)
        ShowAndroidError(message)
        return
    w = QErrorMessage()
    w.setWindowIcon(w.style().standardIcon(QStyle.SP_MessageBoxCritical))
    # w.finished.connect(lambda _: app.quit)
    w.resize(600, 400)
    # 去掉右上角?
    w.setWindowFlags(w.windowFlags() & ~Qt.WindowContextHelpButtonHint)
    w.setWindowTitle(w.tr('Error'))
    # 隐藏图标、勾选框、按钮
    w.findChild(QLabel, '').setVisible(False)
    w.findChild(QCheckBox, '').setVisible(False)
    w.findChild(QPushButton, '').setVisible(False)
    w.showMessage(escape(message))
    w.exec()

def escape(s):
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    s = s.replace('\'', "&#x27;")
    s = s.replace('\n', '<br/>')
    s = s.replace(' ', "&nbsp;")
    return s
