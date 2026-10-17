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
import select
import struct
import subprocess
import threading
import time
from collections import deque

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
ProcName = "libsr_qnn_proc.so"
Version = "sr_qnn 1.4.1 (ONNX Runtime QNN/HTP)"
# QNN 后端库(位于 libsr_qnn.so 同目录，由 onnxruntime-android-qnn 提供)
QnnBackendLib = "libQnnHtp.so"

_lib = None
_proc = None            # _ProcEngine 实例(进程模式)；None = 未启用/失败走 ctypes
_procFailed = False
_procError = ""         # 进程模式失败的具体原因(自检会打印)
_lock = threading.Lock()
_loaded = False
_loadError = ""
_modelIdByName = {}
_modelNameById = {}
_modelInfoById = {}
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
    return _SearchFile(LibName)


def _SearchFile(name):
    envKey = "JM_SR_QNN_PROC" if name == ProcName else "JM_SR_QNN_LIB"
    envLib = os.environ.get(envKey)
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
        path = os.path.join(d, name)
        if os.path.exists(path):
            return path
    return ""


# libsr_qnn.so 的依赖：必须先以 RTLD_GLOBAL 加载，否则 DT_NEEDED 解析不到
# (Android 的 linker 不认 LD_LIBRARY_PATH，靠调用方所在目录/已加载符号)
DependLibs = ("libc++_shared.so", "libonnxruntime.so")


