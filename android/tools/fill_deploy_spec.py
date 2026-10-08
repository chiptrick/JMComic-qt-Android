# coding:utf-8
"""把 wheel / NDK / SDK 的绝对路径写进 pysidedeploy.spec

用逐行替换(不用 re.S 正则)，避免把文件截断；同时校验关键 section 仍然存在。
pysidedeploy.spec 会被 python configparser 读取，注释前缀只认 "/"，所以这里不写注释行。
"""
import argparse
import pathlib
import sys

RequiredSections = ("app", "python", "qt", "android", "buildozer")


def SetKey(lines, section, key, value):
    current = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip().lower()
            continue
        if current == section and (stripped.startswith(key + "=") or stripped.startswith(key + " =")
                                   or stripped.startswith(key + "  =")):
            lines[index] = "{} = {}".format(key, value)
            return True
    return False


def Main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    parser.add_argument("--wheel-pyside", required=True)
    parser.add_argument("--wheel-shiboken", required=True)
    parser.add_argument("--ndk-path", default="")
    parser.add_argument("--sdk-path", default="")
    args = parser.parse_args()

    path = pathlib.Path(args.spec)
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
        print("已去除 UTF-8 BOM")
    lines = raw.decode("utf-8").splitlines()

    changed = []
    if SetKey(lines, "android", "wheel_pyside", args.wheel_pyside):
        changed.append("wheel_pyside")
    if SetKey(lines, "android", "wheel_shiboken", args.wheel_shiboken):
        changed.append("wheel_shiboken")
    if args.ndk_path and SetKey(lines, "buildozer", "ndk_path", args.ndk_path):
        changed.append("ndk_path")
    if args.sdk_path and SetKey(lines, "buildozer", "sdk_path", args.sdk_path):
        changed.append("sdk_path")

    text = "\n".join(lines) + "\n"
    sections = [line.strip()[1:-1].lower() for line in lines
                if line.strip().startswith("[") and line.strip().endswith("]")]
    missing = [s for s in RequiredSections if s not in sections]
    if missing:
        print("错误: 写入后缺少 section {}，请检查 spec 文件".format(missing))
        return 2

    path.write_text(text, encoding="utf-8")
    print("已更新 {} 项: {}".format(len(changed), ", ".join(changed)))
    print("sections: {}".format(sections))
    return 0


if __name__ == "__main__":
    sys.exit(Main())
