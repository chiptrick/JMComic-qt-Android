# android/tools

Android 移植用的脚本集合。**所有脚本都不写死本机路径**，公共路径由 `env.sh` / `env.ps1` 提供，
见 [android/README.md 的 §9.5](../README.md#95-androidtools-的约定路径不写死脚本分两档)。

```bash
# bash 脚本里(紧跟 shebang)
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# PowerShell 脚本里(紧跟 param 块)
. "$PSScriptRoot\env.ps1"
```

覆盖变量（两边同名）：`JM_REPO`、`JM_WORK`、`JM_SDK`、`JM_NDK`、`JM_VENV`、`JM_VPY`、
`JM_ADB`、`JM_SERIAL`、`JM_USER`。

## 目录分档

* `android/tools/*` —— **入口脚本**（68 个）。判据是机械的：**被 `android/README.md`、
  `android/build_android.sh`、根 `README.md`、`.github/workflows/*` 引用到的，再加上文档化的
  构建/验证主链（构建、等待、收货、同步、校验、宿主回归、真机自检），就留在这一层**；
  这些脚本会随代码演进而维护。
* `android/tools/archive/*` —— **移植过程中的一次性排查脚本**（111 个），按历史原貌保留，
  只做了字符串脱敏。它们记录的是"当时踩了什么坑、怎么定位的"，多数只跑过一次，
  **不保证现在还能直接运行**，详见 [archive/README.md](archive/README.md)。

## 入口脚本一览

### 1. 环境准备（WSL2，跑一次）

| 脚本 | 作用 |
| --- | --- |
| `wsl_setup_base.sh` | WSL Ubuntu 构建环境：基础工具 + JDK17 + Python3.11(conda) + 仓库副本 |
| `wsl_setup_base2.sh` | 修正版：micromamba + Python3.11 + 仓库副本，可重复执行 |
| `wsl_setup_android.sh` | Android cmdline-tools + platform 34 + build-tools 35 + NDK r26d |
| `wsl_install_toolchain.sh` | 宿主工具链：PySide6-Essentials + shiboken6(本地 wheel) + buildozer/cython |
| `wsl_config_mirrors.sh` | 配置可到达镜像 + 安装 buildozer/p4a 依赖 + clone p4a(develop) 并改 GitHub 域名 |
| `wsl_build_py311_src.sh` | 源码编译安装 CPython 3.11（buildozer 要求宿主 python ≤ 3.11） |
| `wsl_fetch_deps.sh` | 取 PySide6 / shiboken6 的 `android_aarch64` wheel(cp311) |
| `wsl_fetch_ort.sh` | 取 ONNX Runtime：`android-qnn` AAR + NuGet 头文件 + linux 库 |
| `wsl_fetch_qnn.sh` | 取高通 QNN 运行时 `com.qualcomm.qti:qnn-runtime` AAR |

### 2. 模型准备

| 脚本 | 作用 |
| --- | --- |
| `prepare_models.py` | 把已有 waifu2x onnx(动态 shape) 转成 **NPU 可用的固定 shape** 模型 |
| `wsl_verify_models.sh` | 用 onnxruntime(CPU) 独立验证准备好的 9 个模型：能否加载、IO 形状、推理耗时 |

### 3. 构建

| 脚本 | 作用 |
| --- | --- |
| `wsl_sync.sh` | 把 Windows 侧仓库同步到 WSL 的 ext4 构建树（避开 `/mnt/c` 慢） |
| `wsl_build_native.sh` | 编译 `libsr_qnn.so`：A) Android arm64-v8a(NDK) B) 宿主 x86_64 |
| `wsl_build_apk.sh` | **一键 APK 打包**：填 spec → `--init` → 补丁 → `buildozer android debug` → 收货 |
| `wsl_start_detached_build.sh` | 让 APK 构建在 WSL 内脱离式运行(`setsid+nohup`)，不受宿主会话生命周期影响 |
| `wsl_wait_build.sh` | 等脱离式构建**真正结束**再收货（踩过的坑：没结束就收货拿到的是上一版 APK） |
| `wsl_build_alive.sh` | 判断构建是否还在推进（进程 + 目录增长 + 子进程） |
| `wsl_build_status.sh` | 构建状态速查（失败次数 / 编译进程 / 已解包 recipe / 产出 APK） |
| `wsl_kill_build.sh` | 停掉正在跑的 buildozer/p4a 构建 |
| `wsl_save_build_cache.sh` | 把已编译产物搬出 `.buildozer`（避免被 `--init` 的 `cleanup()` 清掉） |
| `wsl_restore_build_cache.sh` | 把上面搬出去的产物搬回来 |
| `wsl_repack_apk.sh` | 原地重新打包 APK（不跑 deploy 工具的 `--init`） |
| `wsl_install_qt_plugins.sh` | 把 APK 缺的 Qt 插件补进 `libs/arm64-v8a` |
| `wsl_patch_optimize.sh` | 把 p4a Qt bootstrap 里硬编码的 `PYTHONOPTIMIZE=2` 改成 `1` |
| `wsl_fix_recipe_urls.sh` | 修正 p4a recipe 的下载地址（可到达性）+ Python 版本（对齐 cp311） |
| `wsl_fix_java_ca.sh` | JDK `cacerts` 缺 CA 导致 gradle PKIX 失败 → 用系统 CA 生成 truststore |
| `wsl_seed_from_old_storage.sh` | 把旧 storage 里已下载的源码包灌进当前 `packages`，让 p4a 跳过联网 |
| `wsl_seed_sources.py` | 用国内镜像的 PyPI sdist 预置 recipe 源码包到 p4a 缓存 |

