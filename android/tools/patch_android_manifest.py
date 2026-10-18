# coding:utf-8
""" 给 p4a 的 AndroidManifest(qt bootstrap)注入 SAF 桥组件，并去掉多余的存储权限

背景
----
Android 11+ 起 `WRITE_EXTERNAL_STORAGE` 已失效，为了读 /storage/emulated/0，之前
索要了 `READ_EXTERNAL_STORAGE` / `READ_MEDIA_IMAGES` / `MANAGE_EXTERNAL_STORAGE`
(最后一个还要用户去系统设置里手动开"所有文件访问权限")。现在改成 SAF：

    * 选文件 / 选目录 / 另存为 全部走系统选择器(ACTION_OPEN_DOCUMENT[_TREE])，
      **不需要任何存储权限**，授权是 per-URI 的
    * Python 侧调不到 Java API，所以有一个同进程的 SafService + 一个不可见的
      SafPickActivity 做桥(见 tools/saf_bridge.py 与 android/java/org/jmcomic/*)

这两个组件必须声明在 manifest 里，而 p4a 每次构建都会用模板**重新渲染**
src/main/AndroidManifest.xml，所以光补 dists 里的文件不够 —— 得补模板
(bootstraps/qt/build/templates/AndroidManifest.tmpl.xml) 里
`{{ args.extra_manifest_application_xml }}` 那一行。

用法：
    python3 patch_android_manifest.py <manifest...>                    # 渲染出来的 manifest
    python3 patch_android_manifest.py --template <tmpl.xml>            # p4a 模板
    python3 patch_android_manifest.py --java <src> --dist <dist_dir>   # 拷 Java 源
"""
import os
import re
import shutil
import sys

# 必须从 manifest 里**移除**的权限(SAF 之后一个都不需要)
DropPermissions = (
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
    "android.permission.READ_MEDIA_IMAGES",
    "android.permission.READ_MEDIA_VIDEO",
    "android.permission.MANAGE_EXTERNAL_STORAGE",
)

# SAF 桥的两个组件
#
# exported=false：只能被同 uid(本应用)启动。Python 用
# `am start-service --user 0 -n <pkg>/org.jmcomic.SafService` 拉起，调用方就是本应用。
#
# 两个组件都跑在**独立进程** `:saf` 里 —— 这是真机崩溃的修法：
# 之前它们和 Qt 同进程，透明 Activity 一建窗口，进程里就多了一套 HWUI(View 渲染)，
# 从系统选择器返回时 ANativeWindow 被销毁、Qt 那边还在画，直接
# `FORTIFY: pthread_mutex_lock called on a destroyed mutex` -> SIGABRT(实测两崩)。
# 分进程之后 Qt 进程里根本没有第二个窗口，它只是被 onPause 而已。
#
# **绝不能加 android:noHistory="true"**：noHistory 的 Activity 一旦被别的 Activity
# 盖住就被销毁，`onActivityResult` 永远不回调 —— 真机上表现就是"选择器弹出来了，
# 选完什么都没发生"(我们的 onDestroy 把结果写成"取消"了)。
ComponentsXml = """        <service android:name="org.jmcomic.SafService"
                 android:exported="false"
                 android:process=":saf"
                 android:stopWithTask="false" />
        <activity android:name="org.jmcomic.SafPickActivity"
                  android:exported="false"
                  android:process=":saf"
                  android:theme="@android:style/Theme.Translucent.NoTitleBar"
                  android:excludeFromRecents="true"
                  android:configChanges="orientation|screenSize|keyboardHidden|uiMode" />
"""

Marker = "org.jmcomic.SafService"

# 已经注入过的那一段(幂等升级用：属性改了就整段换掉，不然模板里会留着旧写法 ——
# 真机踩过：模板里还是 noHistory="true" 的旧块，Marker 命中就跳过，改动等于没打)
BlockRe = re.compile(
    r"[ \t]*<service android:name=\"org\.jmcomic\.SafService\".*?"
    r"<activity android:name=\"org\.jmcomic\.SafPickActivity\".*?/>[ \t]*\n",
    re.S)


def _Read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _Write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def DropStoragePermissions(text):
    """ 删除多余的存储权限声明；返回 (新文本, 删掉的条数) """
    lines = text.splitlines()
    kept = []
    removed = 0
    for line in lines:
        if "<uses-permission" in line and any(p in line for p in DropPermissions):
            removed += 1
            continue
        kept.append(line)
    return "\n".join(kept) + ("\n" if text.endswith("\n") else ""), removed


