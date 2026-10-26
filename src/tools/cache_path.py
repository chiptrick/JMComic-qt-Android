# coding:utf-8
""" 自定义缓存目录 —— 设置页"缓存位置"按钮背后的那一层

约定
----
* **默认值**见 `Setting.GetDefaultCachePath()`：
      Android -> /storage/emulated/0/Android/data/<包名>/cache/jmcomic-qt
      Windows -> <SavePath>/cache
      Linux   -> $XDG_CACHE_HOME/jmcomic-qt
* **配置项**是 config.ini 的 `[DownloadSetting] CachePath`：
      空串 = 默认值；绝对路径 = 自定义目录(带 jmcomic-qt 这一层)
* **修改入口**：设置 → 下载与缓存 →"缓存位置"按钮(见 view/setting/setting_view.py)。
  手机上选的是**真实可写目录**，不走 SAF 导入(缓存必须能直接 open)。

写入语义
--------
选中目录后，新产生的封面/图片缓存/超分临时图**直接写进新目录**，不会再经过
默认目录。只有"已经在旧目录里的缓存"才会在后台搬一次(整搬；目标已有内容则
逐文件合并且不覆盖)，这样用户改完目录不会丢已经下载/算好的缓存。
"""
import os

from tools import platform_mobile

# 应用在用户选的目录里只占这一个子目录，不往人家目录里散落文件
CacheLeaf = "jmcomic-qt"

# 搬迁线程只由 platform_mobile 统一管理，便于测试等待


def DefaultPath():
    """ 默认缓存目录(平台相关，见 Setting.GetDefaultCachePath) """
    from config.setting import Setting
    return platform_mobile.NormalizeLocalPath(Setting.GetDefaultCachePath())


def CurrentPath():
    """ 当前生效的缓存目录(自定义优先) """
    from config.setting import Setting
    return platform_mobile.NormalizeLocalPath(Setting.GetCachePath())


def IsCustom():
    from config.setting import Setting
    return Setting.IsCustomCachePath()


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


def SetBase(baseDir):
    """ 把缓存目录改成 <baseDir>/jmcomic-qt

    返回 (ok, reason, 旧路径, 新路径, 是否开始后台搬迁)。

    * 路径非法 / 建不了 / 写不进 -> ok=False，配置不变
    * 选中的就是默认目录 -> 配置清空(恢复默认值)
    * 否则把旧目录内容在后台搬到新目录(新缓存从此直接写新目录)
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
    if default and os.path.normcase(target) == os.path.normcase(default):
        # 选回默认目录 = 恢复默认值，配置里不留死路径
        Setting.CachePath.SetValue("")
    else:
        Setting.CachePath.SetValue(target)
    newPath = CurrentPath()

    moving = False
    if oldPath and newPath and os.path.normcase(oldPath) != os.path.normcase(newPath):
        if os.path.isdir(oldPath):
            platform_mobile.MigrateDirAsync(oldPath, newPath, "cache")
            moving = True
    return True, "", oldPath, newPath, moving


def Reset():
    """ 恢复默认缓存目录(并把自定义目录里已有的缓存搬回默认目录) """
    from config.setting import Setting

    default = DefaultPath()
    if not default:
        return False, "没有可用的默认缓存目录", "", "", False
    oldPath = CurrentPath()
    Setting.CachePath.SetValue("")
    newPath = CurrentPath()
    moving = False
    if oldPath and newPath and os.path.normcase(oldPath) != os.path.normcase(newPath):
        if os.path.isdir(oldPath):
            platform_mobile.MigrateDirAsync(oldPath, newPath, "cache")
            moving = True
    return True, "", oldPath, newPath, moving


def MigrateAsync(oldPath, newPath):
    """ 显式搬缓存(给测试/迁移用) """
    return platform_mobile.MigrateDirAsync(oldPath, newPath, "cache")


def WaitMigrate(timeout=30.0):
    """ 等缓存搬迁结束 """
    return platform_mobile.WaitDirMigrate(timeout)