### 4. 规格与补丁

| 脚本 | 作用 |
| --- | --- |
| `patch_buildozer_spec.py` | 注入 requirements / minSdk 34 / 自有 `.so` / 模型 assets / 应用图标 |
| `patch_android_manifest.py` | 直接补 `AndroidManifest.xml`（存储权限等，幂等） |
| `pin_min_sdk.sh` | 把 deploy 生成的工程钉到 Android 14(API 34) 并加入 NPU 模型资产 |
| `fill_deploy_spec.py` | 把 wheel / NDK / SDK 的绝对路径写进 `pysidedeploy.spec` |
| `fix_ps_bom.ps1` | 给 `android/tools` 下的 `.ps1` 补 UTF-8 BOM |

### 5. 校验与自检（APK / 工程）

| 脚本 | 作用 |
| --- | --- |
| `wsl_check_sync.sh` | 检查 Windows 仓库与 WSL 构建树是否一致（避免改完代码却拿旧包验证） |
| `wsl_check_minsdk.sh` | 从 AndroidManifest 读 minSdk / targetSdk / extractNativeLibs |
| `wsl_check_qnn_libs.py` | 查 `onnxruntime-android-qnn` 的 POM 依赖，以及各版本 AAR 是否自带 QNN 运行时 |
| `wsl_check_bundle_content.sh` | 解出 APK 里的 `libpybundle.so`（其实是 tar），确认 Python 运行时依赖齐 |
| `wsl_verify_new_apk.sh` | 深度校验新 APK：包信息 / 原生库 / Qt 插件 / private.tar 里的模型 |
| `wsl_collect_apk.sh` | APK 产出后：校验 + 搬回 Windows 仓库 |
| `wsl_prebuild_check.sh` | 构建前核对：`libsr_qnn.so` 是不是新的、Qt 插件齐不齐、模型在不在 |
| `inspect_pybundle.py` | 检查 p4a 打出的 `stdlib.zip` / `_python_bundle` 的字节码命名方式 |
| `scan_ui_width.py` | 扫描所有 `.ui`，找出竖屏宽度下**放不下**的横向布局行 |

