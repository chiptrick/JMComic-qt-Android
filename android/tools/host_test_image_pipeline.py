# coding:utf-8
"""看图解码链路回归测试(不需要手机/Android SDK，Linux 宿主 offscreen 跑)

覆盖真机报的"看图界面中图片无法正常解密"的三处根因：
  1. ToolUtil.SegmentationPicture / SegmentationPictureToDisk 失败时必须原样返回输入，
     绝不能返回 None(那会让看图界面把 info.data 覆盖成 None，整页图消失)
  2. TaskQImage 的 worker：空数据只能跳过、异常不能打死线程、不能把上一页的图发出去
  3. TaskMulti 在 MultiNum=0(设置被误触) 时也要有 worker，取结果不能永久阻塞

跑法(在 WSL 的构建树里；需要 PySide6 + Pillow，见 android/tools/env.sh 的 JM_WORK/JM_VPY)：
  cd <构建树>/src
  QT_QPA_PLATFORM=offscreen <venv>/bin/python3 android/tools/host_test_image_pipeline.py

1d 段用"真机抓回来的 webp"做真数据闭环，样本不入库(android/build_logs/ 被 gitignore)，
没有样本时该段自动 SKIP；也可以用 JM_REAL_WEBP 指定自己的样本路径。
"""
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="jm_img_pipeline_test_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["JMCOMIC_ANDROID"] = "1"
os.environ["ANDROID_PRIVATE"] = TMP
os.environ["JM_ANDROID_SAVE_DIR"] = os.path.join(TMP, "save")
os.environ["JM_SR_MODELS"] = os.path.join(TMP, "waifu2x-models")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "android"))
try:
    import curl_cffi  # noqa: F401
except Exception:
    sys.path.append(os.path.join(ROOT, "android", "shims"))
# Windows 主机上 setting._xdgDir 会退化成相对目录，切到临时目录里跑，避免写仓库
os.chdir(TMP)

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

app = QApplication([])

from PIL import Image  # noqa: E402
from io import BytesIO  # noqa: E402

from tools import platform_mobile  # noqa: E402

platform_mobile.InitAndroidEnv(app)
assert platform_mobile.IsAndroid(), "测试必须在 Android 模式下跑(TaskMulti 才走线程/clamp)"

from tools.tool import ToolUtil  # noqa: E402
from config.setting import Setting  # noqa: E402
from task.task_multi import TaskMulti  # noqa: E402
from task.task_qimage import TaskQImage, QImageStats  # noqa: E402

FAILS = []
CHECKS = [0]


def check(name, ok, detail=""):
    CHECKS[0] += 1
    if ok:
        print("PASS  {}".format(name))
    else:
        print("FAIL  {}{}".format(name, ("  <- " + str(detail)) if detail else ""))
        FAILS.append(name)
    return ok


def waitUntil(cond, timeout=10.0, step=0.02):
    """ 一边跑事件循环一边等条件成立(worker 通过 Qt 信号把结果投回主线程) """
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(step)
    app.processEvents()
    return cond()


W, H = 64, 240


def makeGradientPng():
    """ 已知渐变的合成 PNG：每行 y 各不相同，方便验证"带子真的搬动了" """
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        for x in range(W):
            px[x, y] = ((x * 4) % 256, y, (x + y) % 256)
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def loadPixels(data):
    with Image.open(BytesIO(data)) as im:
        im.load()
        return im.size, list(im.convert("RGB").getdata())


PNG = makeGradientPng()
ORIG_SIZE, ORIG_PIXELS = loadPixels(PNG)


# --------------------------------------------------------------------------
# 1. 正常路径：与官方算法(jmcomic decode_and_save)逐像素等价，余数 rem != 0 也要过
# --------------------------------------------------------------------------
print("--- 1. SegmentationPicture 正常路径(对齐官方算法) ---")


