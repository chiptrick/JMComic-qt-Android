# coding:utf-8
""" curl_cffi.requests 的纯 python 垫片

用途：在没有编出原生 curl_cffi(curl-impersonate)时，让项目仍能联网。
覆盖本项目用到的接口：Session/get/post/put/stream/iter_content/curl_options/
RESOLVE(强制解析到指定 IP)/http 代理/socks5 代理/超时/重定向/gzip。

限制(重要)：
    * 走 http.client + ssl，**没有 Chrome 的 TLS 指纹**，在开启 Cloudflare 严格
      校验的域名上可能被拦截(403/挑战页)。正式包请编出原生 curl_cffi(见
      android/recipes/curl_cffi)。
    * 只支持 HTTP/1.1(不支持 HTTP2/HTTP3、ECH、DOH)。
"""
import gzip
import http.client
import io
import os
import socket
import ssl
import time
import zlib
from datetime import timedelta
from urllib.parse import urlparse, urlunparse

from . import exceptions  # noqa: F401  保证 curl_cffi.requests.exceptions 可访问
from .exceptions import (ConnectionError, DNSError, HTTPError, ProxyError,  # noqa: F401
                         RequestException, SSLError, Timeout)

DefaultTimeout = 30
MaxRedirect = 10
ChunkSize = 64 * 1024

# 近似 Chrome 的 TLS 参数(只是让握手看起来现代一些，不是真正的指纹伪装)
CipherList = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305"
)


class Headers(dict):
    """ 大小写不敏感的 headers 容器 """

    def __init__(self, data=None):
        super().__init__()
        self._keys = {}
        if data:
            for key, value in (data.items() if hasattr(data, "items") else data):
                self[key] = value

    def __setitem__(self, key, value):
        self._keys[key.lower()] = key
        super().__setitem__(key, value)

    def __getitem__(self, key):
        real = self._keys.get(key.lower())
        if real is None:
            raise KeyError(key)
        return super().__getitem__(real)

    def __contains__(self, key):
        return key.lower() in self._keys

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def update(self, other=None, **kwargs):
        data = {}
        if other:
            data.update(other)
        data.update(kwargs)
        for key, value in data.items():
            self[key] = value

    def setdefault(self, key, default=None):
        if key in self:
            return self[key]
        self[key] = default
        return default

    def pop(self, key, *args):
        real = self._keys.pop(key.lower(), None)
        if real is None:
            if args:
                return args[0]
            raise KeyError(key)
        return super().pop(real, *args)

    def copy(self):
        return Headers(dict(self))


class Cookie(object):
    def __init__(self, name, value, domain="", path="/"):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path

    def __repr__(self):
        return "<Cookie {}={}>".format(self.name, self.value)


class Cookies(object):
    def __init__(self):
        self.jar = []

    def set(self, name, value, domain="", path="/"):
        for cookie in self.jar:
            if cookie.name == name and cookie.domain == domain:
                cookie.value = value
                return
        self.jar.append(Cookie(name, value, domain, path))

    def get_dict(self):
        return {cookie.name: cookie.value for cookie in self.jar}

    def update_from_headers(self, rawHeaders, domain=""):
        for value in rawHeaders:
            first = value.split(";")[0]
            if "=" not in first:
                continue
            name, _, val = first.partition("=")
            self.set(name.strip(), val.strip(), domain)

    def to_header(self):
        return "; ".join("{}={}".format(c.name, c.value) for c in self.jar)


