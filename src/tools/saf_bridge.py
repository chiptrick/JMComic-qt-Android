# coding:utf-8
""" Android SAF(存储访问框架)桥 —— 手机上所有"选文件/选目录"都走这里

为什么要绕这么一圈
------------------
APK 里**没有** pyjnius(p4a 的 libjnius.so 依赖 bootstrap=qt 不提供的
`WebView_AndroidGetJNIEnv`)，PySide6 也没有绑定 `QJniObject` —— Python 侧无法
直接调用 Android 的 Java API。而在此之前，为了读手机存储，APK 索要了
`READ_EXTERNAL_STORAGE` / `READ_MEDIA_IMAGES` / `MANAGE_EXTERNAL_STORAGE`
(最后那个还要用户去系统设置里手动开"所有文件访问权限")，这既过多权限又不可靠。

SAF 是 Android 官方给的、**不需要任何权限**的方案：用户用系统文件选择器挑一次，
系统把那个 URI 的读写权授给本应用(可选持久化)。麻烦的是它只能由 Activity 发起、
结果回到 `onActivityResult`，Python 侧完全够不着。

所以这里用"文件信箱 + 本进程 Service"做桥：

    Python 写 <appData>/saf/inbox/<id>.json   ──┐
                                                ├─ SafService(同进程 Service)
    Python 读 <appData>/saf/outbox/<id>.json  ←─┘   用 ContentResolver 干活
                                                    需要界面时拉起 SafPickActivity

`SafService` 由 `am start-service --user 0` 拉起一次。为什么是 `start-service` 而不是
`start`：Android 14+ 上 `am start` 的调用方包名被写死成 com.android.shell，会被
`assertPackageMatchesCallingUid` 判为"包名不属于调用 uid"直接拒绝(实测 Android 16)；
`start-service` 没有这个检查。

语义约定
--------
* `PickFile` / `PickTree` 返回的都是**本地可读的路径**(选完立刻拷进应用目录)，
  因为整个业务层都是按文件路径干活的(解码、超分、WebDAV 上传…)。
  SAF 的 content:// URI 只有 Java 侧能读，Python 的 open() 打不开。
* 目录选择分两种：
    - `PickTree(..., copy=True)`：树整棵拷进应用目录(导入本地漫画 / 批量超分)
    - `PickTree(..., copy=False)`：只登记授权(下载/缓存目录的"导出目标")
* 所有失败都返回 `None` 或 `{"ok": False, ...}`，绝不抛异常给调用点。

没有桥可用时(桌面端 / 桥没打进 APK / am 被拦)所有函数返回 None，
调用方回落到 `mobile_file_dialog` 的应用内选择器(桌面行为不变)。
"""
import json
import os
import subprocess
import time

from tools import platform_mobile

# 请求文件轮询间隔(毫秒)与默认超时(秒)
PollMs = 60
PingTimeout = 4.0
PickTimeout = 600.0         # 用户在系统选择器里可能翻很久
IoTimeout = 1800.0          # 整棵目录树的拷贝(几十本漫画)可能很慢

ServiceClass = "org.jmcomic.SafService"

_ready = None               # None=还没试过 / True / False
_counter = 0
_lastError = ""


def PackageName():
    try:
        return platform_mobile.GetAndroidPackage()
    except Exception:
        return ""


def BridgeDir():
    """ 信箱根目录(Python 与 Java 都用 <filesDir>/saf) """
    try:
        return os.path.join(platform_mobile.GetAppDataDir(), "saf")
    except Exception:
        return ""


def InboxDir():
    return os.path.join(BridgeDir(), "inbox")


def OutboxDir():
    return os.path.join(BridgeDir(), "outbox")


def LastError():
    return _lastError


def _LogError(es):
    global _lastError
    _lastError = "{}: {}".format(type(es).__name__, es)
    try:
        from tools.log import Log
        Log.Error("saf bridge: {}".format(_lastError))
    except Exception:
        pass


def _OnAndroid():
    try:
        return platform_mobile.IsAndroid()
    except Exception:
        return False


def IsSupported():
    """ 这台设备上"用 SAF 选文件"这条路是否可用(不保证 Service 一定能起来) """
    if not _OnAndroid():
        return False
    if not PackageName():
        # 包名取不到 -> 没法用 am 启 Service；调用方会回落应用内选择器
        return False
    return True


# ---------------------------------------------------------------------------
# 与 Service 的信箱通信
# ---------------------------------------------------------------------------

def _NextId():
    global _counter
    _counter += 1
    # 定宽数字前缀：Java 侧按文件名排序处理，请求顺序与提交顺序一致
    return "{:013d}_{:04d}".format(int(time.time() * 1000), _counter)


