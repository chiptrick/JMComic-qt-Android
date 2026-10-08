# coding:utf-8
"""JMComic Android 入口

pyside6-android-deploy 要求入口文件名为 main.py，打包时本文件位于 APK 的
assets 根目录，业务代码在 app_src/(构建脚本从 ../src 复制)或 ../src(本地调试)。

启动顺序很关键：
    1. 调整 sys.path(业务源码 + sr_qnn 后端 + 可选的依赖垫片)
    2. 创建 QApplication(QStandardPaths 需要)
    3. platform_mobile.InitAndroidEnv()：把配置/数据/缓存/日志重定向到应用私有目录
    4. sr_backend.InstallQnnCompat()：把 sr_qnn 注册为 sr_vulkan 兼容模块
    5. start.Run(app)：走与桌面端相同的主流程(自动跳过单实例/系统托盘等桌面特性)
"""
import os
import sys
import traceback

APP_ROOT = os.path.dirname(os.path.abspath(__file__))


def SetupPath():
    """ 组装 sys.path：业务源码 / NPU 后端 / 依赖垫片 """
    candidates = [
        os.path.join(APP_ROOT, "app_src"),   # 打包时的业务源码
        os.path.join(APP_ROOT, "..", "src"),  # 本地调试
        APP_ROOT,                            # sr_qnn 包
    ]
    for path in candidates:
        path = os.path.abspath(path)
        if os.path.isdir(path) and path not in sys.path:
            sys.path.append(path)
    if APP_ROOT not in sys.path:
        sys.path.append(APP_ROOT)

    # curl_cffi 在没有编出原生扩展时用纯 python 垫片(见 android/shims 说明)
    try:
        import curl_cffi  # noqa: F401  仅探测是否可用
    except Exception:
        shimDir = os.path.join(APP_ROOT, "shims")
        if os.path.isdir(shimDir) and shimDir not in sys.path:
            sys.path.append(shimDir)

    # 必须尽早执行：p4a 把标准库 ctypes/util.py 补丁成
    # `from android._ctypes_library_finder import find_library`，而 p4a 的 android 包在
    # bootstrap=qt 下必然导入失败(见 platform_mobile.InstallCtypesLibraryFinder 的注释)。
    # 不修的话 pycryptodome 导入不了 AES，jmcomic 一个接口都解析不了。
    try:
        from tools import platform_mobile
        platform_mobile.InstallCtypesLibraryFinder()
    except Exception:
        pass
    return


def WriteCrashLog(text):
    """ 启动阶段就崩溃时，把堆栈写到应用私有目录，方便 adb 拉取 """
    try:
        from PySide6.QtCore import QStandardPaths
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        if not base:
            base = os.environ.get("ANDROID_PRIVATE", APP_ROOT)
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "crash.log"), "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass
    try:
        print(text)
    except Exception:
        pass
    return


def _CopyFromAssets(target):
    """ 从 APK assets 里复制 models/（private.tar 没带模型时的兜底）

    Android 上 APK 的 assets 只能用 Qt 的 assets: 文件引擎或 Java AssetManager 读，
    原生 fopen 打不开，所以这里用 QFile 逐个拷贝。
    """
    from PySide6.QtCore import QDir, QFile, QIODevice
    src = QDir("assets:/models")
    if not src.exists():
        return 0
    names = [str(name) for name in src.entryList(QDir.Filter.Files)]
    count = 0
    for name in names:
        if not name.endswith((".onnx", ".bin", ".txt")):
            continue
        data = QFile("assets:/models/" + name)
        if not data.open(QIODevice.OpenModeFlag.ReadOnly):
            continue
        buf = data.readAll()
        data.close()
        out = QFile(os.path.join(target, name))
        if not out.open(QIODevice.OpenModeFlag.WriteOnly):
            continue
        out.write(buf)
        out.close()
        count += 1
    return count


def _HasModels(path):
    """ 目录里同时有 models.txt 和至少一个 .onnx 才算可用 """
    try:
        if not path or not os.path.isdir(path):
            return False
        names = os.listdir(path)
        return ("models.txt" in names) and any(n.endswith(".onnx") for n in names)
    except Exception:
        return False


