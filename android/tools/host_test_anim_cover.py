# coding:utf-8
"""换页动画/封面解码 回归测试（不需要手机，宿主 offscreen 跑）

覆盖 2026-10 动画性能改造的三条不变量：
  1. AnimationStackWidget 走"快照 + 接缝窄带"时，动画结束后必须真的切到目标页，
     且覆盖层要收起来（不能留在屏幕上挡住交互）
  2. 每帧脏区必须只有接缝那一条：两帧揭示区是嵌套的，取并集会退化成整页
  3. 封面按显示尺寸解码：DPR 正确、尺寸不超过目标尺寸的 1.2 倍

跑法（WSL 的构建树里，需要 PySide6）：
  cd <构建树>/src
  QT_QPA_PLATFORM=offscreen <venv>/bin/python3 android/tools/host_test_anim_cover.py
"""
import os
import sys
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QStackedWidget, QVBoxLayout, QWidget

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, _ROOT)

Failures = []


def Check(ok, name):
    print(("  ok  " if ok else "  FAIL ") + name)
    if not ok:
        Failures.append(name)


def MakePage(text, color):
    page = QWidget()
    page.setWindowTitle(text)
    layout = QVBoxLayout(page)
    label = QLabel(text)
    label.setStyleSheet("font-size: 40px; color: %s;" % color)
    layout.addWidget(label)
    page.SwitchCurrent = lambda **kwargs: None
    return page


class StackHarness(object):
    """把 AnimationStackWidget 放进一个真窗口里跑，尽量贴近真机布局"""

    def __init__(self, app):
        # 这里测的是 raster 覆盖层的几何/绘制不变量（窄带、缓存、延后切页），
        # 宿主 offscreen 下没有 RHI，GPU 覆盖层只会让断言跑空，所以显式关掉。
        from component.widget import animation_stack_widget as _asw
        _asw.UseGpuCover = False
        from component.widget.animation_stack_widget import AnimationStackWidget
        self.app = app
        self.win = QWidget()
        self.win.resize(384, 700)
        self.stack = AnimationStackWidget(self.win)
        self.pages = [MakePage("A", "red"), MakePage("B", "green"), MakePage("C", "blue")]
        for page in self.pages:
            self.stack.addWidget(page)
        self.stack.subStackList = [0, 1, 2]
        # 不给布局，显式设定尺寸（模拟竖屏下的真实页面区域）
        self.stack.setGeometry(0, 0, 384, 700)
        self.stack.setCurrentIndex(0)
        self.win.show()
        self.Pump(50)

    def Pump(self, ms):
        end = time.time() + ms / 1000.0
        while time.time() < end:
            self.app.processEvents()
            time.sleep(0.005)
        return


def TestSwitch(harness):
    print("\n[1] 换页：动画结束必须真的切页，覆盖层必须收起")
    stack = harness.stack
    harness.Pump(30)
    stack.SwitchWidgetByIndex(1, refresh=False)
    harness.Pump(600)
    Check(stack.currentIndex() == 1, "切到目标页 index=1 (实际 {})".format(stack.currentIndex()))
    Check(not stack.cover.isVisible(), "覆盖层已隐藏")
    Check(stack.widget(1).isVisible(), "目标页已显示")
    return


def TestBand(harness):
    print("\n[2] 窄带：相邻两帧的脏区只能是一条竖带")
    cover = harness.stack.cover
    cover.resize(384, 700)
    # 模拟"揭示区嵌套"的两帧：脏区宽度必须等于增量，而不是已揭示的总宽度
    band1 = cover._BandRect(0, 48)
    band2 = cover._BandRect(48, 96)
    Check(band1.width() == 48 and band2.width() == 48,
          "每帧脏区宽度=增量 48px (实际 {} / {})".format(band1.width(), band2.width()))
    Check(band1.height() == 700, "脏区高度=整页高")
    whole = cover._BandRect(0, 384)
    Check(whole.width() == 384, "首帧(0->整宽)才是整页宽")
    return


def TestCoverPaint(harness):
    print("\n[3] 覆盖层绘制：只画快照，不碰控件树")
    cover = harness.stack.cover
    prev = QPixmap(384, 700)
    prev.fill(QColor(10, 10, 10))
    next_ = QPixmap(384, 700)
    next_.fill(QColor(200, 200, 200))
    from component.widget.animation_stack_widget import AnimationEnum
    cover.Begin(prev, next_, AnimationEnum.LeftToRight)
    harness.Pump(20)
    cover.SetReveal(200)      # 前进方向：新页从右边缘往左揭示
    harness.Pump(20)
    img = cover.grab().toImage()
    right = img.pixelColor(360, 350)
    left = img.pixelColor(20, 350)
    Check(abs(right.red() - 200) <= 8, "已揭示区(右侧)画的是新页 (r={})".format(right.red()))
    Check(abs(left.red() - 10) <= 8, "未揭示区(左侧)画的是旧页 (r={})".format(left.red()))
    cover.End()
    return