def officialDecode(img, num):
    """ jmcomic JmImageTool.decode_and_save 的独立实现(参考实现)

    over 归最下面那块；从最下面那块开始往上贴 => 每块的落点会带上 over 的偏移。
    """
    if num <= 1:
        return img.copy()
    w, h = img.size
    out = Image.new("RGB", (w, h))
    over = h % num
    c = h // num
    for i in range(num):
        move = c
        ySrc = h - c * (i + 1) - over
        yDst = c * i
        if i == 0:
            move += over
        else:
            yDst += over
        out.paste(img.crop((0, ySrc, w, ySrc + move)), (0, yDst, w, yDst + move))
    return out


def officialEncode(img, num):
    """ 服务端那种"打乱"：先按 [高块, 常块...] 切，再倒序贴回去(decode 的逆) """
    if num <= 1:
        return img.copy()
    w, h = img.size
    out = Image.new("RGB", (w, h))
    over = h % num
    c = h // num
    pieces = []
    y = 0
    for i in range(num):
        move = c + (over if i == 0 else 0)
        pieces.append((y, y + move))
        y += move
    yDst = 0
    for start, end in reversed(pieces):
        coH = end - start
        out.paste(img.crop((0, start, w, end)), (0, yDst, w, yDst + coH))
        yDst += coH
    return out


num = ToolUtil.GetSegmentationNum(epsId=300000, scramble_id=1, pictureName="1.png")
check("GetSegmentationNum(300000, 1, '1.png') >= 4", num >= 4, "num={}".format(num))

# 真实那页一样的高度关系：2100x3018 + num=12 -> rem=6(不是 0！)
check("真实样本 num 复现(1479594/220980/00001 = 12)",
      ToolUtil.GetSegmentationNum(1479594, 220980, "00001") == 12,
      "num={}".format(ToolUtil.GetSegmentationNum(1479594, 220980, "00001")))

for height, tag in ((240, "rem=0(对合)"), (245, "rem=5(非对合)")):
    img = Image.new("RGB", (W, height))
    px = img.load()
    for y in range(height):
        for x in range(W):
            px[x, y] = ((x * 4) % 256, y % 256, (x + y) % 256)
    buf = BytesIO()
    img.save(buf, "PNG")
    plain = buf.getvalue()
    encImg = officialEncode(img, num)
    buf2 = BytesIO()
    encImg.save(buf2, "PNG")
    enc = buf2.getvalue()

    expect = officialDecode(encImg, num)
    check("[{}] 参考实现往返: decode(encode(x)) == x".format(tag), list(expect.getdata()) == list(img.getdata()))

    out = ToolUtil.SegmentationPicture(enc, 300000, 1, "1.png")
    if not check("[{}] SegmentationPicture 返回非空 bytes".format(tag),
                 isinstance(out, (bytes, bytearray)) and len(out) > 0, "out={!r}".format(type(out))):
        FAILS.append("normal path " + tag)
        continue
    size, pixels = loadPixels(out)
    expSize, expPixels = expect.size, list(expect.getdata())
    check("[{}] 尺寸不变".format(tag), size == (W, height), "size={}".format(size))
    check("[{}] 与官方算法逐像素一致".format(tag), pixels == expPixels)
    check("[{}] 结果与输入不同(带子真的动了)".format(tag), out != enc and pixels != list(encImg.getdata()))

    # 二次还原：rem=0 时是对合(会回到被打乱的输入)，rem!=0 时必须"更差"——
    # 无论哪种，做两次都得不到正确的图，所以任何路径都只能对原始字节还原一次。
    back = ToolUtil.SegmentationPicture(out, 300000, 1, "1.png")
    bsize, bpixels = loadPixels(back)
    if height % num == 0:
        check("[{}] 再还原一次 == 回到被打乱的输入(对合，仍然不是正确的图)".format(tag),
              bsize == (W, height) and bpixels == list(encImg.getdata()))
    else:
        check("[{}] 再还原一次 != 一次结果(非对合，绝不能做两次)".format(tag),
              bsize == (W, height) and bpixels != pixels)

