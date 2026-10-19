# coding:utf-8
""" 下载目录切换 —— 换目录时把已经下载的内容搬到新目录

用户把"下载与缓存路径"改到手机存储里的某个目录之后：

1. 之后的所有下载/超分/删除**直接**在 那个目录里发生(见 tools/vfs.py)；
2. 之前已经下载到旧目录(应用专属目录)里的漫画，要在后台搬过去 —— 否则用户会看到
   "我改了路径，但旧书还在原来的地方"，等于没生效。

搬运策略：先整棵复制，**全部成功之后**才删旧目录；中途失败就保留旧目录(宁可多占
一份，也不能把用户已下载的内容删掉)。搬运在后台线程做，不卡界面。
"""
import threading

from tools.log import Log

_migrating = False


def CurrentRoot():
    from config.setting import Setting
    return Setting.GetDownloadRoot()


def Switch(uri, name=""):
    """ 切换下载目录(SAF 树 URI；传空串 = 回到应用专属目录)

    返回 (旧根, 新根, 是否开始后台搬运)
    """
    from config.setting import Setting
    oldRoot = Setting.GetDownloadRoot()
    Setting.SavePathTree.SetValue(uri or "")
    Setting.SavePathTreeName.SetValue(name or "")
    Setting.SaveSettingV(Setting.SavePathTree)
    Setting.SaveSettingV(Setting.SavePathTreeName)
    newRoot = Setting.GetDownloadRoot()
    Log.Warn("download path: {} -> {}".format(oldRoot, newRoot))
    if not oldRoot or oldRoot == newRoot:
        return oldRoot, newRoot, False
    from tools import vfs
    if not vfs.IsDir(oldRoot):
        return oldRoot, newRoot, False
    MigrateAsync(oldRoot, newRoot)
    return oldRoot, newRoot, True


def MigrateAsync(oldRoot, newRoot):
    """ 后台把 oldRoot 的内容搬到 newRoot；全部成功才删旧目录 """
    global _migrating
    if _migrating:
        Log.Warn("download path: 上一次搬运还没结束，跳过本次")
        return False
    _migrating = True

    def Run():
        global _migrating
        from tools import vfs
        try:
            Log.Warn("download path: 开始搬运 {} -> {}".format(oldRoot, newRoot))
            total = vfs.CopyTree(oldRoot, newRoot)
            Log.Warn("download path: 搬运完成，{} 个文件".format(total))
            if total > 0:
                # 复制成功才删旧的：宁可多占一份，也不能删掉用户已下载的内容
                vfs.RemoveTree(oldRoot)
                Log.Warn("download path: 已清理旧目录 {}".format(oldRoot))
        except Exception as es:
            Log.Error(es)
        finally:
            _migrating = False

    thread = threading.Thread(target=Run, name="jm-migrate")
    thread.setDaemon(True)
    thread.start()
    return True
