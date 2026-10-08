# coding:utf-8
"""静态检查 sr_qnn 的 C++ 接口与 Python ctypes 绑定是否一致

Android 原生库没法在 Windows 上编译，所以用这个脚本做“接口漂移”检查：
    1. sr_qnn.h 里声明的 srq_* 函数，必须在 sr_qnn.cpp 里有定义
    2. python 侧 ctypes 绑定/调用的 srq_* 函数，必须在头文件里声明
    3. 每个函数的参数个数要与头文件声明一致(ctypes argtypes 数量)

用法: python android/tools/check_interfaces.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HEADER = os.path.join(ROOT, "android", "sr_qnn", "cpp", "sr_qnn.h")
SOURCE = os.path.join(ROOT, "android", "sr_qnn", "cpp", "sr_qnn.cpp")
PYTHON = os.path.join(ROOT, "android", "sr_qnn", "__init__.py")


def Read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def ParseHeaderParams(text):
    """ 解析头文件声明 -> {函数名: 参数个数} """
    result = {}
    body = text.split("extern \"C\"")[-1]
    for match in re.finditer(r"([A-Za-z_][\w \*]*?)\s+(srq_\w+)\s*\(([^;]*?)\)\s*;", body, re.S):
        name = match.group(2)
        params = match.group(3).strip()
        if not params or params == "void":
            count = 0
        else:
            # 按逗号切分，避免函数指针造成的误判(本接口没有)
            count = len([p for p in params.split(",") if p.strip()])
        result[name] = count
    return result


def ParseSourceDefines(text):
    result = set()
    for match in re.finditer(r"^\s*[A-Za-z_][\w \*]*?\s+(srq_\w+)\s*\(([^)]*)\)\s*\{", text, re.M):
        result.add(match.group(1))
    return result


def ParsePython(text):
    """ 解析 ctypes 绑定 -> {函数名: argtypes 个数}，以及所有被调用的函数名 """
    binds = {}
    for match in re.finditer(r"lib\.(srq_\w+)\.argtypes\s*=\s*\[([^\]]*)\]", text, re.S):
        name = match.group(1)
        args = [a for a in match.group(2).split(",") if a.strip()]
        binds[name] = len(args)
    used = set(re.findall(r"_lib\.(srq_\w+)\s*\(", text))
    used |= set(binds.keys())
    return binds, used


def Main():
    header = ParseHeaderParams(Read(HEADER))
    defines = ParseSourceDefines(Read(SOURCE))
    binds, used = ParsePython(Read(PYTHON))
    errors = []

    for name in sorted(header):
        if name not in defines:
            errors.append("头文件声明了 {} 但 sr_qnn.cpp 里没有定义".format(name))
    for name in sorted(used):
        if name not in header:
            errors.append("python 用了 {} 但 sr_qnn.h 里没有声明".format(name))
    for name, count in sorted(binds.items()):
        if name not in header:
            continue
        if header[name] != count:
            errors.append("{} 参数个数不一致: C {} 个, python argtypes {} 个".format(
                name, header[name], count))
    # 头文件里声明但 python 完全没绑定的(允许，但要提示)
    unbound = sorted(set(header) - used)
    if unbound:
        print("[warn] 头文件有但 python 未使用: {}".format(", ".join(unbound)))

    print("已检查: C 声明 {} 个, C 定义 {} 个, python 绑定 {} 个".format(
        len(header), len(defines), len(binds)))
    if errors:
        print("\n发现 {} 个接口不一致问题:".format(len(errors)))
        for item in errors:
            print("  - {}".format(item))
        return 1
    print("接口一致，检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(Main())