def TestDecode():
    print("\n[4] 封面解码：按显示尺寸解码，DPR 正确")
    from component.widget.comic_item_widget import DecodeCoverPixmap
    img = QImage(800, 1100, QImage.Format_RGB32)
    img.fill(QColor(120, 60, 30))
    paint = QPainter(img)
    paint.fillRect(0, 0, 400, 550, QColor(30, 120, 60))
    paint.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPEG", 85)
    buf.close()
    raw = bytes(data)

    pixmap = DecodeCoverPixmap(raw, 151, 205, 3.75)
    Check(not pixmap.isNull(), "解码成功")
    Check(abs(pixmap.devicePixelRatio() - 3.75) < 0.01,
          "DPR={:.2f}".format(pixmap.devicePixelRatio()))
    w, h = pixmap.width(), pixmap.height()
    Check(w <= 151 * 3.75 * 1.2 and h <= 205 * 3.75 * 1.2,
          "解码尺寸 {}x{} 不超过目标的 1.2 倍".format(w, h))
    Check(w > 0 and h > 0 and abs(w / float(h) - 800 / 1100.0) < 0.05,
          "保持原始宽高比 ({:.3f})".format(w / float(h) if h else 0))
    Check(DecodeCoverPixmap(b"", 151, 205, 3.75).isNull(), "空数据返回空 pixmap")
    Check(DecodeCoverPixmap(b"not an image", 151, 205, 3.75).isNull(), "坏数据不抛异常")
    return


def TestCache(harness):
    print("\n[5] 快照缓存：同一页重复取快照必须复用同一张 pixmap")
    stack = harness.stack
    harness.Pump(30)
    page = stack.widget(2)
    first = stack._RenderPage(page, useCache=True)
    second = stack._RenderPage(page, useCache=True)
    Check(first is not None and first is second, "第二次命中缓存(同一对象)")
    stack.InvalidatePage(page)
    third = stack._RenderPage(page, useCache=True)
    Check(third is not None and third is not first, "InvalidatePage 后会重新渲染")
    return


def TestDeferredSwitchCurrent(harness):
    print("\n[6] SwitchCurrent 必须等动画结束(最后一帧之后)才执行")
    stack = harness.stack
    calls = []

    def Record(**kwargs):
        calls.append(("call", stack.currentIndex()))

    page = stack.widget(0)
    page.SwitchCurrent = Record
    stack.setCurrentIndex(2)
    stack.SwitchWidgetByIndex(0, refresh=False)
    Check(not calls, "动画进行中还没调用 SwitchCurrent")
    harness.Pump(700)
    Check(bool(calls), "动画结束后调用了 SwitchCurrent")
    Check(stack.currentIndex() == 0, "当前页已切到目标页")
    return


def TestSnapshotSize(harness):
    print("\n[7] 快照尺寸必须等于栈尺寸（隐藏页没被 QStackedLayout 排过几何）")
    stack = harness.stack
    page = stack.widget(2)
    # 模拟"设计尺寸"：隐藏页停在 880x805，而栈只有 384x700
    page.resize(880, 805)
    harness.Pump(10)
    pix = stack._RenderPage(page, useCache=False)
    Check(page.size() == stack.size(),
          "拍快照前已把页面拉到栈尺寸 (页面 {}x{} / 栈 {}x{}缺)".format(
              page.width(), page.height(), stack.width(), stack.height())
          if page.size() != stack.size() else "拍快照前已把页面拉到栈尺寸")
    Check(pix is not None, "快照非空")
    if pix is not None:
        dpr = pix.devicePixelRatio()
        Check(abs(pix.width() - stack.width() * dpr) <= 2,
              "快照宽度 = 栈宽 × dpr ({} vs {})".format(pix.width(), stack.width() * dpr))
    # 拍完必须恢复成隐藏，不能把隐藏页留在"逻辑显示"状态
    Check(not page.isVisible(), "拍完快照后目标页仍是隐藏的")
    return


def main():
    app = QApplication(sys.argv)
    harness = StackHarness(app)
    TestSwitch(harness)
    TestBand(harness)
    TestCoverPaint(harness)
    TestDecode()
    TestCache(harness)
    TestDeferredSwitchCurrent(harness)
    TestSnapshotSize(harness)
    print("")
    if Failures:
        print("FAIL: {} 项没通过".format(len(Failures)))
        for item in Failures:
            print("  - {}".format(item))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    code = main()
    # PySide6 在解释器 finalize 阶段会因为 C++ 侧对象已析构而报
    # "bool_dealloc ... refcount error"，把已经 ALL PASS 的退出码盖成非 0。
    # 跑完就硬退出，保证退出码可信（只在测试进程里这么干）。
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
