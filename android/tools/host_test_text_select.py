# coding:utf-8
""" 宿主自测：可选中文本的"触摸长按才选中"门卫(TextSelectGate)

为什么值得单独测：这个改动的全部风险都在"鼠标事件的长按/滑动/抬手三种时序 +
真实鼠标放行"的排列组合上，而真机上没法用 adb 稳定复现"手指按住 500ms 不动"
(`input` 只有 tap/swipe，长按要么太短要么直接变 swipe)，只能在宿主上用假事件
把每条路径跑一遍：

  * 真实鼠标(source=NotSynthesized)：press/move/release 一律放行，桌面行为零改动
  * 触控合成鼠标(source=Synthesized*)：滑动 = move 全拦(不选中)、抬手什么都不做；
    长按(按住不动) = 抬手时全选 + 弹"复制/取消"菜单，release 不再放行
  * 长按后拖动 = 放弃长按(滚动优先，不和 QScroller 抢手指)
  * 安装器：QLabel 挂本身、QTextEdit/QPlainTextEdit 挂视口、幂等、
    顺带补上 TextSelectableByMouse(没有它 QLabel 连文本控件都不建，选不中)
  * 触控路由器 _Classify：带 _jmTextSelect 标记的控件返回 "native"
    (不认领触控，门卫才等得到合成鼠标；没标记的在滚动区里仍是 "view")

顺带把真的 tools/str.py 跑一遍 Reload+CheckStr(Str.Cancel 新增不能撞号/漏翻)。

用法：python3 android/tools/host_test_text_select.py
"""
import logging
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))


# ---------------------------------------------------------------------------
# 桩：只需满足 component.label.text_label / tools.str / mobile_ui_touch 的导入与调用面
# ---------------------------------------------------------------------------

class QObjectStub:
    def __init__(self, *args, **kwargs):
        pass

    def setObjectName(self, name):
        self._objectName = name


class QCoreApplicationStub:
    @staticmethod
    def translate(context, source, disambig=None, n=-1):
        return source


class QPointStub:
    def __init__(self, x=0, y=0):
        self._x, self._y = int(x), int(y)

    def x(self):
        return self._x

    def y(self):
        return self._y

    def __sub__(self, other):
        return QPointStub(self._x - other._x, self._y - other._y)

    def manhattanLength(self):
        return abs(self._x) + abs(self._y)

    def __repr__(self):
        return "QPoint({},{})".format(self._x, self._y)


class QPointFStub:
    """ 和真 QPointF 一样接受 point-like(真 _EventLocalPos 会拿它包一层) """

    def __init__(self, x=0, y=0):
        if hasattr(x, "x") and hasattr(x, "y"):
            self._x, self._y = float(x.x()), float(x.y())
        else:
            self._x, self._y = float(x), float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y

    def __repr__(self):
        return "QPointF({:.0f},{:.0f})".format(self._x, self._y)


class _Signal:
    def __init__(self):
        self._cbs = []

    def connect(self, fn):
        self._cbs.append(fn)

    def fire(self, *args):
        for cb in list(self._cbs):
            cb(*args)


class QTimerStub:
    """ 不自己走时：测试里用 Fire() 模拟"长按时间到" """
    created = []

    def __init__(self, parent=None):
        self._single = False
        self._interval = 0
        self._cb = None
        self._active = False
        self.timeout = _Signal()
        QTimerStub.created.append(self)

    def setSingleShot(self, value):
        self._single = value

    def setInterval(self, value):
        self._interval = value

    def start(self):
        self._active = True

    def stop(self):
        self._active = False

    def Fire(self):
        if self._active:
            self._active = False
            self.timeout.fire()


class FakeAction:
    def __init__(self, text):
        self.text = text
        self.triggered = _Signal()

    def Trigger(self):
        self.triggered.fire(False)


class QMenuStub:
    instances = []

    def __init__(self, parent=None):
        self.parent = parent
        self.actions = []
        self.popupPos = None
        self.closed = False
        self.aboutToHide = _Signal()
        QMenuStub.instances.append(self)

    def addAction(self, text):
        action = FakeAction(text)
        self.actions.append(action)
        return action

    def popup(self, pos):
        self.popupPos = pos

    def close(self):
        if not self.closed:
            self.closed = True
            self.aboutToHide.fire()


