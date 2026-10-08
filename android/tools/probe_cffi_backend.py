# coding:utf-8
"""验证 pycryptodome 的 cffi 后端在"APK 里那套 cffi/pycparser 版本"下能不能用

真机上 pycryptodome 只能走 cffi 后端(p4a 的 Qt bootstrap 把 PYTHONOPTIMIZE 设成 2，
ctypes 后端又因为 ctypes.pythonapi 解析不到 PyObject_GetBuffer 而不可用)。
APK 里带的是 p4a 的 pycparser 2.14 配方 + cffi 2.0.0，所以必须确认这两个版本能配合。

用法: python3 android/tools/probe_cffi_backend.py
"""
import sys

print("python", sys.version.split()[0], "optimize", sys.flags.optimize)
try:
    import cffi
    print("cffi", cffi.__version__)
except Exception as es:
    print("cffi 不可用:", es)
    raise SystemExit(1)
try:
    import pycparser
    print("pycparser", pycparser.__version__)
except Exception as es:
    print("pycparser 不可用:", es)
    pycparser = None

# 1) 最小 ABI 用例：ffi.cdef + ffi.dlopen + 调用 libc
try:
    from cffi import FFI
    ffi = FFI()
    ffi.cdef("int abs(int);")
    libc = ffi.dlopen("libc.so.6")
    print("cffi ABI(cdef+dlopen) OK, abs(-7) =", libc.abs(-7))
except Exception as es:
    print("cffi ABI 失败:", type(es).__name__, es)

# 2) pycryptodome 走哪条后端
try:
    from Crypto.Util import _raw_api
    print("pycryptodome backend:", _raw_api.backend)
except Exception as es:
    print("pycryptodome _raw_api 失败:", type(es).__name__, es)

# 3) AES-ECB 往返
try:
    from Crypto.Cipher import AES
    key = b"0123456789abcdef"
    payload = b'{"code":200,"data":[]}'
    pad = 16 - len(payload) % 16
    raw = payload + bytes([pad]) * pad
    enc = AES.new(key, AES.MODE_ECB).encrypt(raw)
    dec = AES.new(key, AES.MODE_ECB).decrypt(enc)
    ok = dec[:-dec[-1]] == payload
    print("AES-ECB 往返:", ok)
except Exception as es:
    print("AES 失败:", type(es).__name__, es)