class Response(object):
    def __init__(self, statusCode=0, headers=None, content=b"", url="", elapsed=0.0,
                 cookies=None, raw=None, stream=False):
        self.status_code = statusCode
        self.headers = headers if isinstance(headers, Headers) else Headers(headers or {})
        self.url = url
        self.elapsed = timedelta(seconds=elapsed)
        self.cookies = cookies if cookies is not None else Cookies()
        self._content = content
        self._raw = raw if raw is not None else (io.BytesIO(content) if content else io.BytesIO(b""))
        self._closed = False
        self._stream = stream

    @property
    def content(self):
        if self._content is None:
            self._content = self._raw.read()
        return self._content

    @property
    def text(self):
        data = self.content
        encoding = None
        contentType = self.headers.get("content-type", "")
        if "charset=" in contentType.lower():
            encoding = contentType.lower().split("charset=")[-1].split(";")[0].strip()
        for name in (encoding, "utf-8"):
            if not name:
                continue
            try:
                return data.decode(name, "strict")
            except Exception:
                continue
        return data.decode("utf-8", "replace")

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        import json
        return json.loads(self.text)

    def iter_content(self, chunk_size=ChunkSize):
        while True:
            chunk = self._raw.read(chunk_size)
            if not chunk:
                break
            yield chunk

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError("HTTP {}".format(self.status_code))

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if hasattr(self._raw, "close"):
                self._raw.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self):
        return "<Response [{}]>".format(self.status_code)


def _Decompress(data, encoding):
    encoding = (encoding or "").lower()
    try:
        if "gzip" in encoding:
            return gzip.decompress(data)
        if "deflate" in encoding:
            try:
                return zlib.decompress(data)
            except zlib.error:
                return zlib.decompress(data, -zlib.MAX_WBITS)
    except Exception:
        return data
    return data


def _GetCurlOpt():
    """ 取 CurlOpt 枚举

    CurlOpt 定义在 curl_cffi **包顶层**(curl_cffi/__init__.py)，不是 requests 子模块。
    这里原来写成 `from . import CurlOpt`(等价于 import curl_cffi.requests.CurlOpt)，
    必然抛 ImportError，于是每个请求都在 _resolveIp 处失败 —— 真机上表现为"网络错误"。
    """
    from .. import CurlOpt
    return CurlOpt


def _PickResolveIp(resolveList, host, port):
    """ CurlOpt.RESOLVE 形如 ["host:443:1.2.3.4", ...] """
    if not resolveList:
        return None
    for item in resolveList:
        parts = str(item).split(":")
        if len(parts) >= 3 and parts[0].lower() == host.lower():
            return parts[-1]
    return None


def _ConnectTcp(host, port, timeout, resolveIp=None, proxy=None):
    if proxy:
        parsed = urlparse(proxy)
        proxyHost = parsed.hostname
        proxyPort = parsed.port or (1080 if parsed.scheme.startswith("socks") else 8080)
        if parsed.scheme.startswith("socks"):
            try:
                import socks  # PySocks
            except ImportError:
                raise ProxyError("需要 PySocks 才能使用 socks5 代理")
            sock = socks.socksocket()
            sock.set_proxy(socks.SOCKS5, proxyHost, proxyPort,
                           username=parsed.username, password=parsed.password)
            sock.settimeout(timeout)
            try:
                sock.connect((host, port))
            except socket.gaierror as es:
                raise DNSError(str(es))
            except socket.timeout as es:
                raise Timeout(str(es))
            return sock, None
        # http 代理：先连代理
        try:
            sock = socket.create_connection((proxyHost, proxyPort), timeout)
        except socket.gaierror as es:
            raise DNSError(str(es))
        except socket.timeout as es:
            raise Timeout(str(es))
        return sock, (parsed, (proxyHost, proxyPort))

    target = resolveIp or host
    try:
        return socket.create_connection((target, port), timeout), None
    except socket.gaierror as es:
        raise DNSError(str(es))
    except socket.timeout as es:
        raise Timeout(str(es))
    except OSError as es:
        raise ConnectionError(str(es))


def _CreateSslContext():
    """ 建 TLS 上下文

    Android(p4a) 自带的 OpenSSL 没有系统 CA 目录，默认上下文会因为找不到信任根而
    报 "unable to get local issuer certificate" —— 用户看到的就是"网络错误"。
    certifi 已随包，优先用它；拿不到再退回默认(桌面端行为不变)。
    """
    try:
        import certifi
        path = certifi.where()
        if os.path.exists(path):
            return ssl.create_default_context(cafile=path)
    except Exception:
        pass
    return ssl.create_default_context()


