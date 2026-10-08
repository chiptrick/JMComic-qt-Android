# NOTICE —— 归属、第三方组件与许可

本仓库是 [tonquer/JMComic-qt](https://github.com/tonquer/JMComic-qt) 的**修改版**
（Android 移植分支）。

## 1\. 上游归属

* 上游项目：**JMComic-qt** — [https://github.com/tonquer/JMComic-qt](https://github.com/tonquer/JMComic-qt)
* 上游许可证：**GNU Lesser General Public License v3.0**，见本仓库 [LICENSE](LICENSE)
* 本仓库对上游代码的修改（Android 移植、竖屏适配、NPU 超分接入、构建脚本）同样以
**LGPL v3** 提供。按 LGPL v3 第 4 条的要求，修改内容与日期可通过本仓库的
git 提交历史追溯，集中说明见 [android/README.md](android/README.md)。
* 版权归原作者所有；本分支不主张上游代码的版权。

## 2\. 本仓库不分发的内容

|内容|说明|
|-|-|
|waifu2x / Real-ESRGAN 等 **ONNX 模型权重**|`.gitignore` 排除了 `android/sr\_qnn/models/\*.onnx`。请按 [android/sr\_qnn/models/README.md](android/sr_qnn/models/README.md) 用 `android/tools/prepare\_models.py` 自行生成|
|**真机日志、截图、真机配置**|`.gitignore` 排除了 `android/build\_logs/`（含账号、代理 IP、下载样本，属于运行数据，不入库）|
|**漫画内容**|本仓库只有客户端代码，不含任何漫画图片或用户数据|

## 3\. 第三方组件

运行时会用到下列组件。**许可证以上游项目为准**，下表仅列出主要来源，用于说明依赖关系。

### 桌面端与共用（`src/requirements\*.txt`）

|组件|用途|许可证（以上游为准）|
|-|-|-|
|[PySide6 / Qt for Python](https://www.qt.io/qt-for-python)|界面框架（含 Android 版）|LGPL-3.0|
|[Pillow](https://python-pillow.org/)|图片解码/编码|MIT-CMU|
|[pycryptodomex](https://www.pycryptodome.org/)|接口 AES 解密|BSD-2-Clause / Public Domain|
|[lxml](https://lxml.de/)|HTML 解析|BSD-3-Clause|
|[beautifulsoup4](https://www.crummy.com/software/BeautifulSoup/)|HTML 解析|MIT|
|[PySocks](https://github.com/Anorov/PySocks)|代理|BSD|
|[natsort](https://github.com/SethMMorton/natsort)|自然排序|MIT|
|[curl\_cffi](https://github.com/lexiforest/curl_cffi)|HTTP（模拟浏览器指纹），内含 [curl-impersonate](https://github.com/lwthiker/curl-impersonate) / curl|MIT|
|[jmcomic](https://github.com/hect0x7/JMComic-Crawler-Python)|禁漫接口与图片分割算法|MIT|
|[webdavclient3](https://github.com/designerror/webdav-client-python-3)|WebDAV 上传|MIT|
|[tqdm](https://github.com/tqdm/tqdm)|进度条|MPL-2.0 / MIT|
|[pysmb](https://github.com/miketeo/pysmb)|SMB 上传|以上游为准|
|[smbprotocol](https://github.com/jborean93/smbprotocol)|SMB 上传|MIT|
|[cryptography](https://github.com/pyca/cryptography)|macOS/Win7 依赖|Apache-2.0 / BSD-3-Clause|
|[sr-vulkan](https://github.com/tonquer/sr-vulkan)|桌面端超分|以上游为准|

### Android 打包链

|组件|用途|许可证（以上游为准）|
|-|-|-|
|[python-for-android](https://github.com/kivy/python-for-android)|把 Python 运行时与依赖打进 APK|MIT|
|[buildozer](https://github.com/kivy/buildozer)|构建前端|MIT|
|[CPython](https://www.python.org/)|打包进 APK 的 Python 3.11 运行时|PSF-2.0|
|[OpenSSL](https://www.openssl.org/)|TLS（由 p4a 编译）|Apache-2.0|
|[ONNX Runtime](https://github.com/microsoft/onnxruntime)（`onnxruntime-android-qnn`）|NPU 推理|MIT|
|[Qualcomm QNN SDK](https://www.qualcomm.com/developer/software/qualcomm-ai-engine-direct) 运行时（`qnn-runtime` AAR / `libQnnHtp.so` 等）|高通 NPU 后端|**Qualcomm 专有许可**，见下|
|[Android NDK](https://developer.android.com/ndk)|编译 `libsr\_qnn.so`|Android NDK 许可|

> \*\*Qualcomm QNN 运行时是专有组件\*\*：它由 Qualcomm 的 SDK 提供，\*\*不是\*\*开源软件。
> 用它构建出来的 APK 会包含 Qualcomm 的运行时库。\*\*要分发这类 APK，请先自行确认
> 你符合 Qualcomm 的相关许可条款\*\*（例如 Qualcomm AI Engine Direct / QNN SDK 的
> 再分发条件）。本仓库只提供构建脚本，不代为授予任何 Qualcomm 组件的权利。
> 不需要 NPU 超分的场景可以只编译 `requirements\_nosr.txt` 对应的桌面版，或把
> `JM\_QNN\_BACKEND` 指向 CPU 后端。

### 模型与算法来源

|内容|来源|说明|
|-|-|-|
|waifu2x cunet 权重|HuggingFace 上的 waifu2x ONNX 转换仓库（见 [models/README.md](android/sr_qnn/models/README.md)）|**本仓库不包含权重文件**；许可证以该来源仓库为准|
|waifu2x / Real-ESRGAN / Real-CUGAN 算法|[waifu2x-ncnn-vulkan](https://github.com/nihui/waifu2x-ncnn-vulkan)、[Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)、[realcugan-ncnn-vulkan](https://github.com/nihui/realcugan-ncnn-vulkan)|桌面端超分沿用上游实现|
|图片分割算法|[JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python)|Android 侧与其 `decode\_and\_save` 逐像素对齐|

## 4\. 免责声明

* 本项目仅供技术研究与学习交流，**请勿用于其他用途**；请遵守你所在地区的法律法规。
* 本项目与内容提供方没有任何关联；代码中的接口地址来自第三方公开实现。
* 使用本项目产生的任何后果由使用者自行承担。

