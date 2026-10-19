# coding:utf-8
"""JMComic Android 入口

pyside6-android-deploy 要求入口文件名为 main.py，打包时本文件位于 APK 的
assets 根目录，业务代码在 app_src/(构建脚本从 ../src 复制)或 ../src(本地调试)。

启动顺序很关键：
    1. 调整 sys.path(业务源码 + sr_qnn 后端 + 可选的依赖垫片)
    2. 创建 QApplication(QStandardPaths 需要)
    3. platform_mobile.InitAndroidEnv()：把配置/数据/日志重定向到应用私有目录，
       缓存重定向到应用外部缓存目录(/storage/emulated/0/Android/data/<包名>/cache，
       用户清理得到)，下载目录默认指向应用外部私有目录
    4. sr_backend.InstallQnnCompat()：把 sr_qnn 注册为 sr_vulkan 兼容模块
    5. start.Run(app)：走与桌面端相同的主流程(自动跳过单实例/系统托盘等桌面特性)
"""
import os
import sys
import traceback

APP_ROOT = os.path.dirname(os.path.abspath(__file__))


def ApplyEnvFile():
    """ 读取 <AppDataDir>/sr_env.txt 里的 KEY=VALUE 覆盖环境变量

    Android 应用进程没法从 adb 直接设环境变量（setprop 进不了进程环境），
    但 QNN 的每个调优开关都是环境变量驱动的。有了这个文件，换参数只需要
        adb push sr_env.txt /data/local/tmp/ && adb shell run-as <包名> \\
            sh -c 'cat /data/local/tmp/sr_env.txt > files/sr_env.txt'
    就能生效，不必为每个参数重新打包 APK。

    支持的键见 android/sr_qnn/models/README.md 的"参数调试"表，常用的：
        JM_QNN_PERF / JM_QNN_FINALIZE / JM_QNN_VTCM / JM_QNN_RPC_LATENCY
        JM_QNN_HTP_ARCH / JM_QNN_SOC_MODEL / JM_QNN_WORKERS / JM_ORT_LOG
        JM_SR_PROC（0=禁用进程模式；force=即使没有 QNN 运行库也试一次）
    """
    try:
        from PySide6.QtCore import QStandardPaths
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    except Exception:
        base = os.environ.get("ANDROID_PRIVATE", APP_ROOT)
    path = os.path.join(base or APP_ROOT, "sr_env.txt")
    applied = []
    try:
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    continue
                os.environ[key] = value
                applied.append("{}={}".format(key, value))
    except Exception as es:
        WriteDiag("sr_env 读取失败: {}".format(es))
        return
    if applied:
        WriteDiag("sr_env: " + ", ".join(applied))


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


def _ModelSig(path):
    """ 模型目录签名(文件名 + 大小)

    用来判断"APK 里的模型"和"应用私有目录里的旧副本"是不是同一份：
    早期只有当私有目录**没有**模型时才复制，导致升级 APK 后换了模型也永远用旧的
    (旧模型是动态 shape 导出的，QNN 只能跑"HTP+CPU 回退"，超分会明显变慢)。
    """
    try:
        if not path or not os.path.isdir(path):
            return ""
        parts = []
        for name in sorted(os.listdir(path)):
            if not name.endswith((".onnx", ".txt")):
                continue
            try:
                parts.append("{}:{}".format(name, os.path.getsize(os.path.join(path, name))))
            except OSError:
                continue
        return "|".join(parts)
    except Exception:
        return ""


def _CopyModels(src, target):
    """ 复制模型(必须用 copyfile：copy2 的 copystat 在 Android 上会抛 PermissionError) """
    import shutil
    copied = 0
    for name in os.listdir(src):
        if not name.endswith((".onnx", ".bin", ".txt")):
            continue
        try:
            shutil.copyfile(os.path.join(src, name), os.path.join(target, name))
            copied += 1
        except OSError as es:
            WriteDiag("copy {} failed: {}".format(name, es))
    return copied