def InsertComponents(text, anchor=None):
    """ 插入(或整段替换)组件声明；返回 (新文本, 是否有改动)

    已经存在旧版本时会**替换**成当前写法，保证改属性(例如去掉 noHistory)能生效。
    """
    matched = BlockRe.search(text)
    if matched is not None:
        current = matched.group(0)
        if current.strip() == ComponentsXml.strip():
            return text, False
        return text[:matched.start()] + ComponentsXml + text[matched.end():], True
    if Marker in text:
        # 有人手工写过一段格式不同的：不动它，避免改坏
        return text, False
    lines = text.splitlines()
    insertAt = None
    if anchor:
        for index, line in enumerate(lines):
            if anchor in line:
                insertAt = index
                break
    if insertAt is None:
        for index, line in enumerate(lines):
            if "</application>" in line:
                insertAt = index
                break
    if insertAt is None:
        return text, False
    block = ComponentsXml.rstrip("\n").splitlines()
    for offset, line in enumerate(block):
        lines.insert(insertAt + offset, line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), True


def PatchManifest(path):
    """ 渲染出来的 manifest：加组件 + 去权限 """
    text = _Read(path)
    text, inserted = InsertComponents(text)
    text, removed = DropStoragePermissions(text)
    _Write(path, text)
    return inserted, removed


def PatchTemplate(path):
    """ p4a 模板：只在 extra_manifest_application_xml 那行之前插组件 """
    text = _Read(path)
    text, inserted = InsertComponents(text, "{{ args.extra_manifest_application_xml }}")
    if inserted:
        _Write(path, text)
    return inserted


def CopyJava(sourceDir, destDirs):
    """ 把 android/java 下的包拷进若干目标目录(每个都是 .../src/main/java) """
    if not sourceDir:
        return 0
    source = os.path.join(sourceDir, "org")
    if not os.path.isdir(source):
        return 0
    total = 0
    for dest in destDirs:
        if not dest:
            continue
        target = os.path.join(dest, "org")
        os.makedirs(target, exist_ok=True)
        for root, _, files in os.walk(source):
            rel = os.path.relpath(root, source)
            outDir = target if rel == "." else os.path.join(target, rel)
            os.makedirs(outDir, exist_ok=True)
            for name in files:
                if not name.endswith(".java"):
                    continue
                shutil.copyfile(os.path.join(root, name), os.path.join(outDir, name))
                total += 1
    return total


def Main(argv):
    args = argv[1:]
    template = ""
    javaDir = ""
    javaDests = []
    manifests = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--template" and index + 1 < len(args):
            template = args[index + 1]
            index += 2
            continue
        if arg == "--java" and index + 1 < len(args):
            javaDir = args[index + 1]
            index += 2
            continue
        if arg == "--java-dest" and index + 1 < len(args):
            javaDests.append(args[index + 1])
            index += 2
            continue
        if arg == "--dist" and index + 1 < len(args):
            # 兼容老用法：--dist <dist> 等价于 --java-dest <dist>/src/main/java
            javaDests.append(os.path.join(args[index + 1], "src", "main", "java"))
            index += 2
            continue
        manifests.append(arg)
        index += 1

    failed = []
    if template:
        if os.path.exists(template):
            if PatchTemplate(template):
                print("  ~ 已给 p4a 模板加上 SAF 组件: {}".format(template))
            else:
                print("  = 模板已包含 SAF 组件: {}".format(template))
        else:
            print("  ! 模板不存在: {}".format(template))
            failed.append(template)

    for path in manifests:
        if not os.path.exists(path):
            print("  - 跳过(不存在): {}".format(path))
            continue
        try:
            inserted, removed = PatchManifest(path)
            print("  ~ {}: 组件{} / 去掉 {} 条存储权限".format(
                path, "已加" if inserted else "已有", removed))
        except Exception as es:
            print("  ! 补丁失败 {}: {}".format(path, es))
            failed.append(path)

    if javaDir and javaDests:
        # 注意：**必须**同时放进 p4a 的 build 模板树。p4a 每次构建都会把
        # bootstraps/common/build/ 下的 src 重新铺到 dist 里，
        # 只拷进 dist 的 java 会在下一次构建时消失(上次就踩了：manifest 里有组件，
        # 但 dex 里没有类 —— 运行期 am start-service 直接 "Not found")。
        count = CopyJava(javaDir, javaDests)
        if count:
            print("  ~ 已拷入 {} 个文件 -> {}".format(count, " , ".join(javaDests)))
        else:
            print("  ! 没有找到可拷入的 Java 源: {}".format(javaDir))
            failed.append(javaDir)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(Main(sys.argv))
