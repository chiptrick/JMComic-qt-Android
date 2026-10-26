# coding:utf-8
"""下载/缓存目录回归(宿主跑，不需要 Qt/设备)

覆盖本轮"下载目录默认外部存储 + 自定义缓存目录"改动：

1. `_PkgFromPrivate`：从 ANDROID_PRIVATE(/data/user/0/<包名>/files)推包名
2. `_MigrateCacheToExternal`：老版本留在内部私有目录的缓存
   (<files>/cache/jmcomic-qt)启动时搬到外部缓存目录
   —— 整搬 / 新目录已有时逐项合并且不覆盖 / 两边同一个目录时不动 /
      没有旧缓存时什么都不做
3. `NormalizeLocalPath` / `IsInternalDataPath` / `EnsureWritableDir`：
   路径规范化、内部私有目录识别、真实可写校验
4. `NormalizeAndroidSavePath`：历史配置里的 /data/... 下载目录 → 外部目录
5. 缓存目录配置项：默认值、自定义生效、选回默认目录时清空配置
6. 自定义缓存目录搬迁：整搬 / 合并且不覆盖
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

os.environ.setdefault("JMCOMIC_ANDROID", "1")   # 让 platform_mobile 走 Android 语义

from tools import platform_mobile  # noqa: E402


def FreshDir():
    return tempfile.mkdtemp(prefix="jm_cache_test_")


def Write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def Read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def SeedOld(root):
    """ 造一份"老版本留在内部私有目录"的缓存 """
    base = os.path.join(root, "cache", "jmcomic-qt")
    Write(os.path.join(base, "book", "123", "0001.jpg"), "old-page")
    Write(os.path.join(base, "book", "123", "cover"), "old-cover")
    Write(os.path.join(base, "waifu2x", "book", "123"), "old-waifu")
    return base


def TestPackage():
    env = platform_mobile.EnvPrivate
    old = os.environ.get(env, "")
    try:
        os.environ[env] = "/data/user/0/org.jmcomic.qt/files"
        assert platform_mobile._PkgFromPrivate() == "org.jmcomic.qt"
        os.environ[env] = "/data/data/com.foo.bar/files"
        assert platform_mobile._PkgFromPrivate() == "com.foo.bar"
        os.environ[env] = "/tmp/whatever"
        assert platform_mobile._PkgFromPrivate() == ""
        os.environ[env] = "/data/user/0/org.jmcomic.qt/files2"
        assert platform_mobile._PkgFromPrivate() == ""
    finally:
        if old:
            os.environ[env] = old
        else:
            os.environ.pop(env, None)
    print("[ok] _PkgFromPrivate 包名推导(含非法形状)")


def TestCacheMigrateWhole():
    root, cacheBase = FreshDir(), FreshDir()
    oldBase = SeedOld(root)
    platform_mobile._MigrateCacheToExternal(root, cacheBase)
    assert platform_mobile.WaitCacheMigrate(), "搬迁线程没在超时内结束"
    newBase = os.path.join(cacheBase, "jmcomic-qt")
    assert Read(os.path.join(newBase, "book", "123", "0001.jpg")) == "old-page"
    assert Read(os.path.join(newBase, "waifu2x", "book", "123")) == "old-waifu"
    assert not os.path.exists(oldBase), "旧目录应该被搬空删掉"
    print("[ok] 旧缓存整体搬到外部缓存目录")


def TestCacheMigrateMerge():
    root, cacheBase = FreshDir(), FreshDir()
    oldBase = SeedOld(root)
    newBase = os.path.join(cacheBase, "jmcomic-qt")
    Write(os.path.join(newBase, "book", "123", "0001.jpg"), "new-page")
    Write(os.path.join(newBase, "extra"), "new-extra")
    platform_mobile._MigrateCacheToExternal(root, cacheBase)
    assert platform_mobile.WaitCacheMigrate(), "搬迁线程没在超时内结束"
    assert Read(os.path.join(newBase, "book", "123", "0001.jpg")) == "new-page", \
        "已存在的文件不能被旧缓存覆盖"
    assert Read(os.path.join(newBase, "extra")) == "new-extra"
    assert Read(os.path.join(newBase, "waifu2x", "book", "123")) == "old-waifu"
    assert Read(os.path.join(newBase, "book", "123", "cover")) == "old-cover"
    assert not os.path.exists(oldBase), "搬完旧目录要删掉"
    print("[ok] 新目录非空时逐项合并且不覆盖已有文件")


def TestCacheMigrateSameDir():
    root = FreshDir()
    oldBase = SeedOld(root)
    cacheBase = os.path.join(root, "cache")   # XDG_CACHE_HOME 退化到内部时的形状
    platform_mobile._MigrateCacheToExternal(root, cacheBase)
    assert platform_mobile.WaitCacheMigrate()
    assert Read(os.path.join(oldBase, "book", "123", "0001.jpg")) == "old-page", \
        "新旧同一个目录时不能被搬走"
    print("[ok] 新旧是同一个目录时原地不动")


def TestCacheMigrateNothing():
    root, cacheBase = FreshDir(), FreshDir()
    platform_mobile._MigrateCacheToExternal(root, cacheBase)
    assert platform_mobile.WaitCacheMigrate()
    assert not os.path.exists(os.path.join(cacheBase, "jmcomic-qt"))
    print("[ok] 没有旧缓存时不创建新目录")


def TestPathHelpers():
    assert platform_mobile.NormalizeLocalPath("  /tmp/x/../y  ") == os.path.normpath("/tmp/y")
    assert platform_mobile.NormalizeLocalPath("relative/path") == "", "相对路径必须拒绝"
    assert platform_mobile.NormalizeLocalPath("") == ""
    assert platform_mobile.NormalizeLocalPath("saf://t1/a/b") == "saf://t1/a/b"

    assert platform_mobile.IsInternalDataPath("/data/user/0/org.jmcomic.qt/files/JMComic")
    assert platform_mobile.IsInternalDataPath("/data/data/org.jmcomic.qt/files")
    assert not platform_mobile.IsInternalDataPath("/storage/emulated/0/Android/data/org.jmcomic.qt/files")
    assert not platform_mobile.IsInternalDataPath("")

    root = FreshDir()
    deep = os.path.join(root, "a", "b")
    ok, reason = platform_mobile.EnsureWritableDir(deep)
    assert ok and os.path.isdir(deep), reason
    assert not os.path.exists(os.path.join(deep, ".jm_write_probe")), "探针文件要删掉"

    ok, _ = platform_mobile.EnsureWritableDir("relative/dir")
    assert not ok, "相对路径不能当可写目录"

    blocked = os.path.join(root, "blocked")
    with open(blocked, "w", encoding="utf-8") as f:
        f.write("x")
    ok, _ = platform_mobile.EnsureWritableDir(blocked)
    assert not ok, "同名文件占位时不能算可写目录"
    print("[ok] 路径规范化 / 内部目录识别 / 真实可写校验")


def TestSavePathNormalize():
    ext = FreshDir()
    legacy = "/data/user/0/org.jmcomic.qt/files/JMComic"
    got, changed = platform_mobile.NormalizeAndroidSavePath(legacy, external=ext)
    assert got == os.path.normpath(ext) and changed, "内部私有下载目录必须改到外部"

    got, changed = platform_mobile.NormalizeAndroidSavePath(ext, external=ext)
    assert got == os.path.normpath(ext) and not changed

    got, changed = platform_mobile.NormalizeAndroidSavePath("", external=ext)
    assert got == os.path.normpath(ext) and changed, "空下载目录要用外部默认值"

    got, changed = platform_mobile.NormalizeAndroidSavePath("relative", external=ext)
    assert got == os.path.normpath(ext) and changed
    print("[ok] 下载目录默认值/历史内部路径 -> 外部存储")


def TestCacheSetting():
    from config.setting import Setting
    from tools import cache_path

    oldXDG = os.environ.get("XDG_CACHE_HOME", "")
    cacheBase = FreshDir()
    os.environ["XDG_CACHE_HOME"] = cacheBase
    Setting.CachePath._value = ""
    Setting.CachePath.setV = ""
    Setting._cachePathResolved = ""
    default = Setting.GetCachePath()
    assert default == os.path.join(cacheBase, "jmcomic-qt"), default
    assert not Setting.IsCustomCachePath()

    # 不能把配置写进真实 config.ini
    oldSave = Setting.SaveSettingV
    Setting.SaveSettingV = staticmethod(lambda item: None)
    try:
        customBase = FreshDir()
        ok, reason, oldPath, newPath, moving = cache_path.SetBase(customBase)
        assert ok, reason
        assert newPath == os.path.join(customBase, "jmcomic-qt"), newPath
        assert Setting.CachePath.value == newPath
        assert Setting.GetCachePath() == newPath
        assert Setting.IsCustomCachePath()
        print("[ok] 自定义缓存目录生效(直接写新目录): {}".format(newPath))

        # 选回默认目录 = 恢复默认值，配置里不留死路径
        ok, reason, _, newPath, _ = cache_path.SetBase(cacheBase)
        assert ok, reason
        assert Setting.CachePath.value == "", "选回默认目录时配置要清空"
        assert newPath == default
        print("[ok] 选回默认目录 -> 配置清空、回到默认值")

        # 非法路径不改变配置
        Setting.CachePath.SetValue("")
        ok, reason, _, _, _ = cache_path.SetBase("relative/cache")
        assert not ok and reason
        assert Setting.GetCachePath() == default, "非法路径不能生效"
        print("[ok] 非法缓存路径被拒绝，配置不变")
    finally:
        # 先清配置再恢复写入函数，避免把测试值写进真实 config.ini
        Setting.CachePath.SetValue("")
        Setting._cachePathResolved = ""
        Setting._cachePathRejected = ""
        Setting.SaveSettingV = oldSave
        cache_path.WaitMigrate()
        if oldXDG:
            os.environ["XDG_CACHE_HOME"] = oldXDG
        else:
            os.environ.pop("XDG_CACHE_HOME", None)


def TestCacheCustomMigrate():
    from tools import cache_path

    oldBase, newBase = FreshDir(), FreshDir()
    Write(os.path.join(oldBase, "book", "1", "0001.jpg"), "old-page")
    Write(os.path.join(oldBase, "waifu2x", "book", "1"), "old-waifu")
    Write(os.path.join(newBase, "book", "1", "0001.jpg"), "new-page")
    Write(os.path.join(newBase, "extra"), "keep")
    cache_path.MigrateAsync(oldBase, newBase)
    assert cache_path.WaitMigrate(), "搬迁线程没在超时内结束"
    assert Read(os.path.join(newBase, "book", "1", "0001.jpg")) == "new-page"
    assert Read(os.path.join(newBase, "extra")) == "keep"
    assert Read(os.path.join(newBase, "waifu2x", "book", "1")) == "old-waifu"
    assert not os.path.exists(oldBase), "旧缓存目录搬完要删掉"

    # 新目录还不存在：整搬
    oldBase, newBase = FreshDir(), os.path.join(FreshDir(), "sub")
    Write(os.path.join(oldBase, "book", "2"), "page2")
    cache_path.MigrateAsync(oldBase, newBase)
    assert cache_path.WaitMigrate()
    assert Read(os.path.join(newBase, "book", "2")) == "page2"
    assert not os.path.exists(oldBase)
    print("[ok] 换自定义缓存目录时整搬/合并且不覆盖")


def main():
    TestPackage()
    TestCacheMigrateWhole()
    TestCacheMigrateMerge()
    TestCacheMigrateSameDir()
    TestCacheMigrateNothing()
    TestPathHelpers()
    TestSavePathNormalize()
    TestCacheSetting()
    TestCacheCustomMigrate()
    print("下载/缓存目录回归: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
