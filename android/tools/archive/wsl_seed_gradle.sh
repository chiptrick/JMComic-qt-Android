#!/usr/bin/env bash
# 用 curl -k / python 取 gradle 发行版，放进 wrapper 缓存并验证
set -uo pipefail
WORK=/root/jmcomic-build
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
VER=8.14.3
HD=/root/.gradle/wrapper/dists/gradle-$VER-all/h9bud5ffjflfoe91ghcb596uv
ZIP="$HD/gradle-$VER-all.zip"
mkdir -p "$HD"
exec > >(tee -a "$WORK/logs/gradle_seed.log") 2>&1

if [ ! -s "$ZIP" ] || [ "$(stat -c%s "$ZIP")" -lt 10000000 ]; then
    echo "== 下载 gradle $VER (curl -k) =="
    rm -f "$ZIP"
    curl -sSLk --retry 3 -m 1800 -o "$ZIP" "https://services.gradle.org/distributions/gradle-$VER-all.zip" || true
fi
if [ ! -s "$ZIP" ] || [ "$(stat -c%s "$ZIP")" -lt 10000000 ]; then
    echo "== 失败，改用 python+certifi =="
    /root/jmcomic-build/venv311/bin/python - "$ZIP" "$VER" <<'EOF'
import ssl, sys, urllib.request
try:
    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
except Exception:
    ctx = ssl._create_unverified_context()
url = f"https://services.gradle.org/distributions/gradle-{sys.argv[2]}-all.zip"
with urllib.request.urlopen(url, timeout=600, context=ctx) as r, open(sys.argv[1], "wb") as f:
    while True:
        b = r.read(1 << 20)
        if not b:
            break
        f.write(b)
print("ok")
EOF
fi
ls -sh "$ZIP" || { echo "gradle zip 仍未取得"; exit 1; }

echo "== 解压 =="
if [ ! -d "$HD/gradle-$VER" ]; then
    (cd "$HD" && (python3 -m zipfile -e "gradle-$VER-all.zip" . || unzip -q -o "gradle-$VER-all.zip"))
fi
ls -d "$HD/gradle-$VER" && echo "解压 ✓"

echo
echo "== 验证 gradlew --version =="
cd /root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic || exit 1
export ANDROID_HOME=/root/jmcomic-build/android-sdk
export ANDROID_SDK_ROOT=$ANDROID_HOME
export PATH="$JAVA_HOME/bin:$PATH"
timeout 300 ./gradlew --version 2>&1 | tail -12
