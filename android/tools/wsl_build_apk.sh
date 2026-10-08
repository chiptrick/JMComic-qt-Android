#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 在 WSL Ubuntu 里完成 APK 打包
#
# 流程(实测)：
#   0) 同步仓库 + 准备 app_src
#   1) fill_deploy_spec.py 填入 wheel/ndk/sdk 绝对路径
#   2) pyside6-android-deploy --init : 生成 buildozer.spec / Qt recipe / jars 后退出
#      (注意：工具每次启动都会先 cleanup()，它会删掉 buildozer.spec，
#       所以不能"再跑一次工具"，必须自己调 buildozer)
#   3) patch_buildozer_spec.py 注入 requirements / minSdk34 / 自有 .so / 模型 assets
#   4) python -m buildozer android debug 正式打包
#   5) 收集 APK
#
# buildozer 要求宿主 python <= 3.11(见 wsl_build_py311_src.sh)
set -uo pipefail
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

[ -x "$VPY" ] || { echo "缺少 venv311(先跑 wsl_build_py311_src.sh)"; exit 1; }
echo "宿主 python: $($VPY --version)"
if ! "$VPY" -c "import pythonforandroid" 2>/dev/null; then
    "$VPY" -m pip install -q "$P4A" 2>&1 | tail -3
fi
"$VPY" -m pip install -q pkginfo tqdm "packaging==24.1" buildozer "cython<3" sh pexpect jinja2 toml virtualenv appdirs filetype requests six colorama 2>&1 | tail -2
# buildozer 会自己跑 "pip install --user ..."，在 venv 里会失败；这里把它的依赖预装齐
"$VPY" -m pip install -q appdirs "colorama>=0.3.3" jinja2 "sh>=2,<3" meson ninja build toml packaging setuptools "wheel~=0.43.0" 2>&1 | tail -2

PYSIDE_WHL=$(ls "$ANDROID/wheels/"pyside6-*-android_aarch64.whl 2>/dev/null | head -1)
SHIBOKEN_WHL=$(ls "$ANDROID/wheels/"shiboken6-*-android_aarch64.whl 2>/dev/null | head -1)
echo "PySide6  wheel: $PYSIDE_WHL"
echo "shiboken wheel: $SHIBOKEN_WHL"
[ -n "$PYSIDE_WHL" ] && [ -n "$SHIBOKEN_WHL" ] || { echo "缺少 android wheel"; exit 1; }

echo "===== [$(date +%T)] 1. 填 pysidedeploy.spec ====="
cd "$ANDROID"
"$VPY" "$ANDROID/tools/fill_deploy_spec.py" "$ANDROID/pysidedeploy.spec" \
    --wheel-pyside "$PYSIDE_WHL" --wheel-shiboken "$SHIBOKEN_WHL" \
    --ndk-path "$NDK" --sdk-path "$SDK" || { echo "spec 写入失败"; exit 1; }

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
# 插件放进 libs/arm64-v8a 后由 patch_buildozer_spec.py 自动并入 android.add_libs_arm64_v8a
bash "$JM_REPO/android/tools/wsl_install_qt_plugins.sh"

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
    --p4a-dir "$P4A" --recipes "$ANDROID/recipes" \
    --libs "libs/arm64-v8a" --icon "$ICON" --models "$ANDROID/sr_qnn/models" 2>&1 | tail -30
echo "--- 关键配置 ---"
grep -E '^(requirements|source\.include_exts|android\.api|android\.minapi|android\.add_libs_arm64_v8a|android\.permissions|android\.add_assets|p4a\.source_dir|p4a\.local_recipes|android\.ndk_path|android\.sdk_path|package\.name|package\.domain|android\.archs|icon\.filename)' "$ANDROID/buildozer.spec"

echo "===== [$(date +%T)] 3.5 修正 p4a bootstrap 的 PYTHONOPTIMIZE ==="
# Qt bootstrap 硬编码 PYTHONOPTIMIZE=2 -> pycryptodome 放弃 cffi 后端、回落到在 Android 上
# 必然失败的 ctypes 后端 -> AES 全废 -> 接口响应(全是密文)全部解析失败。
# 改成 1：assert 仍然被去掉(行为不变)，但 docstring 保留，cffi/pycparser 可用。
bash "$JM_REPO/android/tools/wsl_patch_optimize.sh" || {
    echo "[FATAL] PYTHONOPTIMIZE 补丁失败，接口解密仍会失败"; exit 1; }

echo "===== [$(date +%T)] 3.6 补 AndroidManifest 存储权限 ====="
# buildozer.spec 里已经带了权限，但 dists/ 下的 manifest 可能是从构建缓存恢复的旧文件
# (p4a 不一定会重渲染)，所以这里再直接补一遍(幂等)：缺了就读不到手机存储里的漫画。
"$VPY" "$JM_REPO/android/tools/patch_android_manifest.py" \
    "$ANDROID/.buildozer/android/platform/build-arm64-v8a/dists/JMComic/src/main/AndroidManifest.xml" \
    "$ANDROID/.buildozer/android/platform/build-arm64-v8a/dists/JMComic/AndroidManifest.xml" || \
    echo "[warn] manifest 补丁有缺失项(首次构建还没有 dists 目录时 buildozer 会用 spec 生成)"

echo "===== [$(date +%T)] 4. 阶段3：buildozer android debug(首次会编译 python3/openssl/libffi 等) ====="
# 每次构建前修正 p4a recipe 里本机不可用的下载地址(openssl.org 证书问题 / github 被墙)
bash "$JM_REPO/android/tools/wsl_fix_recipe_urls.sh"
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

echo "===== [$(date +%T)] 5. 收集产物 ====="
find "$ANDROID" -maxdepth 4 \( -name '*.apk' -o -name '*.aab' \) 2>/dev/null | head
ls -sh "$ANDROID/bin" 2>/dev/null || true
echo "===== [$(date +%T)] 结束 ====="
