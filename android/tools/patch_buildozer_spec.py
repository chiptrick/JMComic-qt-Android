# coding:utf-8
"""给 pyside6-android-deploy 生成的 buildozer.spec 打补丁

工具在首次运行时按 PySide6 wheel 自动生成 buildozer.spec，但有两处它不暴露配置：
    1. app.requirements 被写死成 "python3,shiboken6,PySide6"，应用自己的依赖进不去
    2. 没有 minSdk / 自有原生库(.so) / 资源目录 / p4a 本地源码 的配置项

本脚本在生成之后注入这些配置；工具的 Buildozer.initialize 检测到 buildozer.spec
已存在时会直接沿用(并打印 warning)，所以打完补丁再跑一次即可生效。
（android/tools/pin_min_sdk.sh 是同一思路的简化版，二者择一即可，本脚本更完整。）

用法:
    python android/tools/patch_buildozer_spec.py android/buildozer.spec \
        --p4a-dir /path/to/python-for-android \
        --recipes android/recipes --libs android/libs/arm64-v8a --models android/sr_qnn/models
"""
import argparse
import os
import shutil
import sys

# 应用依赖(p4a 有 recipe 的走 recipe，纯 python 的由 p4a 用 pip 安装)
AppRequirements = [
    "python3", "shiboken6", "PySide6",      # Qt for Python(必须保持在前)
    "setuptools",
    # p4a 用 cpython-311-ctypes-find-library.patch 把 stdlib 的 ctypes/util.py 改成
    # `from android._ctypes_library_finder import find_library`，也就是说 **ctypes.util
    # 强依赖 android 模块**。没有它，凡是要用 ctypes 找库的包都会炸 —— 真机上表现为
    # pycryptodome 的 Crypto/Cipher/AES.py 导入失败(先被 optimize=2 拒绝 cffi、
    # 再在 ctypes 兜底处 ModuleNotFoundError: No module named 'android')，
    # 于是所有加密的接口响应都解不开。android recipe 是 p4a 自带的纯 python 包。
    "android",
    "pillow",                                # 图片尺寸/格式
    # 注意：lxml 不列入。它需要静态 libxml2/libxslt，p4a 下的静态构建非常脆弱
    # (setupinfo 断言 / 头文件路径问题)。项目里 lxml 只用于写 ComicInfo.xml，
    # tools/tool.py 已改为 try lxml -> except 回退标准库 xml.etree.ElementTree。
    "pycryptodome",
    "beautifulsoup4", "soupsieve",           # bs4
    "natsort", "tqdm",
    "requests", "certifi", "charset-normalizer", "idna", "urllib3",
    "python-dateutil", "six",                # webdavclient3 依赖
    "webdavclient3",                         # WebDAV 上传
    "pyasn1", "pysmb",                       # SMB 上传
    "pysocks",                               # socks5 代理(curl_cffi 垫片也会用)
    "typing-extensions",
    "commonx",                               # jmcomic 依赖
    "jmcomic",                               # 走 android/recipes/jmcomic(--no-deps)
]

# 说明：curl_cffi 不在 requirements 里，Android 上由 android/shims/curl_cffi 垫片提供
# (作为 assets 打进 APK)；编出原生 curl-impersonate 后可改成走 recipes/curl_cffi。
SkipRequirements = ["curl_cffi", "curl-cffi"]

# p4a 只把 source.include_exts 放行的文件复制进应用目录(再打成 private.tar)。
# buildozer/工具生成的默认值是 "py,png,jpg,kv,atlas,qml,js"，**不含 onnx/txt**，
# 于是 sr_qnn/models/*.onnx + models.txt 从来没有进过 APK —— 真机上超分后端
# 因此报"NPU 超分后端不可用"(模型数为 0)。
RuntimeExts = ["onnx", "txt"]

Sections = ("app", "buildozer", "android", "python", "qt")


