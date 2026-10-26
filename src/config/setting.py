import os
import sys

from config import config


class SettingValue:
    def __init__(self, tag, defaultV, isNeedReset, des=None):
        self.tag = tag                 # 分类
        self._value = defaultV          # 生效值
        self.setV = defaultV           # 设置的值
        self.defaultV = defaultV       # 默认值
        self.isNeedReset = isNeedReset       # 是否重启生效
        self.des = des          # 描述
        self.autoValue = 0      # 选自动时，自动生效的值
        self.name = ""

    def __lt__(self, other):
        raise OverflowError

    def __gt__(self, other):
        raise OverflowError

    def __eq__(self, other):
        if isinstance(other, SettingValue):
            return id(self) == id(other)
        raise OverflowError

    @property
    def value(self):
        return self._value

    def InitValue(self, value, name):
        value = self.GetSettingV(value, self.defaultV)
        self._value = value
        self.setV = value
        self.name = name
        return

    @staticmethod
    def GetSettingV(v, defV=None):
        try:
            if v:
                if isinstance(defV, int):
                    if v == "true" or v == "True":
                        return 1
                    elif v == "false" or v == "False":
                        return 0
                    return int(v)
                elif isinstance(defV, float):
                    return float(v)
                elif isinstance(defV, list) and isinstance(v, str):
                    return [v]
                else:
                    return v
            return defV
        except Exception as es:
            from tools.log import Log
            Log.Error(es)
        return v

    def GetIndexV(self):
        if not isinstance(self.des, list):
            return ""
        if self._value >= len(self.des):
            return ""
        return self.des[self._value]

    def SetValue(self, value):
        if self.setV == value and self._value == value:
            return

        self.setV = value
        if not self.isNeedReset:
            self._value = value
            self.autoValue = 0
        Setting.SaveSettingV(self)
        # 任何设置变化都可能伴随缓存目录变化(目前是 CachePath)，清掉可写缓存
        Setting._cachePathResolved = ""
        Setting._cachePathRejected = ""


