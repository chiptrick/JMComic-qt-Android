# JMComic-qt · Android 移植分支

> ## ⚠️ AI 生成声明
>
> **本分支的 Android 移植工作由 AI 生成。** 具体包括：
>
> * `android/` 整个目录 —— 打包工程、`libsr_qnn.so` 原生代码（C++/QNN）、模型转换工具、
>   全部构建与验证脚本、`android/README.md`
> * `src/` 下的移动端适配层与相关改动 —— `tools/mobile_ui.py`、`tools/platform_mobile.py`、
>   `tools/mobile_file_dialog.py`、`tools/sr_backend.py`、`tools/waifu2x_check.py`，
>   以及各 `view/` / `task/` / `widget/` 里的移动端分支
> * 本 README、[NOTICE.md](NOTICE.md)、`android/tools/README.md` 等文档
>
> **上游的桌面端代码不是 AI 生成的**，它是原作者 tonquer 等人的作品（见
> [许可证与署名](#许可证与署名) 与 [NOTICE.md](NOTICE.md)）。请不要把整个仓库笼统称为
> “AI 项目”——那等于把上游的工作也划到 AI 名下。
>
> **AI 生成意味着请自行审阅后再使用。** 这些代码经过真机验证和一套宿主回归
> （`android/tools/`，CI 每次提交都会跑），但覆盖并不完整，**不代表没有安全或正确性缺陷**，
> 也不提供任何担保。
>
> 生成方式：由 AI 编码代理在真机上反复实测（日志、像素级比对、adb 断言）+ 宿主回归测试驱动，
> 逐轮定位根因后修改；`android/README.md` 里记录了每一轮的根因与修法。

禁漫天堂第三方客户端。本仓库是 [tonquer/JMComic-qt](https://github.com/tonquer/JMComic-qt) 的
**Android 移植分支**：在上游桌面版（Windows / Linux / macOS）的基础上，增加了完整的 Android
手机版，并针对竖屏重做了界面适配。

> - 本项目**仅供技术研究学习**，请勿用于其他用途，请遵守你所在地区的法律法规。
> - 这是**修改版**，不是上游官方版本。桌面端问题请先看 [NOTICE.md](NOTICE.md) 里的归属说明。
> - 发现问题欢迎提 ISSUE，但请说明是**桌面端**还是 **Android** 的问题。

## 与上游的差异

本分支只做加法，桌面端行为不变（移动端适配层都用 `tools/platform_mobile.IsAndroid()` 和
`tools/mobile_ui.IsEnabled()` 做了门控，非 Android 直接短路）。

| 改动 | 说明 |
| --- | --- |
| **Android 打包** | PySide6(Qt for Android) + python-for-android/buildozer，只出 `arm64-v8a`，最低 **Android 14 (API 34)** |
| **竖屏界面适配** | 抽屉式导航、首页双列封面、详情页堆叠、返回键处理、无系统托盘时降级、最小尺寸放宽、应用内文件选择器（替换在 Android 上会卡死的 `QFileDialog`） |
| **Waifu2x 走高通 NPU** | `libsr_qnn.so`（QNN/HTP）+ `onnxruntime-android-qnn`，9 组共 39 个固定 shape 模型，可选 fp16 / 量化 |
| **两处 Android 专有的坑** | `bootstrap=qt` 下 AES 解密必须补 `ctypes.util`；`PYTHONOPTIMIZE=2` 会让 ctypes 后端在 Android 上必死 —— 详见 [android/README.md](android/README.md) §3.1/§3.2 |

## 下载与安装

* **Android**：构建产物是 `android/JMComic-<版本>-arm64-v8a-debug.apk`。
  这是**调试包（debug 签名）**，直接安装即可自用；要对外分发请自己重新签名。
  debug 包体积较大（约 270MB，含 Qt、Python 运行时和 39 个超分模型）。
* **桌面端**：请到上游 [Releases](https://github.com/tonquer/JMComic-qt/releases) 下载，
  本分支没有额外提供桌面端安装包。

### Android 使用前提

* Android 14 (API 34) 及以上，`arm64-v8a`
* 首次运行需要存储权限（用于下载目录与本地漫画）
* 超分默认使用高通 NPU；非高通机型会在设置里回退到 CPU 后端

## 功能

* 已实现禁漫天堂大部分功能：登录、搜索、漫画详情、下载、看图、本地收藏、NAS 上传
* 支持看图与下载，支持 Waifu2x 超分

## 已知限制

* **用旧版本下载过的图片可能仍是错位的**：早期版本在 Android 上图片分割失败（Pillow 缺 webp
  解码器），文件已经以错误内容落盘。升级后**需要重新下载**才能恢复正常，见
  [android/README.md](android/README.md) §3.5。
* 阅读器走无损的 QImage 路径；按字节重编码的路径对 WEBP 是有损的（q95），只在必要时使用。
* Android 侧「最小化到桌面」会打一条 `NameError: name 'QtOwner' is not defined` 日志（上游遗留，
  仅影响该入口），已知未修。
* 本分支的真机验证主要在 vivo（Android 16 / arm64-v8a）上完成，其它机型可能还有差异。

## 构建

### Android

完整流程（含 WSL2 实测步骤、每个坑的根因、真机自检方法）见 **[android/README.md](android/README.md)**。

```bash
# 入口脚本（按上游惯例，仓库里的 .sh 不带可执行位，统一用 bash 调用）
bash android/build_android.sh          # 一键：编译 libsr_qnn.so + 打包 APK
python android/tools/prepare_models.py # 把 waifu2x onnx 转成 NPU 可用的固定 shape 模型
```

`android/tools/` 下的脚本都不写死本机路径，公共路径由 `env.sh` / `env.ps1` 解析
（见 [android/tools/README.md](android/tools/README.md)）。移植过程中写过的一次性排查脚本
完整保留在 `android/tools/archive/`。

### 桌面端

沿用上游流程，见 [.github/workflows](.github/workflows)（Windows / Linux / macOS 三平台）。
注意：上游那三个桌面端 job 加了 `if: github.repository == 'tonquer/JMComic-qt'`，
只在上游仓库运行；本分支不发布桌面端安装包，需要时删掉那个 `if` 即可。

## CI

| 工作流 | 触发 | 内容 |
| --- | --- | --- |
| [android.yml](.github/workflows/android.yml) | push / PR 到 main、手动 | **本分支自己的 CI**。在 `ubuntu-latest` 上用 Python 3.11 + PySide6-Essentials 6.11.2（Qt offscreen）跑宿主回归：字节码编译、`android/**/*.sh` 语法检查、C++↔ctypes 接口一致性、竖屏冒烟、接口解密链、图片解码链路、应用内文件选择器 |
| [CI.yml](.github/workflows/CI.yml) | push / PR 到 main | 上游的桌面端三平台构建（在本仓库默认不运行） |
| [release.yml](.github/workflows/release.yml) | 打 tag | 上游的桌面端发布流程（在本仓库默认不运行） |

Android 的 CI **不需要手机，也不需要 Android SDK/NDK/QNN SDK**，所以能在 CI 里跑；
真正打 APK 需要 NDK + QNN SDK 且首次冷构建几十分钟，不放在 CI 里。

依赖清单单独放在 [src/requirements_android_ci.txt](src/requirements_android_ci.txt)：
版本以 **APK 里实际装的东西**为准（PySide6 6.11.2、jmcomic 2.7.7、pycryptodome），
而不是桌面端 `requirements.txt` 里的钉子，否则会掩盖移动端才暴露的问题。

本地想跑同一套回归，用 `android/tools/wsl_run_smoke.sh`（WSL/ Linux 均可）。

## 目录结构

```
src/            业务源码（桌面端与 Android 共用）
ui/             Qt Designer 的 .ui
res/            图标、图片等资源
script/         打包辅助脚本
android/        Android 移植专用（见 android/README.md）
  ├─ main.py            入口
  ├─ sr_qnn/            NPU 超分原生库(C++)与模型
  ├─ recipes/ shims/    python-for-android recipe 与 curl_cffi 垫片
  └─ tools/             构建/校验脚本（archive/ 是过程档案）
.github/        CI 与发布流程
```

## 许可证与署名

* 本项目沿用上游的 **GNU LGPL v3**，见 [LICENSE](LICENSE)。
* 这是一个**修改版**：Android 移植相关的修改都记录在本仓库的 git 历史与
  [android/README.md](android/README.md) 中。按 LGPL 的要求，修改部分同样以 LGPL v3 提供。
* 上游项目：[tonquer/JMComic-qt](https://github.com/tonquer/JMComic-qt)
* 第三方组件及其许可证：见 [NOTICE.md](NOTICE.md)

## 感谢以下项目

* 禁漫接口：[JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python)
* 超分功能：[waifu2x-ncnn-vulkan](https://github.com/nihui/waifu2x-ncnn-vulkan)、
  [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN)、
  [realcugan-ncnn-vulkan](https://github.com/nihui/realcugan-ncnn-vulkan)、
  [sr-vulkan](https://github.com/tonquer/sr-vulkan)
* 上游客户端：[tonquer/JMComic-qt](https://github.com/tonquer/JMComic-qt)