def EnsureModels():
    """ 让 sr_qnn 能读到 waifu2x 模型

    模型随 APK 的 private.tar 分发(p4a 解包到 APP_ROOT/sr_qnn/models/)，所以：
        1. 优先**原地使用**解包出来的目录 —— 不复制、不占双份磁盘、启动更快
        2. 该目录不可用时才复制到可写的 JM_SR_MODELS 目录
           (必须用 copyfile：shutil.copy2 的 copystat 会调 chmod/utime，在 Android 上
            抛 PermissionError，真机实测导致循环中断、只拷了第一个文件)
        3. 都没有时退回 APK assets
    """
    try:
        from tools import platform_mobile
        target = platform_mobile.GetAndroidModelDir()
        if _HasModels(target):
            return
        extracted = os.path.join(APP_ROOT, "sr_qnn", "models")
        if _HasModels(extracted):
            # 就地使用：sr_qnn 通过 platform_mobile.GetAndroidModelDir() 读这个环境变量
            os.environ["JM_SR_MODELS"] = extracted
            WriteDiag("models in place: {}".format(extracted))
            return
        sources = [
            extracted,
            os.path.join(os.environ.get("ANDROID_ARGUMENT", ""), "models"),
            os.path.join(APP_ROOT, "models"),
        ]
        src = ""
        for path in sources:
            if _HasModels(path):
                src = path
                break
        os.makedirs(target, exist_ok=True)
        copied = 0
        if src:
            import shutil
            for name in os.listdir(src):
                if not name.endswith((".onnx", ".bin", ".txt")):
                    continue
                try:
                    shutil.copyfile(os.path.join(src, name), os.path.join(target, name))
                    copied += 1
                except OSError as es:
                    WriteDiag("copy {} failed: {}".format(name, es))
            WriteDiag("models copied: {} -> {} ({} files)".format(src, target, copied))
        if not _HasModels(target):
            copied = _CopyFromAssets(target)
            WriteDiag("models from APK assets: {} files -> {}".format(copied, target))
        if not _HasModels(target):
            WriteDiag("EnsureModels: 没有可用的模型! 查找过: {} , assets:/models".format(sources))
    except Exception as es:
        WriteDiag("EnsureModels failed: {}".format(es))
    return


def WriteDiag(text):
    """ 追加一行诊断信息到 <AppDataDir>/android_startup.log

    超分后端在 Log.Init() 之前就初始化了，那时 logging 还没有 handler，
    所有 Log.Warn 都会被丢弃 —— 真机排查只能靠这个文件。
    """
    try:
        from PySide6.QtCore import QStandardPaths
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        if not base:
            base = os.environ.get("ANDROID_PRIVATE", APP_ROOT)
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "android_startup.log"), "a", encoding="utf-8") as f:
            f.write("{}\n".format(text))
    except Exception:
        pass
    try:
        print(text)
    except Exception:
        pass
    return


