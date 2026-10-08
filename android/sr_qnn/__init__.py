# coding:utf-8
""" sr_qnn —— Android 端 waifu2x/Real-ESRGAN 超分引擎

实现：ONNX Runtime + Qualcomm QNN Execution Provider(Hexagon NPU / HTP)
对外接口与桌面端 sr_vulkan 同构，业务代码无需改动：

    sr.init() / sr.initSet(device, threads) / sr.getGpuInfo() / sr.getCpuCoreNum()
    sr.getGpuCoreNum() / sr.getVersion() / sr.setDebug(bool)
    sr.add(imgData, model, taskId, wOrScale, h=0, format="jpg", tileSize=0)
    sr.load(waitMs=0) -> (data, format, taskId, tick) | None
    sr.stop() / sr.remove(ids) / sr.removeWaitProc(ids) / sr.getLastError()
    MODEL_* 模型常量(由 models/models.txt 生成，与桌面端命名一致)

模型文件与清单放在 models/ 目录(JM_SR_MODELS 可覆盖)，
models.txt 每行: <模型名> <tab> <onnx文件> <tab> <原生倍数> <tab> <降噪等级> <tab> <固定输入边长>
"""
import ctypes
import os
import threading

from tools.log import Log
from tools import platform_mobile

# ---------------------------------------------------------------- 模型常量
# 与桌面端 sr_vulkan 一致的模型名(去掉 MODEL_ 前缀)，编号从 1 开始
ModelNames = [
    "WAIFU2X_CUNET_UP1X_DENOISE0X", "WAIFU2X_CUNET_UP1X_DENOISE1X",
    "WAIFU2X_CUNET_UP1X_DENOISE2X", "WAIFU2X_CUNET_UP1X_DENOISE3X",
    "WAIFU2X_CUNET_UP2X",
    "WAIFU2X_CUNET_UP2X_DENOISE0X", "WAIFU2X_CUNET_UP2X_DENOISE1X",
    "WAIFU2X_CUNET_UP2X_DENOISE2X", "WAIFU2X_CUNET_UP2X_DENOISE3X",
    "WAIFU2X_ANIME_UP2X",
    "WAIFU2X_ANIME_UP2X_DENOISE0X", "WAIFU2X_ANIME_UP2X_DENOISE1X",
    "WAIFU2X_ANIME_UP2X_DENOISE2X", "WAIFU2X_ANIME_UP2X_DENOISE3X",
    "WAIFU2X_PHOTO_UP2X",
    "WAIFU2X_PHOTO_UP2X_DENOISE0X", "WAIFU2X_PHOTO_UP2X_DENOISE1X",
    "WAIFU2X_PHOTO_UP2X_DENOISE2X", "WAIFU2X_PHOTO_UP2X_DENOISE3X",
    "REALCUGAN_PRO_UP2X", "REALCUGAN_PRO_UP2X_CONSERVATIVE", "REALCUGAN_PRO_UP2X_DENOISE3X",
    "REALCUGAN_PRO_UP3X", "REALCUGAN_PRO_UP3X_CONSERVATIVE", "REALCUGAN_PRO_UP3X_DENOISE3X",
    "REALCUGAN_SE_UP2X", "REALCUGAN_SE_UP2X_CONSERVATIVE",
    "REALCUGAN_SE_UP2X_DENOISE1X", "REALCUGAN_SE_UP2X_DENOISE2X", "REALCUGAN_SE_UP2X_DENOISE3X",
    "REALCUGAN_SE_UP3X", "REALCUGAN_SE_UP3X_CONSERVATIVE", "REALCUGAN_SE_UP3X_DENOISE3X",
    "REALCUGAN_SE_UP4X", "REALCUGAN_SE_UP4X_CONSERVATIVE", "REALCUGAN_SE_UP4X_DENOISE3X",
    "REALESRGAN_ANIMAVIDEOV3_UP2X", "REALESRGAN_ANIMAVIDEOV3_UP3X", "REALESRGAN_ANIMAVIDEOV3_UP4X",
    "REALESRGAN_X4PLUS_UP4X", "REALESRGAN_X4PLUSANIME_UP4X",
]

