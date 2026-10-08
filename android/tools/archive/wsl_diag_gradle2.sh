#!/usr/bin/env bash
# 手动运行 gradle 包装器，拿到真实错误
set -uo pipefail
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export ANDROID_HOME=/root/jmcomic-build/android-sdk
export ANDROID_SDK_ROOT=$ANDROID_HOME
export PATH="$JAVA_HOME/bin:$PATH"
D=/root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic
cd "$D"
echo "=== distributionUrl ==="
cat gradle/wrapper/gradle-wrapper.properties
echo
echo "=== gradlew --version (最多 240s) ==="
timeout 240 ./gradlew --version 2>&1 | tail -25
echo "exit=$?"
echo
echo "=== 网络: services.gradle.org 可达性 ==="
curl -sS -m 15 -o /dev/null -w 'services.gradle.org: %{http_code}\n' https://services.gradle.org/distributions/ 2>&1 | tail -2
curl -sSL -m 15 -o /dev/null -w 'gradle dist(HEAD): %{http_code}\n' -r 0-100 "$(grep distributionUrl gradle/wrapper/gradle-wrapper.properties | cut -d= -f2 | sed 's/\\//g')" 2>&1 | tail -2
