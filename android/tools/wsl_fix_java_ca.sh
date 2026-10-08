#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# Java(JDK 的 cacerts)里缺部分 CA，导致 gradle wrapper/依赖下载 PKIX 校验失败。
# 这里把系统的 CA 集合导入一个 JKS truststore，并让构建用 JAVA_TOOL_OPTIONS 指向它。
set -uo pipefail
WORK="$JM_WORK"
JKS=/opt/java-ca.jks
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
exec > >(tee -a "$WORK/logs/java_ca.log") 2>&1

if [ ! -f "$JKS" ]; then
    echo "== 从 /etc/ssl/certs 生成 Java truststore =="
    rm -f "$JKS"
    count=0
    mkdir -p /tmp/capems && rm -f /tmp/capems/*
    # ca-certificates 里每个 CA 一个 .pem(可能重名，按 hash 命名)
    for pem in /etc/ssl/certs/*.pem; do
        [ -f "$pem" ] || continue
        out="/tmp/capems/$(basename "$pem")"
        cp -f "$pem" "$out"
    done
    first=1
    for pem in /tmp/capems/*.pem; do
        [ -f "$pem" ] || continue
        alias="ca$count"
        if keytool -importcert -noprompt -trustcacerts -alias "$alias" \
                -file "$pem" -keystore "$JKS" -storepass changeit >/dev/null 2>&1; then
            count=$((count + 1))
        fi
    done
    echo "导入 CA 数: $count"
fi
ls -sh "$JKS" 2>/dev/null || { echo "truststore 生成失败"; exit 1; }
keytool -list -keystore "$JKS" -storepass changeit 2>/dev/null | tail -2

echo
echo "== 用该 truststore 测试 Java 能否访问 gradle/maven/google =="
cat > /tmp/T.java <<'EOF'
import java.net.*;
import java.io.*;
public class T {
    public static void main(String[] a) throws Exception {
        for (String u : a) {
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(u).openConnection();
                c.setRequestProperty("Range", "bytes=0-100");
                c.setConnectTimeout(15000); c.setReadTimeout(15000);
                System.out.println("  ok   " + c.getResponseCode() + "  " + u);
            } catch (Exception e) {
                System.out.println("  FAIL " + u + " -> " + e);
            }
        }
    }
}
EOF
javac -d /tmp /tmp/T.java 2>/dev/null
java -Djavax.net.ssl.trustStore="$JKS" -Djavax.net.ssl.trustStorePassword=changeit -cp /tmp T \
    https://services.gradle.org/distributions/ \
    https://dl.google.com/android/repository/repository2-3.xml \
    https://repo1.maven.org/maven2/ 2>&1 | tail -6