def _SrSelfTest():
    """ 真跑一次超分，回报**最终实际使用的执行后端**

    启动自检发生在任何推理之前，那时 C++ 里的 g_htpEnabled 还是 false，
    backend 会显示 "CPU (ONNX Runtime, QNN 未生效)" —— 这只说明"还没建会话"，
    不代表 NPU 有问题。要证明 HTP 真能用，必须实跑一次。

    默认不执行(会占用启动时间)；验证时用
        adb shell run-as <包名> touch files/sr_selftest
    创建标记文件即可打开。
    """
    out = ["sr selftest: ---- 真实推理自检 ----"]
    # QNN EP 建会话失败的真正原因只有 C++ 侧的 printf 知道，而 Android 应用进程的
    # stdout 默认被丢弃。这里把 fd 1/2 临时重定向到文件，并打开引擎 debug 开关，
    # 就能把 native 侧（含 ONNX Runtime / QNN 的报错）完整落到 sr_native.log。
    nativeFd = {}
    nativeFile = None
    try:
        from tools import platform_mobile
        base = platform_mobile.GetAppDataDir()
    except Exception:
        base = os.environ.get("ANDROID_PRIVATE", APP_ROOT)
    nativePath = os.path.join(base, "sr_native.log")
    try:
        import sr_qnn
        sr_qnn.setDebug(True)
        nativeFile = open(nativePath, "w", buffering=1, encoding="utf-8", errors="replace")
        nativeFd[1] = os.dup(1)
        nativeFd[2] = os.dup(2)
        os.dup2(nativeFile.fileno(), 1)
        os.dup2(nativeFile.fileno(), 2)
        out.append("  native 日志: {}".format(nativePath))
    except Exception as es:
        out.append("  native 日志重定向失败: {}".format(es))
    try:
        import sr_qnn
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QImage
        from tools import sr_backend
        modelId = sr_qnn.GetModelId("WAIFU2X_CUNET_UP2X_DENOISE3X")
        out.append("  engine qnn: {}  model id: {}".format(sr_backend.IsQnn(), modelId))
        size = 64
        raw = bytearray()
        for y in range(size):
            for x in range(size):
                raw += bytes(((x * 4) & 0xFF, (y * 4) & 0xFF, 128))
        img = QImage(bytes(raw), size, size, size * 3, QImage.Format.Format_RGB888)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        taskId = sr_qnn.add(bytes(ba), modelId, 901, 2.0, format="png")
        out.append("  add -> {}".format(taskId))
        if taskId <= 0:
            out.append("  selftest: FAIL (add 被拒: {})".format(sr_qnn.getLastError()))
            return out
        result = sr_qnn.load(120000)
        if not result or not result[0]:
            out.append("  selftest: FAIL (load 无结果: {})".format(sr_qnn.getLastError()))
            return out
        data, _fmt, _backId, tick = result
        got = QImage.fromData(data)
        ok = (got.width() == size * 2 and got.height() == size * 2)
        out.append("  输出 {}x{} (期望 {}x{}), 耗时 {:.3f}s".format(
            got.width(), got.height(), size * 2, size * 2, tick))
        out.append("  HTP 能力: {}".format(sr_qnn.HasHtp()))
        out.append("  实际后端: {}".format(sr_qnn.GetBackendInfo()))
        out.append("  引擎错误: {}".format(sr_qnn.getLastError()))
        out.append("  selftest: {}".format("PASS" if ok else "FAIL(尺寸不符)"))
    except Exception as es:
        out.append("  selftest: FAIL (异常 {})".format(es))
    finally:
        # C 的 stdio 是块缓冲的，进程不退出就不会把 printf 刷到 fd 1(我们重定向的文件)。
        # 不显式 fflush 的话 native 日志永远是 0 行 —— 真机上就是这么踩到的。
        try:
            import ctypes
            ctypes.CDLL("libc.so").fflush(None)
        except Exception:
            pass
        try:
            if nativeFile is not None:
                nativeFile.flush()
                if 1 in nativeFd:
                    os.dup2(nativeFd[1], 1)
                if 2 in nativeFd:
                    os.dup2(nativeFd[2], 2)
                nativeFile.close()
        except Exception:
            pass
        # 把 native 日志搬到诊断里(它会包含 QNN/QNN EP 的具体报错)
        try:
            if os.path.exists(nativePath):
                with open(nativePath, "r", encoding="utf-8", errors="replace") as f:
                    tail = [ln.rstrip() for ln in f if ln.strip()][-25:]
                out.append("  ---- sr_native.log 末尾 {} 行 ----".format(len(tail)))
                out.extend("  | " + ln[:180] for ln in tail)
        except Exception as es:
            out.append("  读取 native 日志失败: {}".format(es))
    return out


