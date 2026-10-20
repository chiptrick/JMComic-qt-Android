# coding:utf-8
"""APK 发布前校验：Qt 加载清单 vs 包内实际 .so

背景(0.47 事故)：pyside6-android-deploy 把 libQt6Test 写进 --qt-libs，
p4a 渲染 dist 的 res/values/libs.xml 后，QtLoader 启动时按清单逐个
System.loadLibrary。QtTest.abi3.so 从未被打进 APK -> UnsatisfiedLinkError
-> "Loading Qt native libraries failed" -> VM 退出，表现为"装完即闪退"，
而且日志里唯一的线索是 E QtLoader 那一行，很容易被当成环境问题。

本脚本在打包后跑：读 APK 里的 array/qt_libs 与 array/load_local_libs，
逐个核对 lib/<abi>/ 下是否真的有对应文件。清单与产物不一致就非 0 退出，
把"带病发布"堵在最后一道关。

用法:
    python check_apk_qt_libs.py <apk> [--abi arm64-v8a|x86_64] [--aapt /path/aapt]
"""
import argparse
import os
import re
import subprocess
import sys
import zipfile


def FindAapt(explicit):
    if explicit:
        return explicit
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or ""
    candidates = []
    if sdk:
        bt = os.path.join(sdk, "build-tools")
        if os.path.isdir(bt):
            for name in sorted(os.listdir(bt), reverse=True):
                candidates.append(os.path.join(bt, name, "aapt"))
    for path in os.environ.get("PATH", "").split(os.pathsep):
        if path:
            candidates.append(os.path.join(path, "aapt"))
    for cand in candidates:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return ""


def DumpArrays(aapt, apk):
    """返回 {数组名: [条目, ...]}；解析失败返回 None"""
    out = subprocess.run([aapt, "dump", "--values", "resources", apk],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    arrays = {}
    current = None
    for line in out.stdout.splitlines():
        header = re.match(r"\s*resource 0x[0-9a-f]+ \S+:array/(qt_libs|load_local_libs|bundled_libs)", line)
        if header:
            current = header.group(1)
            arrays.setdefault(current, [])
            continue
        item = re.match(r'\s*#\d+ \(Key=0x[0-9a-f]+\): \(string8\) "(.*)"', line)
        if item and current:
            arrays[current].append(item.group(1))
            continue
        if line.strip().startswith("resource 0x") and "array/" not in line:
            current = None
    return arrays


def Main():
    parser = argparse.ArgumentParser(description="校验 APK 的 Qt 加载清单与包内 .so 一致")
    parser.add_argument("apk")
    parser.add_argument("--abi", default=os.environ.get("JM_ABI", "arm64-v8a"),
                        choices=("arm64-v8a", "x86_64"))
    parser.add_argument("--aapt", default="", help="aapt 可执行路径(默认从 ANDROID_HOME/PATH 找)")
    args = parser.parse_args()

    if not os.path.isfile(args.apk):
        print("[FAIL] 找不到 APK: {}".format(args.apk))
        return 2
    aapt = FindAapt(args.aapt)
    if not aapt:
        print("[FAIL] 找不到 aapt，请用 --aapt 指定(Android SDK build-tools 里)")
        return 2

    arrays = DumpArrays(aapt, args.apk)
    if not arrays:
        print("[FAIL] aapt 无法解析 APK 资源: {}".format(args.apk))
        return 2

    with zipfile.ZipFile(args.apk) as z:
        names = set(z.namelist())

    libs = [n for n in names if n.startswith("lib/{}/".format(args.abi)) and n.endswith(".so")]
    print("APK: {} ({} 字节)".format(os.path.basename(args.apk), os.path.getsize(args.apk)))
    print("ABI: {}   lib/{} 下 {} 个 .so".format(args.abi, args.abi, len(libs)))

    # lib/ 下只应有一个 ABI 目录：多出来的说明配置串了(arm64/x86_64 混装)
    otherAbis = sorted({n.split("/")[1] for n in names
                        if n.startswith("lib/") and n.count("/") >= 2 and n.endswith(".so")}
                       - {args.abi})
    if otherAbis:
        print("[FAIL] APK 里混进了其它架构的原生库: {}".format(", ".join(otherAbis)))
        return 1
    if not libs:
        print("[FAIL] lib/{} 是空的，这个包根本装不上".format(args.abi))
        return 1

    missing = []
    checked = 0
    for arrayName in ("qt_libs", "load_local_libs", "bundled_libs"):
        for entry in arrays.get(arrayName, []):
            if ";" in entry:
                abi, lib = entry.split(";", 1)
                if abi != args.abi:
                    continue
            else:
                lib = entry
            lib = lib.strip()
            if not lib:
                continue
            # 三类条目的实际文件名：
            #   qt_libs        "x86_64;Qt6Widgets_x86_64"  -> libQt6Widgets_x86_64.so
            #   load_local_libs"x86_64;QtWidgets.abi3.so"   -> QtWidgets.abi3.so(原样)
            #   bundled_libs   "arm64-v8a;xxx.so"           -> 原样
            if lib == "c++_shared":
                path = "lib/{}/libc++_shared.so".format(args.abi)
            elif lib.startswith("Qt6"):
                path = "lib/{}/lib{}.so".format(args.abi, lib)
            elif lib.endswith(".so"):
                path = "lib/{}/{}".format(args.abi, lib)
            else:
                path = "lib/{}/{}.so".format(args.abi, lib)
            checked += 1
            if path not in names:
                missing.append((arrayName, entry, path))

    for arrayName, entry, path in missing:
        print("[FAIL] {}/{} 清单要求 {}，但 APK 里没有 {} —— 启动会 "
              "UnsatisfiedLinkError 闪退".format(arrayName, entry, entry, path))
    print("核对清单条目 {} 个，缺失 {} 个".format(checked, len(missing)))
    if missing:
        return 1

    # 关键库抽查(缺任何一个应用都起不来)
    MustHave = ("libc++_shared.so", "libpython3.14.so", "libpybundle.so",
                "libpyside6.abi3.so", "libshiboken6.abi3.so")
    if args.abi == "arm64-v8a":
        MustHave += ("libonnxruntime.so", "libsr_qnn.so")
    else:
        MustHave += ("libonnxruntime.so", "libsr_qnn.so")
    for lib in MustHave:
        path = "lib/{}/{}".format(args.abi, lib)
        if path not in names:
            print("[FAIL] 缺少关键库 {}".format(path))
            return 1
    print("[OK] 加载清单与包内 .so 完全一致，关键库齐全")
    return 0


if __name__ == "__main__":
    sys.exit(Main())
