#!/usr/bin/env bash
# 在 WSL Ubuntu 里完成 APK 打包
#
# 用法：
#   bash android/tools/wsl_build_apk.sh                       # arm64-v8a(真机)
#   bash android/tools/wsl_build_apk.sh --abi x86_64          # x86_64(模拟器)
#   bash android/tools/wsl_build_apk.sh --version 0.37 --abi x86_64
#
# 一个 APK 只含一种 ABI：p4a 按 arch 分别构建 dist（build-arm64-v8a / build-x86_64），
# 原生库也分目录（android/libs/<abi>）。切换 ABI 不会污染另一套已编译产物。
#
# 流程(实测)：
#   0) 同步仓库 + 准备 app_src
#   1) fill_deploy_spec.py 填入 wheel/ndk/sdk 绝对路径 + 目标 arch
#   2) pyside6-android-deploy --init : 生成 buildozer.spec / Qt recipe / jars 后退出
#      (注意：工具每次启动都会先 cleanup()，它会删掉 buildozer.spec，
#       所以不能"再跑一次工具"，必须自己调 buildozer)
#   3) patch_buildozer_spec.py 注入 requirements / minSdk34 / 自有 .so / 模型 assets
#   4) python -m buildozer android debug 正式打包
#   5) 收集 APK
#
# buildozer 要求宿主 python <= 3.11(见 wsl_build_py311_src.sh)
APP_VERSION=""
ABI_ARG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --version=*) APP_VERSION="${1#--version=}" ;;
        --version)   APP_VERSION="${2:-}"; shift ;;
        --abi=*)     ABI_ARG="${1#--abi=}" ;;
        --abi)       ABI_ARG="${2:-}"; shift ;;
        *) echo "未知参数: $1(用法: wsl_build_apk.sh [--version 0.3] [--abi arm64-v8a|x86_64])"
           exit 1 ;;
    esac
    shift
done
[ -n "$ABI_ARG" ] && export JM_ABI="$ABI_ARG"
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
set -uo pipefail
[ -n "$APP_VERSION" ] && echo "APK 版本号: $APP_VERSION(覆盖默认)"
echo "目标 ABI: $JM_ABI  (wheel=$JM_WHEEL_TAG, 原生库=libs/$JM_ABI, QNN=$JM_QNN)"
WORK="${WORK:-"$JM_WORK"}"
SRC="$WORK/src"
ANDROID="$SRC/android"
SDK="$WORK/android-sdk"
NDK="$SDK/ndk/26.1.10909125"
VPY="$WORK/venv311/bin/python"
DEPLOY="$WORK/venv311/bin/pyside6-android-deploy"
P4A="$WORK/p4a"
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export ANDROID_HOME="$SDK" ANDROID_SDK_ROOT="$SDK" ANDROID_NDK_HOME="$NDK"
# buildozer 会在 PATH 里找 cython/git 等可执行文件，venv311/bin 必须在内
export PATH="$WORK/venv311/bin:$JAVA_HOME/bin:$PATH"
# 关键：buildozer 只在检测到 VIRTUAL_ENV 时才用 "pip install"，
# 否则会用 "pip install --user"（venv 里会直接报错）
export VIRTUAL_ENV="$WORK/venv311"
export PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
# JDK 自带 cacerts 缺部分 CA(gradle/dl.google/maven 的 PKIX 校验会失败)，
# 用系统 CA 生成的 truststore 顶替(见 tools/wsl_fix_java_ca.sh)
if [ -f /opt/java-ca.jks ]; then
    export JAVA_TOOL_OPTIONS="-Djavax.net.ssl.trustStore=/opt/java-ca.jks -Djavax.net.ssl.trustStorePassword=changeit"
    echo "JAVA_TOOL_OPTIONS=$JAVA_TOOL_OPTIONS"
