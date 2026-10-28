# coding:utf-8
""" 超分(waifu2x)后端解析

桌面端：sr_vulkan(Vulkan 计算)，行为与原来完全一致
Android：sr_qnn(ONNX Runtime + 高通 QNN/HTP NPU)，接口与 sr_vulkan 同构

业务代码里的 `from sr_vulkan import sr_vulkan as sr` 不需要改动：
Android 端由 InstallQnnCompat() 把 sr_qnn 注册成 sr_vulkan 模块，
这样 task_waifu2x / main_view / tool / waifu2x_check 等原有调用点全部照旧工作。
"""
import sys
import types

from tools import platform_mobile

_qnnEngine = None
_engineType = ""


def GetSrModule():
    """ 返回当前可用的超分引擎模块，没有则返回 None """
    global _qnnEngine, _engineType
    if _qnnEngine is not None:
        return _qnnEngine
    if not platform_mobile.IsAndroid():
        try:
            from sr_vulkan import sr_vulkan as sr
            _engineType = "vulkan"
            return sr
        except Exception:
            return None
    try:
        import sr_qnn
        if sr_qnn.LoadEngine():
            _qnnEngine = sr_qnn
            _engineType = "qnn"
            return sr_qnn
    except Exception:
        pass
    return None


def InstallQnnCompat():
    """ Android 专用：把 sr_qnn 注册为 sr_vulkan，保持原有 import 语句可用 """
    if not platform_mobile.IsAndroid():
        return False
    sr = GetSrModule()
    if sr is None:
        return False
    module = types.ModuleType("sr_vulkan")
    module.sr_vulkan = sr
    for name in dir(sr):
        if name.startswith("MODEL_"):
            setattr(module, name, getattr(sr, name))
    sys.modules["sr_vulkan"] = module
    # 模型包在 Android 上不存在，注册占位模块避免重复报错
    for name in ("sr_vulkan_model_waifu2x", "sr_vulkan_model_realcugan", "sr_vulkan_model_realesrgan"):
        sys.modules.setdefault(name, types.ModuleType(name))
    return True


def GetEngineType():
    return _engineType


def IsQnn():
    return _engineType == "qnn"


def GetEngineName():
    """ 引擎显示名；QNN 后端还要带上真实挂载状态

    会话建立前 GetBackendInfo() 返回空；建立后可能返回
    "QNN HTP (部分算子 CPU 回退)" / "CPU (ONNX Runtime, QNN 未生效)"。
    这类降级必须让用户在日志里一眼看到，否则会被当成"QNN 超分很慢"。
    """
    if IsQnn():
        info = ""
        try:
            import sr_qnn
            info = sr_qnn.GetBackendInfo()
        except Exception:
            pass
        return "Qualcomm QNN / {}".format(info or "NPU/HTP")
    if _engineType == "vulkan":
        return "Vulkan"
    return "None"


def GetNoNpuReason():
    """ 没用上 NPU 的具体原因；已经用上(或不是 QNN 引擎)时返回空串

    界面只提示"超分未使用 NPU"的话，用户和维护者都不知道该查哪儿：
    最常见的是"这个 APK 打包时漏了 QNN 运行库"，其次是机型拿不到 FastRPC。
    这两种的处理方式完全不同，所以把原因带出来。
    """
    if not IsQnn():
        return ""
    try:
        import sr_qnn
        info = sr_qnn.GetBackendInfo() or ""
        if sr_qnn.HasHtp() and "CPU" not in info:
            return ""
        return sr_qnn.Diagnose()
    except Exception as es:
        return str(es)


def CanUseSubProcessProbe():
    """ Android 下不能 fork 出 python 子进程，跳过 sr_vulkan 的崩溃探测 """
    return platform_mobile.SupportSubProcessProbe