def EnsureModels():
    """ 让 sr_qnn 能读到 waifu2x 模型

    模型随 APK 的 private.tar 分发(p4a 解包到 APP_ROOT/sr_qnn/models/)，所以：
        1. 只要解包目录里有模型就**原地使用** —— 它是随 APK 一起更新的，永远是最新的
        2. 解包目录不可用时，才用应用私有目录的副本；但会用签名比对，**不一样就重新复制**
           (旧逻辑只判断"有没有模型"，升级 APK 后换了模型也不会更新，超分会一直跑旧图)
        3. 两者都没有时退回 APK assets
    """
    try:
        from tools import platform_mobile
        target = platform_mobile.GetAndroidModelDir()
        extracted = os.path.join(APP_ROOT, "sr_qnn", "models")
        if _HasModels(extracted):
            # 就地使用：sr_qnn 通过 platform_mobile.GetAndroidModelDir() 读这个环境变量
            os.environ["JM_SR_MODELS"] = extracted
            WriteDiag("models in place: {}".format(extracted))
            if _HasModels(target) and _ModelSig(target) != _ModelSig(extracted):
                WriteDiag("警告: {} 里的模型是旧版本(已改用在用 APK 内的那份)".format(target))
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
        if _HasModels(target):
            if src and _ModelSig(src) != _ModelSig(target):
                copied = _CopyModels(src, target)
                WriteDiag("models 已更新: {} -> {} ({} files)".format(src, target, copied))
            return
        os.makedirs(target, exist_ok=True)
        copied = 0
        if src:
            copied = _CopyModels(src, target)
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


