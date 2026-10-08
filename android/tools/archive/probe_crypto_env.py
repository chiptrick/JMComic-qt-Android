# coding:utf-8
"""探针：确认 venv311 里 pycryptodome / jmcomic 的可用接口(供主机回归测试使用)"""
import sys
print("python", sys.version)
print("optimize", sys.flags.optimize)
try:
    import Crypto
    from Crypto.Cipher import AES
    print("pycryptodome", Crypto.__version__, "AES", AES)
    import Crypto.Util._raw_api as ra
    print("raw_api backend:", ra.backend)
except Exception as es:
    print("Crypto FAIL:", type(es).__name__, es)
try:
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shims"))
    from jmcomic import JmCryptoTool
    import inspect
    print("JmCryptoTool:", [n for n in dir(JmCryptoTool) if not n.startswith("_")])
    for name in ("decode_resp_data", "encode_resp_data"):
        fn = getattr(JmCryptoTool, name, None)
        if fn is not None:
            print("  ", name, inspect.signature(fn))
except Exception as es:
    print("jmcomic FAIL:", type(es).__name__, es)
