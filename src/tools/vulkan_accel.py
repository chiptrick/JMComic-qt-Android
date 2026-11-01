# coding:utf-8
""" 图片浏览的 Vulkan 渲染加速（桌面端与 Android 共用）

为什么不是"自己写一个 Vulkan 视口"
-----------------------------------
以前的加速实现是给看图视口挂一个 GL 上下文（把 QGraphicsView 的视口换成自带
上下文的控件），让绘制走 GL surface。Vulkan 这条路在 Python 侧走不通：PySide6
没有暴露 QVulkanWindow/QVulkanWindowRenderer，拿不到 VkDevice、swapchain 和
command buffer，没法在脚本里自己建一条渲染管线。

Qt 6 自己就带 Vulkan 后端：窗口部件的合成走 QRhi（QBackingStoreRhiSupport），
后端可以用两个环境变量指定（见 qtbase src/gui/painting/qbackingstorerhisupport.cpp
里的 checkForceRhi）：

    QT_WIDGETS_RHI=1                  # 打开窗口部件的 RHI 合成
    QT_WIDGETS_RHI_BACKEND=vulkan     # 指定 Vulkan 后端

于是 QGraphicsView 的整条绘制链路（QPainter -> 后备存储 -> RHI 纹理 -> 屏幕）
一行都不用改，只把"最后一跳"从 OpenGL 换成 Vulkan。图片的缩放、定位、双页拼接、
GIF 播放全在原路径上，显示效果与以前完全一致。

生效时机
--------
这两个变量在**第一次 flush 窗口**时被读入并静态缓存，之后再改环境变量不生效。
所以开关的语义是"重启生效"，与 Setting.IsOpenVulkan.isNeedReset = True 对应：
本模块只需要在启动、建第一个窗口之前调用一次 ApplyFromSetting()。
"""

import ctypes
import os
import sys

# 打开/指定 Qt 窗口部件 RHI 后端的环境变量（qtbase: QBackingStoreRhiSupport）
ENABLE_ENV = "QT_WIDGETS_RHI"
BACKEND_ENV = "QT_WIDGETS_RHI_BACKEND"
BACKEND_NAME = "vulkan"

# 探测结果缓存：None=还没探测
_supported = None
_detail = "not probed"
# ApplyFromSetting() 的结论，供日志与状态读取
_status = "off"
_applied = False

# Vulkan 常量（只用得到这两个）
_VK_STRUCTURE_TYPE_APPLICATION_INFO = 0
_VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 1
_VK_API_VERSION_1_0 = (1 << 22)


def _IsAndroid():
    try:
        from tools import platform_mobile
        return bool(platform_mobile.IsAndroid())
    except Exception:
        return False


def _LoaderNames():
    """ 各平台 Vulkan loader 的库名（macOS 不用 Vulkan，Qt 在那边走 Metal） """
    if sys.platform == "win32":
        return ("vulkan-1.dll",)
    if sys.platform == "darwin":
        return ()
    if _IsAndroid():
        # Android 7.0(API 24) 起系统自带 loader，属于公开的 NDK 库
        return ("libvulkan.so",)
    return ("libvulkan.so.1", "libvulkan.so")


def _LoadLoader():
    for name in _LoaderNames():
        try:
            return name, ctypes.CDLL(name)
        except OSError:
            continue
    return "", None


def _ProbeByQt():
    """ 让 Qt 自己建一次 Vulkan 实例（和 QRhiVulkan 用的是同一条路）

    返回 True/False，接口不存在时返回 None。
    """
    try:
        from PySide6.QtGui import QVulkanInstance
    except Exception:
        return None
    inst = None
    try:
        inst = QVulkanInstance()
        ok = bool(inst.create())
        if ok:
            try:
                api = inst.supportedApiVersion()
                _SetDetail("qt instance ok, api {}".format(api.toString()))
            except Exception:
                _SetDetail("qt instance ok")
        else:
            _SetDetail("qt instance failed, error {}".format(inst.errorCode()))
        return ok
    except Exception as es:
        _SetDetail("qt instance raised: {}".format(es))
        return False
    finally:
        try:
            if inst is not None:
                inst.destroy()
        except Exception:
            pass


class _VkApplicationInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int32),
        ("pNext", ctypes.c_void_p),
        ("pApplicationName", ctypes.c_char_p),
        ("applicationVersion", ctypes.c_uint32),
        ("pEngineName", ctypes.c_char_p),
        ("engineVersion", ctypes.c_uint32),
        ("apiVersion", ctypes.c_uint32),
    ]


class _VkInstanceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_int32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("pApplicationInfo", ctypes.POINTER(_VkApplicationInfo)),
        ("enabledLayerCount", ctypes.c_uint32),
        ("ppEnabledLayerNames", ctypes.c_void_p),
        ("enabledExtensionCount", ctypes.c_uint32),
        ("ppEnabledExtensionNames", ctypes.c_void_p),
    ]