# --------------------------------------------------------------------------
# 1b. Qt 图像栈版(Android 上真正走的那条)：必须和官方算法逐像素一致
# --------------------------------------------------------------------------
print("--- 1b. Qt 版分割还原(xxxQImage/SegmentationPictureQt) ---")
for height, tag in ((240, "rem=0"), (245, "rem=5")):
    img = Image.new("RGB", (W, height))
    px = img.load()
    for y in range(height):
        for x in range(W):
            px[x, y] = ((x * 3) % 256, y % 256, (x * 2 + y) % 256)
    encImg = officialEncode(img, num)
    buf = BytesIO()
    encImg.save(buf, "PNG")
    enc = buf.getvalue()
    expect = officialDecode(encImg, num)

    q = ToolUtil.SegmentationQImage(enc, 300000, 1, "1.png")
    sameQt = q is not None and not q.isNull() and q.width() == W and q.height() == height
    if sameQt:
        diff = 0
        for y in range(height):
            for x in range(W):
                p = q.pixel(x, y)
                e = expect.getpixel((x, y))
                if (p >> 16 & 255, p >> 8 & 255, p & 255) != tuple(e[:3]):
                    diff += 1
        sameQt = diff == 0
    check("[{}] SegmentationQImage == 官方算法".format(tag), sameQt)

    out = ToolUtil.SegmentationPictureQt(enc, 300000, 1, "1.png")
    okBytes = False
    if out:
        size, pixels = loadPixels(out)
        okBytes = size == (W, height) and pixels == list(expect.getdata())
    check("[{}] SegmentationPictureQt(bytes) == 官方算法".format(tag), okBytes)

# 1c. Pillow 解不了图时必须由 Qt 兜底(真机就是 Pillow 没有 webp 解码器)
print("--- 1c. Pillow 失效时的兜底(真机 webp 场景) ---")
import PIL.Image as _PILImage  # noqa: E402

img = Image.new("RGB", (W, 245))
px = img.load()
for y in range(245):
    for x in range(W):
        px[x, y] = ((x * 5) % 256, y % 256, (x + y * 3) % 256)
enc = BytesIO()
officialEncode(img, num).save(enc, "PNG")
enc = enc.getvalue()
expect = officialDecode(Image.open(BytesIO(enc)), num)

_origOpen = _PILImage.open


def _boomOpen(*args, **kwargs):
    raise UnidentifiedImageError("cannot identify image file (simulated Android Pillow)")


from PIL import UnidentifiedImageError  # noqa: E402

_origIsAndroid = platform_mobile.IsAndroid


def qtPixelsEqual(data, expectImg):
    """ 用 Qt 解码并和参考图逐像素比(Pillow 被故意打坏时用) """
    q = ToolUtil.LoadQImage(data)
    if q is None or q.isNull() or (q.width(), q.height()) != expectImg.size:
        return False
    exp = expectImg.convert("RGB")
    for y in range(q.height()):
        for x in range(q.width()):
            p = q.pixel(x, y)
            if (p >> 16 & 255, p >> 8 & 255, p & 255) != exp.getpixel((x, y)):
                return False
    return True


try:
    _PILImage.open = _boomOpen
    # Android 分支：Qt 直接接管，不会去碰 Pillow
    outA = ToolUtil.SegmentationPicture(enc, 300000, 1, "1.png")
    okA = bool(outA) and qtPixelsEqual(outA, expect)
    check("Android 分支: Pillow 挂了也由 Qt 还原出正确图", okA,
          "len={}".format(len(outA) if outA else 0))

    # 桌面分支(强制 IsAndroid=False)：Pillow 抛异常 -> 走 except -> Qt 兜底
    platform_mobile.IsAndroid = lambda: False
    outB = ToolUtil.SegmentationPicture(enc, 300000, 1, "1.png")
    okB = bool(outB) and outB != enc and qtPixelsEqual(outB, expect)
    check("桌面分支: Pillow 抛异常时用 Qt 兜底(不是原样返回打乱的图)", okB,
          "sameAsInput={}".format(outB == enc))

    # 落盘路径同理
    diskPath = os.path.join(TMP, "seg_qt_fallback.png")
    okC = ToolUtil.SegmentationPictureToDisk(enc, 300000, 1, "1.png", diskPath, "png")
    okC = bool(okC) and qtPixelsEqual(open(diskPath, "rb").read(), expect)
    check("桌面分支: ToDisk 用 Qt 兜底后落盘的是还原图", okC)
