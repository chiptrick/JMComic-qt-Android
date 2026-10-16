# coding:utf-8
"""HTTP/3、ECH 失败自动降级的回归测试(主机，不联网)

背景
----
打开"启用HTTP3/ECH"后 CDN 请求大量失败(日志里成片 `error:XXXReq, ech:True, ..., h3:True`)：

* **HTTP/3 走 UDP**。封掉 UDP 443 的网络里 QUIC 握手一直收不到回应，而 libcurl 自带的
  fallback 只在"HTTP/3 连接**建立失败**"时才触发 —— 一直等不到就只能等到超时；
  它还不看域名，`bytepluses.com`(JM 服务器列表)、`jpacg.cc`(DOH) 这些不说 QUIC 的域名
  也会被设成 HTTP/3。
* **ECH 配置**每 15 分钟从 `cloudflare-ech.com` 拉一次，配置轮换/过期时服务端回
  `ECH_REJECTED`，TLS 握手直接失败。
* `curl_cffi` 没编出 HTTP/3 时设 `HTTP_VERSION=3` 会直接报 `CURLE_UNSUPPORTED_PROTOCOL`。

修法(`src/server/req.py` + `server.py` + `user_handler.py`)：失败后关掉 HTTP/3 / ECH
重试一次，并**记住**(`Http3EchFallback`)，后续请求直接走 HTTP/2 + 普通 SNI。
垫片(`android/shims/curl_cffi`，`HTTP3_ECH_SUPPORTED=False`)下这两项是空操作，
降级重试只会多打一轮 —— `IsAdvancedTlsSupported()` 返回 False，整条链路直接跳过。

本测试分三段(用假的 session 驱动，不发真请求)：
    A. 垫片下：不降级、不改状态(Android 现有行为一字不变)
    B. 真 curl_cffi 下：DowngradeTlsOptions / Http3EchFallback / Reset 的语义
    C. 走真实调用点：`Server._Send`(接口) 与 `DownloadBookHandler`(CDN 图片) 的降级重投

用法: python3 android/tools/host_test_net_fallback.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="jm_netfb_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["JMCOMIC_ANDROID"] = "1"
os.environ["ANDROID_PRIVATE"] = TMP
os.environ["JM_ANDROID_SAVE_DIR"] = os.path.join(TMP, "save")
os.environ["JM_SR_MODELS"] = os.path.join(TMP, "waifu2x-models")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "android"))
sys.path.append(os.path.join(REPO, "android", "shims"))
os.chdir(TMP)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from tools import platform_mobile  # noqa: E402

platform_mobile.InitAndroidEnv(app)

from tools.log import Log  # noqa: E402
from config.setting import Setting  # noqa: E402
from tools.str import Str  # noqa: E402
from qt_owner import QtOwner  # noqa: E402

Log.Init()
Setting.Init()
Setting.InitLoadSetting()
Str.Reload()
QtOwner().SetApp(app)

import curl_cffi.requests.exceptions as exceptions  # noqa: E402
from curl_cffi import CurlOpt, CurlHttpVersion  # noqa: E402
from server import req, res  # noqa: E402
import server.user_handler  # noqa: E402,F401  注册 handler
from server.server import Server, Task  # noqa: E402
from tools.status import Status  # noqa: E402

FAILED = 0


def Fail(text):
    global FAILED
    FAILED += 1
    print("[FAIL] " + text)


def BareReq():
    """不跑 __init__，只造一个能测降级语义的空壳。"""
    return object.__new__(req.ServerReq)


# --------------------------------------------------------------------------
# A. 垫片下：不降级、不改状态
# --------------------------------------------------------------------------
req.ResetHttp3EchFallback()
if req.IsAdvancedTlsSupported() is not False:
    Fail("垫片把 HTTP_VERSION/ECH 当空操作，IsAdvancedTlsSupported() 应为 False")
probe = BareReq()
probe.isH3 = True
probe.isEch = True
probe.curl_opt = {CurlOpt.HTTP_VERSION: CurlHttpVersion.V3, CurlOpt.ECH: "ecl:AAAA"}
if probe.DowngradeTlsOptions(False) is not False:
    Fail("垫片下不该降级重试(只会多打一轮请求)")
if not (probe.isH3 and probe.isEch):
    Fail("垫片下不该改动请求状态(Android 行为必须不变)")
print("[ok] 垫片下 HTTP/3/ECH 不触发降级重试(不改变 Android 现有行为)")

# --------------------------------------------------------------------------
# B. 真 curl_cffi 下的降级语义
# --------------------------------------------------------------------------
originAdvanced = req.IsAdvancedTlsSupported
req.IsAdvancedTlsSupported = lambda: True
try:
    req.ResetHttp3EchFallback()
    probe = BareReq()
    probe.isH3 = True
    probe.isEch = True
    probe.curl_opt = {CurlOpt.HTTP_VERSION: CurlHttpVersion.V3, CurlOpt.ECH: "ecl:AAAA"}
    if probe.DowngradeTlsOptions(False) is not True:
        Fail("网络失败应先关 HTTP/3")
    if probe.isH3 is not False or probe.isEch is not True:
        Fail("第一轮只关 HTTP/3，保留 ECH")
    if probe.curl_opt[CurlOpt.HTTP_VERSION] != CurlHttpVersion.V2_0:
        Fail("关 HTTP/3 后应退回 HTTP/2")
    if req.Http3EchFallback.http3Off is not True:
        Fail("关掉 HTTP/3 后应记住")
    if probe.DowngradeTlsOptions(False) is not True:
        Fail("还在失败就再关 ECH")
    if probe.isEch is not False or req.Http3EchFallback.echOff is not True:
        Fail("第二轮应关掉 ECH 并记住")
    if probe.DowngradeTlsOptions(False) is not False:
        Fail("都关完了不能无限重试")

    # 记住之后，新请求默认不再开
    fresh = req.ServerReq("https://cdn-msp.jmapiproxy1.cc/a.webp", {}, "GET")
    if not fresh.isImg:
        Fail("cdn-msp.jmapiproxy1.cc 应判成图片域名")
    fresh.SetCurlOpt(True, True, "QkJC", None)
    if fresh.isH3 is not False or fresh.isEch is not False:
        Fail("记住失败后，新请求不该再开 HTTP/3/ECH")

    # 重存代理设置 -> 重置
    req.ResetHttp3EchFallback()
    if req.Http3EchFallback.http3Off is not False:
        Fail("ResetHttp3EchFallback 应清掉记忆")

    # ECH 被拒 -> 先关 ECH，保留 HTTP/3
    probe3 = BareReq()
    probe3.isH3 = True
    probe3.isEch = True
    probe3.curl_opt = {CurlOpt.HTTP_VERSION: CurlHttpVersion.V3, CurlOpt.ECH: "ecl:AAAA"}
    if probe3.DowngradeTlsOptions(True) is not True:
        Fail("ECH 被拒应先关 ECH")
    if probe3.isEch is not False or probe3.isH3 is not True:
        Fail("ECH 被拒时保留 HTTP/3")
    print("[ok] HTTP/3、ECH 失败自动降级并记住(ECH 被拒先关 ECH)，Reset 后重置")

    # ----------------------------------------------------------------------
    # C. 真实调用点：Server._Send 与 DownloadBookHandler
    # ----------------------------------------------------------------------
    class FakeResp(object):
        status_code = 200
        headers = {}
        content = b"{}"
        text = "{}"

    class FakeSession(object):
        """前 fails 次抛 Timeout，之后成功；记录每次请求实际用的 HTTP 版本/ECH。"""

        def __init__(self, fails):
            self.curl_options = {}
            self.fails = fails
            self.calls = []

        def _record(self):
            self.calls.append({"ver": self.curl_options.get(CurlOpt.HTTP_VERSION),
                               "ech": CurlOpt.ECH in self.curl_options})
            if len(self.calls) <= self.fails:
                raise exceptions.Timeout("timed out")

        def get(self, *a, **kw):
            self._record()
            return FakeResp()

        def post(self, *a, **kw):
            self._record()
            return FakeResp()

    srv = Server()
    saved = {}
    for name in ("ServerReq", "SpeedTestPingReq"):
        saved[name] = srv.handler.get(name)
        srv.handler[name] = lambda t: None

    def Send(hostReq, fails):
        task = Task(hostReq, backParam="")
        session = FakeSession(fails)
        srv._Send(task, 0, session)
        return session

    try:
        # C1. 失败一次 -> 关 HTTP/3 重试，第二次成功；ECH 还留着
        req.ResetHttp3EchFallback()
        request = req.ServerReq("https://www.cdngwc.cc/latest", {}, "GET")
        if not request.isApi:
            Fail("www.cdngwc.cc 应判成 api 域名")
        request.SetCurlOpt(True, True, "QkJC", None)
        session = Send(request, 1)
        if len(session.calls) != 2:
            Fail("失败一次应重试一次，实际调用 {}".format(len(session.calls)))
        elif (session.calls[0]["ver"] != CurlHttpVersion.V3 or session.calls[0]["ech"] is not True
                or session.calls[1]["ver"] != CurlHttpVersion.V2_0 or session.calls[1]["ech"] is not True):
            Fail("重试应只用 HTTP/2、保留 ECH: {}".format(session.calls))
        else:
            print("[ok] 接口失败一次: 关 HTTP/3 重试成功 -> {}".format(session.calls))

        # C2. 连失败两次 -> 再关 ECH，第三次才成功
        req.ResetHttp3EchFallback()
        request = req.ServerReq("https://www.cdngwc.cc/latest", {}, "GET")
        request.SetCurlOpt(True, True, "QkJC", None)
        session = Send(request, 2)
        if len(session.calls) != 3 or session.calls[2]["ech"] is not False:
            Fail("连失败两次应在第二次降级时关掉 ECH: {}".format(session.calls))
        else:
            print("[ok] 接口连失败两次: 再关 ECH 重试 -> {}".format(session.calls))

        # C3. 都关完了还在失败 -> 不再无限重试
        req.ResetHttp3EchFallback()
        request = req.ServerReq("https://www.cdngwc.cc/latest", {}, "GET")
        request.SetCurlOpt(True, True, "QkJC", None)
        session = Send(request, 99)
        if len(session.calls) != 3:
            Fail("最多两轮降级 + 原始一次 = 3: {}".format(session.calls))
        else:
            print("[ok] 关完还失败不再重试, 调用次数 = {}".format(len(session.calls)))

        # C4. 测速 ping 是诊断，故意不降级
        req.ResetHttp3EchFallback()
        ping = req.SpeedTestPingReq("https://www.cdngwc.cc")
        ping.SetCurlOpt(True, True, "QkJC", None)
        session = Send(ping, 99)
        if len(session.calls) != 1:
            Fail("测速 ping 不该降级重试: {}".format(session.calls))
        else:
            print("[ok] 测速 ping 不降级(让用户看到 h3 到底通不通)")

        # C5. CDN 图片下载失败 -> 降级后重投（ReDownload）
        req.ResetHttp3EchFallback()

        class FailCtx(object):
            def __enter__(self):
                raise exceptions.Timeout("timed out")

            def __exit__(self, *a):
                return False

        class FailStream(object):
            def stream(self, *a, **kw):
                return FailCtx()

        imageReq = req.DownloadBookReq("https://cdn-msp.jmapiproxy1.cc/a.webp")
        imageReq.SetCurlOpt(True, True, "QkJC", None)
        if imageReq.isH3 is not True:
            Fail("图片请求构造后 HTTP/3 应打开")
        imageTask = Task(imageReq, backParam="")
        imageTask.session = FailStream()
        imageTask.status = Status.Ok
        imageTask.res = res.BaseRes("", False)
        redownloaded = []
        originReDownload = srv.ReDownload
        srv.ReDownload = lambda t: redownloaded.append(t.req)
        try:
            srv.handler["DownloadBookReq"](imageTask)
        finally:
            srv.ReDownload = originReDownload
        if not redownloaded:
            Fail("CDN 图片失败后应降级并 ReDownload")
        elif redownloaded[0].isH3 is not False:
            Fail("CDN 图片重投前应已关掉 HTTP/3")
        else:
            print("[ok] CDN 图片失败: 关 HTTP/3 后重投(ReDownload)")
    finally:
        for name, h in saved.items():
            if h is None:
                srv.handler.pop(name, None)
            else:
                srv.handler[name] = h
finally:
    req.IsAdvancedTlsSupported = originAdvanced
    req.ResetHttp3EchFallback()

if req.IsAdvancedTlsSupported() is not False:
    Fail("测试结束后应还原本机能力探测")

print("\n结果: {}".format("全部通过" if FAILED == 0 else "有 {} 项失败".format(FAILED)))
raise SystemExit(1 if FAILED else 0)
