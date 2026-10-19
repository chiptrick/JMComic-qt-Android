# coding:utf-8
""" 宿主自检：看图区触控状态机(_ReaderTouch，纯 QTouchEvent、零合成鼠标)

为什么值得单独测：真机上双指手势没法用 adb 模拟(`input` 只有单指，`sendevent`
要 root)，而这里的坑全在"多条触摸序列 + 触点增删"的状态迁移上：

  * Qt 的多点触摸是**每个触点一个目标控件**的：滚动模式下相邻页是嵌在视口上的
    真实子窗口，两根手指常常落在两条**独立序列**里，每条只有一个点 ——
    只看"本次事件里有几个点"永远等不到两个点
  * 1 指(拖动/点按) -> 2 指(缩放) -> 抬手，每次切换都要保证
    "不误翻页、不误滚动、缩放只结算一次"
  * 缩放之后剩下的那根手指必须被吞掉，否则松手会变成点按翻页

这里用假的事件/触点把每条路径跑一遍。新实现把触控直接映射到看图控件自己的
入口(ScrollValue/ScrollLastPage/ScrollNextPage/ShowAndCloseTool/ScalePicture2)，
**不许再出现任何合成的 QMouseEvent** —— 每个用例都顺手断言这一点。

用法：python3 android/tools/host_test_pinch.py
"""
import logging
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))


# ---------------------------------------------------------------------------
# 桩：只需满足 mobile_ui_reader 的导入与调用面（宿主没有 PySide6）
# ---------------------------------------------------------------------------

class _Any:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _Call()


class _Call:
    def __init__(self, value=None):
        self.value = value

    def __call__(self, *args, **kwargs):
        return _Call()


def _MakeModule(name, attrs):
    module = types.ModuleType(name)
    for attr in attrs:
        setattr(module, attr, type(attr, (_Any,), {}))
    sys.modules[name] = module
    return module


class _EventTypes:
    TouchBegin = "TouchBegin"
    TouchUpdate = "TouchUpdate"
    TouchEnd = "TouchEnd"
    TouchCancel = "TouchCancel"


class _Modifier:
    NoModifier = "none"


class _Attr:
    WA_AcceptTouchEvents = "touch"


class _State:
    Pressed = "pressed"
    Updated = "updated"
    Released = "released"


class QEventStub(_Any):
    Type = _EventTypes


class QPointStub:
    def __init__(self, x=0, y=0):
        # 和真 QPoint 一样：x()/y() 是方法。曾经写成 self.x = int(x)，
        # 实例属性把方法盖住，生产代码里的 local.x() 全部抛
        # TypeError('int' object is not callable) 又被 _Tap 的 except 吞掉，
        # 表现就是"点按被识别成点按、但三个区的动作一个都不触发"
        self._x = int(x)
        self._y = int(y)

    def x(self):
        return self._x

    def y(self):
        return self._y

    def __repr__(self):
        return "QPoint({}, {})".format(self._x, self._y)


class QPointFStub:
    def __init__(self, x=0.0, y=0.0):
        if isinstance(x, QPointFStub):
            self._x, self._y = x._x, x._y
            return
        self._x = float(x)
        self._y = float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y

    def __sub__(self, other):
        return QPointFStub(self._x - other._x, self._y - other._y)

    def manhattanLength(self):
        return abs(self._x) + abs(self._y)

    def __repr__(self):
        return "QPointF({:.0f},{:.0f})".format(self._x, self._y)


class QApplicationStub:
    """ 记录 sendEvent 调用 —— 新实现一次都不许有 """
    events = []

    @staticmethod
    def sendEvent(target, event):
        QApplicationStub.events.append(event)

    @staticmethod
    def widgetAt(point):
        return None

    @staticmethod
    def doubleClickInterval():
        return 400


class QTimerStub:
    """ singleShot 立即执行：缩放结算是延后一拍的，这里同步跑 """

    @staticmethod
    def singleShot(ms, fn):
        fn()