class FakeClipboard:
    def __init__(self):
        self.text = None

    def setText(self, text):
        self.text = text


class QApplicationStub:
    clipboardValue = None

    @staticmethod
    def clipboard():
        return QApplicationStub.clipboardValue


class _EventType:
    MouseButtonPress = "MouseButtonPress"
    MouseMove = "MouseMove"
    MouseButtonRelease = "MouseButtonRelease"
    MouseButtonDblClick = "MouseButtonDblClick"


class QEventStub:
    Type = _EventType


class _MouseSource:
    MouseEventNotSynthesized = 0
    MouseEventSynthesizedBySystem = 1
    MouseEventSynthesizedByQt = 2


class _MouseButtons:
    LeftButton = 1
    RightButton = 2


class _TextFlags:
    NoTextInteraction = 0
    TextSelectableByMouse = 1
    LinksAccessibleByMouse = 2
    TextBrowserInteraction = 2 | 1


class QtStub:
    # 非限定形式(PySide6 6.x 仍然暴露，项目里 Qt.LeftButton 到处都是)
    LeftButton = 1
    RightButton = 2
    MouseButton = _MouseButtons
    MouseEventSource = _MouseSource
    TextSelectableByMouse = _TextFlags.TextSelectableByMouse
    TextBrowserInteraction = _TextFlags.TextBrowserInteraction


# mobile_ui_touch 的 _Classify 用 isinstance 认控件，桩类必须是真类
class _W(QObjectStub):
    pass


def _MakeModule(name, attrs):
    module = types.ModuleType(name)
    for attr in attrs:
        setattr(module, attr, attr)
    return module


def _InstallStubs():
    core = _MakeModule("PySide6.QtCore", [])
    core.QObject = QObjectStub
    core.QCoreApplication = QCoreApplicationStub
    core.QEvent = QEventStub
    core.QPoint = QPointStub
    core.QPointF = QPointFStub
    core.Qt = QtStub
    core.QTimer = QTimerStub
    sys.modules["PySide6.QtCore"] = core
    sys.modules["PySide6"] = _MakeModule("PySide6", [])

    # text_label / mobile_ui_base / mobile_ui_touch 用到的 QtWidgets 名字。
    # 桩类必须是真类：_Classify 靠 isinstance 认控件
    widgetNames = ("QAbstractButton", "QAbstractItemView", "QAbstractScrollArea",
                   "QAbstractSpinBox", "QApplication", "QComboBox", "QGraphicsView",
                   "QLineEdit", "QPlainTextEdit", "QMenu", "QScroller",
                   "QScrollerProperties", "QScrollBar", "QSlider", "QTabBar",
                   "QTextEdit", "QWidget")
    widgets = _MakeModule("PySide6.QtWidgets", [])
    for name in widgetNames:
        setattr(widgets, name, type(name, (QObjectStub,), {}))
    widgets.QApplication = QApplicationStub
    widgets.QMenu = QMenuStub
    sys.modules["PySide6.QtWidgets"] = widgets

    gui = _MakeModule("PySide6.QtGui", [])
    for name in ("QEventPoint", "QGuiApplication", "QInputDevice", "QMouseEvent",
                 "QPointingDevice", "QWheelEvent"):
        setattr(gui, name, type(name, (QObjectStub,), {}))
    sys.modules["PySide6.QtGui"] = gui

    # Log.Error/Warn 带 exc_info=True，宿主上会刷 "NoneType: None"，整个关掉
    logModule = types.ModuleType("tools.log")

    class _Log:
        @staticmethod
        def Error(*args, **kwargs):
            pass

        @staticmethod
        def Warn(*args, **kwargs):
            pass

        @staticmethod
        def Info(*args, **kwargs):
            pass

    logModule.Log = _Log
    sys.modules["tools.log"] = logModule

    # tools.str 用真的(顺带校验 Str.Cancel 不撞号)，tools.mobile_ui 用桩
    ui = types.ModuleType("tools.mobile_ui")
    ui._touchGuard = None
    ui._scrollWatcher = None
    sys.modules["tools.mobile_ui"] = ui


_InstallStubs()
logging.disable(logging.CRITICAL)