class Setting:
    # 自定义缓存目录"已校验可写"的缓存：GetCachePath() 每存取一张图都会调用，
    # 不能每次都 makedirs + 写探针；配置一变(SetValue)就清空重算。
    _cachePathResolved = ""
    # 校验失败的目录也记下来，避免每张图都重试一次 + 刷一条日志
    _cachePathRejected = ""

    # 通用设置
    IsUpdate = SettingValue("GeneraSetting", 1, False)
    Language = SettingValue("GeneraSetting", 0, False, ["Auto", "zh", "hk", "en"])  # ch-zh ch-hk eu
    ThemeIndex = SettingValue("GeneraSetting", 0, False, ["Auto", "light", "dark"])  #
    ThemeColorIndex = SettingValue("GeneraSetting", 0, False)  #

    LogIndex = SettingValue("GeneraSetting", 0, False, ["warn", "info", "debug"])  # Warn Info Debug
    CoverSize = SettingValue("GeneraSetting", 100, False)  #
    TitleLine = SettingValue("GeneraSetting", 2, False)  #
    NotCategoryShow = SettingValue("GeneraSetting", 0, False)  #
    CategorySize = SettingValue("GeneraSetting", 80, False)  #
    # ScaleLevel = SettingValue("GeneraSetting", 0, True, ["Auto", 100, 125, 150, 175, 200])

    IsUseTitleBar = SettingValue("GeneraSetting", 1, True)

    FontName = SettingValue("GeneraSetting", "", True)
    FontSize = SettingValue("GeneraSetting", "", True)
    FontStyle = SettingValue("GeneraSetting", 0, True)

    MultiNum = SettingValue("GeneraSetting", 5, True)

    # 代理设置
    IsHttpProxy = SettingValue("ProxySetting", 0, False, ["", "Http", "Sock5", "system"])
    HttpProxy = SettingValue("ProxySetting", "", False)
    Sock5Proxy = SettingValue("ProxySetting", "", False)
    PreferCDNIP = SettingValue("ProxySetting", "104.18.227.172", False)
    PreferCDNList = SettingValue("ProxySetting", "104.18.227.172,104.16.16.230,104.16.108.62,104.24.169.89,104.19.229.139,104.21.73.214", False)
    IsUseHttps = SettingValue("ProxySetting", 1, False)
    ProxySelectIndex = SettingValue("ProxySetting", 1, False)
    # IsOpenDoh = SettingValue("ProxySetting", 0, False)
    # IsOpenDohPicture = SettingValue("ProxySetting", 0, False)
    DohAddress = SettingValue("ProxySetting", "https://parse.jpacg.cc/parse", False)
    EchConfig = SettingValue("ProxySetting", "", False)
    EchProxyIndex = SettingValue("ProxySetting", 0, False, ["Auto", "true", "false"])
    ProxyIpLastList =  SettingValue("ProxySetting", "", False)
    ProxyIpValue =  SettingValue("ProxySetting", "", False)

    EnableEch = SettingValue("ProxySetting", 1, False)
    IsOpenHTTP3 = SettingValue("ProxySetting", 0, False)

    ApiVersion = SettingValue("ProxySetting", 0, False)
    LastProxyResult = SettingValue("ProxySetting", {}, False)
    ProxyImgSelectIndex = SettingValue("ProxySetting", 1, False)
    PreferCDNIPImg = SettingValue("ProxySetting", "104.18.227.172", False)
    LastIpResult = SettingValue("ProxySetting", {}, False)
    ProxyIpCountry = SettingValue("ProxySetting", "", False)

    HostApiDomain = SettingValue("ProxySetting", "www.cdnutc.me", False)
    HostImgDomain = SettingValue("ProxySetting", "cdn-msp.jmapinodeudzn.net", False)

    IsLoginProxy = SettingValue("ProxySetting", 0, False)
    RegisterProsyIndex = SettingValue("ProxySetting", 1, False)
    ApiTimeOut = SettingValue("ProxySetting", 1, False, [2, 5, 7, 10])
    ImgTimeOut = SettingValue("ProxySetting", 1, False, [2, 5, 7, 10, 15])

    # 下载与缓存
    SavePath = SettingValue("DownloadSetting", "", False)
    # 下载目录(Android 用 SAF 选的目录)
    #
    # 语义：**下载/超分的文件直接写在这个目录里**，不存在"先落私有目录再导出"。
    # 这里只存树 URI 与显示名，真正的路径是 `saf://<key>/commies/…`(见 tools/vfs.py)。
    # 用户没选过目录时退回应用专属目录(SavePath，Android 10+ 无需任何权限)。
    SavePathTree = SettingValue("DownloadSetting", "", False)
    SavePathTreeName = SettingValue("DownloadSetting", "", False)
    SaveNameType = SettingValue("DownloadSetting", 0, False)
    # 缓存目录(封面/图片缓存/超分临时图/zip 临时文件)
    #
    # 配置项：config.ini 的 [DownloadSetting] CachePath
    #   * 空串(默认) = 用平台默认值，见 GetDefaultCachePath()
    #       Android -> /storage/emulated/0/Android/data/<包名>/cache/jmcomic-qt
    #       Windows -> <SavePath>/cache
    #       Linux   -> $XDG_CACHE_HOME/jmcomic-qt
    #   * 绝对路径 = 设置页"缓存位置"选出来的自定义目录(直接写入，不经过默认目录)
    CachePath = SettingValue("DownloadSetting", "", False)

    # Waifu2x设置
    SelectEncodeGpu = SettingValue("Waifu2xSetting", "", True)
    Waifu2xCpuCore = SettingValue("Waifu2xSetting", 0, True)
    # 上次初始化成功的配置(显卡名|cpu线程数|显卡序号|实际线程数)，用于跳过初始化探测
    Waifu2xCheckKey = SettingValue("Waifu2xSetting", "", False)
    Waifu2xTileSize = SettingValue("Waifu2xSetting", 0, False, [0, 200, 100, 32])

    # 封面 Waifu2x
    CoverIsOpenWaifu = SettingValue("Waifu2xSetting", 0, False)
    CoverMaxNum = SettingValue("Waifu2xSetting", 400, False)
    CoverLookModelName = SettingValue("Waifu2xSetting", "MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X", False)
    # CoverLookModel = SettingValue("Waifu2xSetting", 0, False)
    # CoverLookNoise = SettingValue("Waifu2xSetting", 3, False)
    CoverLookScale = SettingValue("Waifu2xSetting", 2.0, False)

    IsOpenWaifu = SettingValue("Waifu2xSetting", 0, False)
    LookMaxNum = SettingValue("Waifu2xSetting", 4096, False)
    LookModelName = SettingValue("Waifu2xSetting", "MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X", False)
    # LookModel = SettingValue("Waifu2xSetting", 0, False)
    # LookNoise = SettingValue("Waifu2xSetting", 3, False)
    LookScale = SettingValue("Waifu2xSetting", 2.0, False)

    DownloadAuto = SettingValue("Waifu2xSetting", 0, False)
    DownloadModelName = SettingValue("Waifu2xSetting", "MODEL_WAIFU2X_CUNET_UP2X_DENOISE3X", False)
    # DownloadModel = SettingValue("Waifu2xSetting", 1, False)
    # DownloadNoise = SettingValue("Waifu2xSetting", 3, False)
    DownloadScale = SettingValue("Waifu2xSetting", 2.0, False)

    # 看图设置
    LookReadMode = SettingValue("ReadSetting", 1, False)
    LookReadFull = SettingValue("ReadSetting", 0, False)
    ScrollSpeed = SettingValue("ReadSetting", 20, False)
    TurnSpeed = SettingValue("ReadSetting", 5000, False)
    ScrollInitSpeed = SettingValue("ReadSetting", 400, False)
    ScrollTime = SettingValue("ReadSetting", 100, False)
    PreDownWaifu2x = SettingValue("ReadSetting", 1, False)
    IsOpenOpenGL = SettingValue("ReadSetting", 0, True)
    # UpDownScrollSpeed = SettingValue("ReadSetting", 100, False)
    # ScaleCnt = SettingValue("ReadSetting", 0, False)

    # 批量超分
    BatchSrImportDir = SettingValue("BatchSrTool", "", False)
    BatchSrExportDir = SettingValue("BatchSrTool", "", False)
    BatchSrState = SettingValue("BatchSrTool", "", False)
    BatchSrFmt = SettingValue("BatchSrTool", "", False)

    BatchSrModelName = SettingValue("BatchSrTool", "MODEL_WAIFU2X_CUNET_UP2X_DENOISE3X", False)
    BatchSrScale = SettingValue("BatchSrTool", 2.0, False)

    # Other
    UserId = SettingValue("Other", "", False)
    Password = SettingValue("Other", "", False)
    ChatSendAction = SettingValue("Other", 0, False, ["CtrlEnter", "Enter"])
    ScreenIndex = SettingValue("Other", 0, False)
    AutoLogin = SettingValue("Other", 0, False)
    AutoSign = SettingValue("Other", 1, False)
    SavePassword = SettingValue("Other", 1, False)
    IsShowCmd = SettingValue("Other", 0, False)
    IsReDownload = SettingValue("Other", 0, False)
    WebpToPng = SettingValue("Other", 0, False)
    IsPreUpdate = SettingValue("Other", 0, False)
    UerAgent = SettingValue("Other", "", False)
    GlobalConfig = SettingValue("Other", "", False)
    ForbidWords = SettingValue("Other", [], False)
    AddForbidWords = SettingValue("Other", [], False)
    IsForbidCategory =SettingValue("Other", True, False)
    IsForbidTag = SettingValue("Other", False, False)
    IsForbidTitle = SettingValue("Other", False, False)
    # IpbMemberId = SettingValue("Other", "", False)
    # IpbPassHash = SettingValue("Other", "", False)
    # Igneous = SettingValue("Other", "", False)
    IsSkipPic = SettingValue("Other", 0, False)

    @staticmethod
    def GetThemeColor():
        if Setting.ThemeColorIndex.value == 0:
            return  "#FF7B00"
        return "#ff4081"

    @staticmethod
    def InitLoadSetting():
        path = os.path.join(Setting.GetConfigPath(), "config.ini")
        from PySide6.QtCore import QSettings
        settings = QSettings(path, QSettings.Format.IniFormat)
        for name in dir(Setting):
            setItem = getattr(Setting, name)
            if isinstance(setItem, SettingValue):
                value = settings.value(setItem.tag + "/" + name, setItem.defaultV)
                setItem.InitValue(value, name)
        from tools.log import Log
        Log.UpdateLoggingLevel()
        from tools import platform_mobile
        if platform_mobile.IsAndroid():
            if not Setting.SavePath.value:
                # Android 10+: 应用外部私有目录，无需存储权限且用户可见
                Setting.SavePath.SetValue(platform_mobile.GetAndroidSavePath())
            # 老配置里的内部私有下载目录 → 外部目录(已下载内容后台搬过去)；
            # 自定义缓存目录与默认目录并存时也在这里补齐遗留内容
            try:
                platform_mobile.ApplyAndroidPathDefaults()
            except Exception as es:
                Log.Error(es)
        elif sys.platform.lower() == "linux" and not Setting.SavePath.value:
            Setting.SavePath.SetValue(Setting.GetDataPath())
        return

    @staticmethod
    def SaveSetting():
        path = os.path.join(Setting.GetConfigPath(), "config.ini")
        from PySide6.QtCore import QSettings
        settings = QSettings(path, QSettings.IniFormat)
        for name in dir(Setting):
            setItem = getattr(Setting, name)
            if isinstance(setItem, SettingValue):
                settings.setValue(setItem.tag + "/" + name, setItem.setV)
        return

    @staticmethod
    def SaveSettingV(setItem):
        path = os.path.join(Setting.GetConfigPath(), "config.ini")
        from PySide6.QtCore import QSettings
        settings = QSettings(path, QSettings.IniFormat)
        if isinstance(setItem, SettingValue) and setItem.name:
            settings.setValue(setItem.tag + "/" + setItem.name, setItem.setV)

    @staticmethod
    def Init():
        for path in [
            Setting.GetConfigPath(),
            Setting.GetDataPath(),
            Setting.GetStatePath(),
        ]:
            os.makedirs(path, exist_ok=True)

        # 缓存目录：自定义目录直接建；默认目录要等 SavePath 就绪
        # (Init 早于 InitLoadSetting，那时 SavePath 还是空)
        if Setting.SavePath.value:
            try:
                os.makedirs(Setting.GetCachePath(), exist_ok=True)
            except Exception:
                pass
        custom = str(Setting.CachePath.value or "").strip()
        if custom:
            try:
                os.makedirs(custom, exist_ok=True)
            except Exception:
                pass
        return

    @staticmethod
    def _xdgDir(envName, default, *subdirs):
        if sys.platform == "win32":
            return "data"
        base = os.environ.get(envName, os.path.join(os.path.expanduser("~"), default))
        return os.path.join(base, "jmcomic-qt", *subdirs)

    @staticmethod
    def GetConfigPath():
        return Setting._xdgDir("XDG_CONFIG_HOME", ".config")

    @staticmethod
    def GetDataPath():
        return Setting._xdgDir("XDG_DATA_HOME", ".local/share")

    @staticmethod
    def GetDefaultCachePath():
        """ 缓存目录的默认值(不看自定义配置)

        桌面 Windows：<SavePath>/cache
        其它桌面端：$XDG_CACHE_HOME/jmcomic-qt(通常 ~/.cache/jmcomic-qt)
        Android：InitAndroidEnv 把 XDG_CACHE_HOME 指到应用外部缓存目录
                 /storage/emulated/0/Android/data/<包名>/cache，
                 所以最终是 …/cache/jmcomic-qt —— 系统"清理缓存"、设置-存储、
                 文件管理器都能看到并手动清掉
        """
        if sys.platform == "win32":
            return os.path.join(Setting.SavePath.value, config.CachePathDir)
        return Setting._xdgDir("XDG_CACHE_HOME", ".cache")

    @staticmethod
    def IsCustomCachePath():
        """ 是否设置了自定义缓存目录 """
        return bool(str(Setting.CachePath.value or "").strip())

    @staticmethod
    def GetCachePath():
        """ 当前生效的缓存目录(自定义优先，默认见 GetDefaultCachePath)

        封面/图片缓存/超分临时图/zip 临时文件都**直接**写在这里 —— 不经过
        任何"临时私有目录"，所以改完目录立即生效。

        自定义目录不可用时(被删、存储卡拔掉、没权限)回退默认值，避免整条图片
        缓存链写不进去。校验结果缓存到 _cachePathResolved：这个函数每张图都会
        调一次，不能每次都建目录/写探针。
        """
        custom = str(Setting.CachePath.value or "").strip()
        if not custom:
            return Setting.GetDefaultCachePath()
        from tools import platform_mobile
        path = platform_mobile.NormalizeLocalPath(custom)
        if not path:
            return Setting.GetDefaultCachePath()
        if path == Setting._cachePathResolved:
            return path
        if path == Setting._cachePathRejected:
            return Setting.GetDefaultCachePath()
        ok, reason = platform_mobile.EnsureWritableDir(path)
        if not ok:
            Setting._cachePathRejected = path
            try:
                from tools.log import Log
                if getattr(Log, "logger", None) is not None:
                    Log.logger.warning(
                        "cache: 自定义缓存目录不可用，回退默认值: {} ({})".format(
                            custom, reason))
            except Exception:
                pass
            return Setting.GetDefaultCachePath()
        Setting._cachePathResolved = path
        return path

    @staticmethod
    def DownloadTreeKey():
        """ 用户选的下载目录(SAF 树)的短 key；没选过/不在手机上返回空串 """
        uri = str(Setting.SavePathTree.value or "")
        if not uri:
            return ""
        try:
            from tools import platform_mobile
            if not platform_mobile.IsAndroid():
                return ""
        except Exception:
            return ""
        try:
            from tools import saf_bridge
            return saf_bridge.TreeKey(uri, Setting.SavePathTreeName.value)
        except Exception:
            return ""

    @staticmethod
    def IsSafDownload():
        return bool(Setting.DownloadTreeKey())

    @staticmethod
    def GetDownloadRoot():
        """ 下载根目录

        配了 SAF 目录 -> `saf://<key>/commies`（文件直接写进用户选的目录）
        否则 -> `<SavePath>/commies`（应用专属目录，Android 10+ 无需权限）
        """
        key = Setting.DownloadTreeKey()
        if key:
            return "saf://{}/{}".format(key, config.SavePathDir)
        return os.path.join(Setting.SavePath.value or "", config.SavePathDir)

    @staticmethod
    def GetDownloadDisplayPath():
        """ 给人看的下载目录(还原成 /storage/emulated/0/… 那种真实路径) """
        from tools import vfs
        return vfs.RealPath(Setting.GetDownloadRoot())

    @staticmethod
    def GetStatePath():
        return Setting._xdgDir("XDG_STATE_HOME", ".local/state")

    @staticmethod
    def GetLogPath():
        if sys.platform == "win32":
            return "logs"
        return Setting._xdgDir("XDG_STATE_HOME", ".local/state", "logs")

