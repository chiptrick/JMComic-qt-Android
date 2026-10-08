# coding:utf-8
"""核对 APK 里的启动器图标(launcher icon)是否就是指定的源图

用法:
    python android/tools/probe_apk_icon.py <apk> [expected.png]

背景: p4a(bootstraps/common/build/build.py) 把 buildozer.spec 的 icon.filename
**原样**拷成 dists/<name>/src/main/res/mipmap/icon.png，清单里是
`android:icon="@mipmap/icon"`。但 aapt2 打包时可能对 res/ 下的 PNG 做无损重编码
(转索引色/去元数据)，所以不能比对文件字节，要比对解出来的像素。

做四件事:
  1) 列出 APK 里所有 icon/mipmap 相关条目(aapt2 可能改路径)
  2) 解出图标，与期望图逐像素比对(尺寸 + 不同像素数 + 最大通道差)
  3) 报告是否还残留 PySide6 自带的 pyside_icon / p4a 默认 kivy-icon
  4) 打印图标资源的实际字节数(便于确认没被换回默认图)
"""
import sys
import zipfile
from io import BytesIO

try:
    from PIL import Image, ImageChops
except ImportError:                                  # pragma: no cover
    print("需要 Pillow")
    sys.exit(2)


def FindIconEntries(zf):
    names = zf.namelist()
    hits = [n for n in names if "icon" in n.lower() or "mipmap" in n.lower()]
    launcher = [n for n in hits
                if n.lower().endswith(".png") and "icon" in n.rsplit("/", 1)[-1].lower()]
    return hits, launcher


def PixelDiff(a, b):
    """ 返回 (尺寸是否相同, 不同像素数, 最大单通道差) """
    if a.size != b.size:
        return False, -1, -1
    a = a.convert("RGBA")
    b = b.convert("RGBA")
    diff = ImageChops.difference(a, b)
    extrema = diff.getextrema()                      # 每通道 (min, max)
    maxDiff = max(e[1] for e in extrema)
    if diff.getbbox() is None:
        return True, 0, 0
    sp = a.load()
    dp = b.load()
    w, h = a.size
    count = 0
    for y in range(h):
        for x in range(w):
            if sp[x, y] != dp[x, y]:
                count += 1
    return True, count, maxDiff


def Main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    apk = sys.argv[1]
    expectPath = sys.argv[2] if len(sys.argv) > 2 else ""
    zf = zipfile.ZipFile(apk)
    hits, launcher = FindIconEntries(zf)
    print("== APK: {} ==".format(apk))
    print("icon/mipmap 相关条目 {} 个:".format(len(hits)))
    for n in hits[:20]:
        print("    {:<52} {:>9} 字节".format(n, zf.getinfo(n).file_size))
    if not hits:
        print("    (没有)")

    expect = None
    if expectPath:
        expect = Image.open(expectPath).convert("RGBA")
        print()
        print("== 期望图: {} ({}x{}) ==".format(expectPath, expect.size[0], expect.size[1]))

    print()
    print("== 图标条目逐像素比对 ==")
    if not launcher:
        print("  !! 没有 png 形式的 icon 条目")
    for n in launcher:
        raw = zf.read(n)
        try:
            img = Image.open(BytesIO(raw))
            img.load()
        except Exception as exc:                     # pragma: no cover
            print("  {}: 解不开 ({})".format(n, exc))
            continue
        print("  {}: {} {} {} 字节".format(n, img.format, "%dx%d" % img.size, len(raw)))
        if expect is None:
            continue
        sameSize, count, maxDiff = PixelDiff(img, expect)
        total = img.size[0] * img.size[1]
        print("      与期望图: 尺寸相同={} 不同像素={}/{} 最大通道差={}".format(
            sameSize, count, total, maxDiff))
        if sameSize and count == 0:
            verdict = "是我们换上的图标(逐像素一致)"
        elif sameSize:
            verdict = "同尺寸但像素不同(可能是别的图)"
        else:
            verdict = "尺寸都不同 —— 不是这张图"
        print("      结论: {}".format(verdict))

    print()
    print("== 残留的工具自带图标 ==")
    leftovers = [n for n in zf.namelist()
                 if "pyside_icon" in n.lower() or "kivy-icon" in n.lower()]
    for n in leftovers:
        print("  !! {}".format(n))
    if not leftovers:
        print("  (没有 pyside_icon / kivy-icon 条目)")
    return 0


if __name__ == "__main__":
    sys.exit(Main())