fi
# p4a 用自己的 urllib 下载源码包，容器里 CA 链可能不全(报 unable to get local issuer
# certificate)；把 certifi 的 CA 包显式指给它
"$VPY" -m pip install -q certifi 2>/dev/null || true
CA_BUNDLE=$("$VPY" -c "import certifi;print(certifi.where())" 2>/dev/null || echo "")
if [ -n "$CA_BUNDLE" ] && [ -f "$CA_BUNDLE" ]; then
    export SSL_CERT_FILE="$CA_BUNDLE"
    export REQUESTS_CA_BUNDLE="$CA_BUNDLE"
    echo "CA bundle: $CA_BUNDLE"
fi
mkdir -p "$WORK/logs"
exec > >(tee -a "$WORK/logs/build_apk.log") 2>&1

echo "===== [$(date +%T)] 0. 同步仓库到 WSL + 准备 app_src ====="
bash "$JM_REPO/android/tools/wsl_sync.sh"
rm -rf "$ANDROID/app_src"
mkdir -p "$ANDROID/app_src"
cp -r "$SRC/src/." "$ANDROID/app_src/"
find "$ANDROID/app_src" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$ANDROID/app_src/logs" 2>/dev/null || true
du -sh "$ANDROID/app_src"

echo "===== [$(date +%T)] 0.5 下载/校验 android wheel(CPython 3.14 + 原生 curl_cffi) ====="
# Qt 6.12.0 abi3(NEEDED libpython3.14.so) + curl_cffi 0.16.3 cp314。
# 幂等：sha256 匹配就跳过；残片会被删掉重下(不要用 -C - 续传留下的半截文件)。
bash "$JM_REPO/android/tools/wsl_fetch_android_wheels.sh" || { echo "[FATAL] android wheel 缺失"; exit 1; }

# libs/<abi> 里的原生库：缺失时自动补 ORT（Qt wheel 里有平台标签，这里没有）。
# libsr_qnn.so 要编译，只提示不自动跑（它要 1 分钟且会再同步一次仓库）。
if [ ! -f "$ANDROID/libs/$JM_ABI/libonnxruntime.so" ]; then
    echo "libs/$JM_ABI/libonnxruntime.so 缺失，自动获取："
    bash "$JM_REPO/android/tools/wsl_fetch_ort.sh" || { echo "[FATAL] 获取 ONNX Runtime 失败"; exit 1; }
fi
if [ ! -f "$ANDROID/libs/$JM_ABI/libsr_qnn.so" ]; then
    echo "[warn] libs/$JM_ABI/libsr_qnn.so 缺失 -> 超分后端不可用。先跑："
    echo "       JM_ABI=$JM_ABI bash android/tools/wsl_build_native.sh"
fi

[ -x "$VPY" ] || { echo "缺少 venv311(先跑 wsl_build_py311_src.sh)"; exit 1; }
echo "宿主 python: $($VPY --version)"
if ! "$VPY" -c "import pythonforandroid" 2>/dev/null; then
    "$VPY" -m pip install -q "$P4A" 2>&1 | tail -3
fi
"$VPY" -m pip install -q pkginfo tqdm "packaging==24.1" buildozer "cython<3" sh pexpect jinja2 toml virtualenv appdirs filetype requests six colorama 2>&1 | tail -2
# buildozer 会自己跑 "pip install --user ..."，在 venv 里会失败；这里把它的依赖预装齐
"$VPY" -m pip install -q appdirs "colorama>=0.3.3" jinja2 "sh>=2,<3" meson ninja build toml packaging setuptools "wheel~=0.43.0" 2>&1 | tail -2

PYSIDE_WHL=$(ls "$ANDROID/wheels/"pyside6-*-"$JM_WHEEL_TAG".whl 2>/dev/null | head -1)
SHIBOKEN_WHL=$(ls "$ANDROID/wheels/"shiboken6-*-"$JM_WHEEL_TAG".whl 2>/dev/null | head -1)
echo "PySide6  wheel: $PYSIDE_WHL"
echo "shiboken wheel: $SHIBOKEN_WHL"
[ -n "$PYSIDE_WHL" ] && [ -n "$SHIBOKEN_WHL" ] || {
    echo "缺少 $JM_ABI 的 android wheel（跑 android/tools/wsl_fetch_android_wheels.sh）"; exit 1; }

