#!/usr/bin/env bash
# 把系统 CA 根证书导入 JDK 的 cacerts（幂等），一次性解决
# "PKIX path building failed / unable to find valid certification path" 这类 TLS 报错。
#
# 为什么：精简 JDK 的 cacerts 只带发行方自带的 CA；在证书链不完整的网络环境
# （或被网关替换证书的内网）里，Java 的严格链校验会失败，而 curl 用系统信任库就能过。
#
# 用法: bash tools/patch_java_cacerts.sh <JAVA_HOME>
set -uo pipefail
JAVA_HOME_DIR="${1:-${JAVA_HOME:-}}"
[ -n "$JAVA_HOME_DIR" ] || { echo "需要 JAVA_HOME" >&2; exit 2; }
CACERTS="$JAVA_HOME_DIR/lib/security/cacerts"
KEYTOOL="$JAVA_HOME_DIR/bin/keytool"
[ -f "$CACERTS" ] || { echo "[FAIL] 找不到 $CACERTS" >&2; exit 2; }
[ -x "$KEYTOOL" ] || { echo "[FAIL] 找不到 keytool" >&2; exit 2; }

# 系统 CA 捆绑包（Fedora/RHEL 与 Debian 各取常见位置）
BUNDLE=""
for cand in /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem \
            /etc/ssl/certs/ca-certificates.crt; do
    [ -f "$cand" ] && BUNDLE="$cand" && break
done
[ -n "$BUNDLE" ] || { echo "[FAIL] 找不到系统 CA 捆绑包" >&2; exit 2; }

MD5FILE="$JAVA_HOME_DIR/lib/security/.jm-cacerts-md5"
cur_md5="$(md5sum "$BUNDLE" 2>/dev/null | cut -d' ' -f1)"
if [ -f "$MD5FILE" ] && [ "$(cat "$MD5FILE" 2>/dev/null)" = "$cur_md5" ]; then
    echo "[OK]   cacerts 已导入过该 CA 包（$BUNDLE），跳过"
    exit 0
fi

# 删掉上一轮导入的 jm-ca-*，再按证书逐个导入（keytool 一次只能导一个）
"$KEYTOOL" -list -keystore "$CACERTS" -storepass changeit 2>/dev/null \
    | grep -oE "jm-ca-[0-9]+" | sort -u \
    | while read -r alias; do
          "$KEYTOOL" -delete -alias "$alias" -keystore "$CACERTS" \
              -storepass changeit >/dev/null 2>&1 || true
      done

n=0; ok=0; fail=0
TMPD="$(mktemp -d "${TMPDIR:-/tmp}/jm-ca.XXXXXX")"
# Fedora 的 bundle 是 p11-kit 格式：注释行与证书块交织，awk/流式拆分会把
# 注释混进 PEM 导致 keytool 报"不是 X.509 证书"——用 python 按 PEM 块精确切分。
python3 - "$BUNDLE" "$TMPD" <<'PY'
import pathlib, re, sys
data = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
blocks = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", data, re.S)
out = pathlib.Path(sys.argv[2])
for i, block in enumerate(blocks, 1):
    (out / ("ca-%03d.pem" % i)).write_text(block + "\n", encoding="utf-8")
print("  拆出 %d 个证书" % len(blocks))
PY
for f in "$TMPD"/ca-*.pem; do
    [ -f "$f" ] || continue
    n=$((n + 1))
    if "$KEYTOOL" -importcert -noprompt -alias "jm-ca-$n" -file "$f" \
            -keystore "$CACERTS" -storepass changeit >/dev/null 2>&1; then
        ok=$((ok + 1))
    else
        fail=$((fail + 1))
    fi
    command rm -f "$f"
done
command rmdir "$TMPD" 2>/dev/null || true
[ "$fail" -eq 0 ] || echo "[warn] $fail 个证书导入失败（多为非 X.509 格式，可忽略）"
printf '%s' "$cur_md5" > "$MD5FILE"
echo "[OK]   已向 $CACERTS 导入 $ok/$n 个系统 CA（bundle: $BUNDLE）"
