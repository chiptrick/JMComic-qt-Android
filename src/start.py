# -*- coding: utf-8 -*-
"""第一个程序"""
import os
import sys
# macOS 修复
import time
import traceback
import signal

from config import config
from config.setting import Setting, SettingValue
from tools import platform_mobile
from tools.log import Log
from tools.str import Str

if sys.platform == 'darwin':
    # 确保工作区为当前可执行文件所在目录
    current_path = os.path.abspath(__file__)
    current_dir = os.path.abspath(os.path.dirname(current_path) + os.path.sep + '.')
    os.chdir(current_dir)


def InitSrEngine():
    """初始化超分后端

    桌面端：sr_vulkan(Vulkan)
    Android：sr_qnn(ONNX Runtime + 高通 QNN/HTP NPU)，注册为 sr_vulkan 兼容模块
    """
    if platform_mobile.IsAndroid():
        from tools import sr_backend
        config.CanWaifu2x = sr_backend.InstallQnnCompat()
        if config.CanWaifu2x:
            Log.Warn("sr engine: {}, version: {}".format(sr_backend.GetEngineName(),
                                                         sr_backend.GetSrModule().getVersion()))
        else:
            config.CanWaifu2x = False
            config.ErrorMsg = "NPU 超分后端不可用"
        return

    try:
        import sr_vulkan_model_waifu2x
        print("import sr_vulkan_model_waifu2x, {}".format(sr_vulkan_model_waifu2x))
        import sr_vulkan_model_realcugan
        print("import sr_vulkan_model_waifu2x, {}".format(sr_vulkan_model_realcugan))
        import sr_vulkan_model_realesrgan
        print("import sr_vulkan_model_waifu2x, {}".format(sr_vulkan_model_realesrgan))
    except Exception as es:
        pass

    try:
        from sr_vulkan import sr_vulkan as sr
        config.CanWaifu2x = True
    except Exception as es:
        config.CanWaifu2x = False
        if hasattr(es, "msg"):
            config.ErrorMsg = es.msg
    return


def CheckProbeArgs():
    """ 供主进程调用的 waifu2x 初始化探测(sr_vulkan 初始化失败会让进程崩溃，
    所以放到子进程里验证)：--sr-probe <显卡名> <cpu线程数> <结果文件> """
    if len(sys.argv) >= 5 and sys.argv[1] == "--sr-probe":
        from tools.waifu2x_check import Waifu2xChecker
        Waifu2xChecker.ProbeMain(sys.argv[2], sys.argv[3], sys.argv[4])
        return True
    return False


def InitQt(app=None):
    """ 导入 Qt、初始化日志与设置，返回 QApplication 与应用内部对象 """
    from qt_error import showError, showError2
    from qt_owner import QtOwner

    from PySide6 import QtWidgets, QtGui  # 导入PySide6部件
    from PySide6.QtNetwork import QLocalSocket, QLocalServer
    # 此处不能删除
    import images_rc

    Log.Init()
    Setting.Init()
    Setting.InitLoadSetting()
    os.environ['QT_IMAGEIO_MAXALLOC'] = "10000000000000000000000000000000000000000000000000000000000000000"
    QtGui.QImageReader.setAllocationLimit(0)
    if Setting.IsUseScaleFactor.value > 0 and not platform_mobile.IsAndroid():
        indexV = Setting.ScaleFactor.value
        # os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
        os.environ["QT_SCALE_FACTOR"] = str(indexV / 100)

    if app is None:
        app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)  # 建立application对象
    return app, QtWidgets, QtGui, QLocalSocket, QLocalServer, QtOwner, showError, showError2


def Run(app=None):
    """ 程序主流程(桌面端与 Android 共用) """
    try:
        app, QtWidgets, QtGui, QLocalSocket, QLocalServer, QtOwner, showError, showError2 = InitQt(app)
    except Exception as es:
        Log.Error(es)
        from PySide6 import QtWidgets as _QtWidgets
        app = _QtWidgets.QApplication.instance() or _QtWidgets.QApplication(sys.argv)
        try:
            from qt_error import showError
            showError(traceback.format_exc(), app)
        except Exception:
            print(traceback.format_exc())
        _StopSr()
        sys.exit(-111)

    # Android 是单 Activity 应用，不需要(也不支持)本地 socket 单实例
    socket = None
    localServer = None
    if not platform_mobile.IsAndroid():
        serverName = 'JMComic-qt'
        socket = QLocalSocket()
        socket.connectToServer(serverName)
        if socket.waitForConnected(500):
            socket.write(b"restart")
            socket.flush()
            socket.close()
            app.quit()
            Log.Warn("server already star")
            sys.exit(1)

        localServer = QLocalServer()  # 没有实例运行，创建服务器
        localServer.listen(serverName)

    Log.Warn("init scene ratio: {}".format(app.devicePixelRatio()))
    try:
        Str.Reload()
        QtOwner().SetApp(app)
        if localServer is not None:
            QtOwner().SetLocalServer(localServer)
        QtOwner().SetFont()
        from view.main.main_view import MainView
        main = MainView()
        main.show()  # 显示窗体
        main.Init()
        if localServer is not None:
            localServer.newConnection.connect(main.OnNewConnection)
    except Exception as es:
        Log.Error(es)
        showError(traceback.format_exc(), app)
        _StopSr()
        sys.exit(-111)

    oldHook = sys.excepthook
    def excepthook(exc_type, exc_value, exc_tb):
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        Log.Error(tb)
        showError2(tb, app)

    sys.excepthook = excepthook
    try:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    except Exception as es:
        Log.Error(es)

    sts = app.exec()
    sys.excepthook = oldHook
    if socket is not None:
        socket.close()
    main.Close()
    _StopSr()
    time.sleep(2)
    print(sts)
    sys.exit(sts)


def _StopSr():
    if not config.CanWaifu2x:
        return
    try:
        from tools import sr_backend
        sr = sr_backend.GetSrModule()
        if sr is not None:
            sr.stop()
    except Exception as es:
        Log.Error(es)
    return


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()

    CheckProbeArgs()
    InitSrEngine()
    Run()