# 把 wheel 复制到构建树里、**source.dir(android/) 之外**再用它。
# 原因(踩过)：x86_64 冷构建进行到 PySide6 recipe 时，报
#     FileNotFoundError: .../android/wheels/pyside6-...-android_x86_64.whl
# 也就是构建过程中这个 90MB 文件被某个步骤删掉了(arm64 构建没触发)。
# recipe 里记的是绝对路径，文件一没就整轮构建白跑。放到 $WORK/wheelhouse/<abi>/
# 之后与 source.dir 无关，任何"清扫工程目录"的行为都碰不到它（与图标同思路）。
WHEELHOUSE="$WORK/wheelhouse/$JM_ABI"
mkdir -p "$WHEELHOUSE"
cp -f "$PYSIDE_WHL" "$SHIBOKEN_WHL" "$WHEELHOUSE/" || { echo "复制 wheel 失败"; exit 1; }
PYSIDE_WHL="$WHEELHOUSE/$(basename "$PYSIDE_WHL")"
SHIBOKEN_WHL="$WHEELHOUSE/$(basename "$SHIBOKEN_WHL")"
echo "wheelhouse: $WHEELHOUSE"
# 防"旧 cp311 wheel 混进 3.14 构建"：pyside6/shiboken6 必须是 abi3(.so 绑
# libpython3.14.so)。wheels 目录里不该再有非 abi3 版(见 wsl_fetch_android_wheels.sh
# 的归档逻辑)—— 有就说明有人手动放了旧 wheel 回来。
for w in "$PYSIDE_WHL" "$SHIBOKEN_WHL"; do
    case "$w" in
        *cp310-abi3*) ;;
        *) echo "[FATAL] $w 不是 3.14 兼容的 cp310-abi3 wheel(旧 cp311?)，拒绝构建"; exit 1 ;;
    esac
done

echo "===== [$(date +%T)] 1. 填 pysidedeploy.spec ====="
cd "$ANDROID"
"$VPY" "$ANDROID/tools/fill_deploy_spec.py" "$ANDROID/pysidedeploy.spec" \
    --wheel-pyside "$PYSIDE_WHL" --wheel-shiboken "$SHIBOKEN_WHL" \
    --arch "$JM_ARCH_NAME" \
    --ndk-path "$NDK" --sdk-path "$SDK" || { echo "spec 写入失败"; exit 1; }

# deployment/ 里缓存着上一次生成的 PySide6 / shiboken6 recipe，recipe 内部**写死了
# 解包哪个 wheel**。切换 ABI 后如果继续复用，p4a 会把 arm64 的 Qt 库当 x86_64 的装进
# APK（链接期才炸）。所以目标 wheel 不在 recipe 里时就强制重新生成。
DEPLOY_RECIPE="$ANDROID/deployment/recipes/PySide6/__init__.py"
if [ -f "$DEPLOY_RECIPE" ] && ! grep -q "$(basename "$PYSIDE_WHL")" "$DEPLOY_RECIPE"; then
    echo "deployment/recipes 指向的不是 $JM_ABI 的 wheel，重新生成:"
    grep -m2 -o '[a-z0-9_]*-android_[a-z0-9_]*\.whl' "$DEPLOY_RECIPE" || true
    rm -rf "$ANDROID/deployment"
fi

