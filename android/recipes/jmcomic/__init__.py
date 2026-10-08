# coding:utf-8
"""python-for-android recipe: jmcomic

为什么需要它：
    jmcomic 依赖 curl-cffi，而 curl-cffi 在 Android 上没有可用的 wheel(需要
    curl-impersonate 原生库)。本项目在 Android 上用 android/shims/curl_cffi
    (纯 python 垫片，随 APK 作为 assets 打包)替代，因此 jmcomic 必须**跳过依赖解析**安装，
    只装本体，其余依赖由 buildozer.spec 的 requirements 显式提供。

    jmcomic 在本项目里只用到 JmCryptoTool(图片分块解密)，导入依赖情况：
        PIL       -> 顶层导入(jm_toolkit)，由 pillow recipe 提供
        Crypto    -> 函数内导入，pycryptodome recipe 提供
        yaml      -> 函数内导入，本项目不触发
        curl_cffi -> jm_async_client 顶层导入，由垫片提供

注意：p4a 会按 recipe 名(小写 jmcomic)匹配目录。
"""
from pythonforandroid.recipe import PythonRecipe


class JmcomicRecipe(PythonRecipe):
    version = "2.7.7"
    url = "https://files.pythonhosted.org/packages/source/j/jmcomic/jmcomic-{version}.tar.gz"
    depends = ["python3", "setuptools", "pillow"]
    # 关键：不解析依赖(否则会去编译 curl-cffi 而失败)
    setup_extra_args = ["--no-deps"]
    call_hostpython_via_targetpython = False


recipe = JmcomicRecipe()