def _SocInfo():
    """ 读设备 SoC 信息

    只有高通骁龙的 Hexagon HTP 能用 QNN；如果是联发科/三星/紫光，QNN 会话必然挂不上，
    超分会退回 CPU EP —— 单块 192 的 cunet 在手机 CPU 上就是 500ms 量级，
    这和"QNN 超分慢得离谱"的现象完全对应，所以自检里必须把 SoC 打出来。
    """
    keys = ("ro.board.platform", "ro.soc.manufacturer", "ro.soc.model",
            "ro.hardware", "ro.product.model")
    values = []
    for key in keys:
        text = ""
        try:
            import subprocess
            text = subprocess.check_output(["getprop", key], stderr=subprocess.DEVNULL,
                                           timeout=2).decode("utf-8", "ignore").strip()
        except Exception:
            try:
                import os as _os
                with _os.popen("getprop " + key) as fp:
                    text = fp.read().strip()
            except Exception:
                text = ""
        values.append("{}={}".format(key, text or "?"))
    return ", ".join(values)


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
    # 打开 ORT 的 INFO 日志：QNN EP 把图切成 NPU/CPU 两段时，ORT 会打
    # "Some nodes were not assigned to the preferred execution providers ...
    #  Number of nodes assigned to CPUExecutionProvider: N" —— 这是判断
    # "到底是机型没有 NPU，还是模型被切分" 的唯一直接证据。
    os.environ.setdefault("JM_ORT_LOG", "1")
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
    profileBase = os.path.join(base, "sr_profile")
    try:
        # 让 ORT 落盘逐节点的 provider 记录：QNN 拒收的算子会以 CPUExecutionProvider
        # 出现，这是"图被切分"时唯一能点名到算子的证据。
        os.environ["JM_SR_PROFILE"] = profileBase
        import glob as _glob
        for old in _glob.glob(profileBase + "*.json"):
            try:
                os.remove(old)
            except Exception:
                pass
    except Exception:
        pass
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
        # 进程模式下 JM_SR_PROFILE / JM_QNN_DEBUG 只在子进程 spawn 时生效，
        # 所以自检要重建一次引擎，否则拿不到逐节点 profile
        try:
            sr_qnn.Reinit()
            modelId = sr_qnn.GetModelId("WAIFU2X_CUNET_UP2X_DENOISE3X")
        except Exception as es:
            out.append("  引擎重建失败: {}".format(es))
        out.append("  引擎模式: {}".format("独立进程(可加载厂商 FastRPC)" if sr_qnn.IsProcMode() else "进程内 ctypes"))
        if not sr_qnn.IsProcMode():
            procErr = sr_qnn.GetProcError()
            if procErr:
                out.append("  进程模式失败: {}".format(procErr))
        out.append("  soc: {}".format(_SocInfo()))

        def _bench(w, h, taskId):
            """ 用一张渐变图跑一次超分，回报耗时与每块平均耗时 """
            raw = bytearray()
            for y in range(h):
                for x in range(w):
                    raw += bytes(((x * 4) & 0xFF, (y * 4) & 0xFF, 128))
            img = QImage(bytes(raw), w, h, w * 3, QImage.Format.Format_RGB888)
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            img.save(buf, "PNG")
            buf.close()
            tid = sr_qnn.add(bytes(ba), modelId, taskId, 2.0, format="png")
            if tid <= 0:
                return ("  {}x{}: add 被拒 {}".format(w, h, sr_qnn.getLastError()), 0.0, 0)
            res = sr_qnn.load(180000)
            if not res or not res[0]:
                return ("  {}x{}: load 无结果 {}".format(w, h, sr_qnn.getLastError()), 0.0, 0)
            data, _fmt, _id, tick = res
            got = QImage.fromData(data)
            # 与 C++ 一致的分块几何：cunet up2x 每块前进 156 像素
            tiles = ((w + 155) // 156) * ((h + 155) // 156)
            return ("  {}x{} -> {}x{}, {:.3f}s, {} 块, {:.1f}ms/块".format(
                w, h, got.width(), got.height(), tick, tiles, tick * 1000.0 / max(1, tiles)),
                tick, tiles)

        # 1 块 + 20 块各跑一次：小图看单次推理开销，大图看吞吐
        line1, _t1, _n1 = _bench(192, 192, 901)
        line2, _t2, n2 = _bench(480, 640, 902)
        out.append(line1)
        out.append(line2)
        # 进程模式：hello 里的后端状态是"建会话之前"的快照，跑完再问一次
        try:
            if sr_qnn.IsProcMode():
                sr_qnn.RefreshStatus()
        except Exception:
            pass
        # 实际装进设备的原生库：判断 libcdsprpc.so(FastRPC，HTP 必需) 到底有没有进包
        try:
            libDir = ""
            with open("/proc/self/maps", "r", errors="replace") as maps:
                for ln in maps:
                    if "libsr_qnn.so" in ln:
                        libDir = os.path.dirname(ln.split()[-1])
                        break
            if libDir:
                names = sorted(n for n in os.listdir(libDir)
                               if n.startswith(("libQnn", "libcdsprpc", "libonnxruntime")))
                out.append("  原生库目录: {}".format(libDir))
                out.append("  已安装的 QNN 库: {}".format(", ".join(names) or "无"))
                out.append("  FastRPC(libcdsprpc.so): {}".format(
                    "已打包" if "libcdsprpc.so" in names else
                    ("未打包 —— 进程模式下由子进程从 /vendor/lib64 加载，属正常"
                     if sr_qnn.IsProcMode() else "缺失(HTP 起不来的根因)")))
        except Exception as es:
            out.append("  原生库检查失败: {}".format(es))
        out.append("  HTP 能力: {}".format(sr_qnn.HasHtp()))
        out.append("  实际后端: {}".format(sr_qnn.GetBackendInfo()))
        out.append("  引擎错误: {}".format(sr_qnn.getLastError()))
        # QNN 一个节点都不接时，只有这条能说明"后端起不来"还是"算子不支持"
        out.append("  HTP 初始化报错: {}".format(sr_qnn.getHtpError() or "无"))
        # 一行汇总，方便直接粘贴：backend 决定"有没有用上 NPU"，ms/块 决定下一步优化方向
        perTile = (_t2 * 1000.0 / n2) if n2 else 0.0
        out.append("  SELFTEST_SUMMARY backend={} htp={} tile_ms={:.0f}".format(
            sr_qnn.GetBackendInfo(), sr_qnn.HasHtp(), perTile))

        # 逐节点 provider 统计：停止引擎让 ORT 把 profile 落盘
        try:
            import glob as _glob
            import json as _json
            sr_qnn.stop()
            counts = {}
            cpuOps = {}
            for path in sorted(_glob.glob(profileBase + "*.json")):
                with open(path, "r", encoding="utf-8", errors="replace") as fp:
                    for line in fp:
                        text = line.strip().rstrip(",")
                        if not text.startswith("{"):
                            continue
                        try:
                            obj = _json.loads(text)
                        except Exception:
                            continue
                        args = obj.get("args") or {}
                        provider = args.get("provider") or ""
                        opName = args.get("op_name") or ""
                        if not provider:
                            continue
                        counts[provider] = counts.get(provider, 0) + 1
                        if "CPU" in provider and opName:
                            cpuOps[opName] = cpuOps.get(opName, 0) + 1
            out.append("  profile providers: {}".format(counts or "无(未落盘)"))
            if cpuOps:
                out.append("  跑在 CPU 上的算子: {}".format(
                    ", ".join("{}x{}".format(k, v) for k, v in sorted(cpuOps.items()))))
        except Exception as es:
            out.append("  profile 解析失败: {}".format(es))
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
                    allLines = [ln.rstrip() for ln in f if ln.strip()]
                # 优先挑"能看出后端/分区/报错"的行：任务耗时那几行会把会话信息挤掉
                keys = ("sr_qnn", "QNN", "assigned", "Failed", "failed", "error", "Error",
                        "session", "Skel", "skel", "HTP", "[ORT", "Gpu", "GPU")
                picked = [ln for ln in allLines if any(k in ln for k in keys)]
                # ORT 自己的日志(现在被重定向进来了)是判断 QNN 拒收原因的关键，
                # 单独再取最后 40 行 ORT 记录，保证不会被我们的 printf 挤掉。
                ortLines = [ln for ln in allLines if ln.startswith("[ORT ")]
                tail = picked[-40:]
                if ortLines:
                    tail = tail + ["---- ORT 日志最后 {} 行 ----".format(min(40, len(ortLines)))]
                    tail = tail + ortLines[-40:]
                # QNN 后端的"根因"往往只出现一次(后面被海量 INFO 淹掉)，单独再捞一遍：
                #   QNN SetupBackend failed ... PLATFORM_NOT_SUPPORTED  -> 后端在本机不可用
                #   Failed to create device / Skel / libcdsprpc           -> FastRPC/DSP 侧问题
                causeKeys = ("SetupBackend failed", "Failed to create device",
                             "PLATFORM_NOT_SUPPORTED", "INVALID_CONFIG", "Skel", "cdsprpc",
                             "backend id:", "CANNOT LINK", "Permission denied",
                             "Exec format", "进程模式")
                causes = []
                for ln in allLines:
                    if any(k in ln for k in causeKeys) and ln not in causes:
                        causes.append(ln)
                if causes:
                    tail = tail + ["---- QNN 根因 {} 行 ----".format(len(causes))]
                    tail = tail + causes[:10]
                # 子进程自己的日志(独立文件，见 sr_qnn._StartProcEngine)：
                # 进程模式失败时，linker/dlerror 的原文只在这里。
                procLog = os.path.join(os.path.dirname(nativePath), "sr_proc.log")
                procLines = []
                try:
                    if os.path.exists(procLog):
                        with open(procLog, "r", encoding="utf-8", errors="replace") as fp:
                            procLines = [ln.rstrip() for ln in fp if ln.strip()]
                except Exception:
                    pass
                if procLines:
                    # 只看引擎/QNN 自己的行，ORT 的内存分配噪音没有价值
                    engineLines = [ln for ln in procLines
                                   if ("[sr_qnn]" in ln) or ("[sr_qnn_proc]" in ln)
                                   or ("SetupBackend" in ln) or ("backend provider" in ln)]
                    show = engineLines if engineLines else procLines
                    tail = tail + ["---- 子进程日志 {} 行(引擎/QNN {} 行): {} ----".format(
                        len(procLines), len(engineLines), procLog)]
                    tail = tail + show[-15:]
                elif not sr_qnn.IsProcMode():
                    tail = tail + ["---- 子进程日志: 空(进程没跑到 main) ----"]
                out.append("  ---- sr_native.log 关键行 {} / 共 {} 行 ----".format(
                    len(tail), len(allLines)))
                out.extend("  | " + ln[:400] for ln in tail)
        except Exception as es:
            out.append("  读取 native 日志失败: {}".format(es))
    # 结论单独落一个文件：android_startup.log 里混着 pycryptodome 等一堆打印，
    # 排查时直接把这一个文件整份发出来就够(自检信息 + native 关键行)
    try:
        base = locals().get("base") or os.environ.get("ANDROID_PRIVATE", APP_ROOT)
        reportPath = os.path.join(base, "sr_report.txt")
        with open(reportPath, "w", encoding="utf-8", errors="replace") as fp:
            fp.write("\n".join(out) + "\n")
        out.append("  报告文件: {}".format(reportPath))
    except Exception as es:
        out.append("  写 sr_report.txt 失败: {}".format(es))
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
        lines.append("external cache dir: {}".format(platform_mobile.GetExternalCacheDir()))
        lines.append("XDG_CACHE_HOME: {}".format(os.environ.get("XDG_CACHE_HOME", "")))
        nativeDirs = platform_mobile.GetNativeLibDirs()
        lines.append("native lib dirs: {}".format(nativeDirs))
        for lib in ("libsr_qnn.so", "libonnxruntime.so", "libQnnHtp.so", "libQnnHtpV79Skel.so"):
            found = [os.path.join(d, lib) for d in nativeDirs
                     if os.path.exists(os.path.join(d, lib))]
            lines.append("  {}: {}".format(lib, found or "NOT FOUND"))
        # Qt 插件文件名带 ABI 后缀(libplugins_imageformats_qsvg_arm64-v8a.so /
        # ..._x86_64.so)，所以这里按前缀找、不写死后缀 —— 否则 x86_64 构建的诊断
        # 会一律报 NOT FOUND，看起来像"插件没打进包"，其实是名字对不上。
        for prefix in ("libplugins_platforms_qtforandroid_",
                       "libplugins_imageformats_qsvg_",
                       "libplugins_imageformats_qjpeg_",
                       "libplugins_imageformats_qgif_",
                       "libplugins_imageformats_qwebp_",
                       "libplugins_iconengines_qsvgicon_",
                       "libplugins_sqldrivers_qsqlite_"):
            hit = ""
            for d in nativeDirs:
                try:
                    for name in sorted(os.listdir(d)):
                        if name.startswith(prefix) and name.endswith(".so"):
                            hit = os.path.join(d, name)
                            break
                except Exception:
                    continue
                if hit:
                    break
            lines.append("  {}*: {}".format(prefix, hit or "NOT FOUND"))
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
        lines.append("sr soc: {}".format(_SocInfo()))
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
        # 必须在 sr_qnn 初始化之前：QNN 的调优开关全部走环境变量
        ApplyEnvFile()
        EnsureModels()

        from tools import sr_backend
        sr_backend.InstallQnnCompat()

        import start
        start.InitSrEngine()
        # 走一遍图像格式探测，确认 Qt 插件是否齐全(缺 qsvg 会让主题里的 svg 图标/交互框全部消失)
        DumpDiagnostics("startup")
        # 下载目录(SAF)自检：只有 <filesDir>/saf/selftest 存在时才跑(见 tools/saf_selftest.py)
        try:
            from tools import saf_selftest
            saf_selftest.Install()
        except Exception:
            pass
        start.Run(app)
    except SystemExit:
        raise
    except Exception:
        WriteCrashLog(traceback.format_exc())
        raise
    return


if __name__ == "__main__":
    Main()
