from PySide6 import QtWidgets
from PySide6.QtCore import QTimer

from component.dialog.base_mask_dialog import BaseMaskDialog
from component.label.gif_label import GifLabel
from config.global_config import GlobalConfig
from config.setting import Setting
from interface.ui_login_new import Ui_LoginNew
from qt_owner import QtOwner
from server import req
from task.qt_task import QtTaskBase
from tools.log import Log
from tools.str import Str
from view.user.login_new_widget import LoginNewWidget
from view.user.login_proxy_new_widget import LoginProxyNewWidget
from view.user.register_new_widget import RegisterNewWidget
from view.user.user_manager_new_widget import UserManagerNewWidget


class LoginNewView(QtWidgets.QWidget, Ui_LoginNew, QtTaskBase):

    def __init__(self):
        super(self.__class__, self).__init__()
        Ui_LoginNew.__init__(self)
        QtTaskBase.__init__(self)
        self.setupUi(self)
        self.tabWidget.setCurrentIndex(0)
        self.tabWidget.currentChanged.connect(self.CheckInit)
        self.loginWidget = LoginNewWidget(self)
        self.proxyWidget = LoginProxyNewWidget(self)
        self.registerWidget = RegisterNewWidget(self)
        self.userManagerWidget = UserManagerNewWidget(self)
        self.isInit = False
        self.echConfigIndex = 0
        self.dohDomainList = []
        # 每5分钟更新echconfig
        self.timer = QTimer(self)
        self.timer.setInterval(1000*(15*60))
        self.timer.timeout.connect(self.HourTimeOut)

    def retranslateUi(self, Nas):
        themId = Setting.ThemeIndex.autoValue
        if themId != 1:
            qss = """
                .QFrame
                {
                    background-color: rgb(253, 253, 253);

                    border:2px solid rgb(234,234,234);
                    border-radius:5px
                }        
                """
        else:
            qss = """
                .QFrame
                {
                    background-color: rgb(50, 50, 50);

                    border:2px solid rgb(35,35,35);
                    border-radius:5px
                }        
                """
        self.tab_4.setStyleSheet(qss)
        Ui_LoginNew.retranslateUi(self, self)

    def SwitchCurrent(self, **kwargs):
        if not self.isInit:
            self.isInit = True
            self.Init()
        refresh = kwargs.get("refresh")
        index = kwargs.get("page")
        if not refresh:
            return
        if index != None:
            self.tabWidget.setCurrentIndex(index)
        self.CheckInit()
        pass

    def CheckInit(self):
        if self.tabWidget.currentIndex() == 3:
            self.proxyWidget.Init()
        elif self.tabWidget.currentIndex() == 1:
            self.registerWidget.Init()
        elif self.tabWidget.currentIndex() == 0:
            self.loginWidget.Init()

    def Init(self):
        self.timer.start()
        self.InitEchConfig()

    def HourTimeOut(self):
        self.InitEchConfig()

    def InitEchConfig(self):
        # self.echConfigIndex = 0
        self.dohDomainList = GlobalConfig.DohUrlList.value[:]
        if Setting.DohAddress.value and Setting.DohAddress.value in self.dohDomainList:
            self.dohDomainList.remove(Setting.DohAddress.value)
        if Setting.DohAddress.value:
            self.dohDomainList.insert(0, Setting.DohAddress.value)
        if not self.dohDomainList:
            return
        request = req.GetEchConfigReq(GlobalConfig.EchDomain.value, self.dohDomainList)
        self.AddHttpTask(request, self.InitEchConfigBack)

    def InitEchConfigBack(self, raw):
        """ ECH 配置回包：成功存起来并 15 分钟后再取，失败 1 分钟重试

        旧版代理页有一行小字(echTick)显示"ECH 配置更新时间"，登录/代理页重构
        (5aa8613) 之后那个标签已经删掉了。之前这里还在 setText，抛的
        AttributeError 被 except 吞掉 —— 表面上"不影响使用"，但异常发生在
        timer.stop() 之前，等于**拿到配置也停不掉失败时设的 1 分钟重试节奏**，
        于是每 1 分钟发一次 DoH 查询。状态现在只记日志(带时间戳)。
        """
        try:
            st = raw.get("st")
            data = raw.get('data')
            if st != Str.Ok or not data:
                Log.Warn("not fetch ech config")
                self.RestartEchTimer(60)
            else:
                QtOwner().echConfig = data
                Log.Info("update ech config, {}".format(data))
                self.RestartEchTimer(15 * 60)
        except Exception as es:
            Log.Error(es)

    def RestartEchTimer(self, seconds):
        """ 重设定时器节奏(先 stop 再改 interval，运行中的 QTimer 才会用新值) """
        self.timer.stop()
        self.timer.setInterval(1000 * seconds)
        self.timer.start()
        return
