# coding:utf-8
""" 宿主自检：看图区双指缩放的状态机(_ReaderPinch)

为什么值得单独测：真机上双指手势没法用 adb 模拟（`input` 只有单指，`sendevent`
要 root），而这里的坑全在"多条触摸序列 + 触点增删"的状态迁移上：

  * Qt 的多点触摸是**每个触点一个目标控件**的：滚动模式下相邻页是
    QGraphicsProxyWidget 里嵌的真实子窗口，两根手指常常落在两条**独立序列**里，
    每条只有一个点 —— 只看"本次事件里有几个点"永远等不到两个点
  * 1 指(鼠标语义) -> 2 指(缩放) -> 抬手，每次切换都要保证
    "不误翻页、不误滚动、缩放只结算一次"
  * 缩放之后剩下的那根手指必须被吞掉，否则松手会被场景当成"点按"翻页

这里用假的事件/触点把每条路径跑一遍，检查合成出来的鼠标事件序列。

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
    MouseButtonPress = "MouseButtonPress"
    MouseMove = "MouseMove"
    MouseButtonRelease = "MouseButtonRelease"


class _MouseButton:
    LeftButton = "Left"
    NoButton = "None"


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
        self.x = int(x)
        self.y = int(y)

    def __repr__(self):
        return "QPoint({}, {})".format(self.x, self.y)


class QPointFStub:
    def __init__(self, x=0.0, y=0.0):
        self._x = float(x)
        self._y = float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y

    def __repr__(self):
        return "QPointF({:.0f}, {:.0f})".format(self._x, self._y)


class QMouseEventStub:
    """ 记录合成出来的鼠标事件 """

    def __init__(self, etype, local, scene, glob, button, buttons, modifiers):
        self.type = etype
        self.local = local
        self.glob = glob

    def __repr__(self):
        return "{}@({},{})".format(self.type, self.local.x, self.local.y)


class QApplicationStub:
    events = []
    widgetAtName = None

    @staticmethod
    def sendEvent(target, event):
        QApplicationStub.events.append(event)

    @staticmethod
    def widgetAt(point):
        return None


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
    core.Qt = type("Qt", (_Any,), {"MouseButton": _MouseButton,
                                   "KeyboardModifier": _Modifier,
                                   "WidgetAttribute": _Attr})
    core.QTimer = QTimerStub
    sys.modules["PySide6.QtCore"] = core

    gui = _MakeModule("PySide6.QtGui", [])
    gui.QEventPoint = type("QEventPoint", (_Any,), {"State": _State})
    gui.QMouseEvent = QMouseEventStub
    sys.modules["PySide6.QtGui"] = gui

    widgets = _MakeModule("PySide6.QtWidgets", [])
    widgets.QApplication = QApplicationStub
    sys.modules["PySide6.QtWidgets"] = widgets
    sys.modules["PySide6"] = _MakeModule("PySide6", [])

    base = _MakeModule("tools.mobile_ui_base", [])
    base.TouchSlopPx = 10
    base._EventLocalPos = lambda event: None
    sys.modules["tools.mobile_ui_base"] = base

    ui = _MakeModule("tools.mobile_ui", [])
    ui._readerDrag = None
    ui._readerPinch = None
    sys.modules["tools.mobile_ui"] = ui


_InstallStubs()

# Log.Warn/Error 带 exc_info=True，宿主上会一直打印 "NoneType: None"，这里关掉
logging.disable(logging.CRITICAL)

import tools.mobile_ui_reader as Reader  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF  # noqa: E402


# ---------------------------------------------------------------------------
# 假的事件 / 控件
# ---------------------------------------------------------------------------

class Point:
    def __init__(self, pid, x, y, state=None):
        self._id = pid
        self._x = x
        self._y = y
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


class FakeView:
    def __init__(self):
        self._jmPinchPreview = False
        self.scales = []
        self.resets = 0
        self.zoom = 1.0

    def scale(self, sx, sy):
        self.scales.append(round(sx, 4))
        self.zoom *= sx

    def resetTransform(self):
        self.resets += 1
        self.zoom = 1.0

    def mapFromGlobal(self, point):
        return QPoint(point.x, point.y)


class FakeTool:
    def __init__(self):
        self.applied = []

    def ScalePicture2(self, percent):
        self.applied.append(percent)


class FakeReadView:
    def __init__(self):
        self.frame = types.SimpleNamespace(scaleCnt=0, mode="LeftRight")
        self.qtTool = FakeTool()
        self.qtTool.stripModel = "LeftRight"


Failures = []


def Check(ok, name):
    print("  {} {}".format("OK  " if ok else "FAIL", name))
    if not ok:
        Failures.append(name)


def NewPinch(readView=None):
    readView = readView or FakeReadView()
    view = FakeView()
    pinch = Reader._ReaderPinch(view, readView, view)
    pinch._target = view
    QApplicationStub.events = []
    return pinch, view, readView


def MouseSeq():
    return [e.type for e in QApplicationStub.events]


def PointSeq():
    return [(e.local.x, e.local.y) for e in QApplicationStub.events]


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------

def TestTap():
    print("\n[1] 单指点按：按下 + 松开")
    pinch, view, _ = NewPinch()
    pinch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 100, 200)]))
    pinch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 100, 200, _State.Released)]))
    Check(MouseSeq() == ["MouseButtonPress", "MouseButtonRelease"], "press + release")
    Check(PointSeq() == [(100, 200), (100, 200)], "坐标 = 触点位置")
    Check(view.scales == [], "没有缩放")


def TestDrag():
    print("\n[2] 单指拖动：按下 + 移动 + 松开")
    pinch, view, _ = NewPinch()
    pinch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 100, 200)]))
    for y in (210, 230, 260):
        pinch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(1, 100, y)]))
    pinch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 100, 260, _State.Released)]))
    Check(MouseSeq() == ["MouseButtonPress", "MouseMove", "MouseMove", "MouseMove",
                         "MouseButtonRelease"], "press + 3 move + release")
    Check(PointSeq()[-1] == (100, 260), "release 在最后一个位置")


def TestPinchOneSequence():
    print("\n[3] 双指(同一条序列)：进缩放 -> 张开 -> 一指抬起结算")
    pinch, view, readView = NewPinch()
    pinch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 400, 1000, _State.Updated)]))
    # 第二根手指落下（同一序列，两个点）
    pinch.eventFilter(None, Event(QEvent.Type.TouchUpdate,
                                  [Point(1, 400, 1000, _State.Updated),
                                   Point(2, 800, 1000, _State.Pressed)]))
    Check(pinch.Pinches == 1, "进入缩放")
    Check(MouseSeq()[:1] == ["MouseButtonPress"], "只合成过一次按下")
    Check(MouseSeq()[-1] == "MouseButtonRelease", "按下被释放(作废了点按)")
    # 张开：400,800 -> 200,1000（距离 400 -> 800，比例 2.0）
    pinch.eventFilter(None, Event(QEvent.Type.TouchUpdate,
                                  [Point(1, 200, 1000, _State.Updated),
                                   Point(2, 1000, 1000, _State.Updated)]))
    Check(len(view.scales) == 1 and abs(view.scales[0] - 2.0) < 0.01,
          "预览按比例缩放({})".format(view.scales))
    Check(view._jmPinchPreview is True, "预览期标记已打开")
    # 一指抬起 -> 结算
    pinch.eventFilter(None, Event(QEvent.Type.TouchUpdate,
                                  [Point(2, 1000, 1000, _State.Released)]))
    Check(readView.qtTool.applied == [200], "结算成 200%({})".format(readView.qtTool.applied))
    Check(view._jmPinchPreview is False, "结算后标记已清")
    Check(view.resets >= 1, "预览变换已复位")
    # 剩下那根手指移动/松开：不能再产生鼠标事件(否则松手变点按翻页)
    before = list(MouseSeq())
    pinch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(1, 300, 1200, _State.Updated)]))
    pinch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 300, 1200, _State.Released)]))
    Check(MouseSeq() == before, "缩放后剩余手指被吞掉")


def TestPinchTwoSequences():
    print("\n[4] 双指(两条独立序列，各一个点)：滚动模式的真实情况")
    pinch, view, readView = NewPinch()
    # 序列 A：手指落在图元上
    pinch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 400, 1500)]))
    Check(MouseSeq() == ["MouseButtonPress"], "第一根手指 -> 按下")
    # 序列 B：手指落在相邻页的嵌入窗口上（Qt 会给一条只有它自己的序列）
    pinch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(2, 900, 1500)]))
    Check(pinch.Pinches == 1, "两条序列合起来也识别成双指")
    Check(MouseSeq() == ["MouseButtonPress", "MouseButtonRelease"],
          "没有多出第二次按下（鼠标语义已作废）")
    # 两条序列各自移动
    pinch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(1, 300, 1500, _State.Updated)]))
    pinch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(2, 1000, 1500, _State.Updated)]))
    Check(len(view.scales) >= 1, "两条序列的位移都能驱动缩放({})".format(view.scales))
    # 序列 A 先抬起
    pinch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(1, 300, 1500, _State.Released)]))
    Check(len(readView.qtTool.applied) == 1, "一指抬起即结算({})".format(readView.qtTool.applied))
    # 序列 B 继续动/松手：都要被吞掉
    before = list(MouseSeq())
    pinch.eventFilter(None, Event(QEvent.Type.TouchUpdate, [Point(2, 900, 1600, _State.Updated)]))
    pinch.eventFilter(None, Event(QEvent.Type.TouchEnd, [Point(2, 900, 1600, _State.Released)]))
    Check(MouseSeq() == before, "结算后不再合成鼠标事件")
    Check(len(pinch._points) == 0, "触点数已清空")


def TestCancel():
    print("\n[5] 触摸被打断(TouchCancel)")
    pinch, view, _ = NewPinch()
    pinch.eventFilter(None, Event(QEvent.Type.TouchBegin, [Point(1, 100, 100)]))
    pinch.eventFilter(None, Event(QEvent.Type.TouchCancel, [Point(1, 100, 100)]))
    Check(MouseSeq()[-1] == "MouseButtonRelease", "按下被收尾")
    Check(pinch._points == {} and pinch._pinching is False, "状态已复位")
    Check(view._jmPinchPreview is False, "预览标记已清")


def TestTinyPinchIgnored():
    print("\n[6] 缩放幅度小于 5%：不结算(避免手指抖动就重排)")
    pinch, view, readView = NewPinch()
    pinch.eventFilter(None, Event(QEvent.Type.TouchBegin,
                                  [Point(1, 400, 1000, _State.Updated),
                                   Point(2, 800, 1000, _State.Pressed)]))
    pinch.eventFilter(None, Event(QEvent.Type.TouchUpdate,
                                  [Point(1, 405, 1000, _State.Updated),
                                   Point(2, 800, 1000, _State.Updated)]))
    pinch.eventFilter(None, Event(QEvent.Type.TouchEnd,
                                  [Point(1, 405, 1000, _State.Released),
                                   Point(2, 800, 1000, _State.Released)]))
    Check(readView.qtTool.applied == [], "没触发重排")
    Check(view.resets >= 1, "预览已复位")


def TestPercentFromScaleCnt():
    print("\n[7] 基准百分比来自 scaleCnt")
    readView = FakeReadView()
    readView.frame.scaleCnt = 3      # 130%
    pinch, view, _ = NewPinch(readView)
    Check(pinch.CurrentPercent() == 130, "scaleCnt=3 -> 130%")
    pinch.eventFilter(None, Event(QEvent.Type.TouchBegin,
                                  [Point(1, 400, 1000, _State.Updated),
                                   Point(2, 800, 1000, _State.Pressed)]))
    # 距离 400 -> 800 = 2.0 倍
    pinch.eventFilter(None, Event(QEvent.Type.TouchUpdate,
                                  [Point(1, 200, 1000, _State.Updated),
                                   Point(2, 1000, 1000, _State.Updated)]))
    pinch.eventFilter(None, Event(QEvent.Type.TouchEnd,
                                  [Point(1, 200, 1000, _State.Released),
                                   Point(2, 1000, 1000, _State.Released)]))
    Check(readView.qtTool.applied == [260], "130% x 2.0 = 260%({})".format(readView.qtTool.applied))


def Main():
    TestTap()
    TestDrag()
    TestPinchOneSequence()
    TestPinchTwoSequences()
    TestCancel()
    TestTinyPinchIgnored()
    TestPercentFromScaleCnt()
    print("\n结果: {} 项失败".format(len(Failures)))
    if Failures:
        for name in Failures:
            print("  - {}".format(name))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(Main())