def _WriteRequest(reqId, payload):
    folder = InboxDir()
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, reqId + ".json")
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, target)
    return target


def _StartService():
    """ 用 am 拉起本进程里的 SafService(见模块注释：只有 start-service 不被拦) """
    package = PackageName()
    if not package:
        return False
    am = "/system/bin/am"
    if not os.path.exists(am):
        am = "am"
    args = [am, "start-service", "--user", "0", "-n",
            "{}/{}".format(package, ServiceClass)]
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out, _ = proc.communicate(timeout=15)
        text = (out or b"").decode("utf-8", "ignore")
        if proc.returncode != 0:
            _LogError("am start-service rc={} out={}".format(proc.returncode, text.strip()[:200]))
            return False
        try:
            from tools.log import Log
            Log.Warn("saf bridge: am start-service -> {}".format(text.strip()[:120]))
        except Exception:
            pass
        return True
    except Exception as es:
        _LogError(es)
        return False


def _WaitResult(path, timeout):
    """ 等 Java 侧把结果写出来(嵌套事件循环，界面不冻) """
    if timeout <= 0:
        return False
    deadline = time.time() + timeout
    try:
        from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
        app = QCoreApplication.instance()
    except Exception:
        app = None
    if app is None:
        while time.time() < deadline:
            if os.path.exists(path):
                return True
            time.sleep(PollMs / 1000.0)
        return os.path.exists(path)
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    state = {"done": False}

    def Tick():
        if os.path.exists(path):
            state["done"] = True
            loop.quit()

    poll = QTimer()
    poll.setInterval(PollMs)
    poll.timeout.connect(Tick)
    poll.start()
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(loop.quit)
    guard.start(int(timeout * 1000))
    try:
        loop.exec()
    finally:
        poll.stop()
        guard.stop()
    return state["done"]


def _Ensure(timeout=PingTimeout):
    """ 保证 Service 在跑(懒启动 + 缓存结果) """
    global _ready
    if _ready:
        return True
    if not IsSupported():
        _ready = False
        return False
    for attempt in (0, 1):
        reqId = _NextId()
        out = os.path.join(OutboxDir(), reqId + ".json")
        try:
            _WriteRequest(reqId, {"id": reqId, "op": "ping"})
        except Exception as es:
            _LogError(es)
            _ready = False
            return False
        if not _WaitResult(out, 1.2 if attempt == 0 else timeout):
            if not _StartService():
                continue
            if not _WaitResult(out, timeout):
                _ready = False
                return False
        try:
            with open(out, "r", encoding="utf-8") as f:
                data = json.load(f)
            os.remove(out)
            if data.get("ok"):
                _ready = True
                return True
        except Exception as es:
            _LogError(es)
    _ready = False
    return False


