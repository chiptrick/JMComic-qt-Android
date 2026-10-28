# coding:utf-8
""" 统一的文件访问层 —— 同一套调用既能写本地路径，也能写 Android SAF 目录

为什么需要
----------
用户把"下载与缓存路径"改成手机存储里的某个目录之后，**下载过程中的每个文件就必须
直接落在那 个目录里**。不能像以前那样先写进应用私有目录、整本下完再拷过去：

  * 下载到一半取消 / 进程被杀，私有目录里会留下一份用户根本不知道的副本；
  * 用户在文件管理器里看不到正在下载的内容；
  * 几十本漫画白占两份空间。

但 SAF 只能给 content:// URI，Python 的 open() 打不开。所以：

    saf://t1/commies/某本/第01话/0001.jpg
       │      │
       │      └── 树里的相对路径(和本地路径段一一对应)
       └── 目录树登记表的短 key(见 tools/saf_bridge.py 的 TreeKey)

本模块把 "saf://" 开头的路径交给 `saf_bridge` 的 socket 数据面直接读写，
其余路径照旧走 os —— 业务代码不用关心自己在写哪一边。

调用约定
--------
* 读写图片用 `Read` / `Write`(按字节)。
* 判断存在/大小/列目录用 `Exists` / `Size` / `ListDir`。
* 拼接/取父目录**必须**用这里的 `Join` / `DirName` / `BaseName`：saf 路径在
  Windows 上跑测试时 os.path 的分隔符会把它拆坏。
* 只支持本地路径的老 API(比如另存为对话框)用 `LocalOnly()` 拿真路径，没有就返回空。
"""
import os
import shutil

from tools import saf_bridge

SafPrefix = "saf://"


def IsSaf(path):
    return str(path or "").startswith(SafPrefix)


def Split(path):
    """ saf://t1/a/b -> (树 URI, "a/b")；不是 saf 路径返回 ("", "") """
    text = str(path or "")
    if not text.startswith(SafPrefix):
        return "", ""
    rest = text[len(SafPrefix):]
    key, _, rel = rest.partition("/")
    return saf_bridge.TreeUri(key), rel


def Join(base, *parts):
    """ 拼路径：saf 路径用 "/"，本地路径交给 os.path.join """
    text = str(base or "")
    if not text.startswith(SafPrefix):
        return os.path.join(text, *[str(p) for p in parts if str(p) != ""]) if parts else text
    for part in parts:
        part = str(part or "")
        if not part:
            continue
        text = text.rstrip("/") + "/" + part.strip("/")
    return text


def DirName(path):
    text = str(path or "").rstrip("/")
    index = text.rfind("/")
    if index < 0:
        return ""
    return text[:index]


def BaseName(path):
    text = str(path or "").rstrip("/")
    index = text.rfind("/")
    return text if index < 0 else text[index + 1:]


def ExtName(path):
    name = BaseName(path)
    index = name.rfind(".")
    return name[index:] if index > 0 else ""


# ---------------------------------------------------------------------------
# 读写
# ---------------------------------------------------------------------------

def Read(path):
    """ 读文件；失败返回 None """
    uri, rel = Split(path)
    if uri:
        return saf_bridge.IoRead(uri, rel)
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None


def Write(path, data):
    """ 写文件(自动建父目录)；成功返回 True """
    if data is None:
        return False
    uri, rel = Split(path)
    if uri:
        return saf_bridge.IoWrite(uri, rel, data)
    try:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, "wb+") as f:
            f.write(data)
        return True
    except Exception as es:
        try:
            from tools.log import Log
            Log.Error(es)
        except Exception:
            pass
        return False


def Exists(path):
    uri, rel = Split(path)
    if uri:
        ok, _, _ = saf_bridge.IoExists(uri, rel)
        return ok
    try:
        return os.path.exists(path)
    except Exception:
        return False


def IsFile(path):
    uri, rel = Split(path)
    if uri:
        ok, isDir, _ = saf_bridge.IoExists(uri, rel)
        return ok and not isDir
    try:
        return os.path.isfile(path)
    except Exception:
        return False


def IsDir(path):
    uri, rel = Split(path)
    if uri:
        ok, isDir, _ = saf_bridge.IoExists(uri, rel)
        return ok and isDir
    try:
        return os.path.isdir(path)
    except Exception:
        return False


def Size(path):
    uri, rel = Split(path)
    if uri:
        ok, isDir, size = saf_bridge.IoExists(uri, rel)
        return size if ok and not isDir else 0
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def Makedirs(path):
    uri, rel = Split(path)
    if uri:
        return saf_bridge.IoMakedirs(uri, rel)
    try:
        if path and not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
        return True
    except Exception:
        return False