def _OpenConnection(parsed, timeout, resolveIp=None, proxy=None, impersonate=None):
    host = parsed.hostname
    isHttps = parsed.scheme == "https"
    port = parsed.port or (443 if isHttps else 80)
    sock, proxyInfo = _ConnectTcp(host, port, timeout, resolveIp, proxy)

    if proxyInfo is not None and isHttps:
        # CONNECT 隧道
        parsedProxy, _ = proxyInfo
        auth = ""
        if parsedProxy.username:
            import base64
            token = "{}:{}".format(parsedProxy.username, parsedProxy.password or "")
            auth = "Proxy-Authorization: Basic {}\r\n".format(
                base64.b64encode(token.encode("utf-8")).decode("ascii"))
        sock.sendall(("CONNECT {0}:{1} HTTP/1.1\r\nHost: {0}:{1}\r\n{2}\r\n"
                      .format(host, port, auth)).encode("utf-8"))
        response = http.client.HTTPResponse(sock)
        response.begin()
        if response.status != 200:
            sock.close()
            raise ProxyError("代理 CONNECT 失败: {}".format(response.status))
        proxyInfo = None

    if isHttps:
        context = _CreateSslContext()
        try:
            context.set_ciphers(CipherList)
        except Exception:
            pass
        try:
            context.set_alpn_protocols(["http/1.1"])
        except Exception:
            pass
        try:
            sock = context.wrap_socket(sock, server_hostname=host)
        except ssl.SSLError as es:
            sock.close()
            raise SSLError(str(es))
        except socket.timeout as es:
            sock.close()
            raise Timeout(str(es))
        except OSError as es:
            sock.close()
            raise ConnectionError(str(es))
    return sock, proxyInfo