class SpecFile(object):
    def __init__(self, path):
        self.path = path
        with open(path, encoding="utf-8") as f:
            self.lines = f.read().splitlines()

    def FindKey(self, section, key):
        """ 返回 (行号, 值) 或 (None, None) """
        current = ""
        for index, line in enumerate(self.lines):
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                current = stripped[1:-1].strip().lower()
                continue
            body = stripped.lstrip("#").strip()
            if body.startswith(key + "=") or body.startswith(key + " ="):
                if current != section:
                    continue
                return index, body.split("=", 1)[1].strip()
        return None, None

    def SetKey(self, section, key, value):
        index, old = self.FindKey(section, key)
        if index is not None:
            if old == value:
                print("  = {}.{} 已经是目标值".format(section, key))
                return False
            self.lines[index] = "{} = {}".format(key, value)
            print("  ~ {}.{}: {} -> {}".format(section, key, old, value))
            return True
        # 追加到对应 section 末尾
        current = ""
        insertAt = len(self.lines)
        for lineIndex, line in enumerate(self.lines):
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                if current == section:
                    insertAt = lineIndex
                    break
                current = stripped[1:-1].strip().lower()
        if insertAt == len(self.lines) and current != section:
            self.lines.append("")
            self.lines.append("[{}]".format(section))
            self.lines.append("{} = {}".format(key, value))
        else:
            self.lines.insert(insertAt, "{} = {}".format(key, value))
        print("  + {}.{} = {}".format(section, key, value))
        return True

    def GetKey(self, section, key):
        return self.FindKey(section, key)[1]

    def DeleteKey(self, section, key):
        """ 整行删除某个键

        注意：不能把 android.add_assets 置成空值来代替删除 —— buildozer 会把空值
        当成一个"asset 条目"传给 p4a，p4a 随后 shutil.copytree(src, 'src/main/assets/')
        撞上刚创建好的同名目录，直接 FileExistsError 打包失败(已实测)。
        """
        index, old = self.FindKey(section, key)
        if index is None:
            return False
        del self.lines[index]
        print("  - 删除 {}.{} (原值: {!r})".format(section, key, old))
        return True

    def Save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines) + "\n")
        print("已写入 {}".format(self.path))


def MergeRequirements(current, wanted):
    items = [v.strip() for v in (current or "").split(",") if v.strip()]
    lower = {v.lower() for v in items}
    for name in wanted:
        if name.lower() in lower or name.lower().replace("_", "-") in lower:
            continue
        if name.lower() in [v.lower() for v in SkipRequirements]:
            continue
        items.append(name)
        lower.add(name.lower())
    # 去掉被显式跳过的
    items = [v for v in items if v.lower() not in [s.lower() for s in SkipRequirements]]
    return ",".join(items)


def MergeExts(current, wanted):
    items = [v.strip() for v in (current or "").split(",") if v.strip()]
    lower = {v.lower() for v in items}
    for name in wanted:
        if name.lower() not in lower:
            items.append(name)
            lower.add(name.lower())
    return ",".join(items)


def CopyRecipes(recipeDir, srcDir):
    if not recipeDir or not srcDir or not os.path.isdir(srcDir):
        return 0
    os.makedirs(recipeDir, exist_ok=True)
    count = 0
    for name in sorted(os.listdir(srcDir)):
        src = os.path.join(srcDir, name)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(recipeDir, name)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        count += 1
    return count


