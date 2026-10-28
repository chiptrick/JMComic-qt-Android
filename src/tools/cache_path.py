# coding:utf-8
""" 自定义缓存目录 —— 设置页"缓存位置"按钮背后的那一层

约定
----
* **默认值**见 `Setting.GetDefaultCachePath()`：
      Android -> /storage/emulated/0/Android/data/<包名>/cache/jmcomic-qt
      Windows -> <SavePath>/cache
      Linux   -> $XDG_CACHE_HOME/jmcomic-qt
* **配置项**：config.ini 的 `[DownloadSetting]`
      * CachePathTree / CachePathTreeName —— 手机上 SAF 选的目录(树 URI + 名字)
      * CachePath —— 本地绝对路径(桌面端/历史配置)
      都为空 = 默认值。手机上选中的目录实际写作 `saf://<key>/jmcomic-qt`。
* **修改入口**：设置 → 下载与缓存 →"缓存位置"按钮
  (见 view/setting/setting_view.py)。

写入语义
--------
选中目录后，新产生的封面/图片缓存/超分临时图**直接写进新目录**(SAF 时由
tools/vfs.py 的数据面逐文件直写)，不会再经过默认目录。只有"已经在旧目录里的
缓存"才会在后台搬一次(目标已有内容则逐文件合并且不覆盖)。
"""
import os
import threading

from config import config
from tools import platform_mobile

# 应用在用户选的目录里只占这一个子目录，不往人家目录里散落文件
CacheLeaf = config.CacheLeafDir

_threads = []


def DefaultPath():
    """ 默认缓存目录(平台相关，见 Setting.GetDefaultCachePath) """
    from config.setting import Setting
    return platform_mobile.NormalizeLocalPath(Setting.GetDefaultCachePath())


def CurrentPath():
    """ 当前生效的缓存目录(可能是 `saf://...`) """
    from config.setting import Setting
    return str(Setting.GetCachePath() or "")


def DisplayPath(path=""):
    """ 给人看的真实路径(SAF 还原成 /storage/emulated/0/…) """
    from tools import vfs
    return vfs.RealPath(path or CurrentPath())


def IsCustom():
    from config.setting import Setting
    return Setting.IsCustomCachePath()


def IsSaf():
    from config.setting import Setting
    return bool(Setting.CacheTreeKey())


def TargetFromBase(baseDir):
    """ 用户选的目录 -> 实际缓存目录

    统一加一层 `jmcomic-qt`，避免把缓存文件直接撒进用户选的目录；
    但有两种"选的其实就是默认位置"的情况不再套娃：
      * 选的正好是默认缓存目录(Windows 是 <SavePath>/cache)
      * 选的是默认缓存目录的父目录(Android/Linux 是 …/cache 或 …)
    用户恰好选到已有的 `…/jmcomic-qt` 时也不套娃。
    """
    base = platform_mobile.NormalizeLocalPath(baseDir)
    if not base or base.startswith("saf://"):
        return ""
    default = DefaultPath()
    if default:
        for candidate in (default, os.path.dirname(default)):
            if candidate and os.path.normcase(candidate) == os.path.normcase(base):
                return default
    if os.path.basename(base) == CacheLeaf:
        return base
    return os.path.join(base, CacheLeaf)


def _Migrate(oldPath, newPath):
    """ 后台把旧缓存搬到新目录；复制成功才删旧的

    本地 <-> SAF 都走 vfs(Read/Write/ListDir/RemoveTree)，这样"缓存目录在
    SAF 树里"也能迁移。文件级不覆盖：新目录里已有的文件优先。
    """
    oldPath = str(oldPath or "")
    newPath = str(newPath or "")
    if not oldPath or not newPath:
        return False
    if os.path.normcase(oldPath) == os.path.normcase(newPath):
        return False

    def Run():
        from tools import vfs
        try:
            if not vfs.IsDir(oldPath):
                return
            # 不覆盖新目录里已有的文件(与新目录版本优先的既定行为一致)
            total = vfs.CopyTree(oldPath, newPath, overwrite=False)
            if total > 0:
                vfs.RemoveTree(oldPath)
            try:
                from tools.log import Log
                Log.logger.warning("cache path: 已搬 {} 个文件 {} -> {}".format(
                    total, oldPath, newPath))
            except Exception:
                pass
        except Exception as es:
            try:
                from tools.log import Log
                Log.logger.warning("cache path: 搬迁失败(保留旧目录): {}".format(es))
            except Exception:
                pass

    thread = threading.Thread(target=Run, name="cache-migrate-vfs", daemon=True)
    _threads.append(thread)
    thread.start()
    return True


