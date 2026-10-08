#!/usr/bin/env python3
"""查 onnxruntime-android-qnn 的 POM 依赖，以及历史版本 AAR 是否自带 QNN 运行库"""
import io
import urllib.request
import zipfile

BASE = "https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android-qnn"


def fetch(url, timeout=60):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


print("=== POM 依赖 (1.23.2) ===")
try:
    pom = fetch(f"{BASE}/1.23.2/onnxruntime-android-qnn-1.23.2.pom").decode("utf-8", "ignore")
    for line in pom.splitlines():
        if any(k in line for k in ("artifactId", "groupId", "version", "dependency")):
            print("  ", line.strip())
except Exception as e:
    print("  POM 获取失败:", e)

print("\n=== maven-metadata 可用版本 ===")
try:
    meta = fetch(f"{BASE}/maven-metadata.xml").decode("utf-8", "ignore")
    import re
    versions = re.findall(r"<version>([^<]+)</version>", meta)
    print("  ", versions[-12:])
except Exception as e:
    print("  获取失败:", e)

print("\n=== 各版本 AAR 里的 .so ===")
for ver in ["1.23.2", "1.22.0", "1.21.0", "1.20.0", "1.19.2", "1.18.0"]:
    try:
        data = fetch(f"{BASE}/{ver}/onnxruntime-android-qnn-{ver}.aar", timeout=120)
        z = zipfile.ZipFile(io.BytesIO(data))
        sos = [n for n in z.namelist() if n.endswith(".so")]
        qnn = [n for n in sos if "qnn" in n.lower() or "htp" in n.lower()]
        print(f"  {ver}: AAR {len(data)//1024//1024}MB, .so {len(sos)} 个, QNN 相关 {len(qnn)} 个")
        for n in qnn[:12]:
            print("      ", n, z.getinfo(n).file_size)
    except Exception as e:
        print(f"  {ver}: 失败 {e}")
