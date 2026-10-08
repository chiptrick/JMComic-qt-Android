# -*- coding: utf-8 -*-
""" 用"接缝分数"客观判断一张图是不是"被分块打乱后没还原回正确顺序"

思路：还原正确的图，块与块相接处两行的差异应该和普通相邻两行差不多；
没还原的图，接缝处会有明显的错位跳变。所以
    ratio = 接缝处平均行差 / 全图平均行差
ratio≈1 说明拼好了，ratio 越大说明越像"错位的拼图"。
真机自检用它来在没有肉眼的情况下证明"图片分割"是否正常。
"""
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "build_logs")


def seam_score(img, num, samples=48):
    """ -> (seam, base, ratio) """
    w, h = img.size
    c = h // num
    rem = h % num
    if c <= 0:
        return -1.0, -1.0, -1.0
    px = img.load()
    step = max(1, w // samples)

    def row_diff(y):
        s = n = 0
        for x in range(0, w, step):
            p1 = px[x, y - 1]
            p2 = px[x, y]
            s += abs(p1[0] - p2[0]) + abs(p1[1] - p2[1]) + abs(p1[2] - p2[2])
            n += 1
        return s / max(1, n)

    bounds = []
    y = 0
    for i in range(num):
        y += c + (rem if i == 0 else 0)
        if 1 <= y < h:
            bounds.append(y)
    seam = sum(row_diff(y) for y in bounds) / max(1, len(bounds))

    base = []
    for k in range(1, 400):
        y = 1 + k * (h - 2) // 400
        if any(abs(y - b) <= 2 for b in bounds):
            continue
        base.append(row_diff(y))
    avg = sum(base) / max(1, len(base))
    return seam, avg, (seam / avg if avg else -1.0)


def main():
    files = [
        ("原图(真机缓存下来的、未还原)", os.path.join(OUT, "page_raw.png"), 12),
        ("本仓库还原后", os.path.join(OUT, "page_repo_decoded.png"), 12),
    ]
    for name, path, num in files:
        if not os.path.isfile(path):
            print("缺少 {}".format(path))
            continue
        with Image.open(path) as im:
            im = im.convert("RGB")
            seam, base, ratio = seam_score(im, num)
            print("{:34s} num={:2d} 接缝={:7.2f} 基线={:7.2f} 比值={:5.2f}".format(
                name, num, seam, base, ratio))

    # 再验证一次"二次还原会彻底错位"：拿还原后的图再还原一次，比值应该爆掉
    with Image.open(os.path.join(OUT, "page_repo_decoded.png")) as im:
        im = im.convert("RGB")
    import math
    w, h = im.size
    num = 12
    c = h // num
    rem = h % num
    out = Image.new("RGB", (w, h))
    y = 0
    for i in range(num):
        move = c + (rem if i == 0 else 0)
        y_src = h - c * (i + 1) - rem
        out.paste(im.crop((0, y_src, w, y_src + move)), (0, y, w, y + move))
        y += move
    out.save(os.path.join(OUT, "page_twice_decoded.png"))
    seam, base, ratio = seam_score(out, num)
    print("{:34s} num={:2d} 接缝={:7.2f} 基线={:7.2f} 比值={:5.2f}".format(
        "错误示例: 还原了两次", num, seam, base, ratio))
    return 0


if __name__ == "__main__":
    sys.exit(main())
