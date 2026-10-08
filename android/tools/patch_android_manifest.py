# coding:utf-8
""" 给 p4a 生成的 AndroidManifest.xml 补上"读取手机存储"所需的权限

背景(真机问题："导入本地漫画 / 图片超分导入本地图片会导致应用卡死")：
    p4a 的 manifest 模板只按 buildozer.spec 的 android.permissions 生成权限，而
    默认值只有 INTERNET / ACCESS_NETWORK_STATE / WAKE_LOCK / WRITE_EXTERNAL_STORAGE。
    Android 11+ 起 WRITE_EXTERNAL_STORAGE 已经完全失效，于是 targetSdk=34 的包在
    Android 14/15/16 上**读不到** /storage/emulated/0 下的 Download / Pictures /
    DCIM（scoped storage）。用户点"导入本地漫画"选目录时满屏 PermissionError，
    表现就是"选不到文件/卡死"。

这里补三条：
    READ_EXTERNAL_STORAGE   Android 12 及以下的读取权限(留着兼容老设备)
    READ_MEDIA_IMAGES       Android 13+ 的图片读取权限
    MANAGE_EXTERNAL_STORAGE "所有文件访问权限"(Android 11+)，需要在系统设置里手动授予：
                           设置 -> 应用 -> 本应用 -> 权限 -> 所有文件访问权限。
                           没有 pyjnius 就没法在应用里弹权限申请框(APK 里没有
                           libjnius.so，PySide6 也没绑定 QJniObject)，所以只能引导用户手动开。

用法：
    python3 android/tools/patch_android_manifest.py <manifest...>
    (manifest 不存在时直接跳过；全部成功返回 0，出现"该补的没补上"返回 1)
"""
import os
import sys

# 必须补上的权限(缺一不可，缺了就是"选不到手机里的文件")
NeedPermissions = (
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.READ_MEDIA_IMAGES",
    "android.permission.MANAGE_EXTERNAL_STORAGE",
)


def Patch(path):
    """ 返回 (是否改动, 缺失权限列表) """
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    missing = [p for p in NeedPermissions
               if 'android:name="{}"'.format(p) not in text]
    if not missing:
        return False, []
    # 缩进跟现有 uses-permission 对齐(真实文件是 4 空格)
    lines = text.splitlines()
    indent = "    "
    insertAt = None
    for index, line in enumerate(lines):
        if "<uses-permission" in line:
            indent = line[:len(line) - len(line.lstrip())]
            insertAt = index + 1
    if insertAt is None:
        # 没有现成的 uses-permission：插到 <application 之前
        for index, line in enumerate(lines):
            if "<application" in line:
                insertAt = index
                break
    if insertAt is None:
        return False, missing
    for permission in missing:
        lines.insert(insertAt, '{}<uses-permission android:name="{}" />'.format(indent, permission))
        insertAt += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return True, []


def Main(argv):
    if len(argv) < 2:
        print("用法: patch_android_manifest.py <AndroidManifest.xml> [...]")
        return 2
    failed = []
    for path in argv[1:]:
        if not os.path.exists(path):
            print("  - 跳过(不存在): {}".format(path))
            continue
        try:
            changed, missing = Patch(path)
        except Exception as es:
            print("  ! 补丁失败 {}: {}".format(path, es))
            failed.append(path)
            continue
        if changed:
            print("  ~ 已补权限 {}: {}".format(path, ", ".join(NeedPermissions)))
        else:
            print("  = 权限已齐: {}".format(path))
        if missing:
            print("  ! {} 仍缺少: {}".format(path, ", ".join(missing)))
            failed.append(path)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(Main(sys.argv))