class Session(object):
    def __init__(self, impersonate=None, curl_options=None, http_version=None,
                 headers=None, timeout=None, **kwargs):
        self.impersonate = impersonate
        self.http_version = http_version
        self.timeout = timeout or DefaultTimeout
        self.headers = Headers(headers or {})
        self.cookies = Cookies()
        self.proxies = kwargs.get("proxies") or {}
        self._curlOptions = dict(curl_options or {})
        self._closed = False

    # --- curl_options -------------------------------------------------
    @property
    def curl_options(self):
        return self._curlOptions

    @curl_options.setter
    def curl_options(self, value):
        self._curlOptions = dict(value or {})

    def _resolveIp(self, host):
        CurlOpt = _GetCurlOpt()
        return _PickResolveIp(self._curlOptions.get(CurlOpt.RESOLVE), host, 443)

    def _proxyFor(self, scheme, proxies):
        data = proxies if proxies is not None else self.proxies
        if not data:
            return None
        if isinstance(data, dict):
            return data.get(scheme) or data.get("all") or data.get(scheme + "s")
        return str(data)

    # --- 请求 ---------------------------------------------------------
    def request(self, method, url, headers=None, data=None, timeout=None, proxies=None,
                cookies=None, stream=False, allowRedirect=True, **kwargs):
        method = method.upper()
        begin = time.time()
        mergedHeaders = Headers(self.headers)
        mergedHeaders.update(headers or {})
        if cookies:
            mergedHeaders["Cookie"] = "; ".join(
                "{}={}".format(key, value) for key, value in dict(cookies).items())
        if self.cookies.jar and "Cookie" not in mergedHeaders:
            mergedHeaders["Cookie"] = self.cookies.to_header()
        if "Accept-Encoding" not in mergedHeaders:
            mergedHeaders["Accept-Encoding"] = "gzip, deflate"
        mergedHeaders.setdefault("Connection", "close")

        body = data
        if isinstance(body, dict):
            from urllib.parse import urlencode
            body = urlencode(body).encode("utf-8")
            mergedHeaders.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        elif body is None:
            body = b""

        redirectLeft = MaxRedirect if allowRedirect else 0
        currentUrl = url
        while True:
            parsed = urlparse(currentUrl)
            if not parsed.scheme:
                raise RequestException("无效的 url: {}".format(currentUrl))
            resolveIp = self._resolveIp(parsed.hostname)
            proxy = self._proxyFor(parsed.scheme, proxies)
            hostHeader = parsed.hostname
            if parsed.port:
                hostHeader += ":{}".format(parsed.port)
            # 走代理时只有明文 http 用绝对地址(absolute-form)；
            # https 会在 _OpenConnection 里建立 CONNECT 隧道，仍必须是 origin-form
            if proxy and parsed.scheme != "https":
                path = currentUrl
            else:
                path = urlunparse(("", "", parsed.path or "/", parsed.params, parsed.query, ""))
            requestHeaders = Headers(mergedHeaders)
            requestHeaders.setdefault("Host", hostHeader)

            # 原来这里写成 `None if proxy else None`，等价于恒传 None，
            # 于是设置里的 http/socks5 代理被静默忽略
            sock, proxyInfo = _OpenConnection(parsed, timeout or self.timeout, resolveIp,
                                              proxy, self.impersonate)
            try:
                headerText = "{} {} HTTP/1.1\r\n".format(method, path)
                for key, value in requestHeaders.items():
                    if value is None:
                        continue
                    headerText += "{}: {}\r\n".format(key, value)
                headerText += "Content-Length: {}\r\n\r\n".format(len(body))
                sock.sendall(headerText.encode("utf-8") + body)
                raw = http.client.HTTPResponse(sock, method=method)
                raw.begin()
            except socket.timeout as es:
                sock.close()
                raise Timeout(str(es))
            except ssl.SSLError as es:
                sock.close()
                raise SSLError(str(es))
            except OSError as es:
                sock.close()
                raise ConnectionError(str(es))

            rawHeaders = Headers()
            setCookies = []
            for key, value in raw.getheaders():
                if key.lower() == "set-cookie":
                    setCookies.append(value)
                else:
                    rawHeaders[key] = value
            self.cookies.update_from_headers(setCookies, parsed.hostname)

            if raw.status in (301, 302, 303, 307, 308) and redirectLeft > 0:
                location = rawHeaders.get("location")
                if location:
                    raw.read()
                    sock.close()
                    if location.startswith("/"):
                        location = "{}://{}{}".format(parsed.scheme, parsed.hostname, location)
                    elif not location.startswith("http"):
                        location = currentUrl.rsplit("/", 1)[0] + "/" + location
                    if raw.status == 303 or (raw.status in (301, 302) and method == "POST"):
                        method = "GET"
                        body = b""
                        mergedHeaders.pop("Content-Type", None)
                    currentUrl = location
                    redirectLeft -= 1
                    continue

            if stream:
                wrapper = _StreamBody(raw, sock, rawHeaders.get("content-encoding"))
                response = Response(raw.status, rawHeaders, None, currentUrl,
                                    time.time() - begin, self.cookies, raw=wrapper, stream=True)
                response._content = None
                return response

            try:
                content = raw.read()
            except socket.timeout as es:
                sock.close()
                raise Timeout(str(es))
            except OSError as es:
                sock.close()
                raise ConnectionError(str(es))
            finally:
                try:
                    sock.close()
                except Exception:
                    pass
            content = _Decompress(content, rawHeaders.get("content-encoding"))
            return Response(raw.status, rawHeaders, content, currentUrl,
                            time.time() - begin, self.cookies)

    def stream(self, method, url, **kwargs):
        kwargs["stream"] = True
        return self.request(method, url, **kwargs)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def head(self, url, **kwargs):
        return self.request("HEAD", url, **kwargs)

    def close(self):
        self._closed = True
        return

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class AsyncSession(object):
    """ curl_cffi 异步会话的同步替身

    jmcomic 的 jm_async_client 顶层写着 `from curl_cffi.requests import AsyncSession`，
    缺这个名字会让 `from jmcomic import JmCryptoTool` 直接 ImportError，
    于是图片解密(JmCryptoTool)整条链断掉 —— 真机上已复现(每个接口都刷这个 traceback)。
    本项目并不使用 jmcomic 的异步客户端，所以这里用同步 Session 包一层，
    保证 import 与 await 调用都能正常工作。
    """

    def __init__(self, *args, **kwargs):
        self._sync = Session(*args, **kwargs)

    @property
    def curl_options(self):
        return self._sync.curl_options

    @curl_options.setter
    def curl_options(self, value):
        self._sync.curl_options = value

    @property
    def cookies(self):
        return self._sync.cookies

    @property
    def headers(self):
        return self._sync.headers

    async def request(self, *args, **kwargs):
        return self._sync.request(*args, **kwargs)

    async def stream(self, *args, **kwargs):
        return self._sync.stream(*args, **kwargs)

    async def get(self, *args, **kwargs):
        return self._sync.get(*args, **kwargs)

    async def post(self, *args, **kwargs):
        return self._sync.post(*args, **kwargs)

    async def put(self, *args, **kwargs):
        return self._sync.put(*args, **kwargs)

    async def head(self, *args, **kwargs):
        return self._sync.head(*args, **kwargs)

    async def close(self):
        self._sync.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self._sync.close()


