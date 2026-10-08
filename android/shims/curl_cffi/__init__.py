# coding:utf-8
""" curl_cffi 顶层兼容层(纯 python 垫片)

仅当真正的 curl_cffi(原生 curl-impersonate 扩展)不可用时才使用，见 android/README.md。
实现的是本项目用到的子集：
    CurlOpt / CurlHttpVersion / CurlSslVersion / Session / requests
"""
from . import requests  # noqa: F401
from .requests import (AsyncSession, Session, Response, get, post, put,  # noqa: F401
                       request, head)

__version__ = "0.0.0-shim"


class _Enum(object):
    def __init__(self, names):
        for index, name in enumerate(names):
            setattr(self, name, index + 10000)

    def __contains__(self, item):
        return isinstance(item, int)


# curl_easy_setopt 里的常用枚举(值与 libcurl 一致的部分不影响使用，语义够用即可)
CurlOpt = _Enum([
    "URL", "WRITEFUNCTION", "HEADERFUNCTION", "POSTFIELDS", "HTTPHEADER", "CUSTOMREQUEST",
    "TIMEOUT", "CONNECTTIMEOUT", "PROXY", "PROXYTYPE", "FOLLOWLOCATION", "MAXREDIRS",
    "SSL_VERIFYPEER", "SSL_VERIFYHOST", "SSLVERSION", "HTTP_VERSION", "RESOLVE",
    "DNS_CACHE_TIMEOUT", "DOH_URL", "ECH", "ALLO", "COOKIE", "ACCEPT_ENCODING", "USERAGENT",
])

CurlHttpVersion = _Enum(["V1_0", "V1_1", "V2_0", "V2TLS", "V2_PRIOR_KNOWLEDGE", "V3", "V3ONLY"])
CurlSslVersion = _Enum(["DEFAULT", "TLSv1", "TLSv1_0", "TLSv1_1", "TLSv1_2", "TLSv1_3"])
CurlInfo = _Enum(["RESPONSE_CODE", "TOTAL_TIME", "EFFECTIVE_URL"])
CurlMOption = _Enum(["PIPEWAIT"])
CurlWsFlag = _Enum(["TEXT", "BINARY"])
CurlWsOpcode = _Enum(["CONT", "TEXT", "BINARY", "CLOSE", "PING", "PONG"])


class Curl(object):
    """ 只提供最小可用实现(本项目未直接使用) """

    def __init__(self, *args, **kwargs):
        self._options = {}

    def setopt(self, option, value):
        self._options[option] = value

    def getinfo(self, info):
        return 0

    def close(self):
        return

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
