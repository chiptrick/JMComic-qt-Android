# coding:utf-8
"""检查 p4a 打出来的 stdlib.zip / _python_bundle 的布局

关心的是：python-for-android 编译标准库时用的字节码命名方式。
- `module.pyc`(legacy，zipimport 唯一认的形式) —— 换 PYTHONOPTIMIZE 也不会丢标准库
- `module.opt-2.pyc` —— 用 optimize=0 启动时会找不到标准库，那就不能随便改 PYTHONOPTIMIZE

用法: python3 android/tools/inspect_pybundle.py <stdlib.zip 或 _python_bundle 目录>
"""
import os
import sys
import zipfile


def InspectZip(path):
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    print("zip: {}  ({} 项)".format(path, len(names)))
    for want in ("os.pyc", "os.py", "os.opt-2.pyc", "os.opt-1.pyc",
                 "json/__init__.pyc", "json/__init__.opt-2.pyc",
                 "ctypes/util.pyc", "ctypes/util.py", "ctypes/util.opt-2.pyc"):
        print("   {:<28} {}".format(want, want in names))
    suffix = {}
    for name in names:
        if not name.endswith(".pyc"):
            continue
        base = os.path.basename(name)
        key = ".opt-2.pyc" if base.endswith(".opt-2.pyc") else (
            ".opt-1.pyc" if base.endswith(".opt-1.pyc") else ".pyc")
        suffix[key] = suffix.get(key, 0) + 1
    print("   字节码命名统计:", suffix)
    legacy = [n for n in sorted(names) if n.endswith(".pyc") and ".opt-" not in n][:5]
    print("   legacy 样例:", legacy)
    return suffix


def InspectDir(path):
    print("目录: {}".format(path))
    for name in sorted(os.listdir(path))[:25]:
        full = os.path.join(path, name)
        print("   {}{}".format(name, "/" if os.path.isdir(full) else ""))
    return {}


def Main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    target = sys.argv[1]
    if os.path.isdir(target):
        InspectDir(target)
        sub = os.path.join(target, "stdlib.zip")
        if os.path.isfile(sub):
            InspectZip(sub)
    elif zipfile.is_zipfile(target):
        suffix = InspectZip(target)
        bad = suffix.get(".opt-2.pyc", 0) + suffix.get(".opt-1.pyc", 0)
        if bad and not suffix.get(".pyc"):
            print("!! 标准库只有 opt-N 命名，改 PYTHONOPTIMIZE 会丢标准库")
            return 2
    else:
        print("既不是目录也不是 zip: {}".format(target))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(Main())