class _StreamBody(object):
    """ 把 http.client 的响应体包装成可迭代的流(惰性读取 + 增量解压) """

    def __init__(self, raw, sock, encoding=""):
        self._raw = raw
        self._sock = sock
        self._encoding = (encoding or "").lower()
        self._decompressor = None
        if "gzip" in self._encoding:
            self._decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        elif "deflate" in self._encoding:
            self._decompressor = zlib.decompressobj()

    def read(self, size=-1):
        if self._decompressor is None:
            try:
                data = self._raw.read(size) if size and size > 0 else self._raw.read()
            except socket.timeout as es:
                raise Timeout(str(es))
            except OSError as es:
                raise ConnectionError(str(es))
            return data or b""

        # 有压缩时：读到有解压结果为止，保证 iter_content 不会提前结束
        out = b""
        while True:
            try:
                chunk = self._raw.read(ChunkSize if (not size or size < 0) else size)
            except socket.timeout as es:
                raise Timeout(str(es))
            except OSError as es:
                raise ConnectionError(str(es))
            if chunk:
                try:
                    out += self._decompressor.decompress(chunk)
                except zlib.error:
                    out += chunk
            else:
                try:
                    out += self._decompressor.flush()
                except zlib.error:
                    pass
                break
            if out:
                break
        return out

    def close(self):
        try:
            self._raw.close()
        except Exception:
            pass
        try:
            self._sock.close()
        except Exception:
            pass


def request(method, url, **kwargs):
    # curl_options 必须传进 Session，否则 RESOLVE 之类的选项会被 **kwargs 静默吞掉
    # (user_handler 的测速处理就是 requests2.get(..., curl_options=...) 这种用法，
    #  丢掉 RESOLVE 会导致测速打到 DNS 解析结果而不是待测 IP)
    curlOptions = kwargs.pop("curl_options", None)
    session = Session(impersonate=kwargs.pop("impersonate", None), curl_options=curlOptions)
    with session:
        return session.request(method, url, **kwargs)


def get(url, **kwargs):
    return request("GET", url, **kwargs)


def post(url, **kwargs):
    return request("POST", url, **kwargs)


def put(url, **kwargs):
    return request("PUT", url, **kwargs)


def head(url, **kwargs):
    return request("HEAD", url, **kwargs)
