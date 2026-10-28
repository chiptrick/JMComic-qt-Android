import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QHeaderView, QAbstractItemView

from component.dialog.base_mask_dialog import BaseMaskDialog
from config import config
from config.setting import Setting
from interface.ui_download_dir import Ui_DownloadDir
from qt_owner import QtOwner
from task.qt_task import QtTaskBase
from tools.str import Str
from tools import mobile_file_dialog


class DownloadDirView(BaseMaskDialog, Ui_DownloadDir, QtTaskBase):
    CloseLogin = Signal()

    def __init__(self, parent=None):
        BaseMaskDialog.__init__(self, parent)
        Ui_DownloadDir.__init__(self)
        QtTaskBase.__init__(self)
        self.widget.adjustSize()
        self.setupUi(self.widget)
        self.selectDir.clicked.connect(self.SelectSavePath)
        self.saveDir.clicked.connect(self.SavePath)

    def SelectSavePath(self):
        from tools import platform_mobile
        if platform_mobile.IsAndroid():
            # 手机上目录只能由 SAF 授予，而 SAF 给的是 URI(只有 ContentResolver 能写)。
            # 选中的目录就是**下载目录本身**：之后每张图直接写进去(见 tools/vfs.py)。
            picked = mobile_file_dialog.PickExportTree(Str.GetStr(Str.SelectFold))
            if not picked:
                return
            from tools import download_path
            download_path.Switch(picked.get("uri") or "", picked.get("name") or "")
            self.Refresh()
            try:
                QtOwner().downloadView.OnDownloadRootChanged()
            except Exception:
                pass
            return
        url = mobile_file_dialog.GetExistingDirectory(self, Str.GetStr(Str.SelectFold))
        if url:
            self.lineEdit.setText(url)
            self.Refresh()

    def Refresh(self):
        from tools import vfs
        root = Setting.GetDownloadRoot()
        display = vfs.RealPath(root)
        self.lineEdit.setText(display)
        self.lineEdit.setReadOnly(True)
        self.downloadDir.setText(display)
        cachePath = Setting.GetCachePath()
        cacheDisplay = Setting.GetCacheDisplayPath()
        waifuDisplay = vfs.RealPath(vfs.Join(cachePath, config.Waifu2xPath))
        self.cacheDir.setText(cacheDisplay)
        self.waifu2xDir.setText(waifuDisplay)
        from tools import platform_mobile
        if platform_mobile.IsAndroid():
            # 缓存默认在应用外部缓存目录(Android 11+ 第三方文件管理器大多进不去
            # Android/data)，tooltip 里把清理途径讲清楚；自定义目录则提示入口
            isCustom = os.path.normcase(cachePath) != os.path.normcase(Setting.GetDefaultCachePath())
            if isCustom:
                self.cacheDir.setToolTip("{}（自定义缓存目录，SAF 授权，可在设置-下载与缓存中更改）".format(cacheDisplay))
            else:
                self.cacheDir.setToolTip("{}（默认缓存目录，可在系统存储设置或文件管理器中手动清理）".format(cacheDisplay))
            self.waifu2xDir.setToolTip(waifuDisplay)

    def SavePath(self):
        from tools import platform_mobile
        if platform_mobile.IsAndroid():
            # 手机上目录在选的时候就已经生效了(SAF)
            if Setting.DownloadTreeKey():
                self.close()
                return
        path = self.lineEdit.text()
        if not path:
            QtOwner().ShowMsg(Str.GetStr(Str.SetDir))
            return
        Setting.SavePath.SetValue(path)
        try:
            QtOwner().downloadView.OnDownloadRootChanged()
        except Exception:
            pass
        self.close()