# 真的 tools.str：Reload + 自校验(Str.Cancel=202 必须登记且不撞号)
# 注意：CheckStr 按 dir(cls) 逐个核对，Python 3.13 起每个类自带 int 型的
# __firstlineno__，在 3.13 上跑原版 CheckStr 必然误报(与本次改动无关，
# 真机是 3.11 没有这个问题)，这里过滤掉 dunder 后逻辑与 CheckStr 一致。
from tools.str import Str  # noqa: E402

Str.Reload()


def _CheckStrNoDunder():
    seen = {}
    for name in dir(Str):
        if name.startswith("__"):
            continue
        value = getattr(Str, name)
        if not isinstance(value, int):
            continue
        if value in seen:
            raise Exception("Already exists str: {} / {}".format(name, seen[value]))
        seen[value] = name
        if value not in Str.strDict:
            raise Exception("Not Found str: " + name)


_CheckStrNoDunder()

from component.label.text_label import InstallTextSelect, TextSelectGate  # noqa: E402


# ---------------------------------------------------------------------------
# 假的事件 / 控件
# ---------------------------------------------------------------------------

class FakePos:
    def __init__(self, x, y):
        self._x, self._y = float(x), float(y)

    def x(self):
        return self._x

    def y(self):
        return self._y


class FakeMouseEvent:
    def __init__(self, etype, x, y, source=0, button=1):
        self._type = etype
        self._x, self._y = float(x), float(y)
        self._source = source
        self._button = button

    def type(self):
        return self._type

    def position(self):
        return FakePos(self._x, self._y)

    def button(self):
        return self._button

    def source(self):
        return self._source


def Press(x=10, y=20, touch=False):
    src = _MouseSource.MouseEventSynthesizedBySystem if touch else _MouseSource.MouseEventNotSynthesized
    return FakeMouseEvent(_EventType.MouseButtonPress, x, y, src)


def Move(x, y, touch=False):
    src = _MouseSource.MouseEventSynthesizedBySystem if touch else _MouseSource.MouseEventNotSynthesized
    return FakeMouseEvent(_EventType.MouseMove, x, y, src)


def Release(x=10, y=20, touch=False):
    src = _MouseSource.MouseEventSynthesizedBySystem if touch else _MouseSource.MouseEventNotSynthesized
    return FakeMouseEvent(_EventType.MouseButtonRelease, x, y, src)


class FakeLabel(QObjectStub):
    """ QLabel 行为面：setSelection/selectedText/textInteractionFlags/mapToGlobal """

    def __init__(self, text="评论内容"):
        super().__init__()
        self._text = text
        self._flags = 0
        self.selection = None
        self._selected = ""
        self.updates = 0
        self.filters = []

    def textInteractionFlags(self):
        return self._flags

    def setTextInteractionFlags(self, flags):
        self._flags = flags

    def text(self):
        return self._text

    def setSelection(self, start, length):
        self.selection = (start, length)

    def hasSelectedText(self):
        return bool(self._selected)

    def selectedText(self):
        return self._selected

    def update(self):
        self.updates += 1

    def mapToGlobal(self, pos):
        return ("global", pos.x(), pos.y())

    def installEventFilter(self, filtr):
        self.filters.append(filtr)


class FakeCursor:
    def __init__(self):
        self.cleared = False

    def clearSelection(self):
        self.cleared = True


class FakeViewport(QObjectStub):
    def __init__(self):
        super().__init__()
        self.filters = []

    def installEventFilter(self, filtr):
        self.filters.append(filtr)

    def mapToGlobal(self, pos):
        return ("global-viewport", pos.x(), pos.y())


class FakeTextEdit(QObjectStub):
    """ QTextEdit/QPlainTextEdit 行为面：鼠标走 viewport，选区走 textCursor """

    def __init__(self, text="简介内容"):
        super().__init__()
        self._text = text
        self._flags = 0
        self.selectedAll = False
        self._cursor = FakeCursor()
        self._viewport = FakeViewport()

    def viewport(self):
        return self._viewport

    def textInteractionFlags(self):
        return self._flags

    def setTextInteractionFlags(self, flags):
        self._flags = flags

    def selectAll(self):
        self.selectedAll = True

    def textCursor(self):
        return self._cursor

    def setTextCursor(self, cursor):
        self._cursor = cursor

    def toPlainText(self):
        return self._text

    def update(self):
        pass


Failures = []


