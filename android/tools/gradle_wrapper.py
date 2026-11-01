# coding:utf-8
"""Gradle wrapper 版本检查 / 改写（8.14.3 落在 3 个 high 级公告的影响区间）

背景
------------------------------------------------------------------
Gradle 的版本不在本仓库里，而在 p4a 生成的 dist：

    .work/<abi>/.../dists/<name>/gradle/wrapper/gradle-wrapper.properties

每次 `pyside6-android-deploy --init` 都会按 p4a 模板重建它，所以"改一次就完了"
是不成立的——必须每次构建后回来看一眼。这个脚本负责看，并可选地改。

为什么只"检查 + 可选改写"而不强制升级：
    cross 大版本（8.x -> 9.x）会移除 8.x 里弃用的 API，而本项目的构建日志里
    Gradle 自己已经打了 "Deprecated Gradle features were used in this build,
    making it incompatible with Gradle 9.0."。强制跳 9 会直接把构建打断。
    同大版本的 8.14.6 只含安全修复，是安全的选择。

用法
------------------------------------------------------------------
    python tools/gradle_wrapper.py --search <目录...>          # 只检查
    python tools/gradle_wrapper.py --search <目录> --min 8.14.6
    python tools/gradle_wrapper.py --search <目录> --set 8.14.6  # 改写（下一次构建生效）
    python tools/gradle_wrapper.py --file <gradle-wrapper.properties> --json

退出码：0 满足下限 / 1 低于下限或找不到 wrapper / 2 参数问题
"""
import argparse
import glob
import json
import os
import re
import sys

URL_RE = re.compile(r"^distributionUrl\s*=\s*(.+)$", re.M)
VER_RE = re.compile(r"gradle-([0-9]+(?:\.[0-9]+)*)-(?:bin|all)\.zip")
DEFAULT_MIN = "8.14.6"


def ParseVer(text):
    try:
        return tuple(int(x) for x in text.split("."))
    except (ValueError, AttributeError):
        return ()


def VerBelow(left, right):
    """left < right（按数字段比较，缺位补 0）"""
    a, b = ParseVer(left), ParseVer(right)
    if not a or not b:
        return False
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return a < b


def FindWrappers(roots):
    found = []
    for root in roots:
        if os.path.isfile(root) and root.endswith(".properties"):
            found.append(root)
            continue
        for path in glob.glob(os.path.join(root, "**", "gradle-wrapper.properties"),
                              recursive=True):
            # 跳过 Gradle 自己的缓存目录（那里的 wrapper 是历史版本，不代表本次构建）
            norm = path.replace("\\", "/")
            if "/.gradle/" in norm or "/caches/" in norm:
                continue
            found.append(path)
    return sorted(set(found))


def ReadVersion(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    match = URL_RE.search(text)
    if not match:
        return "", text
    ver = VER_RE.search(match.group(1).strip())
    return (ver.group(1) if ver else ""), text


def SetVersion(path, version):
    """改写 distributionUrl；同时删掉 distributionSha256Sum（否则校验必失败）"""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        lines = handle.read().splitlines()

    changed = False
    out = []
    for line in lines:
        if line.startswith("distributionSha256Sum"):
            # 换了分发包，旧的校验和一定对不上；留着会让 wrapper 直接拒绝下载
            changed = True
            continue
        if line.startswith("distributionUrl"):
            # 分发包地址用模板生成（默认国内镜像）：downloads.gradle.org 的证书链
            # 会让 JDK 报 PKIX path building failed（见 tools/versions.env 说明）
            template = os.environ.get(
                "JM_GRADLE_DIST_URL_TEMPLATE",
                "https://services.gradle.org/distributions/gradle-{version}-all.zip")
            new_url = template.replace("{version}", version)
            if "{" in new_url or "}" in new_url:
                # 防线：模板占位符没被替换就写盘，gradlew 会拿着坏 URL 下载失败，
                # 报错还藏在几百行之后。宁可这里失败。
                print("[FAIL] distributionUrl 模板未正确渲染: {}".format(new_url))
                return 2
            new_line = "distributionUrl={}".format(new_url.replace(":", "\\:"))
            if new_line != line:
                changed = True
            out.append(new_line)
            continue
        out.append(line)

    if changed:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(out) + "\n")
    return changed


def Main():
    parser = argparse.ArgumentParser(description="检查/改写 Gradle wrapper 版本")
    parser.add_argument("--search", nargs="*", default=[], help="在这些目录下找 wrapper")
    parser.add_argument("--file", default="", help="直接指定 gradle-wrapper.properties")
    parser.add_argument("--min", default=DEFAULT_MIN, help="最低可接受版本（默认 8.14.6）")
    parser.add_argument("--set", default="", help="改写为指定版本")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paths = [args.file] if args.file else FindWrappers(args.search or ["."])
    if not paths:
        print("[WARN] 没找到 gradle-wrapper.properties（dist 还没生成？）")
        return 1 if args.set else 0

    results = []
    for path in paths:
        version, _text = ReadVersion(path)
        below = bool(version) and VerBelow(version, args.min)
        rewritten = False
        if args.set and version != args.set:
            rewritten = SetVersion(path, args.set)
        results.append({
            "path": path, "version": version, "min": args.min,
            "below_min": below, "rewritten_to": args.set if rewritten else "",
        })

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for item in results:
            if item["rewritten_to"]:
                tag = "[INFO]"
            elif item["below_min"]:
                tag = "[FAIL]"
            else:
                tag = "[OK]  "
            print("{} {}  (version={} min={})".format(
                tag, item["path"].replace("\\", "/"), item["version"] or "未知", item["min"]))
            if item["rewritten_to"]:
                print("       已改写为 {}（下一次构建会重新下载 distribution）".format(
                    item["rewritten_to"]))
            elif item["below_min"]:
                print("       低于安全下限：需要 python tools/gradle_wrapper.py "
                      "--search <dist根> --set {}".format(item["min"]))
                print("       或临时接受：JM_GRADLE_MIN={} 设置更低的下限".format(item["version"]))

    return 1 if any(r["below_min"] and not r["rewritten_to"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(Main())
