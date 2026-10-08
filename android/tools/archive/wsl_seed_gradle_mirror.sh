#!/usr/bin/env bash
# 从国内镜像取 gradle 发行版(官方源只有 ~11KB/s)
set -uo pipefail
VER=8.14.3
HD=/root/.gradle/wrapper/dists/gradle-$VER-all/h9bud5ffjflfoe91ghcb596uv
ZIP="$HD/$VER.zip.tmp"
mkdir -p "$HD"
pkill -f 'gradle-8.14.3-all.zip' 2>/dev/null || true
sleep 1
exec > >(tee -a /root/jmcomic-build/logs/gradle_mirror.log) 2>&1

echo "== 候选镜像测速(各拉 3MB) =="
for u in \
  "https://mirrors.huaweicloud.com/gradle/gradle-$VER-all.zip" \
  "https://mirrors.cloud.tencent.com/gradle/gradle-$VER-all.zip" \
  "https://mirrors.aliyun.com/gradle/gradle-$VER-all.zip" \
  "https://downloads.gradle.org/distributions/gradle-$VER-all.zip" ; do
    t0=$(date +%s%N)
    got=$(curl -sSLk -m 25 -o /dev/null -w '%{size_download}' -r 0-3000000 "$u" 2>/dev/null)
    t1=$(date +%s%N)
    ms=$(( (t1 - t0) / 1000000 ))
    kbps=$(( got / 1024 / (ms / 1000 + 1) ))
    printf '%-62s %8s bytes %6s ms  %6s KB/s\n' "$(echo "$u" | cut -c1-62)" "$got" "$ms" "$kbps"
done

echo
echo "== 用最快的镜像下载 =="
for u in \
  "https://mirrors.huaweicloud.com/gradle/gradle-$VER-all.zip" \
  "https://mirrors.cloud.tencent.com/gradle/gradle-$VER-all.zip" \
  "https://mirrors.aliyun.com/gradle/gradle-$VER-all.zip" ; do
    echo "尝试 $u"
    rm -f "$ZIP"
    if curl -sSLk --retry 2 -m 1200 -o "$ZIP" "$u" && [ "$(stat -c%s "$ZIP")" -gt 20000000 ]; then
        echo "  下载完成: $(du -h "$ZIP" | cut -f1)"
        break
    fi
    echo "  失败/太小"
done
if [ ! -s "$ZIP" ] || [ "$(stat -c%s "$ZIP")" -lt 20000000 ]; then
    echo "镜像都失败，保留官方下载(可能仍在进行)"; exit 1
fi

mv -f "$ZIP" "$HD/gradle-$VER-all.zip"
rm -f "$HD/gradle-$VER-all.zip.part" "$HD/gradle-$VER-all.zip.lck"
echo "== 解压 =="
if [ ! -d "$HD/gradle-$VER" ]; then
    (cd "$HD" && (python3 -m zipfile -e "gradle-$VER-all.zip" . || unzip -q -o "gradle-$VER-all.zip"))
fi
ls -d "$HD/gradle-$VER" && echo "解压 ✓"
touch "$HD/gradle-$VER-all.zip.ok"

echo
echo "== 验证 gradlew =="
cd /root/jmcomic-build/src/android/.buildozer/android/platform/build-arm64-v8a/dists/JMComic || exit 1
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export ANDROID_HOME=/root/jmcomic-build/android-sdk
export ANDROID_SDK_ROOT=$ANDROID_HOME
export PATH="$JAVA_HOME/bin:$PATH"
timeout 300 ./gradlew --version 2>&1 | tail -10