def _ProbeByCtypes():
    """ PySide6 没绑定 QVulkanInstance 时，直接调 loader 建一次实例

    只用来判断"这台机器能不能真的建出 VkInstance"，不参与渲染。
    """
    name, lib = _LoadLoader()
    if lib is None:
        _SetDetail("no loader")
        return False
    try:
        getProc = lib.vkGetInstanceProcAddr
        getProc.restype = ctypes.c_void_p
        getProc.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        createPtr = getProc(None, b"vkCreateInstance")
        if not createPtr:
            _SetDetail("loader {} has no vkCreateInstance".format(name))
            return False
        create = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(_VkInstanceCreateInfo),
                                  ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(createPtr)

        appInfo = _VkApplicationInfo()
        appInfo.sType = _VK_STRUCTURE_TYPE_APPLICATION_INFO
        appInfo.pApplicationName = b"JMComic-qt"
        appInfo.pEngineName = b"JMComic-qt"
        appInfo.apiVersion = _VK_API_VERSION_1_0
        createInfo = _VkInstanceCreateInfo()
        createInfo.sType = _VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO
        createInfo.pApplicationInfo = ctypes.pointer(appInfo)

        instance = ctypes.c_void_p()
        result = create(ctypes.byref(createInfo), None, ctypes.byref(instance))
        if result != 0:
            _SetDetail("vkCreateInstance on {} failed: {}".format(name, result))
            return False
        try:
            destroyPtr = getProc(instance, b"vkDestroyInstance")
            if destroyPtr:
                destroy = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(destroyPtr)
                destroy(instance, None)
        except Exception:
            pass
        _SetDetail("vkCreateInstance ok via {}".format(name))
        return True
    except Exception as es:
        _SetDetail("ctypes probe error: {}".format(es))
        return False


def _SetDetail(text):
    global _detail
    _detail = text


def GetProbeDetail():
    return _detail


def IsSupported():
    """ 这台设备上能不能真的开 Vulkan

    先看系统里有没有 loader，再让 Qt（优先）或 loader 建一次 Vulkan 实例。
    只是"能不能试着开"的判断：真正创建 RHI/交换链的是 Qt，失败时它会退回
    默认后端并打警告，不会崩。
    """
    global _supported
    if _supported is not None:
        return _supported

    if not _LoaderNames():
        _SetDetail("platform without vulkan")
        _supported = False
        return _supported

    ok = _ProbeByQt()
    if ok is None:
        ok = _ProbeByCtypes()
    _supported = bool(ok)
    return _supported


def IsActive():
    """ 本次进程是否真的把窗口合成指到了 Vulkan（看环境变量，不猜）

    判据只看后端：ENABLE_ENV(=QT_WIDGETS_RHI) 我们刻意不设（设了会让 QRhiWidget
    拿不到 RHI）。若外部显式设了 0/false，则视为未启用。
    """
    flag = os.environ.get(ENABLE_ENV, "").strip().lower()
    if flag in ("0", "false"):
        return False
    return (os.environ.get(BACKEND_ENV) or "").strip().lower() == BACKEND_NAME


def GetBackendName():
    return BACKEND_NAME if IsActive() else "raster"


def GetStatus():
    return _status


def ApplyFromSetting():
    """ 按设置决定是否启用 Vulkan 合成

    必须在**建第一个窗口之前**调用（桌面端是 QApplication 之前，Android 是
    主窗口 show 之前）。重复调用是安全的：环境变量只会被写成同一个值。
    """
    global _status, _applied
    if _applied:
        return True

    if not _SettingEnabled():
        _status = "off(设置未开启)"
        return False

    if not IsSupported():
        _status = "unavailable({})".format(GetProbeDetail())
        _LogWarn("vulkan accel unavailable: {}".format(GetProbeDetail()))
        return False

    # 调试用（Android 的 sr_env.txt / 桌面端 shell 都可以覆盖）：已显式指定别的后端就尊重
    envBackend = (os.environ.get(BACKEND_ENV) or "").strip().lower()
    if envBackend and envBackend != BACKEND_NAME:
        _status = "ignored(环境变量已指定 {})".format(envBackend)
        _LogWarn("vulkan accel ignored: {}={}".format(BACKEND_ENV, envBackend))
        return False

    # 只写后端，**不写 ENABLE_ENV(=QT_WIDGETS_RHI)**。
    # 实测（Qt 6.12 / TextureView / Adreno）：QT_WIDGETS_RHI=1 会让 QRhiWidget 报
    # "QRhiWidget: No QRhi"，GPU 合成层直接失效、窗口内容区高度还会错乱。
    # Android 上 Qt 默认就用 RHI 合成窗口，这里只需要指定后端。
    os.environ.pop(ENABLE_ENV, None)
    os.environ[BACKEND_ENV] = BACKEND_NAME
    _applied = True
    _status = "on({})".format(GetProbeDetail())
    return True


def _SettingEnabled():
    """ 读"启动时生效"的值（IsOpenVulkan.isNeedReset=True，改完要重启） """
    try:
        from config.setting import Setting
        return bool(Setting.IsOpenVulkan.value)
    except Exception as es:
        _LogError(es)
        return False


def _LogWarn(msg):
    try:
        from tools.log import Log
        Log.Warn(msg)
    except Exception:
        pass


def _LogError(es):
    try:
        from tools.log import Log
        Log.Error(es)
    except Exception:
        pass