LibName = "libsr_qnn.so"
Version = "sr_qnn 1.0.0 (ONNX Runtime QNN/HTP)"
# QNN 后端库(位于 libsr_qnn.so 同目录，由 onnxruntime-android-qnn 提供)
QnnBackendLib = "libQnnHtp.so"

_lib = None
_lock = threading.Lock()
_loaded = False
_loadError = ""
_modelIdByName = {}
_modelNameById = {}
_debug = False
_dummyKeepAlive = []


class SrqResult(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.POINTER(ctypes.c_ubyte)),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("stride", ctypes.c_int),
        ("taskId", ctypes.c_int),
        ("tick", ctypes.c_double),
        ("status", ctypes.c_int),
        ("format", ctypes.c_char * 16),
    ]


def _SearchLib():
    """ 查找 libsr_qnn.so

    查找顺序：环境变量 > 包内目录 > LD_LIBRARY_PATH > 应用私有目录 > native 库目录。

    注意：Android 上 nativeLibraryDir 只能靠 /proc/self/maps 推断，因为 **pyjnius 并没有
    被打进 APK**(实测)，原来只依赖 jnius 的写法会退化成相对路径 "libsr_qnn.so"，
    随后 os.path.isabs() 判定失败 —— 真机上就报"NPU 超分后端不可用"。
    """
    envLib = os.environ.get("JM_SR_QNN_LIB")
    if envLib and os.path.exists(envLib):
        return envLib

    dirs = []
    here = os.path.dirname(os.path.abspath(__file__))
    dirs.append(here)
    dirs.append(os.path.join(here, "libs"))
    dirs.append(os.path.join(os.path.dirname(here), "libs"))
    for path in (os.environ.get("LD_LIBRARY_PATH") or "").split(":"):
        if path:
            dirs.append(path)
    appData = platform_mobile.GetAppDataDir()
    dirs.append(os.path.join(appData, "lib"))
    dirs.append(os.path.join(appData, "native"))
    for path in platform_mobile.GetNativeLibDirs():
        dirs.append(path)

    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        path = os.path.join(d, LibName)
        if os.path.exists(path):
            return path
    return LibName


# libsr_qnn.so 的依赖：必须先以 RTLD_GLOBAL 加载，否则 DT_NEEDED 解析不到
# (Android 的 linker 不认 LD_LIBRARY_PATH，靠调用方所在目录/已加载符号)
DependLibs = ("libc++_shared.so", "libonnxruntime.so")


def _PreloadLibs(libDir):
    """ 预加载依赖库 """
    loaded = []
    for name in DependLibs:
        path = os.path.join(libDir, name)
        if not os.path.exists(path):
            continue
        try:
            ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            loaded.append(name)
        except OSError as es:
            Log.Warn("预加载 {} 失败: {}".format(name, es))
    if loaded:
        Log.Warn("预加载依赖库: {}".format(", ".join(loaded)))
    return loaded


def _Bind(lib):
    lib.srq_init.restype = ctypes.c_int
    lib.srq_init.argtypes = []

    lib.srq_init_set.restype = ctypes.c_int
    lib.srq_init_set.argtypes = [ctypes.c_int, ctypes.c_int]

    lib.srq_set_debug.restype = None
    lib.srq_set_debug.argtypes = [ctypes.c_int]

    lib.srq_get_version.restype = ctypes.c_char_p
    lib.srq_get_version.argtypes = []

    lib.srq_get_backend_info.restype = ctypes.c_char_p
    lib.srq_get_backend_info.argtypes = []

    lib.srq_has_htp.restype = ctypes.c_int
    lib.srq_has_htp.argtypes = []

    lib.srq_get_cpu_core_num.restype = ctypes.c_int
    lib.srq_get_cpu_core_num.argtypes = []

    lib.srq_get_gpu_core_num.restype = ctypes.c_int
    lib.srq_get_gpu_core_num.argtypes = []

    lib.srq_get_last_error.restype = ctypes.c_char_p
    lib.srq_get_last_error.argtypes = []

    lib.srq_set_model_dir.restype = ctypes.c_int
    lib.srq_set_model_dir.argtypes = [ctypes.c_char_p]

    lib.srq_model_count.restype = ctypes.c_int
    lib.srq_model_count.argtypes = []

    lib.srq_model_name.restype = ctypes.c_char_p
    lib.srq_model_name.argtypes = [ctypes.c_int]

    lib.srq_model_info.restype = ctypes.c_char_p
    lib.srq_model_info.argtypes = [ctypes.c_int]

    lib.srq_model_id.restype = ctypes.c_int
    lib.srq_model_id.argtypes = [ctypes.c_char_p]

    lib.srq_add.restype = ctypes.c_int
    lib.srq_add.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_int, ctypes.c_double, ctypes.c_int, ctypes.c_int,
                            ctypes.c_char_p, ctypes.c_int]

    lib.srq_load.restype = ctypes.c_int
    lib.srq_load.argtypes = [ctypes.c_int, ctypes.POINTER(SrqResult)]

    lib.srq_free_result.restype = None
    lib.srq_free_result.argtypes = [ctypes.POINTER(SrqResult)]

    lib.srq_stop.restype = None
    lib.srq_stop.argtypes = []

    lib.srq_remove.restype = None
    lib.srq_remove.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]

    lib.srq_remove_wait.restype = None
    lib.srq_remove_wait.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
    return