class _ProcEngine(object):
    """ 进程模式引擎：把超分跑在独立的 native 进程里。

    为什么(真机 SM8750/vivo 已验证)：QNN HTP 需要厂商库 libcdsprpc.so(FastRPC)。
    App 进程的链接器命名空间只能加载 nativeLibraryDir + public.libraries.txt 列出的库，
    该机型不列 libcdsprpc.so → HTP 永远起不来，QNN 0 分区，超分退化纯 CPU(~400ms/块)。
    独立 native 进程没有这个限制(LD_LIBRARY_PATH 生效)，直接用 /vendor/lib64 里设备
    自带的那份 —— local-dream 等项目的通行做法。详见 sr_qnn_proc.cpp 头注释。

    add()/load() 语义与 ctypes 模式一致：add 入队，load 顺序取结果；remove 只对
    尚未发送的任务生效(已在跑的那张图会算完，结果被丢弃)。
    """

    def __init__(self, exePath, modelDir, logPath, argv=None):
        self.exePath = exePath
        self.argv = argv or [exePath]
        self.modelDir = modelDir
        self.logPath = logPath
        self.proc = None
        self.logFile = None
        self.logStart = 0
        self.ioLock = threading.Lock()
        self.queue = deque()          # 待发送任务
        self.cancelled = set()
        self.dead = False
        self.lastError = ""
        self.version = ""
        self.backend = ""
        self.htp = 0
        self.htpError = ""
        self.cpuCores = 0

    # ------------------------------------------------ 底层帧读写
    def _WriteAll(self, data):
        fd = self.proc.stdin.fileno()
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            if n <= 0:
                raise IOError("write failed")
            view = view[n:]
        return

    def _ReadExact(self, size, timeout=None):
        fd = self.proc.stdout.fileno()
        out = b""
        deadline = (time.time() + timeout) if timeout else None
        while len(out) < size:
            if deadline is not None:
                remain = deadline - time.time()
                if remain <= 0:
                    raise TimeoutError("proc response timeout")
                r, _, _ = select.select([fd], [], [], min(remain, 0.5))
                if not r:
                    continue
            chunk = os.read(fd, size - len(out))
            if not chunk:
                raise IOError("proc exited")
            out += chunk
        return out

    @staticmethod
    def _PackHead(*values):
        return struct.pack(*values)

    def _SendAdd(self, spec, pixels):
        # 与 C++ HandleAdd 的字段顺序严格一致；format 定长 16 字节补零
        fmt = str(spec["format"] or "jpg").encode("utf-8")[:15]
        head = struct.pack(
            "<Iiidiiiiii16si",
            2,                                                    # cmd
            int(spec["taskId"]), int(spec["modelId"]),
            float(spec["scale"]),
            int(spec["targetW"]), int(spec["targetH"]),
            int(spec["width"]), int(spec["height"]),
            int(spec["stride"]), int(spec["channels"]),
            fmt.ljust(16, b"\0"),
            int(spec["tile"] or 0))
        self._WriteAll(head + struct.pack("<I", len(pixels)) + pixels)
        return

    def _RecvResult(self):
        # 头 = cmd(4) taskId(4) status(4) tick(8) outW(4) outH(4) outStride(4) format(16) = 48
        fixed = self._ReadExact(48)
        (cmd, taskId, status) = struct.unpack("<Iii", fixed[:12])
        (tick, ) = struct.unpack("<d", fixed[12:20])
        (outW, outH, outStride) = struct.unpack("<iii", fixed[20:32])
        outFormat = fixed[32:48].split(b"\0")[0].decode("utf-8", "ignore") or "jpg"
        errLen = struct.unpack("<I", self._ReadExact(4))[0]
        err = self._ReadExact(errLen).decode("utf-8", "ignore") if errLen else ""
        pixLen = struct.unpack("<I", self._ReadExact(4))[0]
        pixels = self._ReadExact(pixLen) if pixLen else b""
        return {"taskId": taskId, "status": status, "tick": tick,
                "width": outW, "height": outH, "stride": outStride,
                "format": outFormat, "err": err, "pixels": pixels}

    # ------------------------------------------------ 生命周期
    def _BuildEnv(self):
        libDir = os.path.dirname(os.path.abspath(self.exePath))
        _PrepareQnnEnv(libDir)
        env = dict(os.environ)
        env["JM_SR_MODELS"] = self.modelDir or env.get("JM_SR_MODELS", "")
        ld = env.get("LD_LIBRARY_PATH", "")
        items = [v for v in ld.split(":") if v]
        if libDir not in items:
            items.insert(0, libDir)
        # 独立进程可以读 /vendor —— 设备自带的 libcdsprpc.so(FastRPC)就在这里
        for extra in ("/vendor/lib64", "/odm/lib64", "/system/lib64"):
            if extra not in items:
                items.append(extra)
        env["LD_LIBRARY_PATH"] = ":".join(items)
        if _debug:
            env["JM_QNN_DEBUG"] = "1"
        return env

    def _ReadInfoFrame(self, status):
        """ 读 hello / info 共用的信息帧(字段顺序完全一致，info 的 modelCount=0) """
        self.version = self._ReadExact(64).split(b"\0")[0].decode("utf-8", "ignore")
        self.backend = self._ReadExact(160).split(b"\0")[0].decode("utf-8", "ignore")
        (self.htp, ) = struct.unpack("<i", self._ReadExact(4))
        self.htpError = self._ReadExact(256).split(b"\0")[0].decode("utf-8", "ignore")
        (self.cpuCores, ) = struct.unpack("<i", self._ReadExact(4))
        (count, ) = struct.unpack("<i", self._ReadExact(4))
        for _ in range(count):
            (mid, ) = struct.unpack("<i", self._ReadExact(4))
            # 注意：C++ 侧字符串长度是 u32(见 PutBlob)，这里必须读 4 字节
            nlen = struct.unpack("<I", self._ReadExact(4))[0]
            name = self._ReadExact(nlen).decode("utf-8", "ignore")
            flen = struct.unpack("<I", self._ReadExact(4))[0]
            fname = self._ReadExact(flen).decode("utf-8", "ignore")
            scale, denoise, tile = struct.unpack("<iii", self._ReadExact(12))
            _modelIdByName[name] = mid
            _modelNameById[mid] = name
            _modelInfoById[mid] = (fname, scale, denoise, tile)
            globals()["MODEL_" + name] = mid
        errLen = struct.unpack("<I", self._ReadExact(4))[0]
        return self._ReadExact(errLen).decode("utf-8", "ignore") if errLen else ""

    def Info(self):
        """ 再问一次状态：hello 的快照是建会话之前的，推理后后端/HTP 会变 """
        if self.dead or self.proc is None:
            return False
        try:
            with self.ioLock:
                self._WriteAll(struct.pack("<I", 4))
                (cmd, status) = struct.unpack("<Ii", self._ReadExact(8, timeout=30))
                if cmd != 4:
                    raise IOError("bad info cmd {}".format(cmd))
                self._ReadInfoFrame(status)
            return True
        except Exception as es:
            self.lastError = "info 失败: {}".format(es)
            Log.Warn(self.lastError)
            return False

    def Start(self):
        try:
            self.logFile = open(self.logPath, "ab")
            try:
                self.logStart = self.logFile.tell()
            except Exception:
                self.logStart = 0
            env = self._BuildEnv()
            # close_fds=False 让 CPython 走 posix_spawn（vfork+exec）而不是 fork：
            # App 进程里 Qt 已开了一堆线程，fork 出子进程再 exec 是最容易出事的路径。
            self.proc = subprocess.Popen(
                list(self.argv), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.logFile, env=env, close_fds=False)
        except Exception as es:
            self.lastError = "spawn 失败({}): {}".format(" ".join(self.argv), es)
            Log.Error(self.lastError)
            return False
        # hello(帧结构固定，即使 init 失败也要把整帧读完，否则流会错位)
        try:
            with self.ioLock:
                self._WriteAll(struct.pack("<I", 1))
                (cmd, status) = struct.unpack("<Ii", self._ReadExact(8, timeout=60))
                if cmd != 1:
                    raise IOError("bad hello cmd {}".format(cmd))
                initErr = self._ReadInfoFrame(status)
            if status < 0:
                raise IOError("srq_init failed {}: {}".format(status, initErr))
            return True
        except Exception as es:
            self.lastError = "hello 失败: {}{}".format(es, self._CollectFailure("hello"))
            Log.Error(self.lastError)
            self.Kill()
            return False

    def _CollectFailure(self, stage):
        """ 子进程没起来时收集：退出码 + 它这次写下的日志尾巴(定位是 exec 失败还是崩在引擎里) """
        rc = "?"
        try:
            if self.proc is not None:
                rc = self.proc.poll()
                if rc is None:
                    rc = self.proc.wait(timeout=2)
        except Exception:
            pass
        lines = []
        try:
            if self.logFile is not None:
                self.logFile.flush()
            with open(self.logPath, "rb") as f:
                f.seek(self.logStart)
                data = f.read()[-2000:]
            lines = [ln.strip() for ln in data.decode("utf-8", "replace").splitlines() if ln.strip()]
        except Exception:
            pass
        # 完整细节落盘，报告里只放最有信息量的一行(受 180 字符限制)
        try:
            with open(os.path.join(os.path.dirname(self.logPath) or ".", "sr_proc_fail.txt"),
                      "w", encoding="utf-8", errors="replace") as fp:
                fp.write("{}\nrc={}\n".format(stage, rc))
                fp.write("\n".join(lines[-30:]))
        except Exception:
            pass
        if lines:
            # 链接器/加载器报错里前缀是路径，真正有用的是 ": " 之后；但也可能整行都有用，
            # 所以不再裁剪前缀，而是把整行放在最前面(后面按长度兜底截断)。
            for ln in reversed(lines):
                if ("CANNOT LINK" in ln) or ("cannot locate symbol" in ln) or ("dlopen failed" in ln):
                    return " (rc={} | {})".format(rc, ln[:300])
            return " (rc={} | {})".format(rc, lines[-1][:300])
        return " (rc={} | 子进程没写任何日志 → 死在 exec/动态链接阶段)".format(rc)

    def Kill(self):
        self.dead = True
        try:
            if self.proc is not None:
                try:
                    self.proc.stdin.close()
                except Exception:
                    pass
                try:
                    self.proc.terminate()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if self.logFile is not None:
                self.logFile.close()
        except Exception:
            pass
        return

    # ------------------------------------------------ 对外 API
    def Add(self, spec, pixels):
        with self.ioLock:
            self.queue.append((spec, pixels))
        return 1

    def Load(self, waitMs):
        deadline = time.time() + (max(0, int(waitMs)) / 1000.0) if waitMs and waitMs > 0 else None
        while True:
            item = None
            with self.ioLock:
                while self.queue:
                    spec, pixels = self.queue.popleft()
                    if int(spec["taskId"]) not in self.cancelled:
                        item = (spec, pixels)
                        break
                if item is None:
                    self.cancelled.clear()
            if item is None:
                if deadline is not None and time.time() >= deadline:
                    return None
                if deadline is None:
                    # 引擎语义：add 过的任务一定有结果；没任务时短暂等待
                    time.sleep(0.02)
                    continue
                time.sleep(0.01)
                continue
            spec, pixels = item
            try:
                with self.ioLock:
                    self._SendAdd(spec, pixels)
                    res = self._RecvResult()
            except Exception as es:
                self.lastError = "proc IO 异常: {}".format(es)
                Log.Error(self.lastError)
                self.Kill()
                return {"taskId": spec["taskId"], "status": -100, "tick": 0.0,
                        "width": 0, "height": 0, "stride": 0, "format": spec.get("format") or "jpg",
                        "err": self.lastError, "pixels": b""}
            return res

    def Remove(self, taskIds):
        with self.ioLock:
            for tid in (taskIds or []):
                self.cancelled.add(int(tid))
        return

    def Stop(self):
        try:
            with self.ioLock:
                if self.proc is not None and not self.dead:
                    self._WriteAll(struct.pack("<I", 3))
        except Exception:
            pass
        # 等它自己退出：ORT 是在 srq_stop() 里才把 profile/json 落盘的，
        # 发完停止指令立刻 terminate 会把文件丢掉(真机上表现为 profile providers: 无)。
        try:
            if self.proc is not None and not self.dead:
                self.proc.wait(timeout=8)
        except Exception:
            pass
        self.Kill()
        return


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

    lib.srq_get_htp_error.restype = ctypes.c_char_p
    lib.srq_get_htp_error.argtypes = []

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