def SetTree(uri, name=""):
    """ 设置 SAF 缓存目录(设置页选完目录调用)

    返回 (ok, reason, 旧路径, 新路径, 是否开始后台搬迁)。
    只登记授权 + 建 `jmcomic-qt` 子目录；写权限来自 SAF 的
    takePersistableUriPermission，重启后依然有效。
    """
    from config.setting import Setting
    from tools import saf_bridge

    uri = str(uri or "").strip()
    if not uri:
        return False, "无效目录", "", "", False
    if not saf_bridge.IsSupported():
        return False, "当前设备不支持 SAF", "", "", False
    saf_bridge.IoMakedirs(uri, CacheLeaf)
    # mkdirs 在 Java 侧无论成败都回 ok：真正写一个探针文件才知道授权还在
    probe = "{}/.jm_write_probe".format(CacheLeaf)
    if not saf_bridge.IoWrite(uri, probe, b"jm"):
        return False, "无法写入该目录（授权已失效或目录不可写）", "", "", False
    saf_bridge.IoDelete(uri, probe)

    oldPath = CurrentPath()
    Setting.CachePathTree.SetValue(uri)
    Setting.CachePathTreeName.SetValue(name or saf_bridge.UriDisplayName(uri))
    Setting.CachePath.SetValue("")          # 清掉旧的自定义本地路径
    newPath = CurrentPath()
    moving = _Migrate(oldPath, newPath)
    return True, "", oldPath, newPath, moving


def SetBase(baseDir):
    """ 设置本地缓存目录(桌面端/历史路径；手机上优先用 SetTree)

    返回 (ok, reason, 旧路径, 新路径, 是否开始后台搬迁)。
    * 路径非法 / 建不了 / 写不进 -> ok=False，配置不变
    * 选中的就是默认目录 -> 配置清空(恢复默认值)
    """
    from config.setting import Setting

    target = TargetFromBase(baseDir)
    if not target:
        return False, "路径无效（必须是绝对路径）", "", "", False
    ok, reason = platform_mobile.EnsureWritableDir(target)
    if not ok:
        return False, reason, "", "", False

    oldPath = CurrentPath()
    default = DefaultPath()
    Setting.CachePathTree.SetValue("")
    if default and os.path.normcase(target) == os.path.normcase(default):
        Setting.CachePath.SetValue("")
    else:
        Setting.CachePath.SetValue(target)
    newPath = CurrentPath()
    moving = _Migrate(oldPath, newPath)
    return True, "", oldPath, newPath, moving


def Reset():
    """ 恢复默认缓存目录(并把自定义目录里已有的缓存搬回默认目录) """
    from config.setting import Setting

    default = DefaultPath()
    if not default:
        return False, "没有可用的默认缓存目录", "", "", False
    oldPath = CurrentPath()
    Setting.CachePathTree.SetValue("")
    Setting.CachePathTreeName.SetValue("")
    Setting.CachePath.SetValue("")
    newPath = CurrentPath()
    moving = _Migrate(oldPath, newPath)
    return True, "", oldPath, newPath, moving


def MigrateAsync(oldPath, newPath):
    """ 显式搬缓存(给测试/迁移用) """
    return _Migrate(oldPath, newPath)


def WaitMigrate(timeout=30.0):
    """ 等缓存搬迁结束(测试/退出前用) """
    import time as _time

    deadline = _time.time() + max(0.0, float(timeout))
    for thread in list(_threads):
        try:
            thread.join(max(0.0, deadline - _time.time()))
        except Exception:
            pass
    alive = [t for t in _threads if t.is_alive()]
    _threads[:] = alive
    try:
        platform_mobile.WaitDirMigrate(0.0)
    except Exception:
        pass
    return not alive