def ListDir(path):
    """ 列目录，返回 [(名字, 是否目录)]；失败返回 [] """
    uri, rel = Split(path)
    if uri:
        return saf_bridge.IoList(uri, rel) or []
    out = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    out.append((entry.name, entry.is_dir()))
                except Exception:
                    continue
    except Exception:
        return []
    return out


def RemoveFile(path):
    uri, rel = Split(path)
    if uri:
        return saf_bridge.IoDelete(uri, rel)
    try:
        if os.path.isfile(path):
            os.remove(path)
        return True
    except Exception:
        return False


def RemoveTree(path):
    """ 删目录(递归)或文件 """
    uri, rel = Split(path)
    if uri:
        return saf_bridge.IoDelete(uri, rel)
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, True)
        elif os.path.isfile(path):
            os.remove(path)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 给"只认本地路径"的旧接口用的辅助
# ---------------------------------------------------------------------------

def LocalOnly(path):
    """ saf 路径没有本地等价物，返回空串(调用方据此给出提示而不是硬写) """
    if IsSaf(path):
        return ""
    return path


def RealPath(path):
    """ 界面上给人看的路径：saf 路径尽量还原成 /storage/emulated/0/… """
    uri, rel = Split(path)
    if not uri:
        text = str(path or "")
        if text.startswith(SafPrefix):
            # 树登记表里找不到 key(极端情况)：至少显示一个可读的目录名，
            # 不能把内部的 saf:// 路径直接甩给用户
            key, _, rel2 = text[len(SafPrefix):].partition("/")
            name = saf_bridge.TreeName(key) or "SAF目录"
            return "{}/{}".format(name, rel2) if rel2 else name
        return text
    base = saf_bridge.TreeRealPath(uri)
    if base:
        return "{}/{}".format(base, rel) if rel else base
    name = saf_bridge.TreeName(saf_bridge.TreeKey(uri))
    return "{}/{}".format(name, rel) if rel else (name or uri)


def OpenInFileManager(path):
    """ 用系统文件管理器打开这个目录；返回 (是否成功, 原因) """
    uri, rel = Split(path)
    if uri:
        # 目录可能还没建出来(比如刚选完目录还没下载)：建出来再打开，
        # 用户点"打开目录"看到的应该就是下载目录本身
        saf_bridge.IoMakedirs(uri, rel)
        target = saf_bridge.IoDocUri(uri, rel)
        if target:
            return saf_bridge.OpenUri(target)
        return saf_bridge.OpenUri(uri)
    return saf_bridge.OpenPath(path)


def ReadPicture(basePath):
    """ 和 ToolUtil.LoadCachePicture 一样的"带扩展名探测"的读取

    业务层拿到的路径通常**不带扩展名**(下载时按真实格式补 .jpg/.png/…)，所以
    要依次试。saf 路径也一样：Java 侧每次 stat 都走目录缓存，代价很小。
    """
    formats = (".jpg", ".png", ".gif", ".webp", ".bmp", ".apng")
    text = str(basePath or "")
    if not text:
        return None
    if text[-4:] in formats or text[-5:] in formats:
        data = Read(text)
        return data if data and len(data) >= 20 else None
    for mat in formats:
        data = Read(text + mat)
        if data and len(data) >= 20:
            return data
    return None


def PicturePath(basePath):
    """ 找出真实存在的那个"带扩展名"的路径；找不到返回空串 """
    formats = (".jpg", ".png", ".gif", ".webp", ".bmp", ".apng")
    text = str(basePath or "")
    if not text:
        return ""
    if text[-4:] in formats or text[-5:] in formats:
        return text if IsFile(text) else ""
    for mat in formats:
        path = text + mat
        if IsFile(path):
            return path
    return ""


# ---------------------------------------------------------------------------
# 整棵树复制(改下载目录时把已下载的书搬过去)
# ---------------------------------------------------------------------------

def CopyTree(src, dst, onFile=None, overwrite=True):
    """ 递归复制 src -> dst，返回复制的文件数；失败的文件跳过

    overwrite=False：目标已存在同名文件时跳过(缓存搬迁用：新目录里的优先)
    """
    count = 0
    for name, isDir in ListDir(src):
        source = Join(src, name)
        target = Join(dst, name)
        if isDir:
            count += CopyTree(source, target, onFile, overwrite)
            continue
        if not overwrite and Exists(target):
            continue
        data = Read(source)
        if data is None:
            continue
        if Write(target, data):
            count += 1
            if onFile is not None:
                try:
                    onFile(count, name)
                except Exception:
                    pass
    return count