def _CryptoDiag():
    """ 证明"接口解密链"在真机上真的可用

    p4a 把标准库 ctypes/util.py 补丁成 `from android._ctypes_library_finder import
    find_library`，而 p4a 的 android 包依赖 bootstrap=qt 里不存在的 JNI 符号，
    `import` 必然失败 —— pycryptodome 的 ctypes 回落路径因此整条断掉。
    这里把这条链的每一环都跑一遍并记下来，避免再出现"看着修好了其实没修"的情况。
    """
    lines = []
    try:
        from android._ctypes_library_finder import find_library
        lines.append("ctypes find_library: OK (from {})".format(
            getattr(find_library, "__module__", "?")))
        for name in ("c", "m", "crypto", "ssl", "log"):
            lines.append("  find_library({!r}) = {}".format(name, find_library(name)))
    except Exception as es:
        lines.append("ctypes find_library: FAIL {}: {}".format(type(es).__name__, es))
    try:
        import ctypes.util
        lines.append("ctypes.util: OK (find_library={})".format(
            getattr(ctypes.util.find_library, "__module__", "?")))
    except Exception as es:
        lines.append("ctypes.util: FAIL {}: {}".format(type(es).__name__, es))
    try:
        import base64
        import time
        from hashlib import md5
        from Crypto.Cipher import AES
        from Crypto.Util import _raw_api
        lines.append("pycryptodome: backend={} AES={}".format(_raw_api.backend, AES))
        try:
            from jmcomic import JmCryptoTool, JmMagicConstants
            ts = int(time.time())
            key = md5("{}{}".format(ts, JmMagicConstants.APP_DATA_SECRET).encode()).hexdigest().encode()
            payload = '{"code":200,"data":[]}'
            pad = 16 - len(payload) % 16
            raw = payload.encode() + bytes([pad]) * pad
            enc = base64.b64encode(AES.new(key, AES.MODE_ECB).encrypt(raw)).decode()
            got = JmCryptoTool.decode_resp_data(enc, ts=ts)
            lines.append("jmcomic decode_resp_data: {} ({!r})".format(got == payload, got))
        except Exception as es:
            lines.append("jmcomic decode_resp_data: FAIL {}: {}".format(type(es).__name__, es))
    except Exception as es:
        lines.append("pycryptodome: FAIL {}: {}".format(type(es).__name__, es))
    return lines


