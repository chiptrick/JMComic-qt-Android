#!/usr/bin/env bash
# 1) legacy PyPI 直链是否可用 2) jmcomic 包内部是否强依赖 yaml/curl_cffi
set -uo pipefail
WORK=/root/jmcomic-build
VPY="$WORK/venv-host/bin/python"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"

echo "=== legacy 直链测试 ==="
for u in "https://files.pythonhosted.org/packages/source/j/jmcomic/jmcomic-2.7.7.tar.gz" \
         "https://files.pythonhosted.org/packages/source/P/PyYAML/PyYAML-6.0.2.tar.gz" \
         "https://pypi.tuna.tsinghua.edu.cn/packages/source/j/jmcomic/jmcomic-2.7.7.tar.gz"; do
    code=$(curl -sSL -m 25 -o /dev/null -w '%{http_code}' -r 0-2000 "$u" 2>/dev/null)
    [ -z "$code" ] && code=FAIL
    echo "$code  $u"
done

echo
echo "=== 下载 jmcomic 并检查 import 依赖 ==="
rm -rf /tmp/jmchk && mkdir -p /tmp/jmchk
$VPY -m pip download -q --no-deps -i "$MIRROR" -d /tmp/jmchk jmcomic 2>&1 | tail -2
ls -sh /tmp/jmchk
python3 - <<'EOF'
import glob, tarfile, zipfile, os, re
src = None
for p in glob.glob('/tmp/jmchk/*'):
    if p.endswith('.whl'):
        z = zipfile.ZipFile(p)
        os.makedirs('/tmp/jmchk/x', exist_ok=True)
        z.extractall('/tmp/jmchk/x')
        src = '/tmp/jmchk/x'
    elif p.endswith('.tar.gz'):
        t = tarfile.open(p)
        t.extractall('/tmp/jmchk/x')
        src = '/tmp/jmchk/x'
print('解包到', src)
hits = {}
for root, _, files in os.walk(src):
    for f in files:
        if not f.endswith('.py'):
            continue
        path = os.path.join(root, f)
        text = open(path, encoding='utf-8', errors='ignore').read()
        for mod in ('yaml', 'curl_cffi', 'Cryptodome', 'Crypto', 'PIL'):
            for m in re.finditer(r'^\s*(?:from|import)\s+%s\b' % mod, text, re.M):
                # 记录是顶层还是缩进(函数内)
                line = text[:m.start()].count('\n')
                raw = text.splitlines()[line]
                top = not raw.startswith((' ', '\t'))
                hits.setdefault(mod, []).append((os.path.relpath(path, src), top))
for mod, lst in hits.items():
    top = [x for x in lst if x[1]]
    print('%-10s 引用 %2d 处, 其中顶层(import 即触发) %d 处: %s' % (
        mod, len(lst), len(top), [x[0] for x in top[:5]]))
EOF
