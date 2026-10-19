# coding:utf-8
""" 宿主自检：vfs 路径层(不需要手机)

真机上"下载直接写进用户选的目录"依赖 tools/vfs.py 这一层路径语义：
`saf://<key>/<相对路径>` 与本地路径必须能互换、拼接结果必须一致。这里用一张
内存里的假树把它跑一遍，避免改一次下载逻辑就要在手机上试一次。

    python android/tools/host_test_vfs.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

# --- 用内存假树替掉 saf_bridge ------------------------------------------------
Trees = {
    "t1": "content://com.android.externalstorage.documents/tree/primary%3ADownload%2FJMComic",
    "t2": "content://com.android.externalstorage.documents/tree/primary%3ADownload%2FOther",
}
Files = {"t1": {}, "t2": {}}


def _KeyOf(uri):
    for key, value in Trees.items():
        if value == uri:
            return key
    return ""


fake = types.ModuleType("tools.saf_bridge")
fake.SafPrefix = "saf://"
fake.TreeUri = lambda key: Trees.get(str(key or ""), "")
fake.TreeName = lambda key: "JMComic" if key == "t1" else "Other"
fake.TreeRealPath = lambda uri: "/storage/emulated/0/Download/JMComic" if uri == Trees["t1"] else ""
fake.TreeKey = lambda uri, name="": _KeyOf(uri)


def _Write(uri, rel, data):
    Files[_KeyOf(uri)][rel] = data
    return True


def _Read(uri, rel):
    return Files[_KeyOf(uri)].get(rel)


def _Exists(uri, rel):
    key = _KeyOf(uri)
    if rel in Files[key]:
        return True, False, len(Files[key][rel])
    prefix = rel.rstrip("/") + "/"
    if any(name.startswith(prefix) for name in Files[key]):
        return True, True, 0
    return False, False, 0


def _List(uri, rel):
    key = _KeyOf(uri)
    prefix = (rel.rstrip("/") + "/") if rel else ""
    items = {}
    for name in Files[key]:
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        head, sep, _ = rest.partition("/")
        items[head] = bool(sep)
    return sorted(items.items())


fake.IoWrite = _Write
fake.IoRead = _Read
fake.IoExists = _Exists
fake.IoList = _List
fake.IoMakedirs = lambda uri, rel: True
fake.IoDelete = lambda uri, rel: True
fake.IoDocUri = lambda uri, rel: "doc://" + rel
fake.OpenUri = lambda uri: (True, "")
fake.OpenPath = lambda path: (False, "sandbox")

sys.modules["tools.saf_bridge"] = fake

import tools.vfs as vfs  # noqa: E402

Failed = []


def Check(name, expect, actual):
    if expect != actual:
        Failed.append("{}: 期望 {!r} 实际 {!r}".format(name, expect, actual))
        print("  x {}: 期望 {!r} 实际 {!r}".format(name, expect, actual))
    else:
        print("  . {}".format(name))


def Main():
    print("[1] 路径拼接/拆分")
    Check("IsSaf(saf)", True, vfs.IsSaf("saf://t1/commies"))
    Check("IsSaf(local)", False, vfs.IsSaf("/tmp/a"))
    Check("Split", (Trees["t1"], "commies/a"), vfs.Split("saf://t1/commies/a"))
    Check("Join(saf)", "saf://t1/commies/a/b", vfs.Join("saf://t1/commies", "a", "b"))
    Check("Join(saf 尾斜杠)", "saf://t1/commies/a", vfs.Join("saf://t1/commies/", "a"))
    Check("Join(local)", os.path.join("/tmp", "a"), vfs.Join("/tmp", "a"))
    Check("DirName(saf)", "saf://t1/commies/a", vfs.DirName("saf://t1/commies/a/1.jpg"))
    Check("BaseName(saf)", "1.jpg", vfs.BaseName("saf://t1/commies/a/1.jpg"))
    Check("ExtName", ".jpg", vfs.ExtName("saf://t1/commies/a/1.jpg"))

    print("[2] 写读(相对路径正确落进树)")
    path = vfs.Join("saf://t1/commies", "书名", "original", "第01话", "0001")
    Check("Write", True, vfs.Write(path + ".jpg", b"x" * 100))
    Check("落在树里", "commies/书名/original/第01话/0001.jpg", list(Files["t1"].keys())[0])
    Check("Exists", True, vfs.Exists(path + ".jpg"))
    Check("IsFile", True, vfs.IsFile(path + ".jpg"))
    Check("IsDir(文件)", False, vfs.IsDir(path + ".jpg"))
    Check("Size", 100, vfs.Size(path + ".jpg"))
    Check("Read", b"x" * 100, vfs.Read(path + ".jpg"))

    print("[3] 扩展名探测(业务层拿到的是不带扩展名的路径)")
    data = vfs.ReadPicture(path)
    Check("ReadPicture", b"x" * 100, data)
    Check("PicturePath", path + ".jpg", vfs.PicturePath(path))
    Check("ReadPicture(缺失)", None, vfs.ReadPicture(vfs.Join("saf://t1", "nope", "0009")))

    print("[4] 列目录/真实路径")
    Check("ListDir", [("书名", True)], vfs.ListDir(vfs.Join("saf://t1", "commies")))
    Check("RealPath", "/storage/emulated/0/Download/JMComic/commies", vfs.RealPath("saf://t1/commies"))

    print("[5] 整树复制(换下载目录时搬已下载内容)")
    Files["t2"].clear()
    count = vfs.CopyTree("saf://t1/commies", "saf://t2/commies")
    Check("复制文件数", 1, count)
    Check("新树里有", b"x" * 100, Files["t2"].get("commies/书名/original/第01话/0001.jpg"))

    print("[6] LocalOnly / 打开目录")
    Check("LocalOnly(saf)", "", vfs.LocalOnly("saf://t1/commies"))
    Check("LocalOnly(local)", "/tmp/a", vfs.LocalOnly("/tmp/a"))
    Check("OpenInFileManager(本地)", (False, "sandbox"), vfs.OpenInFileManager("/data/user/0/x"))

    print()
    if Failed:
        print("结果: {} 项失败".format(len(Failed)))
        for item in Failed:
            print("  - " + item)
        return 1
    print("结果: 0 项失败")
    return 0


if __name__ == "__main__":
    sys.exit(Main())