finally:
    _PILImage.open = _origOpen
    platform_mobile.IsAndroid = _origIsAndroid

# --------------------------------------------------------------------------
# 1d. 真机抓回来的真 webp：QImage 域还原必须和官方算法逐像素一致(真数据闭环)
#     样本 = /data/.../files/cache/jmcomic-qt/book/1479594/1/1.webp(真机自己下载的)
#     样本带用户内容，不入库；可用 JM_REAL_WEBP 指向本地副本
# --------------------------------------------------------------------------
print("--- 1d. 真机样本(webp) ---")
realPath = os.environ.get("JM_REAL_WEBP",
                          os.path.join(ROOT, "android", "build_logs", "device_cache_1479594_1_1.jpg"))
if not os.path.isfile(realPath):
    print("SKIP  真机样本不存在: {} (设 JM_REAL_WEBP 指向本地副本可启用)".format(realPath))
else:
    with open(realPath, "rb") as f:
        raw = f.read()
    check("真机样本确实是 webp(RIFF....WEBP)",
          raw[:4] == b"RIFF" and raw[8:12] == b"WEBP", raw[:12].hex())
    check("ImageFormatFromData 认出 webp", ToolUtil.ImageFormatFromData(raw) == "WEBP",
          ToolUtil.ImageFormatFromData(raw))
    sz = ToolUtil.GetPictureSize(raw)
    check("GetPictureSize 能读出 webp 尺寸(Android 的 Pillow 读不出 -> 以前 mat 被兜底成 jpg)",
          (sz[0], sz[1], sz[2]) == (2100, 3018, "webp"), str(sz))
    numReal = ToolUtil.GetSegmentationNum(1479594, 220980, "00001")
    check("真机样本 num == 12", numReal == 12, "num={}".format(numReal))

    with Image.open(BytesIO(raw)) as _im:
        expect = officialDecode(_im.convert("RGB"), numReal)
    qQt = ToolUtil.SegmentationQImage(raw, 1479594, 220980, "00001")
    gotBytes, usedFmt = ToolUtil._SaveQImageToBytes(qQt, "PNG")
    got = Image.open(BytesIO(gotBytes)).convert("RGB")
    check("真机样本: Qt 还原(看图线程那条) == 官方算法(逐像素 {})".format(expect.size),
          got.size == expect.size and got.tobytes() == expect.tobytes(),
          "size={} vs {}".format(got.size, expect.size))

    # bytes 路径：webp 重新编码有损，所以只要求"和官方结果非常接近 + 明显不是原图"
    outBytes = ToolUtil.SegmentationPicture(raw, 1479594, 220980, "00001")
    check("真机样本: bytes 路径保持 webp 输出", ToolUtil.ImageFormatFromData(outBytes) == "WEBP",
          ToolUtil.ImageFormatFromData(outBytes))
    got2 = Image.open(BytesIO(outBytes)).convert("RGB")
    from PIL import ImageChops, ImageStat  # noqa: E402
    meanErr = sum(ImageStat.Stat(ImageChops.difference(got2, expect)).mean) / 3.0
    meanRawErr = sum(ImageStat.Stat(ImageChops.difference(
        Image.open(BytesIO(raw)).convert("RGB"), expect)).mean) / 3.0
    check("真机样本: bytes 路径结果≈官方算法(有损重编码, 平均差 {:.1f}) 且远好于未还原({:.1f})".format(
        meanErr, meanRawErr), meanErr < 6.0 and meanRawErr > 20.0)