def GetProcError():
    """ 进程模式失败原因(自检用) """
    return _procError


def _StartProcEngine(modelDir):
    """ 尝试启动进程模式引擎(优先路径)；失败返回 None，调用方再走 ctypes 兜底

    exec 有两条路：
      1. 直接执行 nativeLibraryDir 里的 libsr_qnn_proc.so（安装器解压后应为 0755；
         部分机型/打包方式会退化成 0644 → EACCES）；
      2. 用 /system/bin/linker64 <elf> 加载 —— linker 只要有读权限即可跑，
         不依赖文件的可执行位。两条路的链接器命名空间都是 default，
         dlopen("libcdsprpc.so") 因此能找到 /vendor/lib64 里的厂商库。
    """
    global _procFailed, _procError
    if os.environ.get("JM_SR_PROC", "1") == "0":
        return None
    exe = _SearchFile(ProcName)
    if not exe or not os.path.exists(exe):
        _procError = "找不到 {} (native 库目录: {})".format(ProcName, platform_mobile.GetNativeLibDirs())
        Log.Warn(_procError)
        return None
    try:
        os.makedirs(modelDir, exist_ok=True)
        # 子进程日志单独一个文件：与 App 进程的 sr_native.log 分开，
        # 否则两边的输出交织在一起，失败原因会被误判(踩过)。
        logPath = os.environ.get("JM_SR_PROC_LOG") or os.path.join(
            platform_mobile.GetAppDataDir(), "sr_proc.log")
        try:
            canExec = bool(os.access(exe, os.X_OK))
            mode = oct(os.stat(exe).st_mode & 0o777)
        except Exception:
            canExec, mode = False, "?"
        # 万一安装时没给可执行位，先试着补上(只读分区会失败，忽略)
        if not canExec:
            try:
                os.chmod(exe, 0o755)
                canExec = bool(os.access(exe, os.X_OK))
            except Exception:
                pass
        attempts = []
        if canExec:
            attempts.append([exe])
        linker = "/system/bin/linker64"
        if os.path.exists(linker):
            attempts.append([linker, exe])
        if not attempts:
            attempts.append([exe])
        errors = []
        for argv in attempts:
            proc = _ProcEngine(exe, modelDir, logPath, argv=argv)
            if proc.Start():
                _procError = ""
                return proc
            errors.append("{} -> {}".format(os.path.basename(argv[0]), proc.lastError))
            proc.Kill()
        _procError = "exe=...{} mode={} X_OK={} | {}".format(
            exe[-24:], mode, canExec, " ; ".join(errors))
        Log.Error("进程模式启动失败: " + _procError)
    except Exception as es:
        _procError = "异常: {}".format(es)
        Log.Error("进程模式启动失败: " + _procError)
    _procFailed = True
    return None