def _Call(op, payload=None, timeout=IoTimeout):
    """ 发一个请求并等结果；返回 dict 或 None(桥不可用/超时) """
    if not _Ensure():
        return None
    request = {"op": op}
    if payload:
        request.update(payload)
    reqId = _NextId()
    request["id"] = reqId
    out = os.path.join(OutboxDir(), reqId + ".json")
    try:
        _WriteRequest(reqId, request)
    except Exception as es:
        _LogError(es)
        return None
    if not _WaitResult(out, timeout):
        _LogError("timeout {}s 等 {} 的结果".format(int(timeout), op))
        return None
    try:
        with open(out, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as es:
        _LogError(es)
        return None
    finally:
        try:
            os.remove(out)
        except Exception:
            pass
    return data


def _Fire(op, payload=None):
    """ 只投递请求，不等结果(导出这种"后台慢慢做"的动作用) """
    if not _Ensure():
        return False
    request = {"op": op}
    if payload:
        request.update(payload)
    reqId = _NextId()
    request["id"] = reqId
    try:
        _WriteRequest(reqId, request)
    except Exception as es:
        _LogError(es)
        return False
    return True


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

def MimeOfFilters(filter):
    """ 把 QFileDialog 风格的过滤器换成 SAF 认的 MIME

    `Image Files(*.jpg *.png)` -> `image/*`；解析不出来给 `*/*`。
    """
    text = (filter or "").lower()
    if not text:
        return "*/*"
    table = (
        (("*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif", "*.bmp"), "image/*"),
        (("*.zip",), "application/zip"),
        (("*.txt", "*.json"), "text/plain"),
        (("*.cbz", "*.cbr"), "*/*"),
    )
    for exts, mime in table:
        for ext in exts:
            if ext in text:
                return mime
    return "*/*"


def PickFile(caption, filter="", copyTo=""):
    """ 选一个文件：返回 (本地路径, 显示名) / False(用户取消) / None(桥不可用)

    SAF 授权的是 content:// URI —— 业务层要的是文件路径，所以选完立刻让 Java 把内容
    拷进 copyTo(默认应用缓存目录)，返回落地后的绝对路径。
    """
    if not IsSupported():
        return None
    target = copyTo or os.path.join(platform_mobile.GetAppDataDir(), "import")
    try:
        os.makedirs(target, exist_ok=True)
    except Exception:
        target = platform_mobile.GetAppDataDir()
    data = _Call("pick", {"kind": "file", "mime": MimeOfFilters(filter),
                          "copyTo": target, "caption": caption or ""}, PickTimeout)
    if not data:
        return None
    if not data.get("ok"):
        return False if data.get("cancel") else None
    path = data.get("path") or ""
    if not path or not os.path.exists(path):
        return None
    return path, (data.get("name") or os.path.basename(path))


def PickSave(caption, defaultName="", filter=""):
    """ 另存为：返回 content:// URI 或 None

    注意：拿回来的是 URI，Python 不能直接写。调用方如果是"把本地文件另存到用户选的
    位置"，应该用 ExportFile。
    """
    if not IsSupported():
        return None
    data = _Call("pick", {"kind": "save", "mime": MimeOfFilters(filter),
                          "defaultName": defaultName or "", "caption": caption or ""},
                 PickTimeout)
    if not data or not data.get("ok"):
        return None
    return data.get("uri") or None


def PickTree(caption, copyTo="", timeout=IoTimeout):
    """ 选一个目录

    copyTo 为空：只登记授权，返回 {"uri","name"}(下载目录的导出目标)
    copyTo 非空：整棵树拷进 copyTo，返回 {"uri","name","path","count"}
    用户取消返回 False，桥不可用返回 None。
    """
    if not IsSupported():
        return None
    data = _Call("pick", {"kind": "tree", "mime": "vnd.android.document/directory",
                          "caption": caption or ""}, PickTimeout)
    if not data:
        return None
    if not data.get("ok"):
        return False if data.get("cancel") else None
    uri = data.get("uri") or ""
    if not uri:
        return None
    result = {"uri": uri, "name": data.get("name") or ""}
    if copyTo:
        copied = CopyTreeIn(uri, copyTo, timeout)
        if not copied:
            return None
        result.update(copied)
    return result


def CopyTreeIn(uri, toDir, timeout=IoTimeout):
    """ 把 SAF 目录树拷到本地目录，返回 {"ok","path","count"} 或 None """
    if not IsSupported() or not uri:
        return None
    try:
        os.makedirs(toDir, exist_ok=True)
    except Exception as es:
        _LogError(es)
        return None
    data = _Call("copyIn", {"uri": uri, "to": toDir}, timeout)
    if not data or not data.get("ok"):
        return None
    return data


def WriteFile(uri, localPath, timeout=IoTimeout):
    """ 把本地文件写到 SAF 的 document URI 上("另存为"选完位置之后) """
    if not IsSupported() or not uri or not localPath:
        return False
    data = _Call("writeFile", {"uri": uri, "from": localPath}, timeout)
    return bool(data and data.get("ok"))


def CopyTreeOut(localDir, treeUri, subPath="", wait=False, timeout=IoTimeout):
    """ 把本地目录拷到 SAF 树的 subPath 下(下载完成后导出到用户选的目录) """
    if not IsSupported() or not localDir or not treeUri:
        return None
    payload = {"from": localDir, "uri": treeUri, "sub": subPath or ""}
    if not wait:
        return {"ok": True} if _Fire("copyOut", payload) else None
    data = _Call("copyOut", payload, timeout)
    if not data or not data.get("ok"):
        return None
    return data


def OpenUri(uri):
    """ 请系统文件管理器打开一个 SAF 目录/文件 URI """
    if not IsSupported() or not uri:
        return False, "unsupported"
    data = _Call("open", {"uri": uri}, 20.0)
    if not data:
        return False, "timeout"
    if data.get("ok"):
        return True, ""
    return False, data.get("reason") or data.get("error") or "failed"


def OpenPath(path):
    """ 请系统文件管理器打开一个本地目录

    应用专属目录(/data/user/0/<pkg>/files、/storage/emulated/0/Android/data/<pkg>/…)
    在 Android 11+ 对其他应用完全不可见，任何文件管理器都打不开 —— 这种情况返回
    (False, "sandbox")，由界面给出可操作的提示。
    """
    if not IsSupported() or not path:
        return False, "unsupported"
    data = _Call("open", {"path": path}, 20.0)
    if not data:
        return False, "timeout"
    if data.get("ok"):
        return True, ""
    return False, data.get("reason") or data.get("error") or "failed"