# --------------------------------------------------------------------------
# 2. 失败路径必须原样返回输入，绝不能是 None
# --------------------------------------------------------------------------
print("--- 2. 失败路径返回原始字节 ---")
BAD_PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8
FAIL_CASES = [
    ("空 bytes", b"", 300000, 1, "1.png"),
    ("随机垃圾", os.urandom(4096), 300000, 1, "1.png"),
    ("截断的 PNG", PNG[:max(1, len(PNG) // 3)], 300000, 1, "1.png"),
    ("scramble_id=''", BAD_PNG, 300000, "", "1.png"),
    ("scramble_id=None", BAD_PNG, 300000, None, "1.png"),
    ("scramble_id 非数字", BAD_PNG, 300000, "abc", "1.png"),
    ("epsId=None + scramble_id=None", BAD_PNG, None, None, None),
]
for name, data, epsId, scrambleId, picName in FAIL_CASES:
    try:
        r = ToolUtil.SegmentationPicture(data, epsId, scrambleId, picName)
        check("失败路径原样返回(非 None): {}".format(name), r is not None and r == data,
              "type={} len={}".format(type(r).__name__, len(r) if r is not None else -1))
    except Exception as es:
        check("失败路径原样返回(非 None): {}".format(name), False, "抛异常了: {!r}".format(es))

for sid in ["", None, "abc", "-", 0, 1.5]:
    try:
        ToolUtil.GetSegmentationNum(300000, sid, "1.png")
        ok, err = True, ""
    except Exception as es:
        ok, err = False, repr(es)
    check("GetSegmentationNum 不因 scramble_id={!r} 抛异常".format(sid), ok, err)

# --------------------------------------------------------------------------
# 3. SegmentationPictureToDisk：失败返回 False，但原始字节仍然落盘
# --------------------------------------------------------------------------
print("--- 3. SegmentationPictureToDisk 失败也要落盘 ---")
garbage = os.urandom(2048)
segPath = os.path.join(TMP, "seg_garbage.png")
r = ToolUtil.SegmentationPictureToDisk(garbage, 300000, 1, "1.png", segPath, "png")
check("垃圾数据返回 False", r is False, "r={!r}".format(r))
check("垃圾数据仍然写出非空文件", os.path.exists(segPath) and os.path.getsize(segPath) > 0,
      "path={} size={}".format(segPath, os.path.getsize(segPath) if os.path.exists(segPath) else -1))

okPath = os.path.join(TMP, "seg_noseg.png")
r2 = ToolUtil.SegmentationPictureToDisk(PNG, 300000, 999999999, "1.png", okPath, "png")
check("num<=1 正常落盘并返回 True", r2 is True and os.path.exists(okPath) and os.path.getsize(okPath) > 0,
      "r={!r}".format(r2))

# --------------------------------------------------------------------------
# 4. TaskQImage worker：空数据跳过、异常不打死线程、不发上一页的图
# --------------------------------------------------------------------------
print("--- 4. TaskQImage worker ---")
received = {}


def recv(img, param):
    received[param] = img


tq = TaskQImage()
tq.AddQImageTask(b"", 1.0, 0, 0, 0, None, recv, 9001)
tq.AddQImageTask(PNG, 1.0, 0, 0, 0, None, recv, 9002)
got = waitUntil(lambda: 9002 in received, timeout=15.0)
check("空数据之后 worker 还活着，有效任务仍能回调", got,
      "received keys={}".format(sorted(received.keys())))
check("空数据任务没有回调(只是跳过，不是发空图)", 9001 not in received)
img = received.get(9002)
check("回调拿到有效 QImage", isinstance(img, QImage) and not img.isNull()
      and (img.width(), img.height()) == (W, H), "img={!r}".format(img))

st = QImageStats()
check("Stats 记录了空数据", st.get("null", 0) >= 1 and st.get("task", 0) >= 2, "stats={}".format(st))

# 反例：两条还原路径都失败时，绝不能把上一张(9002)的图当成本次结果发出去
tm = TaskMulti()
origGet = tm.GetJmPicResultsResult
origSegQ = ToolUtil.SegmentationQImage
origSegQt = ToolUtil.SegmentationPictureQt


def boom(*args, **kwargs):
    raise RuntimeError("simulated descramble failure")


tm.GetJmPicResultsResult = boom
ToolUtil.SegmentationQImage = lambda *a, **k: None      # Qt 那条也废掉
ToolUtil.SegmentationPictureQt = lambda *a, **k: None
try:
    tq.AddQImageTask(PNG, 1.0, 0, 0, 0, (300000, 1, "1.png"), recv, 9003)
    tq.AddQImageTask(PNG, 1.0, 0, 0, 0, None, recv, 9004)
    got2 = waitUntil(lambda: 9004 in received, timeout=15.0)
finally:
    tm.GetJmPicResultsResult = origGet
    ToolUtil.SegmentationQImage = origSegQ
    ToolUtil.SegmentationPictureQt = origSegQt

check("异常任务之后的下一张仍能解码(线程没死)",
      got2 and isinstance(received.get(9004), QImage) and not received[9004].isNull(),
      "received keys={}".format(sorted(received.keys())))
check("异常任务没有回调(NOT 上一页的图)", 9003 not in received,
      "9003 -> {!r}".format(received.get(9003)))
check("异常任务计入 fail", QImageStats().get("fail", 0) >= 1, "stats={}".format(QImageStats()))

# --------------------------------------------------------------------------
# 5. TaskMulti：MultiNum=0 也要有 worker，取结果不能永久阻塞
# --------------------------------------------------------------------------
print("--- 5. TaskMulti MultiNum=0 ---")
Setting.MultiNum.InitValue("0", "MultiNum")
check("Setting.MultiNum 已被强制为 0", Setting.MultiNum.value == 0,
      "value={!r}".format(Setting.MultiNum.value))

tm.Start()
check("MultiNum=0 时 Start() 仍然至少 1 个 worker",
      len(tm.queueList) >= 1 and len(tm.threadList) >= 1 and tm.startNum >= 1,
      "queues={} threads={} startNum={}".format(len(tm.queueList), len(tm.threadList), tm.startNum))
check("Android 上 worker 数被封顶(<=8)", tm.startNum <= 8, "startNum={}".format(tm.startNum))

nQueues = len(tm.queueList)
nThreads = len(tm.threadList)
tm.Start()
check("Start() 幂等(第二次不会再加一批 worker)",
      len(tm.queueList) == nQueues and len(tm.threadList) == nThreads
      and tm._inQueue.qsize() == nQueues,
      "queues={} threads={} slots={}".format(len(tm.queueList), len(tm.threadList), tm._inQueue.qsize()))

t0 = time.time()
res = tm.GetJmPicResultsResult(PNG, 300000, 1, "1.png")
elapsed = time.time() - t0
check("GetJmPicResultsResult 有结果且不阻塞(<15s)", res is not None and elapsed < 15.0,
      "elapsed={:.2f}s res={!r}".format(elapsed, type(res).__name__))
if isinstance(res, (bytes, bytearray)) and res:
    try:
        rsize, rpixels = loadPixels(res)
        check("worker 线程真的做了分割(像素 == 带子搬移结果)",
              rsize == ORIG_SIZE and rpixels != ORIG_PIXELS)
    except Exception as es:
        check("worker 线程真的做了分割", False, repr(es))
check("调用结束后 worker 槽位已归还(队列平衡)", tm._inQueue.qsize() == nQueues,
      "slots={} expect={}".format(tm._inQueue.qsize(), nQueues))

# --------------------------------------------------------------------------
print()
if FAILS:
    print("FAILED {} / {} 项: {}".format(len(FAILS), CHECKS[0], "; ".join(FAILS)))
    print("FAIL")
    sys.exit(1)
print("ALL {} IMAGE PIPELINE CHECKS PASSED".format(CHECKS[0]))
print("PASS")
sys.exit(0)