def _InstallStubs():
    core = _MakeModule("PySide6.QtCore", [])
    core.QEvent = QEventStub
    core.QObject = type("QObject", (_Any,), {})
    core.QPoint = QPointStub
    core.QPointF = QPointFStub
    core.Qt = type("Qt", (_Any,), {"MouseButton": _Any,
                                   "KeyboardModifier": _Modifier,
                                   "WidgetAttribute": _Attr})
    core.QTimer = QTimerStub
    sys.modules["PySide6.QtCore"] = core

    gui = _MakeModule("PySide6.QtGui", [])
    gui.QEventPoint = type("QEventPoint", (_Any,), {"State": _State})
    sys.modules["PySide6.QtGui"] = gui

    widgets = _MakeModule("PySide6.QtWidgets", [])
    widgets.QApplication = QApplicationStub
    sys.modules["PySide6.QtWidgets"] = widgets
    sys.modules["PySide6"] = _MakeModule("PySide6", [])

    base = _MakeModule("tools.mobile_ui_base", [])
    base.TouchSlopPx = 10
    sys.modules["tools.mobile_ui_base"] = base

    ui = _MakeModule("tools.mobile_ui", [])
    ui._readerDrag = None
    ui._readerPinch = None
    sys.modules["tools.mobile_ui"] = ui

    # _Scroll 里 from view.read.read_enum import ReadMode(调用时才导入)
    class ReadModeStub:
        RightLeftScroll2 = "RightLeftScroll2"

        @staticmethod
        def isUpDown(mode):
            return mode in ("UpDown", "UpDownScroll")

        @staticmethod
        def isScroll(mode):
            return mode in ("UpDownScroll", "LeftRightScroll", "RightLeftScroll2")

    _MakeModule("view", [])
    _MakeModule("view.read", [])
    enumMod = _MakeModule("view.read.read_enum", [])
    enumMod.ReadMode = ReadModeStub


_InstallStubs()

# Log.Warn/Error 带 exc_info=True，宿主上会一直打印 "NoneType: None"，这里关掉
logging.disable(logging.CRITICAL)

import tools.mobile_ui_reader as Reader  # noqa: E402
from PySide6.QtCore import QEvent, QPointF  # noqa: E402


# ---------------------------------------------------------------------------
# 假的事件 / 控件
# ---------------------------------------------------------------------------

class Point:
    def __init__(self, pid, x, y, state=None):
        self._id = pid
        self._x = float(x)
        self._y = float(y)
        self._state = state or _State.Pressed

    def id(self):
        return self._id

    def state(self):
        return self._state

    def position(self):
        return QPointF(self._x, self._y)

    def globalPosition(self):
        return QPointF(self._x, self._y)


class Event:
    def __init__(self, etype, points):
        self._type = etype
        self._points = points

    def type(self):
        return self._type

    def points(self):
        return self._points


class FakeScrollBar:
    def __init__(self, maximum=10000):
        self._v = 0
        self._max = maximum
        self.values = []

    def scrollValue(self, v):
        self.values.append(int(v))
        self._v = max(0, min(self._max, self._v + int(v)))

    def value(self):
        return self._v

    def maximum(self):
        return self._max


class FakeTool:
    def __init__(self):
        self.applied = []
        self.stripModel = "UpDown"
        self.turned = 0
        self.next = 0
        self.last = 0

    def ScalePicture2(self, percent):
        self.applied.append(percent)

    def CloseScrollAndTurn(self):
        self.turned += 1

    def NextPage(self):
        self.next += 1

    def LastPage(self):
        self.last += 1


class FakeFrame:
    def __init__(self):
        self.scaleCnt = 0
        self.helpLabel = types.SimpleNamespace(isHidden=lambda: True, hide=lambda: None)


class FakeReadImg:
    def __init__(self):
        self.toolShown = 0

    def ShowAndCloseTool(self):
        self.toolShown += 1


class FakeView:
    def __init__(self, mode="UpDownScroll"):
        self._jmPinchPreview = False
        self.scales = []
        self.resets = 0
        self.zoom = 1.0
        self.frame = FakeFrame()
        self.qtTool = FakeTool()
        self.readImg = FakeReadImg()
        self.vScrollBar = FakeScrollBar()
        self.hScrollBar = FakeScrollBar()
        self.initReadMode = mode
        self.halfScrolls = []

    @property
    def scaleCnt(self):
        # 和真控件一样：scaleCnt 落在 frame 上
        return self.frame.scaleCnt

    def scale(self, sx, sy):
        self.scales.append(round(sx, 4))
        self.zoom *= sx

    def resetTransform(self):
        self.resets += 1
        self.zoom = 1.0

    def mapFromGlobal(self, point):
        return point

    def width(self):
        return 400

    def height(self):
        return 800

    def ScrollValue(self, v):
        self.halfScrolls.append(int(v))

    def ScrollLastPage(self):
        self.qtTool.last += 1

    def ScrollNextPage(self):
        self.qtTool.next += 1


class FakeReadView:
    def __init__(self):
        self.frame = FakeFrame()
        self.qtTool = FakeTool()
        self.qtTool.stripModel = "UpDown"


Failures = []


def Check(ok, name):
    print("  {} {}".format("OK  " if ok else "FAIL", name))
    if not ok:
        Failures.append(name)


def NewTouch(mode="UpDownScroll"):
    QApplicationStub.events = []
    readView = FakeReadView()
    view = FakeView(mode)
    readView.frame = view.frame          # scaleCnt 共享同一份
    readView.qtTool = view.qtTool
    touch = Reader._ReaderTouch(view, readView, view)
    return touch, view, readView


