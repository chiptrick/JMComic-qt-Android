# coding:utf-8
""" 移动端(Android)平台适配层

桌面端(Windows/Linux/macOS)调用这里的所有函数都是空操作，不会改变原有行为。

Android 端由 android/main.py 在创建 QApplication 之后、导入业务模块之前调用
InitAndroidEnv()，作用：
    1. 把配置/数据/缓存/日志目录重定向到应用私有目录(Android 14 无需任何存储权限)
    2. 把下载目录默认指向应用外部私有目录(/storage/emulated/0/Android/data/<包名>/files)
    3. 标记触摸设备、禁用桌面端专有特性(系统托盘/单实例/无边框窗口)
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


def _PkgExternalDir():
    """ 不依赖 pyjnius 推出外部私有目录 /storage/emulated/0/Android/data/<包名>/files """
    private = os.environ.get(EnvPrivate) or ""
    parts = [p for p in private.split("/") if p]
    # /data/user/0/<pkg>/files 或 /data/data/<pkg>/files
    if len(parts) < 4 or parts[-1] != "files":
        return ""
    pkg = parts[-2]
    if not pkg or "." not in pkg:
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


def GetExternalDir():
    """ 应用外部私有目录(Android 10+ 无需权限，用户可通过文件管理器访问) """
    if _externalDir:
        return _externalDir
    return _JniDir("external") or _PkgExternalDir() or GetAppDataDir()


def GetAndroidSavePath():
    """ 下载目录默认值 """
    if _saveDir:
        return _saveDir
    return GetExternalDir()


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

    extern = _JniDir("external") or _PkgExternalDir()
    _externalDir = extern or root

    # XDG 目录重定向：setting._xdgDir 在 linux 平台走 XDG_*，这里全部指到应用私有目录
    os.environ.setdefault("HOME", root)
    for envName, sub in (("XDG_CONFIG_HOME", "config"),
                         ("XDG_DATA_HOME", "data"),
                         ("XDG_CACHE_HOME", "cache"),
                         ("XDG_STATE_HOME", "state")):
        path = os.path.join(root, sub)
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
        os.environ[envName] = path

    # Android 上 OpenGL 走 GLES，禁用桌面端才需要的特性
    global SupportSystemTray, SupportFrameless, SupportSingleInstance, SupportSubProcessProbe
    SupportSystemTray = False
    SupportFrameless = False
    SupportSingleInstance = False
    SupportSubProcessProbe = False

    # waifu2x 模型/后端库目录，供 sr_qnn 查找
    os.environ.setdefault("JM_SR_MODELS", os.path.join(root, "waifu2x-models"))
    # QNN context binary 缓存(QNN 图编译产物，第二次启动快很多)。
    # C++ 侧默认是 <模型目录>/context，而模型目录可能是 private.tar 解包出来的位置，
    # 所以显式指到确定可写的私有目录，避免缓存写不进去
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
