# coding:utf-8
"""python-for-android recipe: curl_cffi(基于 curl-impersonate 的原生 TLS 指纹)

这是 Android 移植里最难缠的依赖：curl_cffi 需要 **curl-impersonate** 版本的
libcurl(带 Chrome 的 TLS/HTTP2 指纹)，而官方没有 Android 预编译包，需要在
构建时用 NDK 自己编一份。

本 recipe 做两件事：
    1. 用 NDK 编译 curl-impersonate(静态 libcurl.a + 头文件)，产物放在
       $CURL_IMPERSONATE_ANDROID/<abi>/lib/libcurl.a
       若该目录已存在(比如你自己编好了/团队缓存了)，直接复用，跳过编译。
    2. 用上述 libcurl 编译 curl_cffi 的 python 扩展(cffi)。

用法(buildozer.spec)：
    requirements = python3,kivy,pyside6,...,curl_cffi
    p4a.local_recipes = android/recipes

需要的环境变量(可用 buildozer.spec 的 [app] 段或 shell 导出)：
    CURL_IMPERSONATE_VERSION  默认 v0.6.1(curl-impersonate-chrome 标签)
    CURL_IMPERSONATE_ANDROID  缓存/产物目录，默认 ~/.cache/curl-impersonate-android
    ANDROID_NDK_HOME          必填

注意：curl-impersonate 上游的 android 支持随版本变化，若某版本编不过，
可以退回 android/shims/curl_cffi(纯 python 垫片，功能可用但没有 TLS 指纹伪装)。
"""
import os

from pythonforandroid.recipe import CompiledComponentsPythonRecipe
from pythonforandroid.toolchain import current_directory, shprint  # noqa: F401
import sh


class CurlCffiRecipe(CompiledComponentsPythonRecipe):
    version = "0.13.0"
    url = "https://github.com/lexiforest/curl_cffi/archive/refs/tags/v{version}.tar.gz"
    # curl_cffi 依赖 cffi / certifi / typing_extensions
    depends = ["setuptools", "cffi", "openssl", "certifi"]
    call_hostpython_via_targetpython = False

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        prefix = self.ImpersonatePrefix(arch)
        env["CURL_IMPERSONATE_PREFIX"] = prefix
        # 让 cffi/setuptools 找到 curl-impersonate
        env["CFLAGS"] = "{} -I{}/include -DCURL_STATICLIB=1".format(
            env.get("CFLAGS", ""), prefix)
        env["LDFLAGS"] = "{} -L{}/lib -lcurl -lssl -lcrypto -lz -ldl".format(
            env.get("LDFLAGS", ""), prefix)
        env["PKG_CONFIG_PATH"] = "{}/lib/pkgconfig".format(prefix)
        env["CURL_CFFI_USE_STATIC_LIBCURL"] = "1"
        return env

    @staticmethod
    def ImpersonateDir():
        return os.environ.get(
            "CURL_IMPERSONATE_ANDROID",
            os.path.join(os.path.expanduser("~"), ".cache", "curl-impersonate-android"))

    def ImpersonatePrefix(self, arch):
        return os.path.join(self.ImpersonateDir(), arch.arch)

    def BuildImpersonate(self, arch):
        """ 用 NDK 编译 curl-impersonate(仅当缓存里没有时) """
        prefix = self.ImpersonatePrefix(arch)
        if os.path.exists(os.path.join(prefix, "lib", "libcurl.a")):
            return prefix

        version = os.environ.get("CURL_IMPERSONATE_VERSION", "v0.6.1")
        workDir = os.path.join(self.ImpersonateDir(), "src")
        if not os.path.exists(workDir):
            os.makedirs(os.path.dirname(workDir), exist_ok=True)
            shprint(sh.git, "clone", "--depth", "1", "--branch", version,
                    "https://github.com/lwthiker/curl-impersonate.git", workDir)

        ndk = os.environ.get("ANDROID_NDK_HOME") or os.environ.get("ANDROID_NDK_ROOT")
        if not ndk:
            raise Exception("请设置 ANDROID_NDK_HOME 才能编译 curl-impersonate")

        api = os.environ.get("CURL_IMPERSONATE_API", "34")
        target = "aarch64-linux-android" if arch.arch == "arm64-v8a" else "armv7a-linux-androideabi"
        toolchain = os.path.join(ndk, "toolchains", "llvm", "prebuilt", "linux-x86_64", "bin")
        env = os.environ.copy()
        env["CC"] = os.path.join(toolchain, "{}{}-clang".format(target, api))
        env["CXX"] = os.path.join(toolchain, "{}{}-clang++".format(target, api))
        env["AR"] = os.path.join(toolchain, "llvm-ar")
        env["RANLIB"] = os.path.join(toolchain, "llvm-ranlib")
        env["STRIP"] = os.path.join(toolchain, "llvm-strip")
        env["CFLAGS"] = "-fPIC -O2"
        env["CXXFLAGS"] = "-fPIC -O2"
        env["LDFLAGS"] = "-fPIC"

        # curl-impersonate 提供 makefile-based 构建；--prefix 指向我们的缓存目录
        with current_directory(workDir):
            shprint(sh.make, "clean", _env=env, _tail=20, _critical=False)
            shprint(sh.make, "build", _env=env, _tail=20, _critical=False)
            shprint(sh.make, "install", "PREFIX={}".format(prefix), _env=env, _tail=20)
        if not os.path.exists(os.path.join(prefix, "lib", "libcurl.a")):
            raise Exception("curl-impersonate 编译失败，请检查 NDK/版本；"
                            "也可以改用 android/shims/curl_cffi 垫片")
        return prefix

    def prebuild_arch(self, arch):
        super().prebuild_arch(arch)
        self.BuildImpersonate(arch)

    def get_recipe_env_with_curl(self, arch):
        return self.get_recipe_env(arch)


recipe = CurlCffiRecipe()
