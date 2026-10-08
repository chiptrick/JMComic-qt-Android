#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 用 venv311 的 python 逐模式测试 urllib 证书校验
set -uo pipefail
VPY="$JM_WORK/venv311/bin/python"
SCRIPT="$JM_REPO/android/tools/wsl_test_urllib_certs.py"
CERTIFI=$("$VPY" -c "import certifi;print(certifi.where())")
echo "certifi=$CERTIFI"
for mode in default certifi unverified; do
    echo "=== $mode ==="
    SSL_CERT_FILE="$CERTIFI" "$VPY" "$SCRIPT" "$mode" 2>&1 | tail -9
done
