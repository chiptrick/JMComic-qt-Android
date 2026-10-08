#!/usr/bin/env python3
"""列出 onnxruntime-android-qnn AAR 内容，确认 QNN 运行库是否包含在内"""
import collections
import zipfile

path = "/root/jmcomic-build/tools/onnxruntime-android-qnn-1.23.2.aar"
z = zipfile.ZipFile(path)
names = z.namelist()
print("总条目:", len(names))
print("顶层目录:", collections.Counter(n.split("/")[0] for n in names))
print("--- .so / qnn 相关 ---")
for n in names:
    low = n.lower()
    if n.endswith(".so") or "qnn" in low:
        print("  ", n, z.getinfo(n).file_size)
print("--- 全部条目(前 60) ---")
for n in names[:60]:
    print("  ", n)
