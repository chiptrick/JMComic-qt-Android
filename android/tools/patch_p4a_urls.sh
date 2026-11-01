#!/usr/bin/env bash
# 把 p4a 源码树里所有 GitHub 下载地址换成可达镜像（幂等）
#
# 覆盖两类地址：
#   https://github.com/...                （recipe 的源码包，绝大多数）
#   https://raw.githubusercontent.com/... （个别 recipe 的补丁文件）
# 同时扫整个 p4a 源码树——p4a 会把自己**复制**到 .buildozer/.../python-for-android/，
# 下载用那份副本，只改 venv 里的没用（实测构建仍直连 GitHub，502/超时）。
#
# 用法：
#   bash tools/patch_p4a_urls.sh <p4a 源码根>     # 根 = 含 pythonforandroid/ 的目录
# 镜像前缀取 JM_GH_MIRROR_PREFIX（默认 https://gh-proxy.com/，见 tools/versions.env）
set -uo pipefail
P4A_ROOT="${1:-}"
PREFIX="${JM_GH_MIRROR_PREFIX:-https://gh-proxy.com/}"
PREFIX="${PREFIX%/}/"
[ -n "$P4A_ROOT" ] || { echo "用法: $0 <p4a 源码根>" >&2; exit 2; }
[ -d "$P4A_ROOT/pythonforandroid/recipes" ] || { echo "不是 p4a 源码根: $P4A_ROOT" >&2; exit 2; }

python3 - "$P4A_ROOT" "$PREFIX" <<'PY'
import os, re, sys
root, prefix = sys.argv[1], sys.argv[2]
# 三个负向断言保证幂等：已经挂在任一已知镜像下的链接不再套第二层
pattern = re.compile(
    r"(?<!gh-proxy\.com/)(?<!ghfast\.top/)(?<!ghproxy\.net/)"
    r"(https://(?:github\.com|raw\.githubusercontent\.com)/)")
count = 0
for dirpath, _, files in os.walk(root):
    if "__pycache__" in dirpath:
        continue
    for name in files:
        if not name.endswith(".py"):
            continue
        path = os.path.join(dirpath, name)
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        new = pattern.sub(prefix + r"\1", text)
        if new != text:
            open(path, "w", encoding="utf-8").write(new)
            count += 1
print("  改写 %d 个文件 -> %s" % (count, prefix))
PY
