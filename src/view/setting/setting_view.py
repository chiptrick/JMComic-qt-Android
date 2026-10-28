import base64
import os
import re
import sys
from functools import partial

from PySide6 import QtWidgets
from PySide6.QtCore import QSettings, Qt, QSize, QUrl, QFile, QTranslator, QLocale
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import QFileDialog

from config import config
from config.setting import Setting, SettingValue
from component.widget.sr_model_table import FormatModelLabel
from interface.ui_setting_new import Ui_SettingNew
from qt_owner import QtOwner
from tools.log import Log
from tools.str import Str
from tools.tool import ToolUtil
from tools import mobile_file_dialog
from tools import platform_mobile
from view.tool.doh_dns_view import DohDnsView


class SettingView(QtWidgets.QWidget, Ui_SettingNew):
    def __init__(self, parent=None):
        super(self.__class__, self).__init__(parent)
        Ui_SettingNew.__init__(self)
        self.setupUi(self)

        # 路径标签：整宽折行显示完整路径(不做中间省略)。水平 sizeHint 不参与
        # 布局宽度计算，否则 QLabel 会按整段路径把整页撑到屏幕外。
        for label in (self.downloadDir, self.cacheDir, self.chatDir, self.waifu2xDir):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Ignored,
                                           QtWidgets.QSizePolicy.Preferred)
            # 高度必须跟着折行算(否则 Qt 只给一行的高度，长路径下半截被裁掉)
            policy.setHeightForWidth(True)
            label.setSizePolicy(policy)

        self.mainSize = None
        self.bookSize = None
        self.readSize = None
        self.userId = ""
        self.passwd = ""
        self.gpuInfos = []
        self.translate = QTranslator()
        for name in QFontDatabase.families():
            self.fontBox.addItem(name)

        # RadioButton:
        self.themeGroup.buttonClicked.connect(partial(self.ButtonClickEvent, Setting.ThemeIndex))
        self.languageGroup.buttonClicked.connect(partial(self.ButtonClickEvent, Setting.Language))
        self.logGroup.buttonClicked.connect(partial(self.ButtonClickEvent, Setting.LogIndex))
        self.proxyGroup.buttonClicked.connect(partial(self.ButtonClickEvent, Setting.IsHttpProxy))
        self.saveNameGroup.buttonClicked.connect(partial(self.ButtonClickEvent, Setting.SaveNameType))

        # CheckButton:
        self.checkBox_IsUpdate.clicked.connect(partial(self.CheckButtonEvent, Setting.IsUpdate, self.checkBox_IsUpdate))
        self.readCheckBox.clicked.connect(partial(self.CheckButtonEvent, Setting.IsOpenWaifu, self.readCheckBox))
        self.preDownWaifu2x.clicked.connect(partial(self.CheckButtonEvent, Setting.PreDownWaifu2x, self.preDownWaifu2x))
        self.coverCheckBox.clicked.connect(partial(self.CheckButtonEvent, Setting.CoverIsOpenWaifu, self.coverCheckBox))
        self.downAuto.clicked.connect(partial(self.CheckButtonEvent, Setting.DownloadAuto, self.downAuto))
        # self.titleBox.clicked.connect(partial(self.CheckButtonEvent, Setting.IsUseTitleBar, self.titleBox))
        self.openglBox.clicked.connect(partial(self.CheckButtonEvent, Setting.IsOpenOpenGL, self.openglBox))

        # LineEdit:
        self.httpEdit.editingFinished.connect(partial(self.LineEditEvent, Setting.HttpProxy, self.httpEdit))
        # self.dohLine.editingFinished.connect(partial(self.LineEditEvent, Setting.DohAddress, self.dohLine))
        # Button:

        # comboBox:
        # self.encodeSelect.currentIndexChanged.connect(partial(self.CheckRadioEvent, "LookReadMode"))
        # self.readModel.currentIndexChanged.connect(partial(self.CheckRadioEvent, Setting.LookModel))
        # self.readNoise.currentIndexChanged.connect(partial(self.CheckRadioEvent, Setting.LookNoise))
        # self.coverModel.currentIndexChanged.connect(partial(self.CheckRadioEvent, Setting.CoverLookModel))
        # self.coverNoise.currentIndexChanged.connect(partial(self.CheckRadioEvent, Setting.CoverLookNoise))
        # self.downModel.currentIndexChanged.connect(partial(self.CheckRadioEvent, Setting.DownloadModel))
        # self.downNoise.currentIndexChanged.connect(partial(self.CheckRadioEvent, Setting.DownloadNoise))

        self.readModelName.clicked.connect(partial(self.CheckOpenSrSelect, Setting.LookModelName, self.readModelName))
        self.coverModelName.clicked.connect(partial(self.CheckOpenSrSelect, Setting.CoverLookModelName, self.coverModelName))
        self.downModelName.clicked.connect(partial(self.CheckOpenSrSelect, Setting.DownloadModelName, self.downModelName))

        self.encodeSelect.currentTextChanged.connect(partial(self.CheckRadioEvent, Setting.SelectEncodeGpu))
        self.threadSelect.currentIndexChanged.connect(partial(self.CheckRadioEvent, Setting.Waifu2xCpuCore))
        self.titleLineBox.currentIndexChanged.connect(partial(self.CheckRadioEvent, Setting.TitleLine))
        self.categoryBox.currentIndexChanged.connect(partial(self.CheckRadioEvent, Setting.NotCategoryShow))
        self.fontBox.currentTextChanged.connect(partial(self.CheckRadioEvent, Setting.FontName))
        self.fontSize.currentTextChanged.connect(partial(self.CheckRadioEvent, Setting.FontSize))
        self.fontStyle.currentIndexChanged.connect(partial(self.CheckRadioEvent, Setting.FontStyle))
        self.tileComboBox.currentIndexChanged.connect(partial(self.CheckRadioEvent, Setting.Waifu2xTileSize))
        self.colorBox.currentIndexChanged.connect(partial(self.CheckRadioEvent, Setting.ThemeColorIndex))

        # spinBox
        # self.preDownNum.valueChanged.connect(partial(self.SpinBoxEvent, "", self.preDownNum))
        self.coverSize.valueChanged.connect(partial(self.SpinBoxEvent, Setting.CoverSize))
        self.categorySize.valueChanged.connect(partial(self.SpinBoxEvent, Setting.CategorySize))
        self.readScale.valueChanged.connect(partial(self.SpinBoxEvent, Setting.LookScale))
        self.coverScale.valueChanged.connect(partial(self.SpinBoxEvent, Setting.CoverLookScale))
        self.downScale.valueChanged.connect(partial(self.SpinBoxEvent, Setting.DownloadScale))
        self.lookMaxBox.valueChanged.connect(partial(self.SpinBoxEvent, Setting.LookMaxNum))
        self.coverMaxBox.valueChanged.connect(partial(self.SpinBoxEvent, Setting.CoverMaxNum))
        self.threadSpin.valueChanged.connect(partial(self.SpinBoxEvent, Setting.MultiNum))

        self.generalButton.clicked.connect(partial(self.MoveToLabel, self.generalLabel))
        # self.readButton.clicked.connect(partial(self.MoveToLabel, self.readLabel))
        self.proxyButton.clicked.connect(partial(self.MoveToLabel, self.proxyLabel))
        self.waifu2xButton.clicked.connect(partial(self.MoveToLabel, self.waifu2xLabel))
        self.downloadButton.clicked.connect(partial(self.MoveToLabel, self.downloadLabel))

        self.setDirButton.clicked.connect(self.SelectSavePath)
        self.cacheDirButton.clicked.connect(self.SelectCachePath)
        self.cacheResetButton.clicked.connect(self.ResetCachePath)
        self.openDownloadDir.clicked.connect(partial(self.OpenDir, self.downloadDir))
        self.openCacheDir.clicked.connect(partial(self.OpenDir, self.cacheDir))
        self.openWaifu2xDir.clicked.connect(partial(self.OpenDir, self.waifu2xDir))

        self.openProxy.clicked.connect(self.OpenProxy)

        self.languageButton3.setVisible(True)
        self.categorySize.setVisible(False)
        if platform_mobile.IsMobile():
            # 聊天缓存这一行当前没有数据来源(永远空着)，手机上直接隐藏省空间
            self.chatDirBox.setVisible(False)

        self.msgLabel.setVisible(False)

        # self.dohButton.clicked.connect(self.OpenDohView)

    def MoveToLabel(self, label):
        p = label.pos()
        self.scrollArea.vScrollBar.ScrollTo(p.y())
        return

    def CheckMsgLabel(self):
        isNeed = False
        for name in dir(Setting):
            setItem = getattr(Setting, name)
            if isinstance(setItem, SettingValue):
                if setItem.isNeedReset:
                    if setItem.value != setItem.setV:
                        isNeed = True
        if isNeed:
            self.msgLabel.setVisible(True)
            QtOwner().ShowErrOne(Str.GetStr(Str.NeedResetSave))
        else:
            self.msgLabel.setVisible(False)
        return

    def ButtonClickEvent(self, setItem, button):
        assert isinstance(setItem, SettingValue)
        mo = re.search(r"\d+", button.objectName())
        if mo:
            value = int(mo.group())
            setItem.SetValue(value)
            if setItem == Setting.ThemeIndex:
                self.SetTheme()
            elif setItem == Setting.LogIndex:
                Log.UpdateLoggingLevel()
            elif setItem == Setting.Language:
                self.SetLanguage()
            elif setItem == Setting.IsHttpProxy:
                pass
                # from server.server import Server
                # Server().UpdateProxy()
            QtOwner().ShowMsgOne(Str.GetStr(Str.SaveSuc))
        self.CheckMsgLabel()
        return

    def CheckButtonEvent(self, setItem, button):
        assert isinstance(setItem, SettingValue)
        setItem.SetValue(int(button.isChecked()))
        QtOwner().ShowMsgOne(Str.GetStr(Str.SaveSuc))
        self.CheckMsgLabel()
        return

    def CheckOpenSrSelect(self, setItem, button):
        if button == self.coverModelName:
            QtOwner().OpenSrSelectModel(setItem.value, self.CheckOpenSrSelectCoverBack)
        elif button == self.readModelName:
            QtOwner().OpenSrSelectModel(setItem.value, self.CheckOpenSrSelectReadBack)
        elif button == self.downModelName:
            QtOwner().OpenSrSelectModel(setItem.value, self.CheckOpenSrSelectDownBack)
        pass

    def CheckOpenSrSelectCoverBack(self, modelName):
        Setting.CoverLookModelName.SetValue(modelName)
        self.SetModelButton(self.coverModelName, modelName)
        return modelName

    def CheckOpenSrSelectReadBack(self, modelName):
        Setting.LookModelName.SetValue(modelName)
        self.SetModelButton(self.readModelName, modelName)
        return modelName

    def CheckOpenSrSelectDownBack(self, modelName):
        Setting.DownloadModelName.SetValue(modelName)
        self.SetModelButton(self.downModelName, modelName)
        return modelName

    def SetModelButton(self, button, modelName):
        """ 按钮上只显示可读名(模型族 · 倍数 · 降噪)，完整 MODEL_ 串只放 tooltip """
        button.setText(FormatModelLabel(modelName))
        button.setToolTip(modelName)

    def CheckRadioEvent(self, setItem, value):
        assert isinstance(setItem, SettingValue)
        setItem.SetValue(value)
        QtOwner().ShowMsgOne(Str.GetStr(Str.SaveSuc))
        if setItem == Setting.IsHttpProxy:
            pass
            # from server.server import Server
            # Server().UpdateProxy()
        elif setItem == Setting.ThemeColorIndex:
            self.SetTheme()
        self.CheckMsgLabel()
        return

    def LineEditEvent(self, setItem, lineEdit):
        assert isinstance(setItem, SettingValue)
        value = lineEdit.text()
        setItem.SetValue(value)
        QtOwner().ShowMsgOne(Str.GetStr(Str.SaveSuc))
        self.CheckMsgLabel()
        # from server.server import Server
        # Server().UpdateProxy()
        return

    def SpinBoxEvent(self, setItem, value):
        assert isinstance(setItem, SettingValue)
        setItem.SetValue(int(value))
        QtOwner().ShowMsgOne(Str.GetStr(Str.SaveSuc))
        self.CheckMsgLabel()
        return

    def OpenDohView(self):
        view = DohDnsView(QtOwner().owner)
        view.show()

    def SwitchCurrent(self, **kwargs):
        self.update()
        refresh = kwargs.get("refresh")
        if refresh:
            self.InitSetting()
        return

    def LoadSetting(self):
        self.InitSetting()
        self.SetTheme()
        self.SetLanguage()
        # from server.server import Server
        # Server().UpdateProxy()
        return

    def ExitSaveSetting(self, mainQsize):
        return

    def InitSetting(self):
        self.checkBox_IsUpdate.setChecked(Setting.IsUpdate.value)
        self.SetRadioGroup("themeButton", Setting.ThemeIndex.value)
        self.SetRadioGroup("languageButton", Setting.Language.value)
        # self.SetRadioGroup("mainScaleButton", Setting.ScaleLevel.value)
        self.SetRadioGroup("proxy", Setting.IsHttpProxy.value)
        self.SetRadioGroup("saveNameButton", Setting.SaveNameType.value)
        self.coverSize.setValue(Setting.CoverSize.value)
        self.categorySize.setValue(Setting.CategorySize.value)
        self.SetRadioGroup("logutton", Setting.LogIndex.value)
        self.httpEdit.setText(Setting.HttpProxy.value)
        self.sockEdit.setText(Setting.Sock5Proxy.value)
        # self.titleBox.setChecked(Setting.IsUseTitleBar.value)
        self.openglBox.setChecked(Setting.IsOpenOpenGL.value)
        for index in range(self.encodeSelect.count()):
            if Setting.SelectEncodeGpu.value == self.encodeSelect.itemText(index):
                self.encodeSelect.setCurrentIndex(index)

        for index in range(self.fontSize.count()):
            if str(Setting.FontSize.value) == self.fontSize.itemText(index):
                self.fontSize.setCurrentIndex(index)

        self.fontStyle.setCurrentIndex(int(Setting.FontStyle.value))

        for index in range(self.fontBox.count()):
            if str(Setting.FontName.value) == self.fontBox.itemText(index):
                self.fontBox.setCurrentIndex(index)

        self.readCheckBox.setChecked(Setting.IsOpenWaifu.value)
        self.preDownWaifu2x.setChecked(Setting.PreDownWaifu2x.value)
        # self.readNoise.setCurrentIndex(Setting.LookNoise.value)
        self.readScale.setValue(Setting.LookScale.value)
        # self.readModel.setCurrentIndex(Setting.LookModel.value)

        self.categoryBox.setCurrentIndex(Setting.NotCategoryShow.value)
        self.titleLineBox.setCurrentIndex(Setting.TitleLine.value)
        self.tileComboBox.setCurrentIndex(Setting.Waifu2xTileSize.value)
        self.coverCheckBox.setChecked(Setting.CoverIsOpenWaifu.value)
        # self.coverNoise.setCurrentIndex(Setting.CoverLookNoise.value)
        self.coverScale.setValue(Setting.CoverLookScale.value)
        # self.coverModel.setCurrentIndex(Setting.CoverLookModel.value)
        self.colorBox.setCurrentIndex(Setting.ThemeColorIndex.value)

        self.downAuto.setChecked(Setting.DownloadAuto.value)
        # self.downNoise.setCurrentIndex(Setting.DownloadNoise.value)
        self.downScale.setValue(Setting.DownloadScale.value)
        self.threadSpin.setValue(Setting.MultiNum.value)
        # self.downModel.setCurrentIndex(Setting.DownloadModel.value)
        self.SetModelButton(self.coverModelName, Setting.CoverLookModelName.value)
        self.SetModelButton(self.readModelName, Setting.LookModelName.value)
        self.SetModelButton(self.downModelName, Setting.DownloadModelName.value)

        self.SetDownloadLabel()

    def OpenProxy(self):
        QtOwner().OpenLogin()
        # loginView = LoginView(QtOwner().owner, False)
        # loginView.tabWidget.setCurrentIndex(0)
        # loginView.tabWidget.removeTab(0)
        # loginView.tabWidget.removeTab(0)
        # loginView.tabWidget.removeTab(0)
        # loginView.loginButton.setText(Str.GetStr(Str.Save))
        # loginView.show()
        #
        # loginView.closed.connect(QtOwner().owner.navigationWidget.UpdateProxyName)
        return

    def retranslateUi(self, SettingNew):
        Ui_SettingNew.retranslateUi(self, SettingNew)
        self.SetDownloadLabel()
        self.SetModelButton(self.coverModelName, Setting.CoverLookModelName.value)
        self.SetModelButton(self.readModelName, Setting.LookModelName.value)
        self.SetModelButton(self.downModelName, Setting.DownloadModelName.value)

    def SetRadioGroup(self, text, index):
        radio = getattr(self, text+str(index))
        if radio:
            radio.setChecked(True)

    # def SetSock5Proxy(self):
    #     try:
    #         import socket
    #         import socks
    #         if not QtOwner().backSock:
    #             QtOwner().backSock = socket.socket
    #         if Setting.IsHttpProxy.value == 2 and Setting.Sock5Proxy.value:
    #             data = Setting.Sock5Proxy.value.replace("http://", "").replace("https://", "").replace("sock5://", "").replace("socks5://", "")
    #             data = data.split(":")
    #             if len(data) == 2:
    #                 host = data[0]
    #                 port = data[1]
    #                 socks.set_default_proxy(socks.SOCKS5, host, int(port))
    #                 socket.socket = socks.socksocket
    #             else:
    #                 QtOwner().ShowMsg(Str.GetStr(Str.Sock5Error))
    #         else:
    #             socks.set_default_proxy()
    #             socket.socket = QtOwner().backSock
    #     except Exception as es:
    #         Log.Error(es)
    #         QtOwner().ShowMsg(Str.GetStr(Str.Sock5Error))

    def SetLanguage(self):
        language = Setting.Language.value

        # Auto
        if language == 0:
            locale = QLocale.system().name()
            Log.Info("Init translate {}".format(locale))
            if locale[:3].lower() == "zh_":
                if locale.lower() == "zh_cn":
                    language = 1
                else:
                    language = 2
            else:
                language = 3

        if language == Setting.Language.autoValue:
            return

        Setting.Language.autoValue = language

        if language == 1:
            QtOwner().app.removeTranslator(self.translate)
        elif language == 2:
            success = self.translate.load(":/file/tr/tr_hk.qm")
            if success:
                QtOwner().app.installTranslator(self.translate)
            else:
                Log.Error("Failed to load hk translation.")
        else:
            success = self.translate.load(":/file/tr/tr_en.qm")
            if success:
                QtOwner().app.installTranslator(self.translate)
            else:
                Log.Error("Failed to load en translation.")
        Str.Reload()
        QtOwner().owner.RetranslateUi()

    def SetTheme(self):
        themeId = Setting.ThemeIndex.value
        if themeId == 0:
            themeId = self.GetSysColor()

        # if themeId == Setting.ThemeIndex.autoValue:
        #     return

        Setting.ThemeIndex.autoValue = themeId

        if themeId == 1:
            if Setting.ThemeColorIndex.value == 0:
                f = QFile(":/file/theme/dark_orange.qss")
            else:
                f = QFile(":/file/theme/dark_pink.qss")
        else:
            if Setting.ThemeColorIndex.value == 0:
                f = QFile(":/file/theme/light_orange.qss")
            else:
                f = QFile(":/file/theme/light_pink.qss")
        f.open(QFile.ReadOnly)
        data = str(f.readAll(), encoding='utf-8')
        if Setting.FontName.value:
            data = data.replace("/*replace*/", "font-family: {};".format(Setting.FontName.value))
        QtOwner().app.setStyleSheet(data)
        f.close()
        QtOwner().localReadView.retranslateUi(QtOwner().localReadView)
        QtOwner().bookInfoView.retranslateUi(QtOwner().bookInfoView)
        self.SetSettingTheme(themeId)

    def SetSettingTheme(self, themId):
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
        self.scrollArea.setStyleSheet(qss)

    def GetSysColor(self):
        # TODO KDE如何获取系统颜色
        if sys.platform == "win32":
            return self.GetWinSysColor() + 1
        elif sys.platform == "darwin":
            return self.GetMacOsSysColor()
        return 1

    def GetWinSysColor(self):
        try:
            path = "HKEY_CURRENT_USER\SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            key = "AppsUseLightTheme"
            settings = QSettings(path, QSettings.NativeFormat)
            value = settings.value(key, 0)
            return value
        except Exception as es:
            Log.Error(es)
        return 1

    def GetMacOsSysColor(self):
        try:
            import subprocess
            cmd = "defaults read -g AppleInterfaceStyle"
            results = subprocess.getoutput(cmd)
            if results == "Dark":
                return 1
            else:
                return 2
        except Exception as es:
            Log.Error(es)
        return 1

    def SaveSetting(self):
        return

    def SelectSavePath(self):
        """ 选择下载目录

        手机上走 SAF(系统文件选择器)。选出来的目录就是**下载目录本身**：之后每一张
        图都直接写进这个目录(见 tools/vfs.py)，不再有"先落应用私有目录、整本下完再
        导出"那一套 —— 那样用户改完设置看不到文件真正落在哪，取消/崩溃还会在私有
        目录留副本。
        """
        from tools import platform_mobile
        if platform_mobile.IsAndroid():
            picked = mobile_file_dialog.PickExportTree(Str.GetStr(Str.SelectFold))
            if not picked:
                # "" = 用户取消；None = SAF 桥不可用(退回应用内选择器)
                if picked is None:
                    url = mobile_file_dialog.GetExistingDirectory(self, Str.GetStr(Str.SelectFold))
                    if url:
                        Setting.SavePath.SetValue(url)
                self.SetDownloadLabel()
                return
            from tools import download_path
            oldRoot, newRoot, moving = download_path.Switch(
                picked.get("uri") or "", picked.get("name") or "")
            self.AfterPathChanged(oldRoot, newRoot)
            if moving:
                # 旧目录里已经下载的内容正在后台搬过去(搬完自动删旧目录)
                QtOwner().ShowMsg(Str.GetStr(Str.Waiting))
                from tools.log import Log
                Log.Warn("download path: 旧目录内容后台搬运中 {} -> {}".format(oldRoot, newRoot))
            return
        url = mobile_file_dialog.GetExistingDirectory(self, Str.GetStr(Str.SelectFold))
        if url:
            oldRoot = Setting.GetDownloadRoot()
            Setting.SavePath.SetValue(url)
            self.AfterPathChanged(oldRoot, Setting.GetDownloadRoot())
        self.SetDownloadLabel()

    def SelectCachePath(self):
        """ 修改缓存目录(封面/图片缓存/超分临时图)

        入口：设置 → 下载与缓存 → "缓存位置"。

        手机上走**系统 SAF 选择器**(ACTION_OPEN_DOCUMENT_TREE)：选中的目录由
        takePersistableUriPermission 持久授权，应用按 `saf://<key>/jmcomic-qt`
        直接读写(见 tools/vfs.py)，重启后仍然有效。
        桌面端 / SAF 桥不可用时回落到本地目录选择器(缓存必须能被 open)。

        选中之后新缓存**直接写进新目录**；只有旧目录里已有的缓存会在后台搬一次。
        """
        from tools import cache_path, platform_mobile
        picked = mobile_file_dialog.PickExportTree(Str.GetStr(Str.SelectFold))
        if picked is None:
            # SAF 桥不可用(桌面端/桥没打进包)：选真实本地目录
            current = cache_path.DisplayPath()
            start = os.path.dirname(current) if current else ""
            if not start or not os.path.isdir(start):
                start = platform_mobile.GetExternalDir()
            path = mobile_file_dialog.PickLocalDir(self, Str.GetStr(Str.SelectFold), start)
            if not path:
                return
            result = cache_path.SetBase(path)
        elif not picked:
            self.SetDownloadLabel()
            return
        else:
            result = cache_path.SetTree(picked.get("uri") or "", picked.get("name") or "")
        self.ApplyCachePathResult(result)

    def ResetCachePath(self):
        """ 恢复默认缓存目录(应用外部缓存目录) """
        from tools import cache_path
        self.ApplyCachePathResult(cache_path.Reset())

    def ApplyCachePathResult(self, result):
        ok, reason, oldPath, newPath, moving = result
        self.SetDownloadLabel()
        if not ok:
            QtOwner().ShowMsg("无法使用该目录：{}".format(reason))
            return
        Log.Warn("cache path: {} -> {}".format(oldPath, newPath))
        if moving:
            QtOwner().ShowMsg(Str.GetStr(Str.Waiting))
        else:
            QtOwner().ShowMsg(Str.GetStr(Str.SaveSuc))

    def AfterPathChanged(self, oldRoot="", newRoot=""):
        """ 目录变了：刷新显示 + 把已下载条目的路径挪到新根(不然还在往旧路径写) """
        self.SetDownloadLabel()
        try:
            QtOwner().downloadView.OnDownloadRootChanged(oldRoot, newRoot)
        except Exception as es:
            from tools.log import Log
            Log.Error(es)
        return

    def SetDownloadLabel(self):
        """ 目录行文案

        显示的是**真实会落盘的位置**：SAF 目录还原成 /storage/emulated/0/…
        (树 URI 里带着 primary:Download/xxx，能还原)，用户一眼能对上文件管理器。
        路径标签整宽折行显示，**不再做中间省略** —— 设置页必须能看全路径。
        """
        from tools import vfs
        display = Setting.GetDownloadDisplayPath()
        if not display:
            display = "./"
        self.downloadDir.setText(display)
        self.downloadDir.setToolTip(display)

        # 缓存(封面/图片缓存/超分临时图)：默认在应用外部缓存目录，也可以在
        # "缓存位置"里用 SAF 选到用户自己的目录(配置项 CachePathTree)。
        # 目录里的文件由 vfs 逐文件直写，不再经过任何 "私有目录中转"。
        cachePath = Setting.GetCachePath()
        cacheDisplay = Setting.GetCacheDisplayPath()
        waifuDisplay = vfs.RealPath(vfs.Join(cachePath, config.Waifu2xPath))
        self.cacheDir.setText(cacheDisplay)
        self.waifu2xDir.setText(waifuDisplay)
        self.cacheDir.setToolTip(cacheDisplay)
        self.waifu2xDir.setToolTip(waifuDisplay)
        if platform_mobile.IsAndroid():
            # 自定义目录不可用时会回退默认值，这里按"实际生效的路径"判断
            isCustom = os.path.normcase(cachePath) != os.path.normcase(Setting.GetDefaultCachePath())
            if isCustom:
                hint = "自定义缓存目录（SAF 授权，可在“缓存位置”里更改）"
            else:
                hint = "默认缓存目录（可在系统存储设置或文件管理器中手动清理）"
            self.cacheDir.setToolTip("{}（{}）".format(cacheDisplay, hint))
        return

    def _PathForLabel(self, label):
        """ 每个目录行对应的**内部路径**(可能是 saf://...) """
        from tools import vfs
        if label is self.downloadDir:
            return Setting.GetDownloadRoot()
        if label is self.cacheDir:
            return Setting.GetCachePath()
        if label is self.waifu2xDir:
            return vfs.Join(Setting.GetCachePath(), config.Waifu2xPath)
        if label is self.chatDir:
            return vfs.Join(Setting.GetCachePath(), config.ChatSavePath)
        return ""

    def OpenDir(self, label):
        """ 打开目录

        * SAF 目录(下载/缓存)：直接打开那个目录的 document URI，系统文件管理器
          会定位进去；这也是"改了缓存位置后打开目录没反应"的修法 —— 之前拿
          `saf://` 的内部路径/Android/data 真实路径去开，系统既没有处理者、
          Android 11+ 的文件管理器也进不去。
        * 本地目录：交给系统文件管理器；打不开就把真实路径告诉用户。
        """
        from tools import mobile_ui, platform_mobile, vfs
        path = self._PathForLabel(label)
        text = vfs.RealPath(path) if path else (
            mobile_ui.FullText(label) if label is not None else "")
        if platform_mobile.IsAndroid():
            if not path:
                QtOwner().ShowMsg("目录：{}".format(text))
                return
            ok, reason = vfs.OpenInFileManager(path)
            if not ok:
                from tools.log import Log
                Log.Warn("open dir: {} -> {}".format(text, reason))
                if reason == "sandbox" and label is self.downloadDir:
                    # 下载目录还是应用专属目录：先去选一个 SAF 目录
                    QtOwner().ShowMsg(Str.GetStr(Str.SetDir))
                else:
                    QtOwner().ShowMsg("目录：{}".format(text))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(text))
        return

    def SetGpuInfos(self, gpuInfo, cpuNum):
        self.gpuInfos = gpuInfo
        config.EncodeGpu = Setting.SelectEncodeGpu.value

        if not self.gpuInfos:
            config.EncodeGpu = "CPU"
            config.Encode = -1
            self.encodeSelect.addItem(config.EncodeGpu)
            self.encodeSelect.setCurrentIndex(0)

        if not config.EncodeGpu or (
                self.gpuInfos and config.EncodeGpu != "CPU" and config.EncodeGpu not in self.gpuInfos):
            # 没有设置过显卡时优先使用独显(NVIDIA/AMD)，避免默认选到核显
            from tools.waifu2x_check import Waifu2xChecker
            index = Waifu2xChecker.PreferGpuId(self.gpuInfos)
            config.EncodeGpu = self.gpuInfos[index]
            config.Encode = index

        index = 0
        if self.gpuInfos:
            for info in self.gpuInfos:
                self.encodeSelect.addItem(info)
                if info == config.EncodeGpu:
                    self.encodeSelect.setCurrentIndex(index)
                    config.Encode = index
                index += 1

            self.encodeSelect.addItem("CPU")

        if config.EncodeGpu == "CPU":
            config.Encode = -1
            self.encodeSelect.setCurrentIndex(index)

        config.UseCpuNum = Setting.Waifu2xCpuCore.value
        if config.UseCpuNum > cpuNum:
            config.UseCpuNum = cpuNum
        for i in range(cpuNum):
            self.threadSelect.addItem(str(i + 1))
        self.threadSelect.setCurrentIndex(config.UseCpuNum)

        Log.Warn("waifu2x GPU: " + str(self.gpuInfos) + ",select: " + str(config.EncodeGpu) + ",use cpu num: " + str(
            config.UseCpuNum))
        return

    def GetGpuName(self):
        return config.EncodeGpu
        # index = config.Encode
        # if index >= len(self.gpuInfos) or index < 0:
        #     return "GPU"
        # return self.gpuInfos[index]