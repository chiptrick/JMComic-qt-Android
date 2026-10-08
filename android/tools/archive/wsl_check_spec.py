#!/usr/bin/env python3
"""复现部署工具读取 pysidedeploy.spec 的结果"""
import configparser

path = "/root/jmcomic-build/src/android/pysidedeploy.spec"
print("=== 文件全文 ===")
print(open(path, encoding="utf-8").read())

parser = configparser.ConfigParser(comment_prefixes="/", strict=False, allow_no_value=True)
parser.read(path)
print("=== sections ===", parser.sections())
for sec in parser.sections():
    print("  [%s] keys=%s" % (sec, parser.options(sec)))
try:
    print("qt.modules =", repr(parser.get("qt", "modules")))
except Exception as e:
    print("qt.modules 读取失败:", e)
try:
    print("buildozer.ndk_path =", repr(parser.get("buildozer", "ndk_path")))
except Exception as e:
    print("buildozer.ndk_path 读取失败:", e)