def _LoadModelTable():
    """ 从 models.txt 读取模型表，生成 MODEL_* 常量 """
    count = _lib.srq_model_count()
    for index in range(count):
        name = _lib.srq_model_name(index)
        if not name:
            continue
        name = name.decode("utf-8")
        modelId = _lib.srq_model_id(name.encode("utf-8"))
        _modelIdByName[name] = modelId
        _modelNameById[modelId] = name
        globals()["MODEL_" + name] = modelId
    # 自检：C++ 内置表/模型清单/界面下拉列表三处必须一致，不一致时提示(不影响运行)
    loaded = set(_modelIdByName.keys())
    expected = set(ModelNames)
    missing = sorted(expected - loaded)
    extra = sorted(loaded - expected)
    if missing or extra:
        Log.Warn("sr_qnn 模型表与界面列表不一致, 缺失:{} 多余:{}".format(missing, extra))
    return count


def LoadEngine(modelDir=None):
    """ 加载本地库并初始化(失败返回 False，不抛异常) """
    global _lib, _loaded, _loadError
    with _lock:
        if _loaded:
            return True
        if _lib is not None:
            return False
        try:
            path = _SearchLib()
            if not os.path.isabs(path) or not os.path.exists(path):
                _loadError = "找不到 {} (解析结果: {}, native 库目录: {})".format(
                    LibName, path, platform_mobile.GetNativeLibDirs())
                Log.Warn(_loadError)
                return False
            _PreloadLibs(os.path.dirname(os.path.abspath(path)))
            _lib = ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            _Bind(_lib)
            _PrepareQnnEnv(os.path.dirname(os.path.abspath(path)))
            if modelDir is None:
                modelDir = platform_mobile.GetAndroidModelDir()
            if modelDir:
                os.makedirs(modelDir, exist_ok=True)
                _lib.srq_set_model_dir(modelDir.encode("utf-8"))
            stat = _lib.srq_init()
            if stat < 0:
                _loadError = _lib.srq_get_last_error().decode("utf-8", "ignore")
                Log.Warn("srq_init failed: {}".format(_loadError))
                return False
            _LoadModelTable()
            if CountAvailableModels() <= 0:
                _loadError = "未找到任何 ONNX 模型，请先运行 android/tools/prepare_models.py " \
                             "生成模型并放到 {}".format(modelDir)
                Log.Warn(_loadError)
                _lib = None
                return False
            _loaded = True
            Log.Warn("sr_qnn loaded: {}, models:{}/{}, htp:{}, backend:{}".format(
                path, CountAvailableModels(), len(_modelIdByName), HasHtp(), GetBackendInfo()))
            return True
        except Exception as es:
            _loadError = str(es)
            Log.Error(es)
            return False