def DumpDiagnostics(reason=""):
    """ 记录关键运行时事实(插件/图像格式/native 库/模型/超分后端)，便于 adb 取证 """
    lines = ["", "===== diagnostics ({}) =====".format(reason)]
    try:
        from tools import platform_mobile
        lines.append("python: {}".format(sys.version.replace("\n", " ")))
        lines.append("sys.flags.optimize: {}".format(sys.flags.optimize))
        lines.append("APP_ROOT: {}".format(APP_ROOT))
        lines.append("ANDROID_PRIVATE: {}".format(os.environ.get("ANDROID_PRIVATE", "")))
        lines.append("ANDROID_ARGUMENT: {}".format(os.environ.get("ANDROID_ARGUMENT", "")))
        lines.append("JM_SR_MODELS: {}".format(os.environ.get("JM_SR_MODELS", "")))
        lines.append("app data dir: {}".format(platform_mobile.GetAppDataDir()))
        lines.append("external dir: {}".format(platform_mobile.GetExternalDir()))
        nativeDirs = platform_mobile.GetNativeLibDirs()
        lines.append("native lib dirs: {}".format(nativeDirs))
        for lib in ("libsr_qnn.so", "libonnxruntime.so", "libQnnHtp.so", "libQnnHtpV79Skel.so",
                    "libplugins_platforms_qtforandroid_arm64-v8a.so",
                    "libplugins_imageformats_qsvg_arm64-v8a.so",
                    "libplugins_imageformats_qjpeg_arm64-v8a.so",
                    "libplugins_imageformats_qgif_arm64-v8a.so",
                    "libplugins_imageformats_qwebp_arm64-v8a.so",
                    "libplugins_iconengines_qsvgicon_arm64-v8a.so",
                    "libplugins_sqldrivers_qsqlite_arm64-v8a.so"):
            found = [os.path.join(d, lib) for d in nativeDirs
                     if os.path.exists(os.path.join(d, lib))]
            lines.append("  {}: {}".format(lib, found or "NOT FOUND"))
        modelDir = platform_mobile.GetAndroidModelDir()
        names = sorted(os.listdir(modelDir)) if os.path.isdir(modelDir) else []
        lines.append("model dir {}: {} entries, {} onnx".format(
            modelDir, len(names), len([n for n in names if n.endswith(".onnx")])))
    except Exception as es:
        lines.append("platform info failed: {}".format(es))
    try:
        from PySide6.QtCore import QCoreApplication, QLibraryInfo
        from PySide6.QtGui import QImageReader
        lines.append("Qt version: {}".format(QCoreApplication.instance().applicationVersion()
                                             or QLibraryInfo.version().toString()))
        lines.append("libraryPaths: {}".format(QCoreApplication.libraryPaths()))
        lines.append("plugin path: {}".format(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)))
        formats = sorted(bytes(f).decode("ascii", "ignore")
                         for f in QImageReader.supportedImageFormats())
        lines.append("image formats: {}".format(formats))
        for need in ("jpeg", "gif", "webp", "svg"):
            lines.append("  {}: {}".format(need, "OK" if need in formats else "MISSING"))
    except Exception as es:
        lines.append("Qt info failed: {}".format(es))
    # pyjnius 是否真的可用(决定能不能调 Android 的 moveTaskToBack / 请求存储权限)。
    # 之前 APK 里没有 libjnius.so，所以 platform_mobile 里所有 JNI 路径都是静默失败的；
    # 这一行让"到底有没有 JNI"直接可判定。
    try:
        import jnius
        lines.append("jnius: import OK ({})".format(getattr(jnius, "__file__", "?")))
        from jnius import autoclass
        for name in ("org.kivy.android.PythonActivity",
                     "org.qtproject.qt.android.bindings.QtActivity"):
            try:
                activity = autoclass(name)
                act = getattr(activity, "mActivity", None)
                lines.append("  {}: mActivity={}".format(name, act))
            except Exception as es:
                lines.append("  {}: {}".format(name, es))
    except Exception as es:
        lines.append("jnius: FAIL {}: {}".format(type(es).__name__, es))
    if reason == "startup":
        lines.extend(_CryptoDiag())
    try:
        import sr_qnn
        from tools import sr_backend
        lines.append("sr engine: {} type={} loaded={}".format(
            sr_backend.GetEngineName(), sr_backend.GetEngineType(), sr_qnn.IsLoaded()))
        lines.append("sr load error: {}".format(sr_qnn.GetLoadError()))
        lines.append("sr models available: {}".format(sr_qnn.CountAvailableModels()))
        lines.append("sr htp capable: {}".format(sr_qnn.HasHtp()))
        lines.append("sr backend: {}".format(sr_qnn.GetBackendInfo()))
    except Exception as es:
        lines.append("sr info failed: {}".format(es))
    # 标记文件存在时跑一次真实推理，证明 NPU 是否真的生效。
    # 跑完就删掉标记：它是一次性开关，留着会每次都多花 1~2 秒启动时间。
    try:
        from tools import platform_mobile
        marker = os.path.join(platform_mobile.GetAppDataDir(), "sr_selftest")
        if os.path.exists(marker):
            try:
                os.remove(marker)
            except Exception:
                pass
            lines.extend(_SrSelfTest())
    except Exception as es:
        lines.append("sr selftest 触发失败: {}".format(es))
    lines.append("===== end diagnostics =====")
    WriteDiag("\n".join(lines))
    return


def Main():
    SetupPath()
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        from tools import platform_mobile
        platform_mobile.InitAndroidEnv(app)
        EnsureModels()

        from tools import sr_backend
        sr_backend.InstallQnnCompat()

        import start
        start.InitSrEngine()
        # 走一遍图像格式探测，确认 Qt 插件是否齐全(缺 qsvg 会让主题里的 svg 图标/交互框全部消失)
        DumpDiagnostics("startup")
        start.Run(app)
    except SystemExit:
        raise
    except Exception:
        WriteCrashLog(traceback.format_exc())
        raise
    return


if __name__ == "__main__":
    Main()
