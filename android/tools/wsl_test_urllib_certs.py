#!/usr/bin/env python3
"""逐个测试 p4a 关心的下载 URL 在 python urllib 下能否通过证书校验"""
import os
import ssl
import sys
import urllib.request

URLS = [
    ("openssl", "https://www.openssl.org/source/openssl-3.3.1.tar.gz"),
    ("openssl-ghproxy", "https://ghproxy.net/https://github.com/openssl/openssl/releases/download/openssl-3.3.1/openssl-3.3.1.tar.gz"),
    ("python.org", "https://www.python.org/ftp/python/3.11.13/Python-3.11.13.tgz"),
    ("sqlite.org", "https://www.sqlite.org/2024/sqlite-autoconf-3450100.tar.gz"),
    ("savannah", "https://download.savannah.gnu.org/releases/freetype/freetype-2.13.2.tar.gz"),
    ("ghproxy", "https://ghproxy.net/https://github.com/libffi/libffi/archive/v3.4.2.tar.gz"),
    ("pypi", "https://pypi.tuna.tsinghua.edu.cn/simple/"),
]

ctx = None
mode = sys.argv[1] if len(sys.argv) > 1 else "default"
if mode == "unverified":
    ctx = ssl._create_unverified_context()
    print("(使用未校验上下文)")
elif mode == "certifi":
    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
    print("(使用 certifi:", certifi.where(), ")")
else:
    print("(使用默认上下文, SSL_CERT_FILE=%s)" % os.environ.get("SSL_CERT_FILE"))

for name, url in URLS:
    try:
        req = urllib.request.Request(url, headers={"Range": "bytes=0-100"})
        opener = urllib.request.urlopen(req, timeout=25, context=ctx) if ctx else \
            urllib.request.urlopen(req, timeout=25)
        print("  ok   %-16s %s" % (name, opener.status))
        opener.close()
    except Exception as es:
        print("  FAIL %-16s %s" % (name, str(es)[:110]))
