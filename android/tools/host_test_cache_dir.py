# coding:utf-8
"""缓存目录重定向回归(宿主跑，不需要 Qt/设备)

覆盖 platform_mobile 为"默认缓存目录改到应用外部缓存目录
(/storage/emulated/0/Android/data/<包名>/cache)"新加的两块逻辑：

1. `_PkgFromPrivate`：从 ANDROID_PRIVATE(/data/user/0/<包名>/files)推包名
2. `_MigrateCacheToExternal`：老版本留在内部私有目录的缓存
   (<files>/cache/jmcomic-qt)启动时搬到外部缓存目录
   —— 整搬 / 新目录已有时逐项合并且不覆盖 / 两边同一个目录时不动 /
      没有旧缓存时什么都不做
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

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


def main():
    # ---- 1. 包名推导(真机 ANDROID_PRIVATE 的形状) -------------------------
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

    # ---- 2. 整搬：外部缓存目录还不存在 --------------------------------
    root, cacheBase = FreshDir(), FreshDir()
    oldBase = SeedOld(root)
    platform_mobile._MigrateCacheToExternal(root, cacheBase)
    assert platform_mobile.WaitCacheMigrate(), "搬迁线程没在超时内结束"
    newBase = os.path.join(cacheBase, "jmcomic-qt")
    assert Read(os.path.join(newBase, "book", "123", "0001.jpg")) == "old-page"
    assert Read(os.path.join(newBase, "waifu2x", "book", "123")) == "old-waifu"
    assert not os.path.exists(oldBase), "旧目录应该被搬空删掉"
    print("[ok] 旧缓存整体搬到外部缓存目录")

    # ---- 3. 合并：外部缓存目录已经有内容，逐项搬、不覆盖 ------------------
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

    # ---- 4. 同一个目录(外部存储不可用、退化成内部目录)：不动 ---------------
    root = FreshDir()
    oldBase = SeedOld(root)
    cacheBase = os.path.join(root, "cache")   # XDG_CACHE_HOME 退化到内部时的形状
    platform_mobile._MigrateCacheToExternal(root, cacheBase)
    assert platform_mobile.WaitCacheMigrate()
    assert Read(os.path.join(oldBase, "book", "123", "0001.jpg")) == "old-page", \
        "新旧同一个目录时不能被搬走"
    print("[ok] 新旧是同一个目录时原地不动")

    # ---- 5. 没有旧缓存：直接返回 ---------------------------------------
    root, cacheBase = FreshDir(), FreshDir()
    platform_mobile._MigrateCacheToExternal(root, cacheBase)
    assert platform_mobile.WaitCacheMigrate()
    assert not os.path.exists(os.path.join(cacheBase, "jmcomic-qt"))
    print("[ok] 没有旧缓存时不创建新目录")

    print("缓存目录重定向回归: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
