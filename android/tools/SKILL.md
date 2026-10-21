# SKILL.md —— Android APK 构建踩坑与处置手册

> 面向本仓库 `android/` 的 PySide6(Qt 6.12) + python-for-android 打包链。
> 记录 2026-10-21 在**全新 WSL2 环境**里从零打出 `arm64-v8a` / `x86_64` 两个 APK 时
> 实际遇到的问题，按「现象 → 原因 → 解决 → 验证」整理，末尾是可直接照做的复用清单。
>
> 环境基线（实测可用的组合）：WSL2 Ubuntu / 非 root 用户 / 5.8 GB 内存（gradle 堆 4096m）
> / JDK 17 / Python 3.11(micromamba → venv311) / PySide6-Essentials 6.12.0 /
> p4a develop(2026.05.09) / NDK r26d / platform 34 / build-tools 35.0.0 / 目标 CPython 3.14.8。

---

## 0. 30 秒定位法

构建失败先看这两份日志，再按关键字跳章节：

```bash
# 全量日志（buildozer 的终端输出都在这里）
tr '\r' '\n' < ~/jmcomic-build/logs/buildozer_full.log | grep -nE "Hunk|FAILED|error:|Traceback|Command failed" | tail -20
# 阶段日志（脚本自己的进度：同步/填 spec/--init/补丁/校验/收货）
tail -30 ~/jmcomic-build/logs/build_apk.log
```

| 日志关键字 | 多半是 | 章节 |
| --- | --- | --- |
| `Failed to find package` / `IO exception while downloading manifest` | sdkmanager 拉不到清单 | §1.1 |
| `ERROR: Could not find a version that satisfies the requirement …`（宿主 pip） | 镜像缺包 / 包名不对 | §1.2 |
| `Download …` 反复重来、`.mark-` 被删 | 源码包下不完整 | §2.1 |
| `Hunk #1 FAILED` | recipe 补丁与源码版本不匹配 | §3.1 |
| `possibly undefined macro: LT_SYS_SYMBOL_USCORE` | 宿主缺 libtool m4 | §3.2 |
| `You must pass --allow-minsdk-ndkapi-mismatch` | minSdk 与 ndk_api 不一致 | §3.3 |
| `PKIX path building failed`（gradle） | Java 信任库缺 CA / 发行包下不来 | §4.1 |
| `Execution failed for task ':packageDebug'` + `java_pid*.hprof` | Gradle OOM | §4.2 |
| `[FATAL] APK 校验失败：加载清单与包内 .so 不一致` | Qt 加载清单 vs 产物缺库 | §5.1 |
| `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | 签名不同（换了构建机/密钥） | §5.2 |
| `INSTALL_FAILED_NO_MATCHING_ABIS` | ABI 装错设备 | §5.3 |

---

## 1. 环境搭建

### 1.1 sdkmanager 拉不到清单

**现象**

`wsl_setup_android.sh` 里 `sdkmanager` 输出：

```
Warning: IO exception while downloading manifest
Warning: Failed to find package 'platform-tools'
```

脚本还“成功”退出（`yes | sdkmanager … | tail -5` 掩盖了退出码），实际什么都没装。

**原因**

sdkmanager 走 `dl.google.com/android/repository/repository2-*.xml` 拉清单，该请求在本机
TLS/网络策略下会失败；而**同一个域名的静态文件直链是通的**。

**解决**

绕开清单，直接下 zip 解包到 sdkmanager 的标准目录布局：

```bash
SDK=~/jmcomic-build/android-sdk
REPO=https://dl.google.com/android/repository

curl -fL -o platform-tools.zip  $REPO/platform-tools-latest-linux.zip
curl -fL -o build-tools-35.zip  $REPO/build-tools_r35_linux.zip
curl -fL -o ndk-r26d.zip        $REPO/android-ndk-r26d-linux.zip

unzip -q platform-tools.zip -d $SDK                       # -> $SDK/platform-tools
unzip -q build-tools-35.zip -d /tmp/bt && mv /tmp/bt/android-* $SDK/build-tools/35.0.0
unzip -q ndk-r26d.zip       -d /tmp/ndk && mv /tmp/ndk/android-ndk-r26d $SDK/ndk/26.1.10909125

