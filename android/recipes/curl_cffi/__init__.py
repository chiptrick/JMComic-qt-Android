# coding:utf-8
"""python-for-android recipe: curl_cffi(官方 android wheel 解包)

背景
----
curl_cffi 需要 **curl-impersonate** 版本的 libcurl(Chrome 的 TLS/HTTP2 指纹 +
HTTP/3 + ECH)。最早这里放的是"用 NDK 自编 curl-impersonate 再编 cffi 扩展"的
recipe，交叉编译链路在 p4a 下跑不通(见 android/README.md §3.10)。

2026-09 起上游发布官方 Android wheel(`android_24_arm64_v8a`)，里面已经静态编好
BoringSSL + ngtcp2/nghttp3(HTTP/3) + ECH，所以这里改成**解包 wheel 进 site-packages**，
与 Qt deploy 工具生成的 PySide6 recipe 同一思路：

    curl_cffi/_wrapper.abi3.so 的 NEEDED：
        libpython3.14.so          -> 目标 CPython 必须是 3.14(见 tools/wsl_patch_p4a_versions.sh)
        libc++_shared-d523468d.so -> 带 hash 的 SONAME，本 recipe 把 NDK 的
                                     libc++_shared.so 按这个文件名放一份进 lib/arm64-v8a/
                                     (与 libpyside6.abi3.so 同层，linker 才找得到)

wheel 的下载与 sha256 校验见 android/tools/wsl_fetch_curl_cffi.sh；没下载就报错，
不在 recipe 里偷偷联网。

用法(buildozer.spec)：
    requirements = python3,...,curl_cffi
    p4a.local_recipes = android/deployment/recipes
"""
import os
import shutil
import zipfile

from pythonforandroid.logger import info
from pythonforandroid.recipe import PythonRecipe

WHEEL_NAME = "curl_cffi-0.16.3-cp314-cp314-android_24_arm64_v8a.whl"
# wheel 里 _wrapper.abi3.so 的 SONAME 依赖(上游按 NDK 版本取的 hash，固定不变)
CPP_SHARED_NAME = "libc++_shared-d523468d.so"


def FindWheel():
    """ 优先环境变量；再按"recipe 被拷到 deployment/recipes 之后"与"源码位置"两套布局找 """
    env = os.environ.get("JM_CURL_CFFI_WHEEL", "")
    if env and os.path.isfile(env):
        return os.path.abspath(env)
    here = os.path.dirname(os.path.abspath(__file__))
    for rel in (
        os.path.join("..", "..", "..", "wheels", WHEEL_NAME),   # <android>/deployment/recipes/curl_cffi
        os.path.join("..", "..", "wheels", WHEEL_NAME),         # <android>/recipes/curl_cffi
    ):
        path = os.path.join(here, rel)
        if os.path.isfile(path):
            return os.path.abspath(path)
    return ""


class CurlCffiRecipe(PythonRecipe):
    name = "curl_cffi"
    version = "0.16.3"
    # curl_cffi 的 METADATA 声明运行时依赖：__init__ 首行就是 `import _cffi_backend`
    depends = ["cffi", "certifi"]
    call_hostpython_via_targetpython = False
    install_in_hostpython = False

    def build_arch(self, arch):
        wheel = FindWheel()
        if not wheel:
            raise Exception(
                "缺少 {}：先跑 android/tools/wsl_fetch_curl_cffi.sh 下载官方 android wheel"
                .format(WHEEL_NAME))

        info("解包 {} 到 site-packages".format(wheel))
        with zipfile.ZipFile(wheel, "r") as z:
            names = z.namelist()
            z.extractall(self.ctx.get_python_install_dir(arch.arch))
        info("  {} 个文件, 其中 .so: {}".format(
            len(names), [n for n in names if n.endswith(".so")]))

        # _wrapper.abi3.so NEEDED libc++_shared-d523468d.so：按这个文件名放一份
        # (PySide6 那边是普通名字的 libc++_shared.so，两份并存，各链各的)
        src = "{}/{}/libc++_shared.so".format(self.ctx.ndk.sysroot_lib_dir, arch.command_prefix)
        dst = "{}/{}".format(self.ctx.get_libs_dir(arch.arch), CPP_SHARED_NAME)
        if not os.path.isfile(src):
            raise Exception("找不到 NDK 的 libc++_shared.so: {}".format(src))
        shutil.copyfile(src, dst)
        info("  {} -> {}".format(src, dst))


recipe = CurlCffiRecipe()