def NoMouse(name):
    Check(QApplicationStub.events == [],
          "{}: 没有任何合成鼠标事件".format(name))


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------

def TestTap():
    print("\n[1] 单指点按：三分区动作(纯触控，不合成鼠标)")
    # 左上 = 菜单开关
    touch, view, _ = NewTouch()
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 100, 100)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 100, 100, _State.Released)]))
    Check(view.readImg.toolShown == 1, "左上点按 -> 弹/收工具菜单")
    Check(view.qtTool.next == 0 and view.qtTool.last == 0, "左上点按不翻页")
    NoMouse("左上点按")

    # 左下 = 上一页(未放大)
    touch, view, _ = NewTouch()
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 100, 700)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 100, 700, _State.Released)]))
    Check(view.qtTool.last == 1 and view.qtTool.next == 0, "左下点按 -> 上一页")

    # 右下 = 下一页(未放大)
    touch, view, _ = NewTouch()
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 350, 700)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 350, 700, _State.Released)]))
    Check(view.qtTool.next == 1 and view.qtTool.last == 0, "右下点按 -> 下一页")

    # 中上/中下 = 半页滚动
    touch, view, _ = NewTouch()
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 200, 100)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 200, 100, _State.Released)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 200, 700)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 200, 700, _State.Released)]))
    Check(view.halfScrolls == [-400, 400], "中上/中下点按 -> 半页滚动({})".format(view.halfScrolls))
    NoMouse("半页点按")

    # 放大后：下边缘不翻页(但菜单照旧)
    touch, view, _ = NewTouch()
    view.frame.scaleCnt = 5
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 350, 700)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 350, 700, _State.Released)]))
    Check(view.qtTool.next == 0, "放大后右下点按不翻页")
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 350, 100)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 350, 100, _State.Released)]))
    Check(view.readImg.toolShown == 1, "放大后右上点按仍能弹菜单")

    # 小位移(阈值内)仍然是点按
    touch, view, _ = NewTouch()
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 100, 100)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(1, 103, 104, _State.Updated)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 103, 104, _State.Released)]))
    Check(view.readImg.toolShown == 1, "3px 漂移仍算点按")
    NoMouse("漂移点按")


def TestDrag():
    print("\n[2] 单指拖动：滚动模式 1:1 跟手(ScrollValue，不合成鼠标)")
    touch, view, _ = NewTouch("UpDownScroll")
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 200, 700)]))
    for y in (650, 600, 550, 500):
        touch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(1, 200, y, _State.Updated)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 200, 500, _State.Released)]))
    Check(touch.Drags == 1, "位移超阈值判定为拖动")
    Check(sum(view.vScrollBar.values) == 200, "划 200px 滚 200px({})".format(view.vScrollBar.values))
    Check(view.qtTool.next == 0 and view.qtTool.last == 0, "拖动不翻页")
    Check(view.readImg.toolShown == 0, "拖动不弹菜单")
    NoMouse("拖动滚动")


def TestPageFlip():
    print("\n[3] 单页模式：滑到边界翻页(和滚轮一致)")
    touch, view, _ = NewTouch("UpDown")
    view.vScrollBar._v = view.vScrollBar.maximum()   # 停在页尾
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 200, 700)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(1, 200, 650, _State.Updated)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 200, 650, _State.Released)]))
    Check(view.qtTool.next == 1, "页尾继续上滑 -> 下一页")

    touch, view, _ = NewTouch("UpDown")
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 200, 100)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(1, 200, 150, _State.Updated)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 200, 150, _State.Released)]))
    Check(view.qtTool.last == 1, "页首继续下滑 -> 上一页")
    NoMouse("边界翻页")

    # 放大后：拖动是平移，不许翻页
    touch, view, _ = NewTouch("UpDown")
    view.frame.scaleCnt = 5
    view.vScrollBar._v = view.vScrollBar.maximum()
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 200, 700)]))
    for y in (650, 600):
        touch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(1, 200, y, _State.Updated)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 200, 600, _State.Released)]))
    Check(view.qtTool.next == 0 and view.qtTool.last == 0, "放大后拖动只平移不翻页")
    Check(len(view.vScrollBar.values) + len(view.hScrollBar.values) > 0, "放大后拖动有平移")