def _PrepareQnnEnv(libDir):
    """ QNN HTP 需要 ADSP_LIBRARY_PATH 指向 DSP skel 库所在目录 """
    try:
        old = os.environ.get("ADSP_LIBRARY_PATH", "")
        need = ["/dsp", "/vendor/dsp", "/system/lib/rfsa/adsp", libDir]
        items = [v for v in old.split(";") if v]
        for v in need:
            if v not in items:
                items.append(v)
        os.environ["ADSP_LIBRARY_PATH"] = ";".join(items)
        # 让 ctypes 能找到 QNN 依赖库
        ld = os.environ.get("LD_LIBRARY_PATH", "")
        if libDir not in ld.split(":"):
            os.environ["LD_LIBRARY_PATH"] = "{}{}{}".format(libDir, ":" if ld else "", ld)
    except Exception as es:
        Log.Error(es)
    return


def IsLoaded():
    return _loaded


def GetLoadError():
    return _loadError


def HasHtp():
    """ 设备是否具备高通 NPU(HTP) """
    if not _loaded:
        return False
    try:
        return _lib.srq_has_htp() > 0
    except Exception:
        return False


def GetBackendInfo():
    if not _loaded:
        return ""
    try:
        return (_lib.srq_get_backend_info() or b"").decode("utf-8", "ignore")
    except Exception:
        return ""


# ---------------------------------------------------------------- 兼容接口
def init():
    """ 与 sr_vulkan 一致：>=0 表示成功 """
    if not _loaded and not LoadEngine():
        return -1
    return 0


def initSet(device=0, threads=0):
    if not _loaded:
        return -1
    stat = _lib.srq_init_set(int(device or 0), int(threads or 0))
    return stat


def setDebug(enable=True):
    global _debug
    _debug = bool(enable)
    if _loaded:
        _lib.srq_set_debug(1 if enable else 0)
    return


def getVersion():
    if _loaded:
        return (_lib.srq_get_version() or Version.encode("utf-8")).decode("utf-8", "ignore")
    return Version


def getGpuInfo():
    """ 设备列表：NPU 优先，CPU 兜底(与 sr_vulkan 的显卡列表语义一致) """
    info = []
    if _loaded and HasHtp():
        info.append("Qualcomm Hexagon NPU (QNN HTP)")
    info.append("CPU (ONNX Runtime)")
    return info


def getCpuCoreNum():
    if _loaded:
        num = _lib.srq_get_cpu_core_num()
        if num > 0:
            return num
    return os.cpu_count() or 4


def getGpuCoreNum():
    if _loaded:
        return _lib.srq_get_gpu_core_num()
    return 0


def getLastError():
    if _loaded:
        return (_lib.srq_get_last_error() or b"").decode("utf-8", "ignore")
    return _loadError


def GetModelId(model):
    """ 模型名或编号 -> 编号 """
    if isinstance(model, int):
        return model
    return _modelIdByName.get(str(model), -1)


def GetModelInfo(modelId):
    """ 返回 (文件, 倍数, 降噪, tile)，无效返回 None """
    if _lib is None:
        return None
    try:
        raw = _lib.srq_model_info(int(modelId))
        if not raw:
            return None
        parts = raw.decode("utf-8", "ignore").split("|")
        if len(parts) < 4:
            return None
        return parts[0], int(parts[1]), int(parts[2]), int(parts[3])
    except Exception:
        return None


def CountAvailableModels():
    """ 统计 models 目录里真实存在的 onnx 数量 """
    if _lib is None:
        return 0
    modelDir = os.environ.get("JM_SR_MODELS") or platform_mobile.GetAndroidModelDir()
    files = set()
    for modelId in _modelNameById.keys():
        info = GetModelInfo(modelId)
        if info and os.path.exists(os.path.join(modelDir, info[0])):
            files.add(info[0])
    return len(files)


def GetModelName(modelId):
    return _modelNameById.get(modelId, "")


def _DecodeImage(imgData):
    """ 用 Qt 解码任意格式(jpg/png/webp/gif/bmp/apng) """
    from PySide6.QtGui import QImage
    image = QImage.fromData(imgData)
    if image.isNull():
        return None
    if image.hasAlphaChannel():
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        channels = 4
    else:
        image = image.convertToFormat(QImage.Format.Format_RGB888)
        channels = 3
    stride = image.bytesPerLine()
    buf = bytes(image.constBits())
    _dummyKeepAlive.append(buf)
    if len(_dummyKeepAlive) > 8:
        _dummyKeepAlive.pop(0)
    return image.width(), image.height(), stride, channels, buf


