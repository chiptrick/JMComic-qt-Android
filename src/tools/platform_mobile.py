# coding:utf-8
""" 移动端(Android)平台适配层

桌面端(Windows/Linux/macOS)调用这里的所有函数都是空操作，不会改变原有行为。

Android 端由 android/main.py 在创建 QApplication 之后、导入业务模块之前调用
InitAndroidEnv()，作用：
    1. 把配置/数据/日志目录重定向到应用私有目录(/data/user/0/<包名>/files，
       Android 14 无需任何存储权限)，把**缓存**目录指向应用外部缓存目录
       (/storage/emulated/0/Android/data/<包名>/cache) —— 封面/图片缓存/超分
       临时图都是可再生数据，放外部用户才清理得掉(系统"清理缓存"、设置-存储、
       文件管理器都能看到它)，内部私有目录留给配置/数据库/模型这些删了会出事的
    2. 把下载目录默认指向应用外部私有目录
       (/storage/emulated/0/Android/data/<包名>/files/commies)
    3. 校验/校正路径：历史配置里落在内部私有目录的下载目录会被改到外部目录，
       并把已下载的内容搬过去；自定义缓存目录不可用时由 Setting 回退默认值
    4. 标记触摸设备、禁用桌面端专有特性(系统托盘/单实例/无边框窗口)

下载与缓存都**直接写目标目录**：要么是应用外部目录的真实路径，要么是用户用
SAF 选的目录(见 tools/vfs.py)，不存在"先落私有目录再拷贝"。
"""
import os
import sys

# python-for-android 在启动时写入的环境变量
EnvPrivate = "ANDROID_PRIVATE"           # /data/user/0/<pkg>/files(应用私有目录)
EnvAppPath = "ANDROID_APP_PATH"          # 应用自身目录(只读)
EnvArgument = "ANDROID_ARGUMENT"
EnvAppDir = "JM_ANDROID_APP_DIR"         # 可选：外部注入
EnvSaveDir = "JM_ANDROID_SAVE_DIR"       # 可选：外部注入下载目录
EnvFlag = "JMCOMIC_ANDROID"              # 可选：强制标记为 Android

# Android 上不需要的桌面特性
SupportSystemTray = True                 # 系统托盘
SupportFrameless = True                  # 无边框窗口(QFramelessWindow)
SupportSingleInstance = True             # QLocalServer 单实例
SupportSubProcessProbe = True            # waifu2x 子进程探测

_androidInited = False
_appDataDir = ""
_saveDir = ""
_externalDir = ""
_nativeLibDirs = None
_migrateThreads = []                    # 后台目录搬迁线程(缓存/下载目录变更)


def IsAndroid():
    """ 是否运行在 Android 上 """
    if os.environ.get(EnvFlag) == "1":
        return True
    if hasattr(sys, "getandroidapilevel"):
        return True
    if EnvPrivate in os.environ or EnvArgument in os.environ:
        return True
    return False


def IsMobile():
    """ 需要按移动端交互(触摸/竖屏)处理的平台 """
    return IsAndroid()


def IsTouchDevice():
    return IsAndroid()


def _JniDir(name):
    """ 通过 pyjnius 取 Android 目录，取不到返回空串 """
    try:
        import jnius  # noqa: F401  python-for-android 自带
        from jnius import autoclass
        for activityName in ("org.kivy.android.PythonActivity",
                             "org.qtproject.qt.android.bindings.QtActivity"):
            try:
                activity = autoclass(activityName)
                act = getattr(activity, "mActivity", None)
                if act is None:
                    continue
                if name == "files":
                    d = act.getFilesDir()
                elif name == "external":
                    d = act.getExternalFilesDir(None)
                elif name == "external_cache":
                    d = act.getExternalCacheDir()
                else:
                    d = act.getCacheDir()
                if d is not None:
                    return str(d.getAbsolutePath())
            except Exception:
                continue
    except Exception:
        pass
    return ""


