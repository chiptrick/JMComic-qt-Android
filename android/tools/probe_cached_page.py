# -*- coding: utf-8 -*-
""" 离线复现真机"图片分割异常/错位"

真机日志里的关键行：
    SegmentationPicture failed, epsId:1479594 scrambleId:220980 len:1091216
    err:cannot identify image file <_io.BytesIO object ...>

也就是：Android 上的 Pillow 打不开 JM 的 webp 图片(缺 webp 解码器)，
SegmentationPicture 抛异常 → 兜底返回原始字节 → 看图界面直接显示"被打乱的原图"
→ 用户看到的就是"图片分割异常、图像错位"。

这个脚本用桌面 Pillow 证明两件事：
1) 同样这些字节，桌面 Pillow 能正常解码(说明问题在 Android 的 Pillow 编解码器，不在算法)；
2) 本仓库的分割算法与官方 jmcomic 的 decode_and_save 完全等价(逐像素相同)。
"""
import hashlib
import math
import os
import sys
from io import BytesIO

from PIL import Image, features

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "build_logs")
RAW = os.path.join(OUT, "device_cache_1479594_1_1.jpg")   # 真机缓存下来的原始(打乱)图


def get_num(eps_id, scramble_id, picture_name):
    eps_id = int(eps_id)
    scramble_id = int(scramble_id)
    if eps_id < scramble_id:
        return 0
    if eps_id < 268850:
        return 10
    x = 10 if eps_id < 421926 else 8
    s = "{}{}".format(eps_id, picture_name).encode()
    num = ord(hashlib.md5(s).hexdigest()[-1])
    return num % x * 2 + 2


def repo_decode(img, num):
    """ 本仓库 ToolUtil.SegmentationPicture 的算法(原样抄过来) """
    if num <= 1:
        return img
    size = (width, height) = img.size
    des = Image.new(img.mode, size)
    rem = height % num
    c = math.floor(height / num)
    block = []
    total_h = 0
    for i in range(num):
        h = c * (i + 1)
        if i == num - 1:
            h += rem
        block.append((total_h, h))
        total_h = h
    h = 0
    for start, end in reversed(block):
        co_h = end - start
        des.paste(img.crop((0, start, width, end)), (0, h, width, h + co_h))
        h += co_h
    return des


def jmcomic_decode(img, num):
    """ 官方 jmcomic JmImageTool.decode_and_save 的算法 """
    if num == 0:
        return img.copy()
    w, h = img.size
    des = Image.new("RGB", (w, h))
    over = h % num
    for i in range(num):
        move = math.floor(h / num)
        y_src = h - (move * (i + 1)) - over
        y_dst = move * i
        if i == 0:
            move += over
        else:
            y_dst += over
        des.paste(img.crop((0, y_src, w, y_src + move)), (0, y_dst, w, y_dst + move))
    return des


def main():
    lines = []
    lines.append("PIL {} / jpg={} webp={} zlib={}".format(
        Image.__version__, features.check("jpg"), features.check("webp"), features.check("zlib")))
    lines.append("Image.OPEN keys: {}".format(sorted(Image.OPEN.keys())))

    if not os.path.isfile(RAW):
        lines.append("缺少真机样本: {}".format(RAW))
        print("\n".join(lines))
        return 1

    with open(RAW, "rb") as f:
        data = f.read()
    lines.append("真机缓存字节数: {} head: {}".format(len(data), data[:16].hex()))

    img = Image.open(BytesIO(data))
    lines.append("桌面 Pillow 解码: format={} size={} mode={}".format(img.format, img.size, img.mode))

    # 真机日志里 epsId/scrambleId 和图片地址(.../photos/1479594/00001.webp)
    eps_id, scramble_id, picture_name = 1479594, 220980, "00001"
    num = get_num(eps_id, scramble_id, picture_name)
    lines.append("epsId={} scrambleId={} pictureName={} -> num={}".format(
        eps_id, scramble_id, picture_name, num))

    img = img.convert("RGB")
    mine = repo_decode(img, num)
    ref = jmcomic_decode(img, num)
    diff = 0
    for a, b in zip(mine.getdata(), ref.getdata()):
        if a != b:
            diff += 1
    lines.append("仓库算法 vs jmcomic 官方算法: 不同像素={}".format(diff))

    img.save(os.path.join(OUT, "page_raw.png"))
    mine.save(os.path.join(OUT, "page_repo_decoded.png"))
    ref.save(os.path.join(OUT, "page_official_decoded.png"))
    lines.append("已写出 page_raw.png / page_repo_decoded.png / page_official_decoded.png")

    # 顺带验证"自逆"这个假设是错的(rem != 0 时二次分割会错位)，
    # 这正是本轮之前那个自检用例没能发现问题原因。
    twice = repo_decode(mine, num)
    over = img.size[1] % num
    lines.append("高度 {} % num {} = rem {} -> 二次分割与一次分割不同像素={}".format(
        img.size[1], num, over,
        sum(1 for a, b in zip(twice.getdata(), mine.getdata()) if a != b)))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