def _EncodeImage(raw, width, height, stride, format):
    """ 用 Qt 编码回 jpg/png/webp """
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage
    image = QImage(raw, width, height, stride, QImage.Format.Format_RGB888)
    if image.isNull():
        return None
    fmt = (format or "jpg").upper()
    if fmt in ("JPG", "JPEG"):
        fmt = "JPG"
    elif fmt == "PNG":
        fmt = "PNG"
    elif fmt == "WEBP":
        fmt = "WEBP"
    else:
        fmt = "JPG"
    byteArray = QByteArray()
    buffer = QBuffer(byteArray)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = image.save(buffer, fmt, 95)
    buffer.close()
    if not ok:
        return None
    return bytes(byteArray)


def add(imgData, model, taskId, scaleOrW=0, h=0, format="jpg", tileSize=0):
    """ 添加超分任务

    与 sr_vulkan 调用方式一致：
        scale<=0 时第 4/5 个参数是目标宽高(width/high)，否则第 4 个参数是放大倍数
    返回 >0 表示成功(任务号)，<=0 表示失败
    """
    if not _loaded and not LoadEngine():
        return -1
    try:
        modelId = GetModelId(model)
        if modelId < 0:
            Log.Warn("sr_qnn unknown model: {}".format(str(model)))
            return -2
        decoded = _DecodeImage(imgData)
        if decoded is None:
            Log.Warn("sr_qnn decode image failed")
            return -3
        width, height, stride, channels, buf = decoded
        targetW = 0
        targetH = 0
        scale = float(scaleOrW or 0)
        if float(h or 0) > 0:
            # 目标宽高模式：sr_vulkan 用 width/high 表示目标尺寸
            targetW = int(scaleOrW or 0)
            targetH = int(h or 0)
            scale = 0
        cbuf = ctypes.cast(ctypes.c_char_p(buf), ctypes.POINTER(ctypes.c_ubyte))
        stat = _lib.srq_add(cbuf, int(width), int(height), int(stride), int(channels),
                            int(modelId), int(taskId), ctypes.c_double(scale),
                            int(targetW), int(targetH),
                            str(format or "jpg").encode("utf-8"), int(tileSize or 0))
        return stat
    except Exception as es:
        Log.Error(es)
        return -4


def load(waitMs=0):
    """ 阻塞等待一个超分结果

    返回 (data, format, taskId, tick)；失败或没有结果返回 None
    """
    if not _loaded:
        return None
    try:
        result = SrqResult()
        ctypes.memset(ctypes.byref(result), 0, ctypes.sizeof(result))
        got = _lib.srq_load(int(waitMs or 0), ctypes.byref(result))
        if got <= 0:
            return None
        format = (result.format or b"jpg").decode("utf-8", "ignore") or "jpg"
        taskId = int(result.taskId)
        tick = float(result.tick)
        if result.status < 0 or not result.data:
            _lib.srq_free_result(ctypes.byref(result))
            return None, format, taskId, tick
        raw = ctypes.string_at(result.data, result.stride * result.height)
        width = int(result.width)
        height = int(result.height)
        stride = int(result.stride)
        _lib.srq_free_result(ctypes.byref(result))
        data = _EncodeImage(raw, width, height, stride, format)
        return data, format, taskId, tick
    except Exception as es:
        Log.Error(es)
        return None


def _MakeIdArray(taskIds):
    ids = [int(v) for v in (taskIds or [])]
    if not ids:
        return None, 0
    array = (ctypes.c_int * len(ids))()
    for index, value in enumerate(ids):
        array[index] = value
    return array, len(ids)


def remove(taskIds):
    if not _loaded:
        return
    array, count = _MakeIdArray(taskIds)
    if count:
        _lib.srq_remove(array, count)
    return


def removeWaitProc(taskIds):
    if not _loaded:
        return
    array, count = _MakeIdArray(taskIds)
    if count:
        _lib.srq_remove_wait(array, count)
    return


def stop():
    if not _loaded:
        return
    try:
        _lib.srq_stop()
    except Exception as es:
        Log.Error(es)
    return


def GetModelList():
    """ 当前 models.txt 里的模型名列表 """
    return list(_modelIdByName.keys())