def ResetStatics():
    """ 桩的 instances/created 是类级累计的，每个用例开头清一次 """
    QMenuStub.instances = []
    QTimerStub.created = []


def Check(condition, message):
    if condition:
        print("  ok  {}".format(message))
    else:
        Failures.append(message)
        print("  FAIL {}".format(message))


def NewGate(widget, target=None):
    return TextSelectGate(widget, target if target is not None else widget)


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------

def TestMousePassThrough():
    ResetStatics()
    print("\n[1] 真实鼠标：press/move/release 一律放行，不动门卫状态")
    label = FakeLabel()
    gate = NewGate(label)
    Check(gate.eventFilter(label, Press()) is False, "鼠标 press 放行")
    Check(gate.eventFilter(label, Move(80, 90)) is False, "鼠标 move 放行(拖选照旧)")
    Check(gate.eventFilter(label, Release(80, 90)) is False, "鼠标 release 放行")
    Check(label.selection is None, "鼠标全程不碰选区")
    Check(not QTimerStub.created, "鼠标操作连长按计时器都不建")


def TestTouchSlideBlocked():
    ResetStatics()
    print("\n[2] 触摸滑动：move 全拦(不选中)，抬手什么都不做")
    label = FakeLabel()
    gate = NewGate(label)
    Check(gate.eventFilter(label, Press(touch=True)) is False, "触摸 press 放行(链接/光标靠它)")
    Check(gate.eventFilter(label, Move(10, 22, touch=True)) is True, "小幅 move 也拦(不许起选)")
    Check(gate.eventFilter(label, Move(10, 120, touch=True)) is True, "大幅 move 拦(当滚动)")
    Check(gate.eventFilter(label, Release(10, 120, touch=True)) is False, "滑动抬手放行、无菜单")
    Check(label.selection in (None, (0, 0)), "滑动全程没有选中")
    Check(not QMenuStub.instances, "滑动不弹菜单")
    Check(not gate._armed, "滑动后长按未成立")


def TestLongPressSelectsAll():
    ResetStatics()
    print("\n[3] 触摸长按：抬手时全选 + 弹复制菜单，release 不再放行")
    label = FakeLabel("这是一段评论")
    gate = NewGate(label)
    gate.eventFilter(label, Press(30, 40, touch=True))
    timer = gate._EnsureTimer()
    Check(timer._interval == 500, "长按阈值 500ms")
    timer.Fire()                                   # 按住不动，时间到
    Check(gate._armed, "长按成立")
    handled = gate.eventFilter(label, Release(30, 41, touch=True))
    Check(handled is True, "长按抬手被拦(不长按链接)")
    Check(label.selection == (0, len("这是一段评论")), "全选整段文字")
    Check(label.updates >= 1, "选区变化触发重绘")
    Check(len(QMenuStub.instances) == 1, "弹出长按菜单")
    menu = QMenuStub.instances[-1]
    Check(menu.popupPos == ("global", 30, 40), "菜单弹在按下点")
    Check([a.text for a in menu.actions] == [Str.GetStr(Str.Copy), Str.GetStr(Str.Cancel)],
          "菜单项=复制/取消")


def TestLongPressThenDragCancels():
    ResetStatics()
    print("\n[4] 长按后又拖动：放弃长按(滚动优先)，抬手无菜单")
    label = FakeLabel()
    gate = NewGate(label)
    gate.eventFilter(label, Press(30, 40, touch=True))
    gate._EnsureTimer().Fire()
    Check(gate._armed, "长按先成立")
    Check(gate.eventFilter(label, Move(30, 200, touch=True)) is True, "拖动 move 仍拦")
    Check(not gate._armed, "拖动超过阈值 -> 放弃长按")
    Check(gate.eventFilter(label, Release(30, 200, touch=True)) is False, "抬手放行")
    Check(label.selection in (None, (0, 0)), "没有选中残留")
    Check(not QMenuStub.instances, "不弹菜单")


