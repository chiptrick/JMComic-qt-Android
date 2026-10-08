#!/usr/bin/env bash
# 探测 WSL Ubuntu 是否具备 Android 构建条件(只读，不改环境)
echo "=== os ==="
cat /etc/os-release | head -3
echo "=== cpu/mem/disk ==="
nproc; free -h | head -2; df -h / "$HOME" | tail -2
echo "=== python ==="
python3 --version 2>&1
for v in 3.10 3.11 3.12 3.13; do command -v "python$v" >/dev/null && echo "python$v: $(python$v --version 2>&1)"; done
python3 -m venv --help >/dev/null 2>&1 && echo "venv: ok" || echo "venv: MISSING"
echo "=== java ==="
java -version 2>&1 | head -2 || echo "java: MISSING"
echo "=== build tools ==="
for c in git curl unzip zip cmake make gcc g++ rsync file aapt2; do
    p=$(command -v "$c" 2>/dev/null)
    printf '%-8s %s\n' "$c" "${p:-MISSING}"
done
echo "=== android sdk/ndk ==="
echo "ANDROID_HOME=${ANDROID_HOME:-unset} ANDROID_SDK_ROOT=${ANDROID_SDK_ROOT:-unset} ANDROID_NDK_HOME=${ANDROID_NDK_HOME:-unset}"
for d in "$HOME/Android/Sdk" "$HOME/android-sdk" /opt/android-sdk /usr/lib/android-sdk; do
    [ -d "$d" ] && echo "found sdk dir: $d" && ls "$d"
done
echo "=== network ==="
for url in https://pypi.org/simple/ https://repo1.maven.org/maven2/ \
           https://download.qt.io/official_releases/QtForPython/pyside6/ \
           https://raw.githubusercontent.com/microsoft/onnxruntime/main/README.md \
           https://dl.google.com/android/repository/repository2-3.xml; do
    code=$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null) || code=FAIL
    printf '%-70s %s\n' "$url" "$code"
done
echo "=== repo mount ==="
ls /path/to/JMComic-qt 2>/dev/null | head -5 || echo "repo not visible"
echo "=== symlink support on /mnt/c ==="
t=/path/to/JMComic-qt/.wsl_symlink_test
if ln -s /tmp "$t" 2>/dev/null; then echo "symlink: ok"; rm -f "$t"; else echo "symlink: FAILED"; fi