# platforms/android-34 与宿主无关，直接复用 Windows 侧 SDK 里那份
cp -r /mnt/c/Users/<user>/AppData/Local/Android/Sdk/platforms/android-34 $SDK/platforms/

# AGP 需要“已接受许可”的标记文件，否则报 license not accepted
printf '24333f8a63b6825ea9c5514f83c2829b004d1fee\n84831b9409646a918e30573bab4c9c91346d8abd\n' \
  > $SDK/licenses/android-sdk-license
```

**验证**：`$SDK/platform-tools/adb version`、`$SDK/build-tools/35.0.0/aapt2` 存在、
`$SDK/ndk/26.1.10909125/toolchains/llvm/prebuilt/linux-x86_64/bin/clang --version` 正常。

### 1.2 `pyside6-android-deploy` 在 PyPI 上 404

**现象**：`pip install pyside6-android-deploy` 报找不到包（PyPI / 清华源都是 404）。
`build_android.sh` 里那行 `pip install pyside6-android-deploy` 其实早就装不上。

**原因**：该命令**不是独立发行包**，而是随 **Linux 平台的 `PySide6-Essentials` wheel**
一起安装的入口脚本（Windows wheel 里没有，所以桌面 venv 看不到它）。

**解决**：在 Linux(WSL) 的 py311 venv 里装同版本 PySide6：

```bash
$VPY -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
    "PySide6-Essentials==6.12.0" "shiboken6==6.12.0" buildozer "cython<3" pexpect packaging
