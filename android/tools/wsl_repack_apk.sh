#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 原地重新打包 APK(不跑 deploy 工具的 --init)
#
# 为什么需要它：pyside6-android-deploy --init 每次都会 cleanup()，会清掉 .buildozer
# 里的编译产物 —— 一次冷构建要几十分钟，改一个 spec 键不值得重来。
# 这里直接复用已编译好的 dist，只重打 buildozer.spec 补丁再跑 buildozer。
#
# 前提：buildozer.spec 已存在(由 wsl_build_apk.sh 的 --init 生成过)
set -uo pipefail
WORK="${WORK:-"$JM_WORK"}"
SRC="$WORK/src"
ANDROID="$SRC/android"
SDK="$WORK/android-sdk"
NDK="$SDK/ndk/26.1.10909125"
VPY="$WORK/venv311/bin/python"
P4A="$WORK/p4a"

export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export ANDROID_HOME="$SDK" ANDROID_SDK_ROOT="$SDK" ANDROID_NDK_HOME="$NDK"
export PATH="$WORK/venv311/bin:$JAVA_HOME/bin:$PATH"
export VIRTUAL_ENV="$WORK/venv311"
export PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
if [ -f /opt/java-ca.jks ]; then
    export JAVA_TOOL_OPTIONS="-Djavax.net.ssl.trustStore=/opt/java-ca.jks -Djavax.net.ssl.trustStorePassword=changeit"
fi
CA_BUNDLE=$("$VPY" -c "import certifi;print(certifi.where())" 2>/dev/null || echo "")
if [ -n "$CA_BUNDLE" ] && [ -f "$CA_BUNDLE" ]; then
    export SSL_CERT_FILE="$CA_BUNDLE" REQUESTS_CA_BUNDLE="$CA_BUNDLE"
fi
mkdir -p "$WORK/logs"
exec > >(tee -a "$WORK/logs/repack.log") 2>&1

echo "===== [$(date +%T)] 0. 同步仓库(保留 libs/wheels/.buildozer) ====="
bash "$JM_REPO/android/tools/wsl_sync.sh"

echo "===== [$(date +%T)] 1. 重装 Qt 插件到 libs ====="
bash "$JM_REPO/android/tools/wsl_install_qt_plugins.sh" || true

[ -f "$ANDROID/buildozer.spec" ] || { echo "缺少 buildozer.spec，请先跑 wsl_build_apk.sh 生成"; exit 1; }

echo "===== [$(date +%T)] 2. 原地重打 buildozer.spec 补丁 ====="
"$VPY" "$ANDROID/tools/patch_buildozer_spec.py" "$ANDROID/buildozer.spec" \
    --p4a-dir "$P4A" --recipes "$ANDROID/recipes" \
    --libs "libs/arm64-v8a" --models "$ANDROID/sr_qnn/models" 2>&1 | tail -20
echo "--- 关键配置 ---"
grep -E '^(source\.include_exts|android\.add_libs_arm64_v8a|android\.minapi|android\.api|android\.add_assets)' "$ANDROID/buildozer.spec" | cut -c1-200
if grep -qE '^android\.add_assets' "$ANDROID/buildozer.spec"; then
    echo "[FATAL] android.add_assets 仍然存在，p4a 打包会 FileExistsError"
    exit 1
fi

echo "===== [$(date +%T)] 2.5 修正 p4a bootstrap 的 PYTHONOPTIMIZE ====="
# 必须在 buildozer 之前跑：dist 里那份 PythonActivity.java 才是 Gradle 编译的
bash "$JM_REPO/android/tools/wsl_patch_optimize.sh" || {
    echo "[FATAL] PYTHONOPTIMIZE 补丁失败"; exit 1; }

echo "===== [$(date +%T)] 3. buildozer android debug(复用已编译 recipe) ====="
cd "$ANDROID"
yes | "$VPY" -m buildozer android debug 2>&1 | tee "$WORK/logs/buildozer_full.log" | tail -100
echo "buildozer exit=${PIPESTATUS[1]}"

echo "===== [$(date +%T)] 4. 产物 ====="
ls -sh "$ANDROID/bin" 2>/dev/null || echo "(bin 目录为空)"
find "$ANDROID" -maxdepth 3 -name '*.apk' 2>/dev/null
echo "===== [$(date +%T)] 结束 ====="
