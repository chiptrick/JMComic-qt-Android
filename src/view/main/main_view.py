import sys
from functools import partial

from PySide6.QtCore import Qt, QEvent, QPoint, QTimer, Signal
from PySide6.QtGui import QIcon, QMouseEvent, QGuiApplication, QFont
from PySide6.QtWidgets import QButtonGroup, QToolButton, QLabel, QWidget

from component.dialog.loading_dialog import LoadingDialog
from component.label.gif_label import GifLabel
from component.label.msg_label import MsgLabel
from component.system_tray_icon.my_system_tray_icon import MySystemTrayIcon
from component.widget.main_widget import Main
from config import config
from config.setting import Setting
from qt_owner import QtOwner
from server import req, GlobalConfig
from server.server import Server
from task.qt_task import QtTaskBase
from task.task_multi import TaskMulti
from task.task_qimage import TaskQImage
from task.task_waifu2x import TaskWaifu2x
from tools import mobile_ui, platform_mobile, sr_backend
from tools.log import Log
from view.download.download_dir_view import DownloadDirView
from view.read.read_pool import QtReadImgPoolManager


class MainView(Main, QtTaskBase):
    """ 主窗口 """
    WindowsSizeChange = Signal()
    # 缩放窗口时，合并中间过程重绘的间隔(毫秒)
    # 每次resize都会重绘整个窗口(60个左右控件，耗时30ms上下)，拖动窗口边框时
    # 会不停触发resize，导致窗口一直闪烁重绘，这里把重绘合并到缩放间隙执行
    ResizeRepaintInterval = 60
    # 最大化/还原/全屏等状态切换后，这段时间内的尺寸变化立即重绘，不做合并
    StateChangeInterval = 200
    # 是否处于最大化/还原/全屏状态切换中
    _isStateChange = False

    def __init__(self):
        QtOwner().SetOwner(self)
        Main.__init__(self)
        QtTaskBase.__init__(self)
        # 缩放合并用的定时器
        self._resizeRepaintTimer = QTimer(self)
        self._resizeRepaintTimer.setSingleShot(True)
        self._resizeRepaintTimer.setInterval(MainView.ResizeRepaintInterval)
        self._resizeRepaintTimer.timeout.connect(self.ResetResizeRepaint)
        # 状态切换(最大化/还原/全屏)结束后自动清除标记的定时器
        self._stateChangeTimer = QTimer(self)
        self._stateChangeTimer.setSingleShot(True)
        self._stateChangeTimer.setInterval(MainView.StateChangeInterval)
        self._stateChangeTimer.timeout.connect(self._EndStateChange)
        self.resize(600, 600)
        self.setWindowTitle("JMComic")
        self.setWindowIcon(QIcon(":/png/icon/logo_round.png"))
        # self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_QuitOnClose, True)
        # QtOwner().app.lastWindowClosed.connect(self.LastWindowsClose)
        screens = QGuiApplication.screens()
        # print(screens[0].geometry(), screens[1].geometry())
        if Setting.ScreenIndex.value >= len(screens):
            desktop = QGuiApplication.primaryScreen().geometry()
        else:
            desktop = screens[Setting.ScreenIndex.value].geometry()

        self.adjustSize()
        self.resize(desktop.width() // 4 * 3, desktop.height() // 4 * 3)
        self.move(self.width() // 8+desktop.x(), max(0, desktop.height()-self.height()) // 2+desktop.y())
        print(desktop.size(), self.size())
        self.setAttribute(Qt.WA_StyledBackground, True)

        self.loadingDialog = LoadingDialog(self)
        self.navigationWidget.helpButton.click()
        self.subStackWidget.setCurrentIndex(self.subStackWidget.indexOf(self.helpView))
        self.__initWidget()

        # 窗口切换相关
        self.toolButtons = []
        self.toolLabels = []
        self.toolButtonGroup = QButtonGroup()
        self.toolButtonGroup.idClicked.connect(self.SwitchWidgetByIndex)
        self.menuButton.clicked.connect(self.CheckShowMenu)
        self.UpdateTabBar()

        # self.subStackWidget.setCurrentIndex(0)


        self.settingView.LoadSetting()
        GlobalConfig.LoadSetting()

        self.searchView.searchTab.hide()
        self.searchView2.bookList.isOpen2 = True
        self.searchView2.searchWidget.hide()
        self.searchView2.cateLabel.hide()
        self.searchView2.monthBox.hide()
        self.searchView2.typeBox.hide()
        self.searchView2.yearBox.hide()
        if platform_mobile.SupportSystemTray:
            self.myTrayIcon = MySystemTrayIcon()
            self.myTrayIcon.show()
        else:
            # Android 没有系统托盘
            self.myTrayIcon = None
        self.totalStackWidget.currentChanged.connect(self.SwitchReadView)
        self.waifu2xToolView.headButton.setVisible(False)
        # 手机竖屏适配(桌面端为空操作)
        mobile_ui.Apply(self)
        # self.readView.LoadSetting()
        # QApplication.instance().installEventFilter(self)
        # QtOwner().app.paletteChanged.connect(self.CheckPaletteChanged)

    @property
    def isMaxSize(self):
        return QtOwner().isMaxSize

    @isMaxSize.setter
    def isMaxSize(self, v):
        QtOwner().isMaxSize = v

    def BackOldSize(self):
        self.isMaxSize = self.isMaximized()
        return

    def SwitchReadView(self, i):
        ## 备份原来的大小
        if i == 0:
            # windows
            if not sys.platform == "darwin" and not platform_mobile.IsAndroid():
                if self.isMaxSize and self.windowState != Qt.WindowState.WindowMaximized:
                    self.showMaximized()
            # Macos只有全屏和非全屏
        return

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            timer = getattr(self, "_stateChangeTimer", None)
            if timer is not None:
                # 最大化/还原/全屏是一次性的状态切换：Qt 自己只会重绘一次，
                # 结束缩放合并、按正常流程重绘即可。若走缩放合并，
                # 窗口内容要等几十毫秒才刷新，看起来就是最大化时闪烁重绘
                self._isStateChange = True
                timer.start()
                self.ResetResizeRepaint()
            self.WindowsSizeChange.emit()
            if platform_mobile.IsAndroid():
                mobile_ui.LogUiEvent("windowStateChange -> {} visible={} active={}".format(
                    self.windowState().name if hasattr(self.windowState(), "name") else "?",
                    self.isVisible(), self.isActiveWindow()))
        return super(self.__class__, self).changeEvent(event)

    def showEvent(self, event):
        # 防止窗口在暂停重绘期间被隐藏/显示后一直不刷新
        self.ResetResizeRepaint()
        mobile_ui.OnShown(self)
        return super(self.__class__, self).showEvent(event)

    def hideEvent(self, event):
        if platform_mobile.IsAndroid():
            mobile_ui.LogUiEvent("hideEvent (窗口被隐藏)")
        return super(self.__class__, self).hideEvent(event)

    def resizeEvent(self, event):
        super(self.__class__, self).resizeEvent(event)
        timer = getattr(self, "_resizeRepaintTimer", None)
        if timer is None or not self.isVisible():
            return

        # 手机竖屏/旋转/软键盘弹出：重新适配抽屉几何与最小尺寸(桌面端空操作)
        mobile_ui.OnResize(self)

        if self._isStateChange:
            # 状态切换引起的尺寸变化：按正常流程重绘，不做缩放合并
            self.ResetResizeRepaint()
            return

        # 拖动窗口边框时会连续收到resize事件，每个都重绘整个窗口会闪烁，
        # 所以先暂停重绘，等缩放停下来后再统一重绘一次
        if timer.isActive():
            return
        self.PauseRepaint()

    def PauseRepaint(self):
        """ 暂停窗口重绘，等缩放停下来后再统一重绘一次 """
        if self.isVisible() and self.updatesEnabled():
            self.setUpdatesEnabled(False)
            # 加载框，提示条等子窗口是独立的窗口，不受主窗口暂停重绘的影响
            for child in self.findChildren(QWidget, "", Qt.FindDirectChildrenOnly):
                if child.isWindow():
                    child.setUpdatesEnabled(True)
        self._resizeRepaintTimer.start(MainView.ResizeRepaintInterval)

    def _EndStateChange(self):
        self._isStateChange = False

    def ResetResizeRepaint(self):
        """ 结束重绘合并，恢复窗口重绘并同步刷新一次 """
        timer = getattr(self, "_resizeRepaintTimer", None)
        if timer is not None:
            timer.stop()
        if not self.updatesEnabled():
            self.setUpdatesEnabled(True)
            # 同步重绘一次，保证缩放结束后窗口内容是最新的(异步update可能被合并丢弃)
            self.repaint()
        return

    # def eventFilter(self, watched, event) -> bool:
    #     if watched == QtOwner().app:
    #         print(event.type(), event)
    #     return False

    # def event(self, ev):
    #     """Catch system events."""
    #     # print(ev)
    #     if ev.type() == QEvent.ApplicationPaletteChange:  # detect theme switches
    #         pass
    #         # style = interface_style()  # light or dark
    #         # if style is not None:
    #         #     QIcon.setThemeName(style)
    #         # else:
    #         #     QIcon.setThemeName("light")  # fallback
    #     return super().event(ev)
    #
    # def CheckPaletteChanged(self, data):
    #     print(data)

    @property
    def subStackList(self):
        return self.subStackWidget.subStackList

    @subStackList.setter
    def subStackList(self, value):
        self.subStackWidget.subStackList = value

    def __initWidget(self):
        self.navigationWidget.indexButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.indexView)))
        self.navigationWidget.settingButton.clicked.connect(partial(self.SwitchWidgetByIndex, self.subStackWidget.indexOf(self.settingView)))
        self.navigationWidget.searchButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.searchView)))
        self.navigationWidget.collectButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.favoriteView)))
        self.navigationWidget.helpButton.clicked.connect(partial(self.SwitchWidgetByIndex, self.subStackWidget.indexOf(self.helpView)))
        self.navigationWidget.commentButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.allCommentView)))
        self.navigationWidget.waifu2xButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.waifu2xToolView)))
        self.navigationWidget.downloadButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.downloadView)))
        self.navigationWidget.categoryButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.categoryView)))
        self.navigationWidget.myCommentButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.myCommentView)))
        self.navigationWidget.historyButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.historyView)))
        self.navigationWidget.remoteHistoryButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.remoteHistoryView)))
        self.navigationWidget.localReadButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.localReadView)))
        self.navigationWidget.localCollectButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.localFavoriteView)))
        self.navigationWidget.weekButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.weekView)))
        self.navigationWidget.nasButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.nasView)))
        self.navigationWidget.batchSrButton.clicked.connect(partial(self.SwitchWidgetAndClear, self.subStackWidget.indexOf(self.batchSrView)))

    def RetranslateUi(self):
        #main folder
        Main.retranslateUi(self, self)
        #category folder
        self.categoryView.retranslateUi(self.categoryView)
        #comment folder
        self.allCommentView.retranslateUi(self.allCommentView)
        self.commentView.retranslateUi(self.commentView)
        self.myCommentView.retranslateUi(self.myCommentView)
        self.subCommentView.retranslateUi(self.subCommentView)
        #download folder
        self.downloadAllView.retranslateUi(self.downloadAllView)
        self.downloadView.retranslateUi(self.downloadView)
        self.downloadSomeView.retranslateUi(self.downloadSomeView)
        #help folder
        self.helpView.retranslateUi(self.helpView)
        #history folder
        self.historyView.retranslateUi(self.historyView)
        self.remoteHistoryView.retranslateUi(self.remoteHistoryView)
        #index folder
        self.indexView.retranslateUi(self.indexView)
        self.weekView.retranslateUi(self.weekView)
        #info folder
        self.bookEpsView.retranslateUi(self.bookEpsView)
        self.bookInfoView.retranslateUi(self.bookInfoView)
        #read folder
        self.readView.retranslateUi(self.readView)
        #search folder
        self.searchView.retranslateUi(self.searchView)
        #setting folder
        self.settingView.retranslateUi(self.settingView)
        #tool folder
        self.waifu2xToolView.retranslateUi(self.waifu2xToolView)
        self.batchSrView.retranslateUi(self.batchSrView)
        #user folder
        self.favoriteView.retranslateUi(self.favoriteView)
        self.localFavoriteView.retranslateUi(self.localFavoriteView)
        self.localReadView.retranslateUi(self.localReadView)
        self.localReadAllView.retranslateUi(self.localReadAllView)
        self.localReadEpsView.retranslateUi(self.localReadEpsView)
        #widgets
        self.navigationWidget.retranslateUi(self.navigationWidget)
        self.searchView2.retranslateUi(self.searchView2)
        self.nasView.retranslateUi(self.nasView)
        self.localReadView.retranslateUi(self.localReadView)
        self.bookInfoView.retranslateUi(self.bookInfoView)
        self.loginNewView.retranslateUi(self.loginNewView)

    def Init(self):
        IsCanUse = False
        self.SwitchWidgetAndClear(self.subStackWidget.indexOf(self.helpView))
        self.helpView.Init()
        self.downloadView.Init()
        self.nasView.Init()
        Server().Init()
        # sr_vulkan 初始化失败会直接让进程崩溃(0xC0000005)，进程内无法捕获，
        # 所以先在子进程里探测一次，失败就禁用超分，保证程序能正常启动
        waifu2xGpuId = None
        waifu2xCpuNum = None
        if config.CanWaifu2x:
            if sr_backend.CanUseSubProcessProbe():
                ok, waifu2xGpuId, waifu2xCpuNum, errMsg = self.CheckWaifu2x()
            else:
                # Android: sr_qnn(ONNX Runtime + QNN) 初始化不会让进程崩溃，
                # 且无法 fork python 子进程，直接进程内初始化
                ok, waifu2xGpuId, waifu2xCpuNum, errMsg = True, None, None, ""
            if not ok:
                config.CanWaifu2x = False
                config.ErrorMsg = errMsg
        if config.CanWaifu2x:
            from sr_vulkan import sr_vulkan as sr
            stat = sr.init()
            sr.setDebug(True)
            if stat < 0:
                pass
                # QtOwner().ShowMsg(self.tr("未发现支持VULKAN的GPU, Waiuf2x当前为CPU模式, " + ", code:{}".format(str(stat))))
                # CPU 模式，暂时不开放看图下的转换
                # config.IsOpenWaifu = 0
                # self.settingForm.checkBox.setEnabled(False)
                # self.qtImg.frame.qtTool.checkBox.setEnabled(False)

            IsCanUse = True
            gpuInfo = sr.getGpuInfo()
            cpuNum = sr.getCpuCoreNum()
            gpuNum = sr.getGpuCoreNum()
            self.settingView.SetGpuInfos(gpuInfo, cpuNum)
            # 以探测时的显卡/线程为准，避免设置界面显示的设备与实际使用的不一致
            if waifu2xGpuId is not None and 0 <= waifu2xGpuId < len(gpuInfo or []):
                config.Encode = waifu2xGpuId
                config.EncodeGpu = gpuInfo[waifu2xGpuId]
            if waifu2xCpuNum is not None:
                config.UseCpuNum = waifu2xCpuNum
            # if not gpuInfo or (gpuInfo and config.Encode < 0) or (gpuInfo and config.Encode >= len(gpuInfo)):
            #     config.Encode = 0

            sts = sr.initSet(config.Encode, config.UseCpuNum)
            TaskWaifu2x().Start()

            version = sr.getVersion()
            config.Waifu2xVersion = version
            self.helpView.waifu2x.setText(config.Waifu2xVersion)
            # 记录验证通过的配置：下次同样的配置可以直接初始化，不用再探测
            from tools.waifu2x_check import Waifu2xChecker
            Waifu2xChecker.SaveCheckKey(Setting.SelectEncodeGpu.value, Setting.Waifu2xCpuCore.value,
                                        config.Encode, config.UseCpuNum)
            Log.Warn("Waifu2x init:{}, encode:{}, version:{}, code:{}, cpuNum:{}/{}, gpuNum:{}, gpuList:{}".format(
                stat, config.Encode, version, sts, config.UseCpuNum, cpuNum, gpuNum, gpuInfo
            ))
        else:
            QtOwner().ShowError("Waifu2x Error, " + config.ErrorMsg)
            Log.Warn("Waifu2x Error: " + str(config.ErrorMsg))

        if not IsCanUse:
            self.settingView.readCheckBox.setEnabled(False)
            self.settingView.coverCheckBox.setEnabled(False)
            self.settingView.downAuto.setEnabled(False)
            self.readView.frame.qtTool.checkBox.setEnabled(False)
            Setting.DownloadAuto.SetValue(0)
            Setting.CoverIsOpenWaifu.SetValue(0)
            # self.downloadView.radioButton.setEnabled(False)
            self.waifu2xToolView.checkBox.setEnabled(False)
            self.waifu2xToolView.changeButton.setEnabled(False)
            self.waifu2xToolView.changeButton.setEnabled(False)
            self.waifu2xToolView.modelName.setEnabled(False)
            self.waifu2xToolView.ttaModel.setEnabled(False)
            self.waifu2xToolView.changeButton.setEnabled(False)
            self.waifu2xToolView.SetStatus(False)
            Setting.IsOpenWaifu.SetValue(0)

        if Setting.IsUpdate.value:
            self.helpView.InitUpdate()

        TaskMulti().Start()
        self.searchView.InitWord()
        self.msgLabel = MsgLabel(self)
        self.msgLabel.hide()
        # self.AddHttpTask(req.LoginCheck301Req(), callBack=self.LoginCheckBack)
        # QtReadImgPoolManager().Init()

        if not Setting.SavePath.value:
            view = DownloadDirView(self)
            view.show()
            view.closed.connect(self.OpenLoginView)
        else:
            self.OpenLoginView()

    def CheckWaifu2x(self):
        """ 探测 waifu2x(sr_vulkan) 能否正常初始化

        该库在部分显卡/驱动环境下初始化会直接让进程崩溃，进程内捕获不到，
        所以放到子进程里验证；返回 (是否可用, 显卡序号, cpu线程数, 失败原因)
        """
        try:
            from tools.waifu2x_check import Waifu2xChecker
            ok, gpuId, realCpuNum, errMsg = Waifu2xChecker().Check(Setting.SelectEncodeGpu.value,
                                                                   Setting.Waifu2xCpuCore.value)
            Log.Warn("Waifu2x check: ok:{}, gpuId:{}, cpuNum:{}, msg:{}".format(ok, gpuId, realCpuNum, errMsg))
            return ok, gpuId, realCpuNum, errMsg
        except Exception as es:
            # 探测本身出错时不改变原有流程
            Log.Error(es)
            return True, None, None, ""

    # def LoginCheckBack(self, raw):
    #     self.AddHttpTask(req.LoginPreReq())

    def ClearTabBar(self):
        for toolButton in self.toolButtons:
            self.menuLayout.removeWidget(toolButton)
            toolButton.setParent(None)
        for label in self.toolLabels:
            self.menuLayout.removeWidget(label)
            label.setParent(None)
        self.toolButtons = []
        self.toolLabels = []
        self.subStackList = []
        return

    def UpdateTabBar(self):
        for index, i in enumerate(self.subStackList):
            if index >= len(self.toolButtons):
                button = QToolButton()
                button.setCheckable(True)
                button.setText(self.subStackWidget.widget(i).windowTitle())

                if index == 0:
                    button.setChecked(True)
                else:
                    label = QLabel(">")
                    self.menuLayout.addWidget(label)
                    self.toolLabels.append(label)

                self.toolButtonGroup.addButton(button)
                self.toolButtonGroup.setId(button, i)
                self.menuLayout.addWidget(button)
                self.toolButtons.append(button)
        return

    def OpenLoginView(self):
        self.navigationWidget.OpenLoginView()
        # 如果以前登录过才弹出登录
        # if Setting.Password.value:
        #     self.navigationWidget.OpenLoginView()
        # else:
        #     self.LoginSucBack()

    def LoginSucBack(self):
        self.SwitchWidgetAndClear(self.subStackWidget.indexOf(self.indexView))

    def SwitchWidgetNext(self):
        index = self.subStackWidget.currentIndex()
        if index in self.subStackList:
            subIndex = self.subStackList.index(index)
            if subIndex >= len(self.subStackList) -1:
                return
            self.SwitchWidgetByIndex(self.subStackList[subIndex+1])

    def SwitchWidgetLast(self):
        index = self.subStackWidget.currentIndex()
        if index in self.subStackList:
            subIndex = self.subStackList.index(index)
            if subIndex <= 0:
                return
            self.SwitchWidgetByIndex(self.subStackList[subIndex-1])

    def SwitchWidget(self, widget, **kwargs):
        return self.SwitchWidgetByIndex(self.subStackWidget.indexOf(widget), **kwargs)

    def SwitchWidgetByIndex(self, index, **kwargs):
        if index == self.subStackWidget.currentIndex():
            self.subStackWidget.widget(index).SwitchCurrent(**kwargs)
            return
        if index not in self.subStackList:
            # 需要清除後面的界面
            # 当前页不在 subStackList 里时(直接操作过页面栈、或状态被外部改过)，
            # list.index() 会抛 ValueError: N is not in list，整个导航就断了。
            # 这里退化成"从头开始"，至少保证能切过去。
            try:
                currrentListIndex = self.subStackList.index(self.subStackWidget.currentIndex())
            except ValueError:
                currrentListIndex = -1
                Log.Warn("subStackList 里没有当前页 {}，按从头开始处理".format(
                    self.subStackWidget.currentIndex()))
            subStackList = self.subStackList[:currrentListIndex+1]

            self.ClearTabBar()
            self.subStackList = subStackList
            self.subStackList.append(index)
            self.UpdateTabBar()
        self.subStackWidget.SwitchWidgetByIndex(index, **kwargs)
        # self.toolButtonGroup.id()
        for button in self.toolButtons:
            if self.toolButtonGroup.id(button) == index:
                button.setChecked(True)
                button.setText(self.subStackWidget.widget(index).windowTitle())
        return

    def SwitchWidgetAndClear(self, index):
        self.ClearTabBar()
        self.subStackList = [index]
        kwargs = {"refresh": True}
        self.subStackWidget.SwitchWidgetByIndex(index, **kwargs)
        self.UpdateTabBar()
        # 手机端：点击导航后自动收起抽屉
        mobile_ui.CloseDrawer(self)
        return

    # def resizeEvent(self, e):
    #     super().resizeEvent(e)
    #     self.adjustWidgetGeometry()

    # def LastWindowsClose(self):
    #     self.window().close()
    #     return

    def closeEvent(self, a0) -> None:
        if self.totalStackWidget.currentIndex() == 1:
            self.readView.Close()
            a0.ignore()
            return

        if not self.isHidden():
            if platform_mobile.SupportSystemTray and Setting.ShowCloseType.value == 1 and QtOwner().closeType == 1:
                QtOwner().app.setQuitOnLastWindowClosed(False)
                self.myTrayIcon.show()
                self.hide()
                a0.ignore()
                return
            # if not Setting.IsNotShowCloseTip.value and QtOwner().closeType == 1:
                # log = ShowCloseDialog(QtOwner().owner)
                # log.show()
                # log.LoadSetting()
                # a0.ignore()
                # return

            # if  Setting.ShowCloseType.value == 2:
            #     self.myTrayIcon.show()
            #     self.hide()
            #     a0.ignore()
            #     return
        QtOwner().app.setQuitOnLastWindowClosed(True)
        super().closeEvent(a0)
        # reply = QtOwner().ShowMsgBox(QMessageBox.Question, self.tr('提示'), self.tr('确定要退出吗？'))
        self.GetExitScreen()

        # 点击关闭按钮或者点击退出事件会出现图标无法消失的bug，需要手动将图标内存清除
        # self.myTrayIcon = None
        a0.accept()

    def GetExitScreen(self):
        screens = QGuiApplication.screens()
        # print(self.pos())
        # for screen in screens:
        #     print(screen.geometry())
        screen = QGuiApplication.screenAt(self.pos()+QPoint(self.width()//2, self.height()//2))
        if screen in screens:
            index = screens.index(screen)
            Setting.ScreenIndex.SetValue(index)
            Log.Info("Exit screen index:{}".format(str(index)))

    def CheckShowMenu(self):
        # 手机端：抽屉由 mobile_ui 接管(避开顶栏 + 带遮罩/点空白关闭)，
        # 不能用基类 aniShow/aniHide —— 它们的宽度动画会和 setFixedWidth 互相打架
        if mobile_ui.ToggleDrawer(self):
            return
        if self.navigationWidget.isHidden():
            self.navigationWidget.aniShow()
        else:
            self.navigationWidget.aniHide()
        return

    def keyPressEvent(self, event) -> None:
        # Android 返回键/手势：优先收看图菜单，其次退看图、回退页面，最后退到后台
        # (真机上按下和抬起都会来，去抖在 mobile_ui.HandleBackKey 里做)
        if event.key() in (Qt.Key_Escape, Qt.Key.Key_Back):
            if mobile_ui.HandleBackKey(self):
                event.accept()
                return
        return super(self.__class__, self).keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        # 返回键的按下已经在 keyPressEvent 里处理并 accept 了，抬起这里只做兜底
        if event.key() in (Qt.Key_Escape, Qt.Key.Key_Back):
            mobile_ui.HandleBackKey(self)
            event.accept()
            return
        return super(self.__class__, self).keyReleaseEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.ForwardButton:
            self.SwitchWidgetNext()
        elif event.button() == Qt.BackButton:
            self.SwitchWidgetLast()
        self.searchView.lineEdit.CheckClick(event.pos())
        return super(self.__class__, self).mousePressEvent(event)
    #
    # def changeEvent(self, ev):
    #     if sys.platform == 'darwin':
    #         OSX_LIGHT_MODE = 236
    #         OSX_DARK_MODE = 50
    #         if ev.type() == QEvent.PaletteChange:
    #             bg = self.palette().color(QPalette.Active, QPalette.Window)
    #             if bg.lightness() == OSX_LIGHT_MODE:
    #                 print("MacOS light theme")
    #                 return
    #             elif bg.lightness() == OSX_DARK_MODE:
    #                 print("MacOS dark theme")
    #                 return
    #     return super(self.__class__, self).changeEvent(ev)

    def nativeEvent(self, eventType, message):
        # print(eventType, message)
        if eventType == "windows_generic_MSG":
            try:
                from ctypes.wintypes import POINT
                import ctypes.wintypes
            except Exception as es:
                return super(self.__class__, self).nativeEvent(eventType, message)

            msg = ctypes.wintypes.MSG.from_address(message.__int__())
            # print(msg.message, self.GetWinSysColor())
            if msg.message == 26 and Setting.ThemeIndex.value == 0:
                self.settingView.SetTheme()

        return super(self.__class__, self).nativeEvent(eventType, message)

    def Close(self):
        # TODO 停止所有的定时器以及线程
        self.loadingDialog.close()
        self.downloadView.Close()
        self.nasView.Close()
        self.searchView.Stop()
        self.readView.Stop()
        self.batchSrView.Stop()
        self.navigationWidget.Stop()
        TaskWaifu2x().Stop()
        TaskQImage().Stop()
        # QtReadImgPoolManager().Stop()
        # TaskDownload().Stop()
        Server().Stop()
        TaskMulti().Stop()
        # QtTask().Stop()

    def OnNewConnection(self):
        socket = QtOwner().localServer.nextPendingConnection()
        socket.readyRead.connect(self.OnReadConnection)
        return

    def OnReadConnection(self):
        conn = self.sender()
        if not conn:
            return
        data = conn.readAll()
        if data == b"restart":
            self.show()
            self.showNormal()
