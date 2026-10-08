# coding:utf-8
"""真机 AES 不可用问题的回归测试(主机侧)

背景(真机 logcat 实录)
---------------------
    File ".../Crypto/Util/_raw_api.py", line 173, in <module>
        from ctypes.util import find_library
    File ".../python3/Lib/ctypes/util.py", line 11, in <module>
        from android._ctypes_library_finder import find_library as _find_lib
    File ".../site-packages/android/__init__.py", line 8, in <module>
        from android._android import *
    ImportError: dlopen failed: cannot locate symbol "WebView_AndroidGetJNIEnv"
                 referenced by ".../site-packages/android/_android.so"
    During handling of the above exception, another exception occurred:
    ImportError: CFFI with optimize=2 fails due to pyparser bug.

p4a 的 Qt bootstrap 硬编码 PYTHONOPTIMIZE=2，pycryptodome 因此**主动**放弃 cffi 后端、
回落到 ctypes 后端；而 ctypes 后端的第一行 import 被 p4a 打的 android 补丁炸掉，
于是 Crypto.Cipher.AES 永远导入失败 —— jmcomic 每个接口的响应都是密文，全都解析不了。

本测试用**子进程**复现这个过程，分两个阶段：
    before: 放一个"导入即失败"的 android 包(等价于真机上 dlopen 失败)，断言复现失败
    after : 先调 platform_mobile.InstallCtypesLibraryFinder()，断言补丁行可用、
            AES 可用、jmcomic 的 decode_resp_data 能真正解出明文

用法: python3 android/tools/host_test_crypto_android.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(REPO, "src")
SHIMS = os.path.join(REPO, "android", "shims")

# 与真机 p4a 生成的 android/__init__.py 等价：顶层就 import 一个加载不了的扩展
FAKE_ANDROID_INIT = '''\
# 等价于 p4a 的 android 包：这一行在 bootstrap=qt 下必然 dlopen 失败
from android._android import *  # noqa
'''

FAKE_ANDROID_FINDER = '''\
# 等价于 p4a 的 _ctypes_library_finder：依赖没有打进 APK 的 pyjnius
from jnius import autoclass


def find_library(name):
    raise AssertionError("不应该走到这里")
'''

CHILD = r'''
import os
import sys

phase = sys.argv[1]
sys.path.insert(0, os.environ["JM_FAKE_ANDROID"])
sys.path.insert(0, os.environ["JM_SHIMS"])
sys.path.insert(0, os.environ["JM_SRC"])


def Check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        sys.exit(1)


# 复现 p4a 补丁后的 ctypes/util.py 顶层那两行
def PatchedImport():
    from android._ctypes_library_finder import find_library as _find_lib
    return _find_lib


if phase == "before":
    try:
        PatchedImport()
    except Exception as es:
        print("ok   复现成功: {}".format(type(es).__name__))
        print("     " + str(es)[:120])
        sys.exit(0)
    print("FAIL 竟然导入成功，没能复现真机现象")
    sys.exit(1)

from tools import platform_mobile
Check(platform_mobile.InstallCtypesLibraryFinder(force=True), "装上了 android 垫片")

findLib = PatchedImport()
Check(callable(findLib), "p4a 补丁行 `from android._ctypes_library_finder import find_library` 可用")
Check(not getattr(findLib, "__module__", "").startswith("jnius"), "用的是我们自己的实现")

import ctypes.util
Check(ctypes.util.find_library is not None, "import ctypes.util 成功")

# p4a 的 android/__init__.py 绝不能被真的执行
real = sys.modules["android"]
Check(getattr(real, "__jmcomic_shim__", False), "sys.modules['android'] 是我们的垫片")
Check(not hasattr(real, "_android"), "没有去 dlopen _android.so")

# 真机用的是绝对路径加载原生库，find_library 只是必须"能 import"
try:
    from Crypto.Util import _raw_api
    Check(_raw_api.backend in ("ctypes", "cffi"), "pycryptodome backend={}".format(_raw_api.backend))
except Exception as es:
    Check(False, "pycryptodome _raw_api 导入失败: {}".format(es))

from Crypto.Cipher import AES
from hashlib import md5
import base64
import time

ts = int(time.time())
payload = '{"code":200,"data":[]}'
# 先用一个固定的 16 字节 key 验证 AES-ECB 本身可用(与密钥怎么派生无关)
key = b"0123456789abcdef"
pad = 16 - len(payload) % 16
raw = payload.encode() + bytes([pad]) * pad
enc = base64.b64encode(AES.new(key, AES.MODE_ECB).encrypt(raw)).decode()
dec = AES.new(key, AES.MODE_ECB).decrypt(base64.b64decode(enc))
Check(dec[:-dec[-1]].decode() == payload, "AES-ECB 加解密往返正确")

# 用 jmcomic 真正会走的那条路(Secret 从 jmcomic 自己的常量取，不写死)
from jmcomic import JmCryptoTool, JmMagicConstants

ts2 = int(time.time())
key2 = md5("{}{}".format(ts2, JmMagicConstants.APP_DATA_SECRET).encode()).hexdigest().encode()
raw2 = payload.encode()
pad2 = 16 - len(raw2) % 16
raw2 += bytes([pad2]) * pad2
enc2 = base64.b64encode(AES.new(key2, AES.MODE_ECB).encrypt(raw2)).decode()
got = JmCryptoTool.decode_resp_data(enc2, ts=ts2)
Check(got == payload, "jmcomic.JmCryptoTool.decode_resp_data 解出明文: {!r}".format(got))
print("ALL OK")
'''


def RunChild(scriptPath, fakeDir, phase):
    env = dict(os.environ)
    env["JM_FAKE_ANDROID"] = fakeDir
    env["JM_SRC"] = SRC
    env["JM_SHIMS"] = SHIMS
    env["PYTHONPATH"] = os.pathsep.join([SRC, SHIMS])
    proc = subprocess.run([sys.executable, scriptPath, phase], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def CheckOptimizeLevels():
    """-OO/-O 下 pycryptodome 选的后端必须不同

    这是"真机 AES 修好了没有"的核心机制：
      -OO (等价于 p4a 原来的 PYTHONOPTIMIZE=2) -> pycryptodome 主动放弃 cffi，回落 ctypes；
            而 ctypes 后端在 Android 上必炸(ctypes.pythonapi 解析不到 PyObject_GetBuffer)
      -O  (p4a bootstrap 改成 1)               -> 走 cffi，AES 可用
    主机上 ctypes 后端恰好能用，所以只能断言"后端选的是哪个"，不能断言"失败"。
    """
    probe = os.path.join(HERE, "probe_cffi_backend.py")
    failed = 0
    print("\n===== 优化级别与后端选择 =====")
    for flag, expect in (("-OO", "ctypes"), ("-O", "cffi")):
        proc = subprocess.run([sys.executable, flag, probe],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        text = proc.stdout.decode("utf-8", "replace")
        line = [ln for ln in text.splitlines() if ln.startswith("pycryptodome backend:")]
        got = line[0].split(":", 1)[1].strip() if line else "(无)"
        ok = (got == expect)
        print("{} python {} -> backend={} (期望 {})".format(
            "ok  " if ok else "FAIL", flag, got, expect))
        if not ok:
            failed += 1
    return failed


def Main():
    print("python:", sys.version.replace("\n", " "))
    with tempfile.TemporaryDirectory() as tmp:
        fakeDir = os.path.join(tmp, "fake")
        os.makedirs(os.path.join(fakeDir, "android"))
        with open(os.path.join(fakeDir, "android", "__init__.py"), "w", encoding="utf-8") as f:
            f.write(FAKE_ANDROID_INIT)
        with open(os.path.join(fakeDir, "android", "_ctypes_library_finder.py"), "w",
                  encoding="utf-8") as f:
            f.write(FAKE_ANDROID_FINDER)

        scriptPath = os.path.join(tmp, "child.py")
        with open(scriptPath, "w", encoding="utf-8") as f:
            f.write(CHILD)

        failed = 0
        for phase in ("before", "after"):
            print("\n===== 子进程阶段: {} =====".format(phase))
            code, text = RunChild(scriptPath, fakeDir, phase)
            print(text.rstrip())
            if code != 0:
                failed += 1
                print("阶段 {} 失败(退出码 {})".format(phase, code))
        failed += CheckOptimizeLevels()
        print("\n结果: {}".format("全部通过" if failed == 0 else "有 {} 项失败".format(failed)))
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(Main())