### 6. 宿主回归（在自己电脑上跑，不需要手机）

| 脚本 | 作用 |
| --- | --- |
| `wsl_run_smoke.sh` | 五道门合集：竖屏冒烟 + 接口一致性 + 解密链 + 图片管线 + 文件选择器 |
| `wsl_run_smoke_only.sh` | 只跑 Android 竖屏冒烟，输出到 `/tmp/smoke.txt` |
| `wsl_run_host_test.sh` | 只跑宿主 `sr_qnn` 逻辑测试（不重新编译） |
| `wsl_run_imgtest.sh` | 图片管线（分割还原 / QImage 解码）宿主回归 |
| `wsl_run_urllib_tests.sh` | 用 venv311 逐模式测试 urllib 证书校验 |
| `wsl_test_urllib_certs.py` | 逐个测试 p4a 关心的下载 URL 在 `urllib` 下能否通过证书校验 |
| `check_interfaces.py` | 静态检查 `sr_qnn` 的 C++ 接口与 Python ctypes 绑定是否一致 |
| `smoke_test_android.py` | 竖屏适配冒烟（offscreen，不联网）：抽屉/详情页堆叠/返回键/降级等 |
| `host_test_sr_qnn.py` | 引擎逻辑自测：固定 shape 分块拼接、缩放、编解码、任务 API、模型回退 |
| `host_test_image_pipeline.py` | 看图解码链路回归（含真数据闭环，样本缺失时该段 SKIP） |
| `host_test_file_dialog.py` | 应用内文件选择器回归（委托/排序/过滤/权限降级/嵌套事件循环） |
| `host_test_crypto_android.py` | Android 模式下接口解密链（AES）回归 |
| `dump_ui.py` | 打印 `.ui` 的结构骨架（类名/对象名/几何/布局行列），用于规划竖屏排版 |

### 7. 真机

| 脚本 | 作用 |
| --- | --- |
| `verify_on_device.ps1` | 一键真机验证：安装 APK → 启动 → 拉自检日志 → 逐项判定 |
| `run_device_reader_selftest.ps1` | 干净地跑一次"看图界面自检"：打标记 → 启动 → 轮询等自检块落盘 |
| `wsl_normal_start_check.sh` | 普通启动路径检查：不创建标记文件，确认没有自检开锁/报错 |
| `wsl_sync_file_dialog.sh` | 同步"应用内文件选择器"的改动到 WSL 构建树并做 `py_compile` |
| `wsl_run_file_dialog_asuser.sh` | 以非 root 用户再跑一次文件选择器回归（真权限位那条分支） |
| `probe_grid_cover.py` | 首页网格：封面宽 / 每行个数 / 视口变化后的收敛 |
| `probe_touch_selftest.py` | 触摸事件自检 |
| `probe_seg_selftest.py` | 图片分割还原自检 |
| `probe_cached_page.py` | 离线复现真机"图片分割异常/错位"（证明是 Android 的 Pillow 缺解码器） |
| `probe_seam_score.py` | 用"接缝分数"客观判断一张图是不是被打乱后没还原 |
| `probe_pillow_android.sh` | 查看打好的 APK 里 Pillow 到底带了哪些编解码器 |
| `probe_apk_icon.py` | 逐像素比对 APK 里的启动器图标与源图 |
| `probe_cffi_backend.py` | 检查 `curl_cffi` 在设备上用的是哪个后端 |

## 约定

* 脚本一律 `#!/usr/bin/env bash` + `set -uo pipefail`（需要时再 `-e`），并且**先 source `env.sh`**。
* 中间产物、日志、真机证据写进 `$JM_WORK/logs`、`$JM_WORK/icon`、`android/build_logs`；
  其中 `android/build_logs/` 已被 `.gitignore` 排除，**不要提交**（含真机账号/代理 IP/样本图）。
* 新增脚本如果只跑过一次，请放进 `archive/`，别留在这一层。