def TestPinchOneSequence():
    print("\n[4] 双指(同一条序列)：进缩放 -> 张开 -> 一指抬起结算")
    touch, view, readView = NewTouch()
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 400, 1000)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchUpdate,
                                  [Point(1, 400, 1000, _State.Updated),
                                   Point(2, 800, 1000, _State.Pressed)]))
    Check(touch.Pinches == 1, "进入缩放")
    Check(touch.Drags == 0, "1->2 指转换不算拖动")
    # 张开：400,800 -> 200,1000（距离 400 -> 800，比例 2.0）
    touch.eventFilter(None, Event(QEvent.Type.TouchUpdate,
                                  [Point(1, 200, 1000, _State.Updated),
                                   Point(2, 1000, 1000, _State.Updated)]))
    Check(len(view.scales) == 1 and abs(view.scales[0] - 2.0) < 0.01,
          "预览按比例缩放({})".format(view.scales))
    Check(view._jmPinchPreview is True, "预览期标记已打开")
    # 一指抬起 -> 结算
    touch.eventFilter(None, Event(QEvent.Type.TouchUpdate,
                                  [Point(2, 1000, 1000, _State.Released)]))
    Check(readView.qtTool.applied == [200], "结算成 200%({})".format(readView.qtTool.applied))
    Check(view._jmPinchPreview is False, "结算后标记已清")
    Check(view.resets >= 1, "预览变换已复位")
    # 剩下那根手指移动/松开：不许变点按(否则松手就翻页/弹菜单)
    before = (view.qtTool.next, view.qtTool.last, view.readImg.toolShown)
    touch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(1, 300, 1200, _State.Updated)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 300, 1200, _State.Released)]))
    Check((view.qtTool.next, view.qtTool.last, view.readImg.toolShown) == before,
          "缩放后剩余手指被吞掉(不点按)")
    NoMouse("双指缩放")


def TestPinchTwoSequences():
    print("\n[5] 双指(两条独立序列，各一个点)：滚动模式的真实情况")
    touch, view, readView = NewTouch()
    # 序列 A：手指落在图元上
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 400, 1500)]))
    # 序列 B：手指落在相邻页的嵌入窗口上（Qt 会各给一条只有它自己的序列）
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(2, 900, 1500)]))
    Check(touch.Pinches == 1, "两条序列合起来也识别成双指")
    Check(touch.Drags == 0, "第二根手指落下不算拖动")
    # 收拢：距离 500 -> 250，比例 0.5
    touch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(1, 525, 1500, _State.Updated)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(2, 775, 1500, _State.Updated)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 525, 1500, _State.Released)]))
    Check(readView.qtTool.applied == [50], "结算成 50%({})".format(readView.qtTool.applied))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(2, 775, 1500, _State.Released)]))
    Check(view.readImg.toolShown == 0 and view.qtTool.next == 0,
          "整段手势不产生点按(不翻页/不弹菜单)")
    NoMouse("两条序列缩放")


def TestCancel():
    print("\n[6] TouchCancel：手势作废，不点按、预览撤掉")
    touch, view, _ = NewTouch()
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 100, 100)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchCancel, [Point(1, 100, 100)]))
    Check(view.readImg.toolShown == 0, "被打断不算点按")
    Check(touch.Cancels == 1, "记录取消次数")
    # 手势作废后新的点按要正常
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 100, 100)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 100, 100, _State.Released)]))
    Check(view.readImg.toolShown == 1, "取消后新的点按正常")
    NoMouse("取消手势")


def TestDragThenPinch():
    print("\n[7] 拖动中途加第二根手指：拖动作废，进缩放，松手不点按")
    touch, view, readView = NewTouch("UpDownScroll")
    touch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 200, 700)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(1, 200, 650, _State.Updated)]))
    scrolled = sum(view.vScrollBar.values)
    touch.eventFilter(None, Event(QEvent.Type.TouchUpdate,
                                  [Point(1, 200, 650, _State.Updated),
                                   Point(2, 300, 650, _State.Pressed)]))
    Check(touch.Pinches == 1, "拖动中途加第二根手指 -> 进入缩放")
    touch.eventFilter(None, Event(QEvent.Type.TouchUpdate,
                                  [Point(1, 150, 650, _State.Updated),
                                   Point(2, 350, 650, _State.Updated)]))
    touch.eventFilter(None, Event(QEvent.Type.TouchEnd,
                                  [Point(1, 150, 650, _State.Released),
                                   Point(2, 350, 650, _State.Released)]))
    Check(view.readImg.toolShown == 0 and view.qtTool.next == 0,
          "松手不点按(不翻页/不弹菜单)")
    Check(sum(view.vScrollBar.values) == scrolled, "进缩放后不再滚动")
    NoMouse("拖动转缩放")


def main():
    TestTap()
    TestDrag()
    TestPageFlip()
    TestPinchOneSequence()
    TestPinchTwoSequences()
    TestCancel()
    TestDragThenPinch()
    print()
    if Failures:
        print("FAIL: {} 项不过: {}".format(len(Failures), Failures))
        return 1
    print("OK: 看图区触控状态机全部通过(零合成鼠标)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