echo "===== [$(date +%T)] 2. 阶段1：生成 buildozer.spec / recipe / jars(--init) ====="
# --init 会 rmtree(.buildozer)，先把已编译产物移出去(下一步 2.5 再搬回)
bash "$JM_REPO/android/tools/wsl_save_build_cache.sh" || true
# buildozer 检测到以 root 运行时会交互问 "continue [y/n]"，这里用 yes 自动回答
yes | "$DEPLOY" --config-file "$ANDROID/pysidedeploy.spec" \
    --wheel-pyside="$PYSIDE_WHL" --wheel-shiboken="$SHIBOKEN_WHL" \
    --ndk-path="$NDK" --sdk-path="$SDK" \
    --keep-deployment-files --force --init -v 2>&1 | tail -25
ls -la "$ANDROID/buildozer.spec" || { echo "buildozer.spec 未生成"; exit 1; }
RECIPE_DIR=$(grep -E '^p4a.local_recipes' "$ANDROID/buildozer.spec" | head -1 | cut -d= -f2- | xargs)
echo "工具 recipe 目录: $RECIPE_DIR"
ls "$RECIPE_DIR" 2>/dev/null | head -5

echo "===== [$(date +%T)] 2.5 恢复已编译产物 ====="
# pyside6-android-deploy 每次启动都会 cleanup()，里面是 shutil.rmtree(project_dir/.buildozer)
# —— 会把上一步编译好的 recipe 全清掉。所以构建前先把它们移出去(见 wsl_sync 前的 save)，
# --init 之后再搬回来，避免每次都付一次 30 分钟的冷构建代价。
bash "$JM_REPO/android/tools/wsl_restore_build_cache.sh" || true

echo "===== [$(date +%T)] 3. 阶段2：补丁 buildozer.spec ====="
# 先补 Qt 插件(缺 qsvg -> 主题 svg 图标/设置交互框全空白；缺 qsqlite -> QtSql 全废)
# 插件放进 libs/$JM_ABI 后由 patch_buildozer_spec.py 并入 android.add_libs_<abi>
bash "$JM_REPO/android/tools/wsl_install_qt_plugins.sh"

# 可选的厂商原生库(android/vendor_libs/*.so)。
# 主要用途：QNN HTP 懒加载 libcdsprpc.so(FastRPC) 与 DSP 通信，如果机型没把它列进
# public.libraries.txt，应用命名空间里就找不到它，HTP 设备建不起来 —— 表现是
# "QNN 会话能建但一个节点都不接"。把 `adb pull /vendor/lib64/libcdsprpc.so` 放进
# android/vendor_libs/ 重新打包，它就会随 app 的 lib 目录一起加载。
# x86_64 模拟器没有 QNN，这些 arm64 厂商库一律不并（并进去只会白占体积）。
if [ "$JM_QNN" = "1" ] && compgen -G "$ANDROID/vendor_libs/*.so" >/dev/null; then
    cp -f "$ANDROID/vendor_libs/"*.so "$SRC/android/libs/$JM_ABI/" 2>/dev/null || true
    echo "已并入厂商库: $(ls "$ANDROID/vendor_libs" | tr '\n' ' ')"
fi

# 应用图标：工具生成的 buildozer.spec 默认指向 PySide6 自带的 pyside_icon.jpg，
# 装到手机上启动器图标就是 PySide 的 logo。这里用仓库里的 res/icon/logo_round.png
# (与主窗口/托盘图标同一张图，512x512 带 alpha)。
# 刻意拷到 $WORK/icon 下 —— 它在 source.dir(=src/android) 之外，不会被 p4a 再打
# 一份进 private.tar。
ICON="$WORK/icon/app_icon.png"
mkdir -p "$(dirname "$ICON")"
cp -f "$SRC/res/icon/logo_round.png" "$ICON"
echo "应用图标: $ICON ($(stat -c %s "$ICON") 字节, $(md5sum "$ICON" | cut -d' ' -f1))"

"$VPY" "$ANDROID/tools/patch_buildozer_spec.py" "$ANDROID/buildozer.spec" \
    --p4a-dir "$P4A" --recipes "$ANDROID/recipes" --abi "$JM_ABI" \
    --libs "libs/$JM_ABI" --icon "$ICON" --models "$ANDROID/sr_qnn/models" \
    ${APP_VERSION:+--version "$APP_VERSION"} 2>&1 | tail -30