def TestCopyAction():
    ResetStatics()
    print("\n[5] 菜单复制：复制的是整段文字；菜单一收高亮也没了")
    QApplicationStub.clipboardValue = FakeClipboard()
    label = FakeLabel("要复制的文字")
    label._selected = "要复制的文字"
    gate = NewGate(label)
    gate.eventFilter(label, Press(5, 6, touch=True))
    gate._EnsureTimer().Fire()
    gate.eventFilter(label, Release(5, 6, touch=True))
    menu = QMenuStub.instances[-1]
    menu.actions[0].Trigger()                       # 点"复制"
    Check(QApplicationStub.clipboardValue.text == "要复制的文字", "剪贴板拿到整段文字")
    label._selected = ""
    menu.aboutToHide.fire()                         # 菜单关闭
    Check(label.selection == (0, 0), "菜单关闭后清掉高亮")


def TestQuickTapStillWorks():
    ResetStatics()
    print("\n[6] 触摸轻点(不到 500ms)：press/release 都放行，链接点按不受影响")
    label = FakeLabel()
    gate = NewGate(label)
    gate.eventFilter(label, Press(touch=True))
    gate.eventFilter(label, Release(touch=True))    # 很快抬手，计时器没响
    Check(label.selection in (None, (0, 0)), "轻点不选中")
    Check(not QMenuStub.instances, "轻点不弹菜单")


def TestInstallLabel():
    ResetStatics()
    print("\n[7] 安装器(QLabel)：挂控件本身、幂等、补上可选中标志")
    label = FakeLabel()
    label.setTextInteractionFlags(_TextFlags.NoTextInteraction)
    Check(InstallTextSelect(label) is True, "首次安装成功")
    Check(label._jmTextSelect is True, "打上 _jmTextSelect 标记(触控路由器认它)")
    Check(len(label.filters) == 1, "过滤器挂在控件本身")
    Check(isinstance(label.filters[0], TextSelectGate), "过滤器就是门卫")
    Check(int(label._flags) & int(_TextFlags.TextSelectableByMouse), "补上 TextSelectableByMouse")
    Check(InstallTextSelect(label) is False, "重复安装是空操作")


def TestInstallTextEdit():
    ResetStatics()
    print("\n[8] 安装器(QTextEdit/QPlainTextEdit)：过滤器挂视口，坐标换算也走视口")
    edit = FakeTextEdit()
    Check(InstallTextSelect(edit) is True, "首次安装成功")
    Check(len(edit._viewport.filters) == 1, "过滤器挂在视口上(鼠标事件投视口)")
    gate = edit._viewport.filters[0]
    gate.eventFilter(edit._viewport, Press(7, 8, touch=True))
    gate._EnsureTimer().Fire()
    gate.eventFilter(edit._viewport, Release(7, 8, touch=True))
    Check(edit.selectedAll, "长按 -> selectAll()")
    menu = QMenuStub.instances[-1]
    Check(menu.popupPos == ("global-viewport", 7, 8), "菜单位置用视口坐标换算")
    Check(menu.actions[0].Trigger is not None, "复制项可用")


def TestClassifyNative():
    ResetStatics()
    print("\n[9] 触控路由器 _Classify：带标记 -> native；没标记在滚动区里 -> view")
    import tools.mobile_ui_touch as Touch
    from PySide6.QtWidgets import QAbstractItemView

    router = Touch._TouchRouter()

    marked = FakeLabel()
    marked._jmTextSelect = True
    Check(router._Classify(marked) == "native", "带 _jmTextSelect -> native(不认领触控)")

    # 没标记、但在已接管滚动的滚动区里：仍然是 view(行为不变)
    area = type("FakeUserList", (QAbstractItemView,), {})()
    area._jmTouchScroll = True
    plain = FakeLabel()
    plain.parentWidget = lambda: area
    Check(router._Classify(plain) == "view", "滚动区里的普通控件仍是 view")

    # 标记要在父链上生效：控件自己没标、祖先标了也算(评论项整体打标的场景)
    child = FakeLabel()
    child.parentWidget = lambda: marked
    Check(router._Classify(child) == "native", "祖先带标记 -> native")


def main():
    TestMousePassThrough()
    TestTouchSlideBlocked()
    TestLongPressSelectsAll()
    TestLongPressThenDragCancels()
    TestCopyAction()
    TestQuickTapStillWorks()
    TestInstallLabel()
    TestInstallTextEdit()
    TestClassifyNative()
    print()
    if Failures:
        print("FAIL: {} 项不过: {}".format(len(Failures), Failures))
        return 1
    print("OK: 触摸长按门卫全部通过(鼠标零改动 / 滑动不选中 / 长按全选+复制)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
