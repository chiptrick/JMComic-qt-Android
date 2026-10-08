#!/usr/bin/env bash
# 彻底解决 Java TLS：
#   1) 用系统 CA 生成的 truststore 直接替换 JDK 的 cacerts(所有 JVM 都信任)
#   2) 用 curl 预置 gradle 发行版 zip，绕开 wrapper 的下载(它用的是自己的 JVM)
set -uo pipefail
WORK=/root/jmcomic-build
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
GRADLE_VER=8.14.3
exec > >(tee -a "$WORK/logs/java_ca2.log") 2>&1

echo "== 1) 替换 JDK cacerts =="
CACERTS="$JAVA_HOME/lib/security/cacerts"
if [ -f /opt/java-ca.jks ]; then
    [ -f "$CACERTS.orig" ] || cp -f "$CACERTS" "$CACERTS.orig"
    cp -f /opt/java-ca.jks "$CACERTS"
    echo "已替换 $CACERTS (备份 $CACERTS.orig)"
    keytool -list -keystore "$CACERTS" -storepass changeit 2>/dev/null | tail -1
else
    echo "缺少 /opt/java-ca.jks，先跑 wsl_fix_java_ca.sh"
fi

echo
echo "== 2) 预置 gradle $GRADLE_VER 发行版 =="
HASH_DIR=$(ls -d /root/.gradle/wrapper/dists/gradle-$GRADLE_VER-all/*/ 2>/dev/null | head -1)
if [ -z "$HASH_DIR" ]; then
    # 手动算出 wrapper 的 hash 目录名(base36(md5(url)))，先建一个占位再取实际名
    mkdir -p /root/.gradle/wrapper/dists/gradle-$GRADLE_VER-all
    HASH_DIR=/root/.gradle/wrapper/dists/gradle-$GRADLE_VER-all/$(python3 - <<EOF
import base64, hashlib
url = "https://services.gradle.org/distributions/gradle-$GRADLE_VER-all.zip"
digest = hashlib.md5(url.encode()).digest()
num = int.from_bytes(digest, "big")
alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
s = ""
while num:
    num, rem = divmod(num, 36)
    s = alphabet[rem] + s
print(s)
EOF
)
    mkdir -p "$HASH_DIR"
fi
echo "wrapper 目录: $HASH_DIR"
ZIP="$HASH_DIR/gradle-$GRADLE_VER-all.zip"
if [ ! -s "$ZIP" ]; then
    echo "curl 下载 gradle 发行版(约 150MB)..."
    curl -sSL --retry 3 -m 1800 -o "$ZIP" "https://services.gradle.org/distributions/gradle-$GRADLE_VER-all.zip"
fi
ls -sh "$ZIP" 2>/dev/null || { echo "gradle zip 下载失败"; exit 1; }
# wrapper 会自己解压；这里也直接解压一份并写 .ok，双保险
if [ ! -d "$HASH_DIR/gradle-$GRADLE_VER" ]; then
    (cd "$HASH_DIR" && python3 -m zipfile -e "gradle-$GRADLE_VER-all.zip" . 2>/dev/null || unzip -q -o "gradle-$GRADLE_VER-all.zip")
fi
touch "$ZIP.ok" 2>/dev/null || true
ls -d "$HASH_DIR"/gradle-$GRADLE_VER 2>/dev/null && echo "已解压 ✓"

echo
echo "== 3) 给 gradle daemon 也配上 truststore =="
mkdir -p /root/.gradle
cat > /root/.gradle/gradle.properties <<'EOF'
org.gradle.jvmargs=-Xmx3g -Djavax.net.ssl.trustStore=/opt/java-ca.jks -Djavax.net.ssl.trustStorePassword=changeit
org.gradle.daemon=false
EOF
cat /root/.gradle/gradle.properties

echo
echo "== 4) 验证: 直接跑 gradlew --version(不下载发行版) =="
cd /root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic 2>/dev/null || exit 1
export ANDROID_HOME=/root/jmcomic-build/android-sdk
export ANDROID_SDK_ROOT=$ANDROID_HOME
export PATH="$JAVA_HOME/bin:$PATH"
timeout 300 ./gradlew --version 2>&1 | tail -12
