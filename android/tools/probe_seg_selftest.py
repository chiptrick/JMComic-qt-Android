# -*- coding: utf-8 -*-
""" 调自检里"逐像素"比对为什么全不同(宿主) """
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="jm_segdbg_")
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
os.chdir(TMP)

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

app = QApplication([])
from tools import platform_mobile  # noqa: E402

platform_mobile.InitAndroidEnv(app)
from tools import mobile_ui  # noqa: E402
from tools.tool import ToolUtil  # noqa: E402

num = 8
src = mobile_ui._SegMakeTestImage(num, 5)
print("src format", src.format(), "size", src.size(), "formatname", src.format().name if hasattr(src.format(), "name") else src.format())
for (x, y) in [(0, 0), (0, 1), (0, 100), (10, 0), (23, 260)]:
    print("  src pixel({},{}) = {:08x}".format(x, y, src.pixel(x, y) & 0xffffffff))

enc = mobile_ui._SegOfficialQt(src, num)
print("enc format", enc.format().name if hasattr(enc.format(), "name") else enc.format())
for (x, y) in [(0, 0), (0, 1), (0, 260)]:
    print("  enc pixel({},{}) = {:08x}".format(x, y, enc.pixel(x, y) & 0xffffffff))

ba = QByteArray()
buf = QBuffer(ba)
buf.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.WriteOnly)
enc.save(buf, "PNG")
encBytes = bytes(ba)
buf.close()
print("enc png bytes", len(encBytes))

fixed = ToolUtil.SegmentationPicture(encBytes, 300000, 1, "1.png")
print("fixed len", len(fixed) if fixed else 0)
qFix = ToolUtil.LoadQImage(fixed)
print("qFix format", qFix.format().name if hasattr(qFix.format(), "name") else qFix.format(), "size", qFix.size())
for (x, y) in [(0, 0), (0, 1), (0, 260)]:
    print("  qFix pixel({},{}) = {:08x}".format(x, y, qFix.pixel(x, y) & 0xffffffff))

same, diff = mobile_ui._SegSamePixels(src, qFix)
print("_SegSamePixels(src, qFix) ->", same, diff)
a = src.convertToFormat(QImage.Format.Format_ARGB32)
b = qFix.convertToFormat(QImage.Format.Format_ARGB32)
print("a format", a.format().name, "b format", b.format().name)
print("a pixel00 {:08x} b pixel00 {:08x}".format(a.pixel(0, 0) & 0xffffffff, b.pixel(0, 0) & 0xffffffff))
print("bits equal", bytes(a.constBits()) == bytes(b.constBits()))
print("a bytes head", bytes(a.constBits())[:16].hex())
print("b bytes head", bytes(b.constBits())[:16].hex())
print("a bytesPerLine", a.bytesPerLine(), "b", b.bytesPerLine(), "len", len(bytes(a.constBits())), len(bytes(b.constBits())))
