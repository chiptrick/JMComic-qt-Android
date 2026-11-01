# coding:utf-8
"""脚本卫生检查：换行符 / BOM / shebang / 可执行位

背景
------------------------------------------------------------------
仓库用 .gitattributes 约束了 android/**/*.sh 必须是 LF，但只要有一次
"在 Windows 上直接改文件 + 复制粘贴"，就可能混进 CRLF。CRLF 的 shell 脚本在
Linux/WSL 下的报错是：

    bash: ./build_android.sh: /usr/bin/env: bad interpreter: No such file or directory

看起来像"环境没装 bash"，实际是文件第一行的 \\r 让内核找不到解释器。
同理，UTF-8 BOM 会让 shebang 变成 \\ufeff#!/usr/bin/env bash，一样起不来。

所以把这件事做成可自动化的一道检查，而不是靠人记得。

用法
------------------------------------------------------------------
    python tools/check_scripts.py [路径...]        # 默认检查 android/
    python tools/check_scripts.py --fix            # 就地修（CRLF->LF，去 BOM）
    python tools/check_scripts.py --json           # 给 CI 用

退出码：0 干净（或已全部修复）/ 1 有问题
"""
import argparse
import json
import os
import sys

SKIP_DIRS = {
    ".work", ".buildozer", ".venv", "build_logs", "app_src", "libs", "dist",
    "wheels", "__pycache__", "archive", ".git", "models_stage", "logs",
}
TARGET_EXT = (".sh", ".py")


def IterScripts(roots):
    for root in roots:
        if os.path.isfile(root):
            yield root, os.path.basename(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in sorted(filenames):
                if name.endswith(TARGET_EXT):
                    yield os.path.join(dirpath, name), name


def CheckFile(path):
    """返回 (问题列表, 是否可自动修)"""
    problems = []
    with open(path, "rb") as handle:
        raw = handle.read()

    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append("UTF-8 BOM（shebang 会失效）")

    if b"\r\n" in raw:
        lines = raw.count(b"\r\n")
        problems.append("CRLF 换行（{} 行），Linux/WSL 下会 bad interpreter".format(lines))
    elif b"\r" in raw:
        problems.append("存在孤立 CR 字符")

    if path.endswith(".sh"):
        first = raw.split(b"\n", 1)[0]
        if not first.startswith(b"#!"):
            problems.append("缺少 shebang")
        elif b"bash" not in first:
            problems.append("shebang 不是 bash: {}".format(
                first.decode("utf-8", "replace")))
        if os.name != "nt" and not os.access(path, os.X_OK):
            problems.append("缺少可执行位（影响直接 ./x.sh 调用）")

    return problems


def FixFile(path, problems):
    with open(path, "rb") as handle:
        raw = handle.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    if b"\r\n" in raw:
        raw = raw.replace(b"\r\n", b"\n")
    with open(path, "wb") as handle:
        handle.write(raw)
    if path.endswith(".sh") and os.name != "nt":
        mode = os.stat(path).st_mode
        os.chmod(path, mode | 0o111)
    return True


def Main():
    parser = argparse.ArgumentParser(description="检查脚本的换行符/BOM/shebang/可执行位")
    parser.add_argument("paths", nargs="*", help="默认 android/")
    parser.add_argument("--fix", action="store_true", help="就地修复可自动修的问题")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    roots = args.paths or [os.getcwd()]
    findings = []
    fixed = 0

    for path, name in IterScripts(roots):
        try:
            problems = CheckFile(path)
        except OSError as exc:
            findings.append({"path": path, "problems": ["读取失败: {}".format(exc)]})
            continue
        if not problems:
            continue
        if args.fix:
            FixFile(path, problems)
            fixed += 1
            continue
        findings.append({"path": path, "problems": problems})

    if args.json:
        print(json.dumps({"checked_fixed": fixed, "findings": findings},
                         ensure_ascii=False, indent=2))
    else:
        for item in findings:
            print("[FAIL] {}".format(os.path.relpath(item["path"])))
            for problem in item["problems"]:
                print("       - {}".format(problem))
        if fixed:
            print("[FIX]  已修复 {} 个文件（CRLF->LF / 去 BOM / 补可执行位）".format(fixed))
        if not findings:
            print("[OK]  脚本换行符/shebang/可执行位检查通过{}".format(
                "（已顺带修复 {} 个）".format(fixed) if fixed else ""))
        elif not args.fix:
            print("\n修复：python tools/check_scripts.py --fix   （或在 git 里重新 checkout）")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(Main())