echo "--- 关键配置 ---"
grep -E '^(requirements|version|source\.include_exts|android\.api|android\.minapi|android\.add_libs_|android\.permissions|android\.add_assets|p4a\.source_dir|p4a\.local_recipes|android\.ndk_path|android\.sdk_path|package\.name|package\.domain|android\.archs|icon\.filename)' "$ANDROID/buildozer.spec"

echo "===== [$(date +%T)] 3.5 修正 p4a bootstrap 的 PYTHONOPTIMIZE ==="
# Qt bootstrap 硬编码 PYTHONOPTIMIZE=2 -> pycryptodome 放弃 cffi 后端、回落到在 Android 上
# 必然失败的 ctypes 后端 -> AES 全废 -> 接口响应(全是密文)全部解析失败。
# 改成 1：assert 仍然被去掉(行为不变)，但 docstring 保留，cffi/pycparser 可用。
bash "$JM_REPO/android/tools/wsl_patch_optimize.sh" || {
    echo "[FATAL] PYTHONOPTIMIZE 补丁失败，接口解密仍会失败"; exit 1; }

echo "===== [$(date +%T)] 3.6 SAF 桥：Java 源 + manifest 组件 ====="
# 选文件/选目录改成 SAF(系统选择器)之后不再需要任何存储权限；
# 桥本身是本进程的 Service + 一个透明 Activity，必须：
#   1) 把 android/java/org/jmcomic/*.java 拷进 dist 的 src/main/java(编译前就位)
#   2) 组件写进 p4a 的 manifest **模板**(p4a 每次构建都按模板重新渲染，
#      只补 dists 里渲染出来的文件下次就被覆盖了)
DIST="$ANDROID/.buildozer/android/platform/build-$JM_ABI/dists/JMComic"
"$VPY" "$JM_REPO/android/tools/patch_android_manifest.py" \
    --template "$P4A/pythonforandroid/bootstraps/qt/build/templates/AndroidManifest.tmpl.xml" \
    --java "$ANDROID/java" \
    --java-dest "$P4A/pythonforandroid/bootstraps/common/build/src/main/java" \
    --java-dest "$DIST/src/main/java" \
    "$DIST/src/main/AndroidManifest.xml" \
    "$DIST/AndroidManifest.xml" || \
    echo "[warn] SAF 组件/Java 源补丁有缺失项(首次构建还没有 dists 目录时属正常)"

echo "===== [$(date +%T)] 3.7 Gradle 堆上限(2500m 不够，:packageDebug 会 OOM) ====="
# 现象只有一句 "Execution failed for task ':packageDebug'"，真凶是 dist 目录里同时
# 出现的 java_pid*.hprof(400MB 堆转储)。改 p4a 模板才不会被下次构建覆盖回去。
bash "$JM_REPO/android/tools/wsl_patch_gradle_mem.sh" || {
    echo "[FATAL] Gradle 内存补丁失败，:packageDebug 大概率 OOM"; exit 1; }

echo "===== [$(date +%T)] 4. 阶段3：buildozer android debug(首次会编译 python3/openssl/libffi 等) ====="
# buildozer 1.6.0 的 add_libs 映射表里没有 x86_64（只有 arm64-v8a），不补的话
# android.add_libs_x86_64 会被完全忽略 -> APK 里没有我们自己的 .so，且无任何报错。
bash "$JM_REPO/android/tools/wsl_patch_buildozer_addlibs.sh" || {
    echo "[FATAL] buildozer add_libs 补丁失败，x86_64 的原生库进不了 APK"; exit 1; }
