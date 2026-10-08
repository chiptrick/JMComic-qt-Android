# coding:utf-8
""" curl_cffi.requests 异常定义(与真实 curl_cffi 同名，保证 except 分支可用) """


class CurlError(Exception):
    """ 所有 curl 错误的基类 """


class RequestException(CurlError):
    pass


class ConnectionError(RequestException):  # noqa: A001 与 curl_cffi 命名保持一致
    pass


class DNSError(ConnectionError):
    pass


class SSLError(ConnectionError):
    pass


class Timeout(RequestException):
    pass


class HTTPError(RequestException):
    pass


class ProxyError(ConnectionError):
    pass


class InterfaceError(RequestException):
    pass


class ContentDecodingError(RequestException):
    pass