def Main():
    parser = argparse.ArgumentParser(description="为 JMComic 补丁 buildozer.spec")
    parser.add_argument("spec", help="生成的 buildozer.spec 路径")
    parser.add_argument("--p4a-dir", default="", help="python-for-android 源码目录(避免联网克隆)")
    parser.add_argument("--recipes", default="", help="本项目 recipe 目录(会被拷贝进工具的 recipe_dir)")
    parser.add_argument("--libs", default="", help="自有 .so 目录(相对 project_dir)")
    parser.add_argument("--icon", default="", help="应用图标 PNG(替换 PySide6 自带的 pyside_icon.jpg)")
    parser.add_argument("--models", default="", help="超分模型目录(有 .onnx 时才加入 assets)")
    parser.add_argument("--api", default="34", help="targetSdk，默认 34")
    parser.add_argument("--minapi", default="34", help="minSdk，默认 34(用户要求不考虑 Android 14 以下)")
    args = parser.parse_args()

    if not os.path.exists(args.spec):
        print("找不到 {}".format(args.spec))
        return 2

    print("== 补丁 {}".format(args.spec))
    spec = SpecFile(args.spec)
    # --libs/--models 允许写相对路径，但必须相对 **spec 所在目录** 解析，
    # 而不是当前工作目录(buildozer 也是按 spec 目录解析 add_libs 的)。
    # 原来直接 os.path.isdir(相对路径) 会依赖 cwd，换个目录跑就静默跳过 add_libs。
    specDir = os.path.dirname(os.path.abspath(args.spec))

    def Resolve(path):
        if not path:
            return ""
        return path if os.path.isabs(path) else os.path.join(specDir, path)

    # 注意：buildozer.spec 里 android.*/p4a.* 都是 [app] 段下的"带点键名"，
    # 不能写成独立的 [android]/[p4a] 段，否则会被 buildozer 忽略。
    current = spec.GetKey("app", "requirements") or ""
    merged = MergeRequirements(current, AppRequirements)
    if merged != current:
        spec.SetKey("app", "requirements", merged)

    spec.SetKey("app", "android.api", str(args.api))
    spec.SetKey("app", "android.minapi", str(args.minapi))
    spec.SetKey("app", "android.archs", "arm64-v8a")
    spec.SetKey("app", "android.accept_sdk_license", "True")
    spec.SetKey("app", "android.private_storage", "True")
    if args.libs:
        soFiles = []
        libsScan = Resolve(args.libs)
        if os.path.isdir(libsScan):
            soFiles = sorted(n for n in os.listdir(libsScan) if n.endswith(".so"))
        if soFiles:
            # spec 里仍写相对路径(buildozer 按 spec 目录解析)，保持与既有构建一致
            spec.SetKey("app", "android.add_libs_arm64_v8a",
                        ",".join(os.path.join(args.libs, n) for n in soFiles))
            print("  原生库 {} 个: {}".format(len(soFiles), ", ".join(soFiles)))
        else:
            print("  [warn] {} 里没有 .so，跳过 add_libs".format(libsScan))

    # 应用图标：工具生成 buildozer.spec 时把 icon.filename 写死成 PySide6 自带的
    # deploy_lib/pyside_icon.jpg，装到手机上启动器显示的就是 PySide 的 logo。
    # 这里换成项目自己的图标(res/icon/logo_round.png，与窗口/托盘图标同源)。
    # p4a(common/build/build.py) 会把该文件**原样**拷成 src/main/res/mipmap/icon.png，
    # 不缩放也不校验尺寸，所以给 512x512 的 PNG 即可(带 alpha，圆角背景透明)。
    # 注意 qt bootstrap 的 res 模板里没有 mipmap-anydpi-v26，用不了自适应图标
    # (--icon-fg/--icon-bg 会因为目标目录不存在直接抛 FileNotFoundError)。
    if args.icon:
        iconPath = Resolve(args.icon)
        if os.path.isfile(iconPath):
            spec.SetKey("app", "icon.filename", iconPath)
        else:
            print("  [warn] 找不到图标 {}，仍用工具自带的 pyside_icon.jpg".format(iconPath))

    # 超分模型随 private.tar 分发：
    #   source.include_exts 放行 onnx/txt 后，sr_qnn/models/ 会被复制进 p4a 的应用目录，
    #   运行时解包到 <ANDROID_PRIVATE>/app/sr_qnn/models/，由 android/main.py 的
    #   EnsureModels() 复制到可写的模型目录(JM_SR_MODELS)。
    # 刻意不设 android.add_assets：那会往 APK 里再塞一份 ~45MB 的副本，而且 p4a 的
    # assets 只能通过 Qt 的 assets:/ 或 Java AssetManager 读，原生 fopen 打不开。
    if args.models:
        modelsScan = Resolve(args.models)
        if os.path.isdir(modelsScan) and any(n.endswith(".onnx") for n in os.listdir(modelsScan)):
            exts = MergeExts(spec.GetKey("app", "source.include_exts"), RuntimeExts)
            spec.SetKey("app", "source.include_exts", exts)
            # 必须整行删掉，不能写空值(见 DeleteKey 的注释)
            spec.DeleteKey("app", "android.add_assets")
            print("  模型随 private.tar 分发, source.include_exts={}".format(exts))
        else:
            print("  [warn] {} 里没有 .onnx，跳过模型配置".format(modelsScan))

    # 用本地 p4a 源码(我们已经把 recipe 里的 GitHub 直链改成了可达镜像)，
    # 否则 buildozer 会去 clone github.com(本机不可达)
    if args.p4a_dir:
        spec.SetKey("app", "p4a.source_dir", os.path.abspath(args.p4a_dir))
        spec.SetKey("app", "p4a.branch", "")

    # 合并本项目 recipe 到工具生成的 recipe_dir
    recipeDir = spec.GetKey("app", "p4a.local_recipes")
    if args.recipes and recipeDir:
        count = CopyRecipes(recipeDir, os.path.abspath(args.recipes))
        print("  已拷贝 {} 个自定义 recipe 到 {}".format(count, recipeDir))
    elif args.recipes:
        print("  [warn] buildozer.spec 里没有 p4a.local_recipes，无法合并自定义 recipe")

    permissions = spec.GetKey("app", "android.permissions") or ""
    perms = [p.strip() for p in permissions.split(",") if p.strip()]
    # 读取手机存储：Android 11+ 起 WRITE_EXTERNAL_STORAGE 失效，缺这几条的话
    # "导入本地漫画/导入本地图片"选目录时全是 PermissionError(真机上表现为选不到文件/卡死)。
    # MANAGE_EXTERNAL_STORAGE 需要用户去系统设置里手动授予"所有文件访问权限"。
    for need in ("android.permission.INTERNET", "android.permission.ACCESS_NETWORK_STATE",
                 "android.permission.WAKE_LOCK",
                 "android.permission.READ_EXTERNAL_STORAGE",
                 "android.permission.READ_MEDIA_IMAGES",
                 "android.permission.MANAGE_EXTERNAL_STORAGE"):
        if need not in perms:
            perms.append(need)
    spec.SetKey("app", "android.permissions", ",".join(perms))

    spec.SetKey("buildozer", "log_level", "2")
    # WSL 里通常以 root 构建：buildozer 的键名是 warn_on_root，值必须是字符串 '0'
    # (写成 False 会被当成非空字符串，仍会交互询问)
    spec.SetKey("buildozer", "warn_on_root", "0")
    spec.Save()
    return 0


if __name__ == "__main__":
    sys.exit(Main())