def LoadEngine(modelDir=None):
    """ 加载引擎并初始化(失败返回 False，不抛异常)

    优先进程模式(QNN HTP 的 FastRPC 只有子进程能拿到)，失败再回退 ctypes。
    """
    global _lib, _proc, _loaded, _loadError
    with _lock:
        if _loaded:
            return True
        if _lib is not None or _proc is not None:
            return False
        if modelDir is None:
            modelDir = platform_mobile.GetAndroidModelDir()
        proc = _StartProcEngine(modelDir)
        if proc is not None:
            if CountAvailableModels() > 0:
                _proc = proc
                _loaded = True
                Log.Warn("sr_qnn loaded(进程模式): {}, models:{}/{}, htp:{}, backend:{}".format(
                    proc.exePath, CountAvailableModels(), len(_modelIdByName),
                    proc.htp, proc.backend))
                return True
            _loadError = "未找到任何 ONNX 模型，请把模型放到 {}".format(modelDir)
            Log.Warn(_loadError)
            proc.Kill()
            return False
        # ---- ctypes 兜底(进程模式不可用时；此时 QNN HTP 多半起不来，走 CPU EP) ----
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
            Log.Warn("sr_qnn loaded(ctypes): {}, models:{}/{}, htp:{}, backend:{}".format(
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


def IsProcMode():
    """ 当前是否跑在独立进程里(QNN HTP 能拿到厂商 FastRPC 库的唯一途径) """
    return _proc is not None


def GetLoadError():
    return _loadError


def HasHtp():
    """ 设备是否具备高通 NPU(HTP) """
    if not _loaded:
        return False
    if _proc is not None:
        return _proc.htp > 0
    try:
        return _lib.srq_has_htp() > 0
    except Exception:
        return False


def GetBackendInfo():
    if not _loaded:
        return ""
    if _proc is not None:
        return _proc.backend
    try:
        return (_lib.srq_get_backend_info() or b"").decode("utf-8", "ignore")
    except Exception:
        return ""


def RefreshStatus():
    """ 重新向子进程查询后端/HTP 状态

    进程模式下 hello 拿到的是"建会话之前"的快照(那时一定是 QNN 未生效)，
    状态要在真正跑过推理之后再问一次才准确。
    """
    if _proc is not None:
        return _proc.Info()
    return False


# ---------------------------------------------------------------- 兼容接口
def init():
    """ 与 sr_vulkan 一致：>=0 表示成功 """
    if not _loaded and not LoadEngine():
        return -1
    return 0


def initSet(device=0, threads=0):
    if not _loaded:
        return -1
    if _proc is not None:
        # 进程模式：线程数在子进程 spawn 时定好(引擎自动)，运行时不再改
        return 0
    stat = _lib.srq_init_set(int(device or 0), int(threads or 0))
    return stat


def setDebug(enable=True):
    global _debug
    _debug = bool(enable)
    if _loaded and _proc is None:
        _lib.srq_set_debug(1 if enable else 0)
    return


def getVersion():
    if _loaded and _proc is not None:
        return _proc.version or Version
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
    if _loaded and _proc is not None and _proc.cpuCores > 0:
        return _proc.cpuCores
    if _loaded and _proc is None:
        num = _lib.srq_get_cpu_core_num()
        if num > 0:
            return num
    return os.cpu_count() or 4


def getGpuCoreNum():
    if _loaded and _proc is None:
        return _lib.srq_get_gpu_core_num()
    return 0


def getLastError():
    if _loaded and _proc is not None:
        return _proc.lastError
    if _loaded:
        return (_lib.srq_get_last_error() or b"").decode("utf-8", "ignore")
    return _loadError


def getHtpError():
    """ 第一次严格 HTP 失败的原始报错（QNN 一个节点都不接时的真正原因） """
    if _loaded and _proc is not None:
        return _proc.htpError
    if _loaded:
        try:
            return (_lib.srq_get_htp_error() or b"").decode("utf-8", "ignore")
        except Exception:
            return ""
    return ""


def GetModelId(model):
    """ 模型名或编号 -> 编号 """
    if isinstance(model, int):
        return model
    return _modelIdByName.get(str(model), -1)


def GetModelInfo(modelId):
    """ 返回 (文件, 倍数, 降噪, tile)，无效返回 None """
    # 没有 ctypes 库时以进程/表里的信息为准(引擎启动过程中 _proc 尚未赋值也要能查)
    if _lib is None:
        return _modelInfoById.get(int(modelId))
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
    if _lib is None and not _modelInfoById:
        return 0
    modelDir = os.environ.get("JM_SR_MODELS") or platform_mobile.GetAndroidModelDir()
    files = set()
    if _lib is None:
        for modelId, info in _modelInfoById.items():
            if info and info[0] and os.path.exists(os.path.join(modelDir, info[0])):
                files.add(info[0])
        return len(files)
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
        if _proc is not None:
            spec = {"taskId": int(taskId), "modelId": modelId, "scale": scale,
                    "targetW": targetW, "targetH": targetH, "width": width, "height": height,
                    "stride": stride, "channels": channels, "format": format, "tile": int(tileSize or 0)}
            _proc.Add(spec, buf)
            return 1
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
        if _proc is not None:
            res = _proc.Load(waitMs)
            if res is None:
                return None
            taskId = int(res["taskId"])
            tick = float(res["tick"])
            format = res["format"] or "jpg"
            if res["status"] < 0:
                # lastError 语义：最近一次任务的错误(成功则清零)，
                # 便于上层区分"这次为什么没有结果"(如模型文件缺失)而不是
                # 只能看到空结果、也读不到很久以前的陈旧错误
                _proc.lastError = res.get("err") or ""
                if _proc.lastError:
                    Log.Warn("sr_qnn task {}: {}".format(taskId, _proc.lastError))
                return None, format, taskId, tick
            _proc.lastError = ""
            data = _EncodeImage(res["pixels"], res["width"], res["height"], res["stride"], format)
            return data, format, taskId, tick
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
    if _proc is not None:
        _proc.Remove(taskIds)
        return
    array, count = _MakeIdArray(taskIds)
    if count:
        _lib.srq_remove(array, count)
    return


def removeWaitProc(taskIds):
    if not _loaded:
        return
    if _proc is not None:
        _proc.Remove(taskIds)
        return
    array, count = _MakeIdArray(taskIds)
    if count:
        _lib.srq_remove_wait(array, count)
    return


def stop():
    if not _loaded:
        return
    try:
        if _proc is not None:
            _proc.Stop()
        else:
            _lib.srq_stop()
    except Exception as es:
        Log.Error(es)
    return


def Reinit(modelDir=None):
    """ 诊断用：按当前环境变量重新初始化引擎

    进程模式下 JM_SR_PROFILE / JM_QNN_DEBUG 之类的开关只能在子进程 spawn 时生效，
    所以自检要拿到逐节点 profile 时必须重启子进程。
    """
    global _proc, _lib, _loaded
    try:
        stop()
    except Exception:
        pass
    _proc = None
    _lib = None
    _loaded = False
    return LoadEngine(modelDir)


def GetModelList():
    """ 当前 models.txt 里的模型名列表 """
    return list(_modelIdByName.keys())
