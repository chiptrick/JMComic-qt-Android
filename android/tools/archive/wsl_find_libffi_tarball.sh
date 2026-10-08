#!/usr/bin/env bash
# 找一个"真的含 configure"的 libffi release 包
set -uo pipefail
VER=3.4.2
TMP=/tmp/lf_probe.tar.gz
test_src() {
    local name="$1" url="$2"
    rm -f "$TMP"
    local code
    code=$(curl -sSL -m 90 -o "$TMP" -w '%{http_code}' "$url" 2>/dev/null)
    local size=0
    [ -f "$TMP" ] && size=$(stat -c%s "$TMP")
    local has="?"
    if [ "$size" -gt 100000 ]; then
        if tar -tzf "$TMP" >/dev/null 2>&1; then
            if tar -tzf "$TMP" 2>/dev/null | grep -qE '/configure$'; then has=YES; else has=no; fi
        else
            has="不是tar(可能是错误页)"
        fi
    fi
    printf '%-52s http=%-4s %8s bytes  configure=%s\n' "$name" "$code" "$size" "$has"
}
echo "=== 候选源 ==="
test_src "sourceware.org" "https://sourceware.org/pub/libffi/libffi-$VER.tar.gz"
test_src "tuna/sourceware" "https://mirrors.tuna.tsinghua.edu.cn/sourceware/libffi/libffi-$VER.tar.gz"
test_src "ustc/sourceware" "https://mirrors.ustc.edu.cn/sourceware/libffi/libffi-$VER.tar.gz"
test_src "aliyun?" "https://mirrors.aliyun.com/libffi/libffi-$VER.tar.gz"
test_src "ghproxy release" "https://ghproxy.net/https://github.com/libffi/libffi/releases/download/v$VER/libffi-$VER.tar.gz"
test_src "github release 直连" "https://github.com/libffi/libffi/releases/download/v$VER/libffi-$VER.tar.gz"
echo
echo "=== cffi 里是否自带 libffi 源码(备选) ==="
/root/jmcomic-build/venv311/bin/python - <<'EOF'
try:
    import cffi, os
    d = os.path.dirname(cffi.__file__)
    print("cffi:", d)
    print("含 libffi 目录:", os.path.isdir(os.path.join(d, "libffi")))
except Exception as es:
    print("cffi 未安装:", es)
EOF