def _QtDir(qtStandardPath):
    """ 通过 Qt 的 QStandardPaths 取目录(需要 QApplication 已创建) """
    try:
        from PySide6.QtCore import QStandardPaths
        path = QStandardPaths.writableLocation(qtStandardPath)
        if path:
            return str(path)
    except Exception:
        pass
    return ""


def GetAppDataDir():
    """ 应用私有数据目录 """
    if _appDataDir:
        return _appDataDir
    return os.environ.get(EnvPrivate) or _JniDir("files") or os.path.expanduser("~")


# 目录名里 Android 用的 abi 短名(APK 里是 lib/arm64-v8a，解压到磁盘后是 lib/arm64)
_AbiDirNames = ("arm64", "arm64-v8a", "arm", "armeabi-v7a", "x86", "x86_64", "riscv64")


def _LibDirsFromMaps():
    """ 从 /proc/self/maps 推断 native 库目录(完全不依赖 pyjnius)

    Android 会把 APK 的 lib/<abi>/*.so 解压到 /data/app/<pkg>-<hash>/lib/<abi>/。
    本进程一定加载了 libpython3.11.so，它的所在目录就是我们要找的目录。
    这是 pyjnius 未随包时的唯一可靠途径(实测 pyjnius 确实没被打进 APK)。
    """
    found = []
    try:
        with open("/proc/self/maps", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 6:
                    continue
                path = parts[-1]
                if not path.startswith("/") or ".so" not in path:
                    continue
                folder = os.path.dirname(path)
                if os.path.basename(folder) in _AbiDirNames and folder not in found:
                    found.append(folder)
    except Exception:
        pass
    return found


def GetNativeLibDirs():
    """ 应用 native 库目录候选(给 ctypes 找自有 .so 用) """
    global _nativeLibDirs
    if _nativeLibDirs is not None:
        return _nativeLibDirs
    dirs = []
    try:
        import jnius  # noqa: F401
        from jnius import autoclass
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        path = str(activity.getApplicationInfo().nativeLibraryDir)
        if path:
            dirs.append(path)
    except Exception:
        pass
    for path in _LibDirsFromMaps():
        if path not in dirs:
            dirs.append(path)
    _nativeLibDirs = dirs
    return dirs


def GetExternalDir():
    """ 应用外部私有目录(Android 10+ 无需权限，用户可通过文件管理器访问) """
    if _externalDir:
        return _externalDir
    return _JniDir("external") or _PkgExternalDir() or GetAppDataDir()


def _PkgFromPrivate():
    """ 从 /data/user/0/<pkg>/files(或 /data/data/<pkg>/files)里取包名 """
    private = os.environ.get(EnvPrivate) or ""
    parts = [p for p in private.split("/") if p]
    if len(parts) < 4 or parts[-1] != "files":
        return ""
    pkg = parts[-2]
    if not pkg or "." not in pkg:
        return ""
    return pkg


def _PkgExternalDir():
    """ 不依赖 pyjnius 推出外部私有目录 /storage/emulated/0/Android/data/<包名>/files """
    pkg = _PkgFromPrivate()
    if not pkg:
        return ""
    for root in ("/storage/emulated/0/Android/data", "/sdcard/Android/data"):
        path = os.path.join(root, pkg, "files")
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            continue
        if os.path.isdir(path):
            return path
    return ""


def _PkgExternalCacheDir():
    """ 不依赖 pyjnius 推出外部缓存目录 /storage/emulated/0/Android/data/<包名>/cache

    和 _PkgExternalDir 一个套路：Android 10+ 应用读写自己的外部缓存目录不需要
    任何权限；它是系统公认的"缓存"(设置-存储里能看到、系统"清理缓存"会清)，
    也是用户手里文件管理器/root 能进去手动删的位置 —— 默认缓存就放这。
    """
    pkg = _PkgFromPrivate()
    if not pkg:
        return ""
    for root in ("/storage/emulated/0/Android/data", "/sdcard/Android/data"):
        path = os.path.join(root, pkg, "cache")
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            continue
        if os.path.isdir(path):
            return path
    return ""


def GetExternalCacheDir():
    """ 应用外部缓存目录(取不到时退回外部私有目录下的 cache) """
    return _JniDir("external_cache") or _PkgExternalCacheDir() or os.path.join(
        _JniDir("external") or _PkgExternalDir() or GetAppDataDir(), "cache")


def GetAndroidSavePath():
    """ 下载目录默认值

    应用外部私有目录(/storage/emulated/0/Android/data/<包名>/files)：
    Android 10+ 读写自己的外部目录不需要任何存储权限，用户在文件管理器里
    也能看到(而不是只存在于 /data/user/0 里、只能靠"清除数据"处理)。
    """
    if _saveDir:
        return _saveDir
    return GetExternalDir()


# 内部私有存储前缀：用户/文件管理器看不到，系统"清理缓存"也不会动
_InternalDataPrefixes = ("/data/user/0/", "/data/data/", "/data/user_de/0/")


def NormalizeLocalPath(path):
    """ 规范化本地路径：去空白、展开 ~、折叠 "." 与 ".."

    * 空串 / 相对路径返回 "" —— 下载与缓存目录必须是绝对路径，否则运行时
      工作目录一变(Android 上是 "/")就会写到意料之外的地方
    * `saf://...` 原样返回(它不是文件系统路径，交给 tools/vfs.py 处理)
    """
    text = str(path or "").strip()
    if not text:
        return ""
    if text.startswith("saf://"):
        return text
    text = os.path.expanduser(text)
    if not os.path.isabs(text):
        return ""
    return os.path.normpath(text)


def IsInternalDataPath(path):
    """ 是否位于应用内部私有存储(/data/user/0/<包名>/…)

    这类目录只有应用自己看得到：文件管理器进不去、系统"清理缓存"不显示，
    只有"清除数据/卸载"才会删 —— 所以下载与缓存默认值必须避开。
    """
    p = NormalizeLocalPath(path)
    if not p:
        return False
    return any(p.startswith(prefix) for prefix in _InternalDataPrefixes)


def EnsureWritableDir(path, probeName=".jm_write_probe"):
    """ 确认目录存在且真能写(建目录 + 写探针文件 + 删除)，返回 (ok, reason)

    不用 os.access：Android 的外部存储是 FUSE，权限位看不出来是否可写，
    真正写一次才知道；同时也能提前发现"目录被同名文件占了"这种脏状态。
    """
    p = NormalizeLocalPath(path)
    if not p or p.startswith("saf://"):
        return False, "invalid path"
    try:
        os.makedirs(p, exist_ok=True)
    except Exception as es:
        return False, "makedirs: {}".format(es)
    probe = os.path.join(p, probeName)
    try:
        with open(probe, "wb") as f:
            f.write(b"jm")
        os.remove(probe)
        return True, ""
    except Exception as es:
        return False, "write: {}".format(es)


def NormalizeAndroidSavePath(path, external=None):
    """ 规范 Android 下载根目录，返回 (路径, 是否改动)

    老配置里的 SavePath 可能落在内部私有目录(/data/user/0/<包名>/files 或
    …/files/JMComic)：用户看不见、卸载即没，也谈不上"自己清理"。这种历史值
    统一改成应用外部私有目录(/storage/emulated/0/Android/data/<包名>/files)。
    外部目录取不到时保留原值，保证功能还能用。
    """
    ext = NormalizeLocalPath(external) or NormalizeLocalPath(GetExternalDir())
    current = NormalizeLocalPath(path)
    if not current:
        return ext, bool(ext)
    legacy = IsInternalDataPath(current)
    root = NormalizeLocalPath(GetAppDataDir())
    if root and (current == root or current.startswith(root + os.sep)):
        legacy = True
    if legacy and ext and current != ext:
        return ext, True
    return current, False


def GetAndroidPackage():
    """ 本应用包名(用于 am 启动自带组件) —— 不依赖 pyjnius

    `/data/user/0/<pkg>/files` 或 `/data/data/<pkg>/files` 里倒数第二段就是包名。
    取不到时返回空串，调用方据此判定"桥不可用"。
    """
    private = os.environ.get(EnvPrivate) or GetAppDataDir() or ""
    parts = [p for p in str(private).replace("\\", "/").split("/") if p]
    if len(parts) >= 2:
        for index in range(len(parts) - 1, 0, -1):
            name = parts[index]
            if "." in name and not name.endswith(".files"):
                return name
    return ""


def _LogMigrate(msg):
    """ 搬迁日志

    别用 Log.Warn/Info/Error 那组静态方法：它们一律 exc_info=True，不在
    except 块里调用会往日志里喷一段 "NoneType: None" 的假堆栈。
    """
    try:
        from tools.log import Log
        Log.logger.warning(msg)
    except Exception:
        try:
            print(msg, flush=True)
        except Exception:
            pass


def _MergeMove(src, dst):
    """ 递归把 src 里"dst 还没有"的条目搬过去(文件级不覆盖)

    只按顶层条目跳过会把"同一本书的新旧页"整个跳过、白丢一批缓存，
    所以必须递归到文件。
    """
    import shutil

    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        source = os.path.join(src, name)
        target = os.path.join(dst, name)
        if os.path.isdir(source):
            _MergeMove(source, target)
        elif not os.path.exists(target):
            shutil.move(source, target)


def _MigrateWork(oldDir, newDir, label):
    """ 把 oldDir 的内容搬到 newDir；全部成功才删 oldDir(失败保留旧的，不丢数据) """
    import shutil

    try:
        if not os.path.isdir(oldDir):
            return
        try:
            if os.path.realpath(oldDir) == os.path.realpath(newDir):
                return
        except Exception:
            return
        if not os.path.isdir(newDir) or not os.listdir(newDir):
            # 新目录不存在或还是空的：整体搬过去(同分区是 rename，瞬时的)
            os.makedirs(os.path.dirname(newDir), exist_ok=True)
            if os.path.isdir(newDir):
                shutil.rmtree(newDir, ignore_errors=True)
            shutil.move(oldDir, newDir)
        else:
            _MergeMove(oldDir, newDir)
            shutil.rmtree(oldDir, ignore_errors=True)
        _LogMigrate("{}: 已迁到 {}".format(label, newDir))
    except Exception as es:
        _LogMigrate("{}: 搬迁失败(保留原目录): {} ({})".format(label, es, oldDir))


def MigrateDirAsync(oldDir, newDir, label="dir", waitFirst=False):
    """ 后台搬目录(跨分区只能拷贝+删除，不能卡启动/界面)

    :param waitFirst: 先等此前启动的搬迁结束 —— "默认缓存目录 → 自定义缓存目录"
        必须排在启动时"内部私有目录 → 默认缓存目录"之后，否则会看到默认目录
        还没建好就直接跳过，留下一份谁也不会再用的旧缓存。
    """
    import threading

    previous = list(_migrateThreads) if waitFirst else []

    def _Work():
        for thread in previous:
            try:
                thread.join(60.0)
            except Exception:
                pass
        _MigrateWork(oldDir, newDir, label)

    thread = threading.Thread(target=_Work, name="jm-migrate", daemon=True)
    _migrateThreads.append(thread)
    thread.start()
    return thread


def WaitDirMigrate(timeout=30.0):
    """ 等所有搬迁线程结束(测试/退出前用)；没有搬运过直接返回 True """
    import time as _time

    threads = list(_migrateThreads)
    deadline = _time.time() + max(0.0, float(timeout))
    for thread in threads:
        try:
            thread.join(max(0.0, deadline - _time.time()))
        except Exception:
            pass
    alive = [t for t in _migrateThreads if t.is_alive()]
    _migrateThreads[:] = alive
    return not alive


def _MigrateCacheToExternal(root, cacheBase):
    """ 把老版本放在内部私有目录的缓存搬到外部缓存目录(见 InitAndroidEnv)

    只搬 `<root>/cache/jmcomic-qt`(也就是 Setting.GetCachePath() 的实际内容：
    封面/图片缓存/超分临时图/zip 临时文件)，模型(waifu2x-models)和 QNN 编译
    缓存(waifu2x-cache)不搬 —— 它们不是用户可清理的缓存，重新下载/编译代价大。
    同分区 rename 是瞬时的；内部→外部跨分区只能拷贝+删除，所以放后台线程。
    """
    oldDir = os.path.join(root, "cache", "jmcomic-qt")
    newDir = os.path.join(cacheBase, "jmcomic-qt")
    return MigrateDirAsync(oldDir, newDir, "cache")


def WaitCacheMigrate(timeout=30.0):
    """ 兼容旧名字：等所有缓存/目录搬迁结束 """
    return WaitDirMigrate(timeout)


def _CheckSafCacheAsync(key):
    """ 后台确认 SAF 缓存目录仍可写(授权被收回/目录被删 -> 回退默认目录)

    不能在 GetCachePath() 里同步做：服务首次启动 + 一次 IPC 要几百毫秒，
    而那个函数在建主窗口时就会被调用。这里失败后写回 _cacheSafOk=False，
    后续取路径时 Setting 自动回退默认目录。
    """
    from config import config
    from config.setting import Setting
    from tools import saf_bridge

    uri = saf_bridge.TreeUri(key)
    if not uri:
        return

    def Work():
        ok = False
        try:
            saf_bridge.IoMakedirs(uri, config.CacheLeafDir)
            # mkdirs 无论成败都回 ok，必须真写一次探针才能发现授权失效
            probe = "{}/.jm_write_probe".format(config.CacheLeafDir)
            ok = saf_bridge.IoWrite(uri, probe, b"jm")
            if ok:
                saf_bridge.IoDelete(uri, probe)
        except Exception:
            ok = False
        Setting._cacheSafKey = key
        Setting._cacheSafOk = ok
        if not ok:
            _LogMigrate("cache: SAF 缓存目录不可写，回退默认目录: {}".format(
                Setting.CachePathTreeName.value or key))

    import threading
    threading.Thread(target=Work, name="cache-saf-check", daemon=True).start()


def ApplyAndroidPathDefaults():
    """ 设置读完之后校正 Android 的下载/缓存目录，并把旧位置的内容搬过去

    在 Setting.InitLoadSetting() 末尾调用(必须在配置读完之后)：
      1. 历史遗留的内部私有下载目录(/data/...) → 外部私有目录；已下载的
         `commies` 内容在后台搬过去，之后新下载直接写外部目录；
      2. 设置了自定义缓存目录时，把默认缓存目录里残留的内容补搬过去 ——
         正常在设置页改目录时已经搬过，这里只兜底"改完立刻被杀进程"的情况。
    """
    if not IsAndroid():
        return
    from config import config
    from config.setting import Setting

    current = NormalizeLocalPath(Setting.SavePath.value)
    target, changed = NormalizeAndroidSavePath(current)
    if target:
        # 目录被删/存储卡拔掉时 makedirs 会失败：退到应用外部目录，别让整个
        # 下载链在第一次写文件时才报错
        ok, _ = EnsureWritableDir(target)
        if not ok:
            fallback = NormalizeLocalPath(GetExternalDir())
            if fallback and fallback != target:
                target, changed = fallback, True
                ok, _ = EnsureWritableDir(target)
        try:
            os.makedirs(os.path.join(target, config.SavePathDir), exist_ok=True)
        except Exception:
            pass
        if changed:
            Setting.SavePath.SetValue(target)
            oldRoot = os.path.join(current, config.SavePathDir) if current else ""
            newRoot = os.path.join(target, config.SavePathDir)
            if oldRoot and os.path.isdir(oldRoot):
                MigrateDirAsync(oldRoot, newRoot, "download")

    try:
        effective = NormalizeLocalPath(Setting.GetCachePath())
        default = NormalizeLocalPath(Setting.GetDefaultCachePath())
        # SAF 缓存由 cache_path.SetTree 在切换时用 vfs 搬，不能走本地 shutil
        if effective and default and effective != default and not effective.startswith("saf://"):
            # 不在这里判断默认目录是否非空：启动时"内部→默认"的搬迁可能还在跑，
            # 交给后台线程(先等前一个搬完)再判断；没有可搬的东西就是空转一次
            MigrateDirAsync(default, effective, "cache", waitFirst=True)
    except Exception:
        pass

    # SAF 缓存：后台确认授权还有效(失败则回退默认目录，不阻塞首帧)
    try:
        key = Setting.CacheTreeKey()
        if key:
            _CheckSafCacheAsync(key)
    except Exception:
        pass


def InitAndroidEnv(app=None):
    """ Android 环境初始化，必须在导入 config/setting 之前调用（桌面端直接返回） """
    global _androidInited, _appDataDir, _saveDir, _externalDir
    if _androidInited or not IsAndroid():
        return
    _androidInited = True

    from PySide6.QtCore import QStandardPaths

    root = os.environ.get(EnvAppDir) or ""
    if not root:
        root = GetAppDataDir()
    if not root:
        root = _QtDir(QStandardPaths.StandardLocation.AppDataLocation) or os.path.expanduser("~")
    root = os.path.abspath(root)
    try:
        os.makedirs(root, exist_ok=True)
    except Exception:
        pass
    _appDataDir = root

    saveDir = os.environ.get(EnvSaveDir) or _JniDir("external") or _PkgExternalDir() or ""
    if not saveDir:
        # 外部私有目录取不到时退化为私有目录，保证功能可用
        saveDir = os.path.join(root, "JMComic")
    _saveDir = saveDir
    try:
        os.makedirs(os.path.join(saveDir, "commies"), exist_ok=True)
    except Exception:
        pass

    extern = _JniDir("external") or _PkgExternalDir() or os.environ.get(EnvSaveDir) or ""
    _externalDir = extern or root

    # 缓存放应用外部缓存目录(/storage/emulated/0/Android/data/<包名>/cache)：
    # 封面/图片缓存/超分临时图都是可再生数据，放外部用户才清理得掉 —— 系统
    # "清理缓存"、设置-存储、文件管理器/root 都能看到并删掉它。
    # 外部目录不可用时退到外部私有目录下的 cache，再不行才退回内部私有目录。
    cacheBase = _JniDir("external_cache") or _PkgExternalCacheDir()
    if not cacheBase:
        cacheBase = os.path.join(extern or root, "cache")

    # XDG 目录重定向：setting._xdgDir 在 linux 平台走 XDG_*，这里全部指到应用目录
    # (配置/数据/日志留在内部私有目录；cacheBase 本身就是缓存目录，不再拼 "cache")
    os.environ.setdefault("HOME", root)
    for envName, sub, base in (("XDG_CONFIG_HOME", "config", root),
                               ("XDG_DATA_HOME", "data", root),
                               ("XDG_CACHE_HOME", "", cacheBase),
                               ("XDG_STATE_HOME", "state", root)):
        path = os.path.join(base, sub) if sub else base
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
        os.environ[envName] = path

    # 老版本的缓存在内部私有目录(<root>/cache/jmcomic-qt)，搬到外部缓存目录，
    # 否则同一个缓存存两份、旧的那份用户还清理不到。跨文件系统只能拷贝+删除，
    # 放后台线程做，不拖慢启动。
    _MigrateCacheToExternal(root, cacheBase)

    # Android 上 OpenGL 走 GLES，禁用桌面端才需要的特性
    global SupportSystemTray, SupportFrameless, SupportSingleInstance, SupportSubProcessProbe
    SupportSystemTray = False
    SupportFrameless = False
    SupportSingleInstance = False
    SupportSubProcessProbe = False

    # waifu2x 模型/后端库目录，供 sr_qnn 查找。模型是用户显式下载的，算数据不算
    # 缓存，留在内部私有目录(删了要重新下载，还可能打断正在跑的超分)
    os.environ.setdefault("JM_SR_MODELS", os.path.join(root, "waifu2x-models"))
    # QNN context binary 缓存(QNN 图编译产物，第二次启动快很多)。
    # C++ 侧默认是 <模型目录>/context，而模型目录可能是 private.tar 解包出来的位置，
    # 所以显式指到确定可写的私有目录，避免缓存写不进去。
    # 这个刻意**不跟缓存目录走外部**：context binary 要被反复 mmap，放 FUSE 挂载的
    # 外部存储上又慢又容易出怪问题；它由模型版本决定、体积有限，重新编译即可。
    os.environ.setdefault("JM_SR_CACHE", os.path.join(root, "waifu2x-cache"))

    # Android(p4a) 的 OpenSSL 没有系统 CA 目录：把随包 certifi 的 CA 指给它，
    # 否则 requests/urllib 的 HTTPS 证书校验一律失败(用户看到的就是"网络错误")
    try:
        import certifi
        caFile = certifi.where()
        if os.path.exists(caFile):
            for name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
                os.environ.setdefault(name, caFile)
    except Exception:
        pass

    # pycryptodome 的 cffi 后端默认用 RTLD_DEEPBIND 打开自带原生库。
    # 那是 glibc 专有标志，Android 的 bionic 不认，保险起见直接关掉
    # (它只是想避免符号被其它库里同名符号抢先，这里没有这种场景)
    os.environ.setdefault("PYCRYPTODOME_DISABLE_DEEPBIND", "1")

    # Qt 在 Android 上默认使用系统字体，禁止 Qt 去加载不存在的桌面字体
    os.environ.setdefault("QT_QPA_PLATFORM", "android")
    return


def GetAndroidModelDir():
    """ waifu2x(NPU) 模型目录 """
    return os.environ.get("JM_SR_MODELS") or os.path.join(GetAppDataDir(), "waifu2x-models")


# ##############################################################################
# ctypes.util 修复：pycryptodome(AES) 在 Android 上完全不可用的根因
# ##############################################################################
#
# python-for-android 的 python3 recipe 会把标准库 Lib/ctypes/util.py 整个替换成：
#
#     if True:
#         from android._ctypes_library_finder import find_library as _find_lib
#
# 而 p4a 的 android 包(顶层 __init__.py)第一件事就是 `from android._android import *`，
# 也就是 dlopen site-packages/android/_android.*.so。这个扩展依赖 p4a **SDL2/webview
# bootstrap** 里的 JNI 符号 WebView_AndroidGetJNIEnv；本项目用的是 bootstrap=qt，
# 该符号不存在，于是 dlopen 必然失败：
#
#     ImportError: dlopen failed: cannot locate symbol "WebView_AndroidGetJNIEnv"
#                  referenced by ".../site-packages/android/_android.so"
#
# 甚至连带 _ctypes_library_finder 自己也不可用(它要 `from jnius import autoclass`，
# 而 pyjnius 没打进 APK)。结果是 `import ctypes.util` 直接抛 ImportError ——
# 而 pycryptodome 的 Crypto/Util/_raw_api.py 在 sys.flags.optimize == 2 时
# (p4a 的 Qt bootstrap 硬编码了 setEnvironmentVariable("PYTHONOPTIMIZE","2"))
# 会**故意**放弃 cffi 后端、回落到 ctypes 后端，第一行就是 `from ctypes.util import
# find_library`。于是 Crypto.Cipher.AES 永远导入失败，jmcomic 的
# JmCryptoTool.decode_resp_data 无法解密任何响应 —— 表现就是"登录报错、首页也报错"
# (接口返回的全部是密文)。
#
# 注意 pycryptodome 真正的原生库是用**绝对路径**加载的
# (load_pycryptodome_raw_lib -> load_lib(full_name)，full_name 含 "."，不会再调用
# find_library)，所以这里只要让 `import ctypes.util` 能成功、并提供一个**不依赖
# pyjnius** 的 find_library 实现即可。

_LibNameRe = None
_FinderInstalled = False


def _LibNameMatches(searchName, fileName):
    """ 与 p4a 的 does_libname_match_filename 等价：
        匹配 mymodule.so / libmymodule.so / mymodule.arm64.so / mymodule.so.1.3.4 等 """
    global _LibNameRe
    import re
    if _LibNameRe is None:
        _LibNameRe = re.compile(r"^(lib)?([^.]+)\.(.*\.)?so(\.[0-9]+)*$")
    mo = _LibNameRe.match(fileName)
    if not mo:
        return False
    stem = mo.group(2)
    return stem == searchName or ("lib" + stem) == searchName


def GetCtypesLibSearchDirs():
    """ find_library 的搜索目录：应用自带 .so 目录 + 系统库目录 """
    dirs = []
    for path in GetNativeLibDirs():
        if path and path not in dirs:
            dirs.append(path)
    if sys.maxsize > 2 ** 32:
        dirs.extend(["/system/lib64", "/system/lib"])
    else:
        dirs.append("/system/lib")
    return [d for d in dirs if os.path.isdir(d)]


def FindLibrary(name):
    """ 不依赖 pyjnius 的 find_library(名字匹配规则与 p4a 一致) """
    if not name:
        return None
    # 已经是绝对路径/带目录的直接返回
    if os.sep in name:
        return name if os.path.exists(name) else None
    try:
        for folder in GetCtypesLibSearchDirs():
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for fileName in names:
                if _LibNameMatches(name, fileName):
                    return os.path.join(folder, fileName)
            # 也接受直接同名(例如 "libc++_shared.so" 这种整体当 name 传进来的)
            if name in names:
                return os.path.join(folder, name)
    except Exception:
        pass
    return None


def InstallCtypesLibraryFinder(force=False):
    """ 用一个纯 python 的 android 包顶掉 p4a 那个必然导入失败的包

    只替换 sys.modules 里的 `android` 与 `android._ctypes_library_finder`，
    **不执行**真实 android/__init__.py，因此不会去 dlopen _android.so。
    真实 android 包的目录仍然挂在 __path__ 上，其他子模块的导入行为不变。

    返回 True 表示已装好(或本来就装好了)。
    """
    global _FinderInstalled
    if _FinderInstalled:
        return True
    if not IsAndroid() and not force:
        return False
    try:
        import importlib.util
        import types
        # 真的 android 包已经成功导入过，说明这个 bootstrap 支持它，别乱动
        if "android" in sys.modules:
            return False
        searchPath = []
        try:
            spec = importlib.util.find_spec("android")
            if spec is not None and spec.submodule_search_locations:
                searchPath = list(spec.submodule_search_locations)
        except Exception:
            searchPath = []

        pkg = types.ModuleType("android")
        pkg.__doc__ = ("JMComic 的 android 兼容包：p4a 的 _android.so 在 bootstrap=qt 下"
                       "无法加载(缺 WebView_AndroidGetJNIEnv)，这里只补 ctypes 需要的 finder。")
        pkg.__path__ = searchPath
        pkg.__jmcomic_shim__ = True

        finder = types.ModuleType("android._ctypes_library_finder")
        finder.find_library = FindLibrary
        finder.does_libname_match_filename = _LibNameMatches
        finder.get_activity_lib_dir = lambda activityName: None
        finder.__jmcomic_shim__ = True
        pkg._ctypes_library_finder = finder

        sys.modules["android"] = pkg
        sys.modules["android._ctypes_library_finder"] = finder
        _FinderInstalled = True
        return True
    except Exception:
        return False


def GetScreenSize(app=None):
    """ 屏幕尺寸(逻辑像素) """
    try:
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen:
            size = screen.size()
            return size.width(), size.height()
    except Exception:
        pass
    return 0, 0