ls $WORK/venv311/bin | grep -i deploy        # 应出现 pyside6-android-deploy
```

**注意**：`PySide6-Essentials` 的版本必须与 `wsl_fetch_android_wheels.sh` 里的
`QT_VER`（6.12.0）一致，否则 deploy 工具读 spec 会与 android wheel 打架。

### 1.3 非 root 用户下 JM_WORK 指向 /root

**现象**：脚本全部照默认值跑，第一步就 `Permission denied`。

**原因**：`env.sh` 默认 `JM_WORK=/root/jmcomic-build`（作者以 root 构建）。
WSL 默认用户不是 root 时该目录不可写，且本机 `sudo` 需要交互密码（脚本里 `apt-get` 反而
用不上——实测编译工具链、dev 头文件都已齐备，只有 ccache 缺失，p4a 会打一行 warning 继续）。

**解决**：所有入口脚本统一前缀 `JM_WORK=$HOME/jmcomic-build`：

```bash
cd ~/jmcomic-build/src && \
JM_WORK=$HOME/jmcomic-build JM_ABI=arm64-v8a bash android/tools/wsl_build_apk.sh --abi arm64-v8a
```

---

## 2. 源码包下载

### 2.1 CPython 源码包反复“重下”

**现象**：`buildozer_full.log` 里 `Downloading python3` 连续出现 3+ 次，每次都从 0 开始，
`packages/python3/v3.14.8.tar.gz` 长到 20~29 MB 就没下文（完整是 32,119,003 字节）。

**原因**：`ghproxy.net` 代理 32 MB 的 GitHub archive 会中途断流（`IncompleteRead`）。
p4a `recipe.py` 的逻辑是“有文件但没 `.mark-` 标记 → 先删文件再重下”，所以每次都是全新一轮。

**解决**：`hostpython3` 与 `python3` 用的是**同一个** tarball，把已下完整的那份复灌并补标记：

```bash
P=~/jmcomic-build/src/android/.buildozer/android/platform/build-<abi>/packages
cp -f $P/hostpython3/v3.14.8.tar.gz $P/python3/v3.14.8.tar.gz
touch $P/python3/.mark-v3.14.8.tar.gz
tar -tzf $P/python3/v3.14.8.tar.gz >/dev/null && echo OK
```

**验证**：日志里不再出现 `rm -f .mark-v3.14.8.tar.gz`，直接进入 `Building python3`。

> 同类问题通用处理：任何 recipe 卡在反复 `Downloading X` 时，先看 `packages/<name>/` 里
> 文件大小是否等于源站 `Content-Length`（`curl -sSI <url> | grep -i content-length`），
> 不完整就换个镜像/代理下好再复灌 + `touch .mark-<filename>`。

### 2.2 并行跑另一个 ABI 的 fetch，把当前 ABI 的 wheel 归档掉了

**现象**：arm64 构建进行中，我并行跑了 `JM_ABI=x86_64 wsl_fetch_android_wheels.sh`，
随后 arm64 构建报“缺少 arm64 的 android wheel”，`wheels/` 里 aarch64 的 whl 不见了。

**原因**：该脚本为了“一个 APK 只放一种 ABI”，会把非目标 ABI 的 wheel `mv` 到 `wheels/archive/`。
构建脚本在 fetch 之后还要再 `ls wheels/pyside6-*-<tag>.whl` 取路径，文件被搬走就取不到。

**解决**：把文件搬回来，并且**构建期间不要并行跑其它 ABI 的 fetch**：

```bash
mv -f ~/jmcomic-build/src/android/wheels/archive/*android_aarch64.whl \
      ~/jmcomic-build/src/android/wheels/
```

**复用实践**：构建脚本已经把 wheel 复制到 `$WORK/wheelhouse/<abi>/` 再使用（与 source.dir 解耦），
所以即便 `wheels/` 被清理也不影响已开始的构建——前提是别在“fetch → 取路径”这段窗口里动它。

---

## 3. p4a recipe / 交叉编译

### 3.1 recipe 补丁打不上（`Hunk #1 FAILED`）

**现象**

```
patching file Lib/sysconfig/__init__.py
Hunk #1 FAILED at 702.
1 out of 1 hunk FAILED -- saving rejects to file Lib/sysconfig/__init__.py.rej
```

`p4a` 退出，`--init` 之后的 recipe 全部没编。

**原因**：`pythonforandroid/recipes/python3/patches/3.14_armv7l_fix.patch` 是针对
**cpython-3.14.0** 生成的；本项目用 3.14.8，上游已经把 `armv7l/armv8l -> armeabi_v7a`
的映射写进 `Lib/sysconfig/__init__.py`，补丁上下文不存在了。而且本项目只打
`arm64-v8a` / `x86_64`，这条 armv7l 补丁本来就用不到。

**解决**：在 recipe 里去掉这条补丁（幂等编辑，别用 `sed` 硬替换多行）：

```python
# p4a/pythonforandroid/recipes/python3/__init__.py
if _p_version.minor >= 14:
    self.patches.append('patches/3.14_fix_remote_debug.patch')   # 保留这条（dry-run 通过）
    # 3.14.8 上游已修好 armv7l 映射，且本工程只打 arm64-v8a/x86_64，跳过过期补丁
```

顺手删掉半成品构建目录，让配方重新解包：`rm -rf .../build/other_builds/python3`。

**验证**：`patch -p1 --dry-run -d <源码目录> -i <补丁>` 逐个试，只允许“已应用过”的失败项。

### 3.2 libffi `autoreconf`：`LT_SYS_SYMBOL_USCORE` 未定义

**现象**

```
configure.ac:215: error: possibly undefined macro: LT_SYS_SYMBOL_USCORE
autoreconf: error: /usr/bin/autoconf failed with exit status: 1
```

**原因**：libffi 源码是 git archive（不含 `configure`），recipe 会跑 `autoreconf -vif`；
该宏由 `libltdl-dev` 提供的 m4 定义，宿主没装这个包（`/usr/share/aclocal` 里没有）。
`p4a` 的 `get_recipe_env()` 只返回 arch 环境，**不会透传宿主 `os.environ`**，所以
`export ACLOCAL_PATH=…` 对 recipe 内部无效。

**解决**：两件事一起做。

```bash
# ① 用 conda 的 libtool(2.5.4) 提供 m4（不需要 root，不污染系统）
~/jmcomic-build/tools/micromamba install -y -q -p ~/jmcomic-build/mamba/envs/py311 \
    -c conda-forge libtool
grep -n "AC_DEFUN(\[LT_SYS_SYMBOL_USCORE" \
    ~/jmcomic-build/mamba/envs/py311/share/aclocal/*.m4     # ltdl.m4 里有定义
```

```python
# ② recipe 里把 ACLOCAL_PATH 显式塞进 autoreconf 的环境
# p4a/pythonforandroid/recipes/libffi/__init__.py
def build_arch(self, arch):
    env = self.get_recipe_env(arch)
    if os.environ.get('ACLOCAL_PATH'):          # 需要 import os
        env['ACLOCAL_PATH'] = os.environ['ACLOCAL_PATH']
```

构建时带上：

```bash
ACLOCAL_PATH=$HOME/jmcomic-build/mamba/envs/py311/share/aclocal \
JM_WORK=… JM_ABI=… bash android/tools/wsl_build_apk.sh --abi …
```

**验证**：libffi 目录里手动 `autoreconf -vif` 返回 0 并生成 `configure`；
构建日志不再出现该宏错误，直接进入 `./configure --host=aarch64-linux-android…`。

### 3.3 minSdk 与 ndk_api 不一致被拦

**现象**

```
WARNING: --minsdk argument does not match the api that is compiled against…
You must pass --allow-minsdk-ndkapi-mismatch to build with --minsdk different to the target NDK api
```

**原因**：本项目有意为之——`buildozer.spec` 里 `android.minapi=34`（最低 Android 14），
而 dist 是用 `android.ndk_api=28` 编的（工程既有产物一直如此）。新版 p4a 的
`bootstraps/common/build/build.py` 把这种组合从“警告”升级成“必须显式确认”。

**解决**：把该开关默认打开（只影响本机构建树，不动仓库代码）：

```python
# p4a/pythonforandroid/bootstraps/common/build/build.py
ap.add_argument('--allow-minsdk-ndkapi-mismatch', default=True,   # 原 default=False
                action='store_true', help=…)
```

**验证**：日志出现 `Proceeding with --minsdk not matching build target api`，
随后 `# Android packaging done!`。产物 `aapt dump badging` 应显示 `sdkVersion:'34'`。

> 若想彻底消除警告，正解是让 dist 也按 `android.ndk_api=34` 重编（要重编全部 recipe，
> 时间成本高）。改 minSdk 为 28 会突破“最低 Android 14”的产品约束，不要这么干。

---

## 4. Gradle 打包

### 4.1 Gradle 发行包 / 依赖下载 `PKIX path building failed`

**现象**

```
Exception in thread "main" javax.net.ssl.SSLHandshakeException: PKIX path building failed…
  at …下载 https://services.gradle.org/distributions/gradle-8.14.3-all.zip
```

**原因**：两层原因叠加。
① 宿主 JDK 的信任库 `/opt/java-ca.jks` 是旧快照（root 所有，改不动），链不上新 CA；
② `services.gradle.org` 在 WSL 里连 TLS 握手都过不去（curl 也报 `unable to get local issuer`）。

**解决**

```bash
# ① 发行包换腾讯镜像手动下好，塞进 wrapper 缓存（目录名是 wrapper 算出来的 hash）
D=~/.gradle/wrapper/dists/gradle-8.14.3-all/10utluxaxniiv4wxiphsi49nj
curl -fL -o $D/gradle-8.14.3-all.zip \
    https://mirrors.cloud.tencent.com/gradle/gradle-8.14.3-all.zip
unzip -l $D/gradle-8.14.3-all.zip >/dev/null && echo ZIP_OK
```

```bash
# ② 用系统 CA 重新生成一份可写的信任库
for f in /etc/ssl/certs/*.pem; do
  keytool -importcert -noprompt -trustcacerts -alias "$(basename "$f" .pem)" \
    -file "$f" -keystore ~/java-ca.jks -storepass changeit >/dev/null 2>&1
done
```

```properties
# ③ 写进 gradle.properties（模板 + 已渲染的 dist 都要写，否则下次 --init 被覆盖）
systemProp.javax.net.ssl.trustStore=/home/<user>/java-ca.jks
systemProp.javax.net.ssl.trustStorePassword=changeit
```

扫描范围（`wsl_patch_gradle_mem.sh` 里同样的教训：只改源码会漏掉 dist 与 site-packages 副本）：

```bash
find ~/jmcomic-build/p4a \
     ~/jmcomic-build/venv311/lib/python3.11/site-packages \
     ~/jmcomic-build/src/android/.buildozer \
     -name 'gradle*.properties'
```

**验证**：Gradle 正常下载 AGP/maven 依赖，`buildozer exit=0`。

> 另一种更省事的取向：既然只是本机构建，也可以只在 gradle 侧加
> `--allow-insecure` 类参数，但会弱化校验，不如换信任库干净。

### 4.2 `:packageDebug` OOM

**现象**：Gradle 只报一句 `Execution failed for task ':packageDebug'.`，
dist 目录里多出 400 MB 的 `java_pid*.hprof`。

**原因**：`packageDebug` 要把 ~200 MB 的 `assets/private.tar` 和 ~500 MB 原生库压进 APK，
p4a 模板里 `org.gradle.jvmargs=-Xmx2500m` 不够。

**解决**：`wsl_patch_gradle_mem.sh` 已把模板与渲染产物统一改到 4096m（构建脚本每次会调用），
本机 5.8 GB 内存下可用；改前记得清掉旧的 `java_pid*.hprof` 占空间。

**验证**：同一任务 20 秒左右通过；`free -m` 观察峰值不要顶到 swap。

---

## 5. 产物校验与安装

### 5.1 加载清单与包内 `.so` 不一致

**现象**：应用装完即闪退，日志只有一行 `E QtLoader`；或构建脚本报
`[FATAL] APK 校验失败：加载清单与包内 .so 不一致`。

**原因**：QtLoader 按 `array/qt_libs` 清单逐个 `loadLibrary`，清单里有、包里没有的库
（典型是 `QtTest.abi3.so` 或漏拷的插件）会让启动直接失败。

**解决**：产物必须过 `check_apk_qt_libs.py`（`wsl_build_apk.sh` 第 4.5 步已内置）：

```bash
$VPY android/tools/check_apk_qt_libs.py <apk> --abi arm64-v8a --aapt <sdk>/build-tools/35.0.0/aapt
```

**验证输出**：`核对清单条目 22 个，缺失 0 个` / `[OK] 加载清单与包内 .so 完全一致`。

### 5.2 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`（签名不同）

**现象**

```
Success: streamed 408108469 bytes
Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: Existing package org.jmcomic.jmcomic signatures do not match newer version]
```

**原因**：设备上已有同包名、但用**另一套调试密钥**签的版本（换构建机、换 `~/.android/debug.keystore`
或之前装过 release 包）。

**解决**：只能先卸载再装——**这会清掉应用数据**，不要替用户擅自执行：

```bash
adb uninstall org.jmcomic.jmcomic     # 用户确认后再做
adb install -r android/JMComic-<ver>-<abi>-debug.apk
```

**复用实践**：固定一台机器/一份 `debug.keystore` 做 Android 调试包，避免每次换签名；
需要保留数据升级就统一用 release 签名。

### 5.3 装错 ABI

**现象**：`INSTALL_FAILED_NO_MATCHING_ABIS`，或装上了但一启动就崩（`.so` 找不到）。

**原因**：一个 APK 只含一种 ABI 的原生库：`arm64-v8a` 给真机，`x86_64` 给模拟器/虚拟机。
在 x86_64 AVD 上装 arm64 包必然失败。

**解决**：先确认目标架构再选包：

```bash
adb shell getprop ro.product.cpu.abi     # x86_64 -> 装 x86_64 包；arm64-v8a -> 装 arm64 包
aapt dump badging <apk> | grep native-code
```

---

## 6. 可复用实践要点（照做清单）

**构建前**

1. **先确认环境基线**：`python 3.11` 宿主、PySide6-Essentials 与 android wheel 同版本、
   NDK/platform/build-tools 版本齐、`JM_WORK` 在非 root 可写目录。
2. **一个 ABI 一次构建，串行**：不要并行跑另一个 ABI 的 `wsl_fetch_*`（会搬 wheel、抢 venv/pip）。
3. **先把下载搞定再进编译**：大文件（CPython/Pillow/lxml）先确认 `Content-Length` 与实际大小一致，
   不完整就换镜像（腾讯/清华/华为云都验证过可用）并复灌 `.mark-`。
4. **不要用并行构建换时间**：本机内存 5.8 GB，gradle 已占 4 GB 堆，再叠一个 recipe 编译会 OOM。

**构建中**

5. **只改构建树，不改业务代码**：`$WORK/p4a` 的 recipe/build.py 补丁是环境适配，
   用“幂等、可重跑”的 python 片段改（见 §3.1/§3.2/§3.3）；能进 `android/tools/wsl_patch_*.sh`
   就进脚本，方便下次复现。
6. **补丁要扫全范围**：模板 + 已渲染 dist + `site-packages` 里的副本三处都要改，
   否则下次 `--init` 覆盖回去（`wsl_patch_gradle_mem.sh` 的做法可参照）。
7. **复用源码包缓存**：`keep-<abi>/packages` 里的 tarball 与 arch 无关，可直接拷给另一个 ABI，
   省掉重复下载与断流风险：`cp -a keep-arm64-v8a/packages/. build-x86_64/packages/`。
8. **失败先看 `buildozer_full.log` 的最后一个 `Traceback`**，再往上看 20 行找真实原因
   （p4a 的报错栈常把根因藏在 `RAN: …` 与 `STDOUT:` 之间）。

**构建后**

9. **三件套验收**：`aapt dump badging`（包名/版本/minSdk/ABI）+ `check_apk_qt_libs.py`（清单一致）
   + `wsl_collect_apk.sh`（顺带把日志收进 `android/build_logs/`）。
10. **安装前确认 ABI 与签名**：`ro.product.cpu.abi` 决定装哪个包；签名不一致只提示用户卸载，
    不擅自动数据。
11. **记录耗时与体积**：冷构建（含 recipe 编译）约 40~60 分钟/ABI，缓存命中后重新打包约 4~5 分钟；
    `arm64` 包 ~450 MB（218 个 `.so`），`x86_64` 包 ~389 MB（198 个 `.so`），差异主要来自 QNN 运行库。

---

## 7. 命令速查

```bash
export JM_WORK=$HOME/jmcomic-build
export ACLOCAL_PATH=$JM_WORK/mamba/envs/py311/share/aclocal

# 首次：宿主工具链 / SDK / p4a / 依赖
bash android/tools/wsl_setup_android.sh                 # 若 sdkmanager 失败见 §1.1 改直链
bash android/tools/wsl_fetch_android_wheels.sh          # 按 JM_ABI 取 PySide6/shiboken
bash android/tools/wsl_fetch_ort.sh                     # ONNX Runtime（arm64 带 QNN，x86_64 纯 CPU）
bash android/tools/wsl_build_native.sh                  # 编译 libsr_qnn.so

# 打包（串行，一个 ABI 一次）
cd $JM_WORK/src && JM_ABI=arm64-v8a bash android/tools/wsl_build_apk.sh --abi arm64-v8a
cd $JM_WORK/src && JM_ABI=x86_64    bash android/tools/wsl_build_apk.sh --abi x86_64

# 校验 + 收货（会拷回 Windows 仓库 android/ 并归档日志）
JM_ABI=arm64-v8a bash android/tools/wsl_collect_apk.sh

# 产物核验 / 安装
aapt dump badging android/JMComic-<ver>-arm64-v8a-debug.apk | grep -E "package|sdkVersion|native-code"
adb install -r android/JMComic-<ver>-<abi>-debug.apk
```

**日志位置**：`$JM_WORK/logs/{setup_*.log,prep_*.log,build_native.log,build_apk.log,buildozer_full.log}`，
收货后另有一份在 `android/build_logs/`。
