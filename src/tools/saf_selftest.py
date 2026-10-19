# coding:utf-8
""" 下载目录(SAF)自检 —— 由文件触发，只在需要排查时跑

为什么要有它：真机上"下载目录直写"这条链路(下载线程 -> vfs -> socket -> Java ->
ContentResolver)没法用 adb 单独触发(输入注入点不准、下载按钮要联网)，而它坏了
表现又只是"文件没出现在那个目录"。这里给一个可控的探针：

    adb shell "run-as <包名> sh -c 'echo 1 > files/saf/selftest'"

重启应用后 4 秒，它会用**和下载完全相同的入口**走一遍 写 / 读 / 列目录 / 删除，
结果写进 `<state>/saf_selftest.txt` 与日志，然后把触发文件删掉(不会反复跑)。
"""
import os

from tools.log import Log


def TriggerFile():
    from tools import saf_bridge
    return os.path.join(saf_bridge.BridgeDir(), "selftest")


def ResultFile():
    try:
        from config.setting import Setting
        return os.path.join(Setting.GetStatePath(), "saf_selftest.txt")
    except Exception:
        return ""


def saf_bridge_last_error():
    from tools import saf_bridge
    return saf_bridge.IoError


def Install():
    """ 启动时调用：只有触发文件存在时才排一次自检 """
    try:
        if not os.path.exists(TriggerFile()):
            return False
        from PySide6.QtCore import QTimer
        QTimer.singleShot(4000, Run)
        Log.Warn("saf selftest: 已排队(4s 后执行)")
        return True
    except Exception as es:
        Log.Error(es)
        return False


def Run():
    lines = ["===== saf selftest ====="]
    try:
        from config.setting import Setting
        from tools import vfs

        root = Setting.GetDownloadRoot()
        lines.append("下载根目录: {}".format(root))
        lines.append("真实路径: {}".format(Setting.GetDownloadDisplayPath()))
        lines.append("SAF 模式: {}".format(Setting.IsSafDownload()))

        base = vfs.Join(root, "自检", "第01话")
        data = b"selftest-" * 500
        path = vfs.Join(base, "0001")
        checks = []
        written = vfs.Write(path + ".jpg", data)
        checks.append(("write", written))
        lines.append("write {}: {}".format(path, written))
        exists = vfs.IsFile(path + ".jpg")
        checks.append(("exists", exists))
        lines.append("exists: {}".format(exists))
        size = vfs.Size(path + ".jpg")
        checks.append(("size", size == len(data)))
        lines.append("size: {} (期望 {})".format(size, len(data)))
        readOk = vfs.Read(path + ".jpg") == data
        checks.append(("read", readOk))
        lines.append("read: {}".format(readOk))
        picOk = vfs.ReadPicture(path) == data
        checks.append(("readpicture", picOk))
        lines.append("readpicture(无扩展名): {}".format(picOk))
        names = [name for name, isDir in vfs.ListDir(base)]
        checks.append(("listdir", "0001.jpg" in names))
        lines.append("listdir: {}".format(names))
        # 再写第二页，确认同一目录下连续写入不会退化成"每页列一遍目录"
        second = vfs.Write(vfs.Join(base, "0002") + ".jpg", data[:100])
        checks.append(("write 0002", second))
        lines.append("write 0002: {}".format(second))
        deleted = vfs.RemoveTree(vfs.Join(root, "自检"))
        checks.append(("delete", deleted))
        lines.append("delete: {}".format(deleted))
        # 目录本身可能删不掉：ExternalStorageProvider 对目录的 deleteDocument 会
        # 直接抛 "Failed to delete"(哪怕目录已经空了)。用户在意的是文件没了。
        filesGone = not vfs.IsFile(vfs.Join(base, "0001.jpg")) and not vfs.IsFile(vfs.Join(base, "0002.jpg"))
        checks.append(("files gone", filesGone))
        lines.append("文件已删除: {}".format(filesGone))
        lines.append("空目录残留(可接受): {}".format(vfs.IsDir(vfs.Join(root, "自检"))))
        failed = [name for name, ok in checks if not ok]
        lines.append("结果: {}".format("OK" if not failed else "FAIL " + ", ".join(failed)))
        Log.Warn("saf selftest: 错误详情 {}".format(saf_bridge_last_error()))
    except Exception as es:
        import traceback
        lines.append("异常: {}".format(es))
        lines.append(traceback.format_exc())
    lines.append("===== end =====")

    text = "\n".join(lines)
    for line in lines:
        Log.Warn("saf selftest: " + line)
    try:
        path = ResultFile()
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
    except Exception as es:
        Log.Error(es)
    try:
        os.remove(TriggerFile())
    except Exception:
        pass
    return text