# 每次构建前修正 p4a recipe 里本机不可用的下载地址(openssl.org 证书问题 / github 被墙)
bash "$JM_REPO/android/tools/wsl_fix_recipe_urls.sh"
# 目标 CPython 切 3.14 + cffi 升 2.1.1(curl_cffi 0.16.3 的 _wrapper.abi3.so NEEDED
# libpython3.14.so；cffi 2.0.0 不支持 3.14)。幂等。
bash "$JM_REPO/android/tools/wsl_patch_p4a_versions.sh" || {
    echo "[FATAL] p4a recipe 版本补丁失败，目标 Python 不是 3.14"; exit 1; }
# 把大体积/慢速的源码包用国内镜像预置进 p4a 缓存(Pillow 45MB、lxml、pycryptodome)
"$VPY" "$JM_REPO/android/tools/wsl_seed_sources.py" || true
# ghproxy 下载 27MB 的 CPython 会中途断流(http.client.IncompleteRead)导致 hostpython3/
# python3 recipe 失败；把已下载好的源码包从旧 storage 目录灌进当前 packages 目录，
# p4a 见到同名 .mark-* 就会跳过下载
bash "$JM_REPO/android/tools/wsl_seed_from_old_storage.sh" || true
# 用 python zipfile 解压 cmdline-tools 不会保留可执行位，p4a 需要 avdmanager 可执行
chmod +x "$SDK/cmdline-tools/latest/bin/"* 2>/dev/null || true
# buildozer 只在 $SDK/tools/bin/sdkmanager 找 sdkmanager(旧布局)，
# 而我们用的是 cmdline-tools/latest，这里做个目录软链兼容
if [ ! -e "$SDK/tools/bin/sdkmanager" ]; then
    ln -sfn "$SDK/cmdline-tools/latest" "$SDK/tools"
    echo "已建立 $SDK/tools -> cmdline-tools/latest"
fi
ls -l "$SDK/tools/bin/sdkmanager" "$SDK/cmdline-tools/latest/bin/avdmanager" || true
cd "$ANDROID"
# warn_on_root=0 已在补丁里设置；yes 只是兜底
# 完整日志落盘(便于排查 recipe 编译失败)，终端只显示尾部
yes | "$VPY" -m buildozer android debug 2>&1 | tee "$WORK/logs/buildozer_full.log" | tail -120
echo "buildozer exit=${PIPESTATUS[1]}"
echo "完整日志: $WORK/logs/buildozer_full.log ($(wc -l < "$WORK/logs/buildozer_full.log" 2>/dev/null) 行)"

echo "===== [$(date +%T)] 4.5 校验 APK：Qt 加载清单 vs 包内 .so ====="
# 0.47 事故复盘：QtLoader 按 libs.xml 的清单逐个 loadLibrary，清单里有而包里没有
# 的库(QtTest.abi3.so)会让应用"装完即闪退"，且日志里只有一行 E QtLoader，
# 极容易被误判成环境问题。这里在收集产物前把清单和产物对一遍，不一致就 fail。
NEW_APK=$(ls -t "$ANDROID"/JMComic-*-"$JM_ABI"-debug.apk 2>/dev/null | head -1)
AAPT_BIN=$(ls "$SDK"/build-tools/*/aapt 2>/dev/null | sort -V | tail -1)
if [ -z "$NEW_APK" ]; then
    echo "[FATAL] 没找到 $JM_ABI 的 APK，构建可能失败了"
    exit 1
fi
"$VPY" "$ANDROID/tools/check_apk_qt_libs.py" "$NEW_APK" --abi "$JM_ABI" --aapt "$AAPT_BIN" || {
    echo "[FATAL] APK 校验失败：加载清单与包内 .so 不一致，这个包装上去会闪退"
    echo "        排查：aapt dump --values resources 看 array/qt_libs 与 array/load_local_libs"
    exit 1
}

echo "===== [$(date +%T)] 5. 收集产物 ====="
find "$ANDROID" -maxdepth 4 \( -name '*.apk' -o -name '*.aab' \) 2>/dev/null | head
ls -sh "$ANDROID/bin" 2>/dev/null || true
echo "===== [$(date +%T)] 结束 ====="
