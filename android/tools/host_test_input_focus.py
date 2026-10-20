# coding:utf-8
""" 宿主自检：文本输入框的点按/聚焦链路(触控不吞事件 + 兜底聚焦 + 防误触)

真机现象："设置页所有输入框都点不进去、打不了字"。输入框靠 Qt 把**未消费的触控**
合成成鼠标才能拿到焦点，所以这条链路上任何一环把触控吞掉，输入框就彻底哑掉：

  * 应用级过滤器一吞事件，QWidgetWindow 的合成就不会发生；
  * 同一时刻还有别的触点被认领/残留序列没收尾，旧实现 `handled = bool(_seqs)`
    会把**所有**触控都当成"已处理"，输入框跟着一起哑(按钮不受影响，因为它们走
    公开入口激活) —— 这就是"只有输入框不能输入"的根因路径；
  * 就算没被吞，父级滚动区的 QScroller 把手势判成滚动时，合成也会被抑制。

这个自检在宿主上用真 Qt 造一套"滚动区 + 单行/多行输入框 + 只读日志 + 按钮"，
用假触控事件直接喂 `_TouchRouter`，逐条验证：

  1. 输入框按下：不吞事件、不 accept、分类是 "input"
  2. 抬手后确实聚焦，且光标落在手指位置
  3. 已经聚焦时不再动光标(避免"重复聚焦→双击选词→下次输入覆盖原内容")
  4. 在输入框上滑动：不聚焦、不动光标(防误触)
  5. 表里已有别的触点被认领时，落在输入框上的触控**仍然不被吞**
  6. 残留序列(抬手丢了)会按 id 重建，不会把输入框永久饿死
  7. 只读文本框不弹输入法(分类 native)
  8. 鼠标点按行为不变(仍然能聚焦/落光标)
  9. 点非输入区域不会把焦点抢到输入框上

需要本机有 PySide6；CI 里的 python3 没有就直接 SKIP(退出码 0)。
用法：python android/tools/host_test_input_focus.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QEventPoint
    from PySide6.QtWidgets import (QApplication, QCheckBox, QLabel, QLineEdit,
                                   QPlainTextEdit, QPushButton, QScrollArea,
                                   QSpinBox, QVBoxLayout, QWidget)
    from PySide6.QtTest import QTest
except Exception as es:                      # pragma: no cover - CI 的宿主没有 PySide6
    print("SKIP: 本机没有 PySide6 ({})".format(es))
    sys.exit(0)

import tools.mobile_ui_touch as touch  # noqa: E402

Failures = []


def Check(condition, message):
    if condition:
        print("  ok  {}".format(message))
    else:
        Failures.append(message)
        print("  FAIL {}".format(message))


# ---------------------------------------------------------------------------
# 假触控事件(只实现 _TouchRouter 用到的接口)
# ---------------------------------------------------------------------------

class FakePoint:
    def __init__(self, pid, state, glob):
        self._id = pid
        self._state = state
        self._glob = QPointF(glob)

    def id(self):
        return self._id

    def state(self):
        return self._state

    def globalPosition(self):
        return self._glob


class FakeTouch:
    def __init__(self, etype, points):
        self._type = etype
        self._points = list(points)
        self._accepted = False

    def type(self):
        return self._type

    def points(self):
        return self._points

    def accept(self):
        self._accepted = True

    def isAccepted(self):
        return self._accepted


def Press(router, target, glob, pid=0):
    ev = FakeTouch(QEvent.Type.TouchBegin,
                   [FakePoint(pid, QEventPoint.State.Pressed, glob)])
    return router.OnTouch(target, ev), ev


def Move(router, target, glob, pid=0):
    ev = FakeTouch(QEvent.Type.TouchUpdate,
                   [FakePoint(pid, QEventPoint.State.Updated, glob)])
    return router.OnTouch(target, ev), ev


def Release(router, target, glob, pid=0):
    ev = FakeTouch(QEvent.Type.TouchEnd,
                   [FakePoint(pid, QEventPoint.State.Released, glob)])
    return router.OnTouch(target, ev), ev


def CenterOf(widget):
    return widget.mapToGlobal(widget.rect().center())


class Scene:
    """ 一页"已接管手指滚动"的设置页：单行/多行/只读/按钮/勾选框 """

    def __init__(self, app):
        self.app = app
        self.page = QWidget()
        self.page.resize(360, 640)
        lay = QVBoxLayout(self.page)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        inner = QWidget()
        inner.setMinimumHeight(1400)
        v = QVBoxLayout(inner)
        self.label = QLabel("说明文字")
        v.addWidget(self.label)
        self.edit = QLineEdit("abcdef")
        v.addWidget(self.edit)
        self.edit2 = QLineEdit("second")
        v.addWidget(self.edit2)
        self.readonly = QPlainTextEdit("只读日志内容")
        self.readonly.setReadOnly(True)
        v.addWidget(self.readonly)
        self.spin = QSpinBox()
        v.addWidget(self.spin)
        self.btn = QPushButton("按钮")
        v.addWidget(self.btn)
        self.check = QCheckBox("勾选")
        v.addWidget(self.check)
        v.addStretch(1)
        self.area.setWidget(inner)
        lay.addWidget(self.area)
        self.page.show()
        app.processEvents()
        # 和 mobile_ui 的入口一致：滚动区交给 QScroller，视口接受触控
        touch.MakeScrollable(self.area)
        app.processEvents()
        self.viewport = self.area.viewport()
        self.router = touch._TouchRouter()
        self.router.Enabled = True

    def Flush(self):
        self.app.processEvents()


def TestClassify(scene):
    print("\n[1] 分类：输入框走 input，只读/滚动区其它控件保持原样")
    router = scene.router
    Check(router._Classify(scene.edit) == "input", "QLineEdit -> input")
    Check(router._Classify(scene.edit.viewport() if hasattr(scene.edit, "viewport") else scene.edit)
          == "input", "QLineEdit 自身/内部件 -> input")
    Check(router._Classify(scene.readonly) == "native", "只读 QPlainTextEdit -> native(不弹输入法)")
    Check(router._Classify(scene.spin) == "spin", "QSpinBox -> spin(聚焦可键入，见 host_test_spin_focus)")
    Check(router._Classify(scene.spin.lineEdit()) == "spin",
          "QSpinBox 内部输入行 -> spin(不算独立输入框)")
    Check(router._Classify(scene.label) == "view", "滚动区里的普通标签 -> view(滑动不点)")


def TestTapFocus(scene):
    print("\n[2] 点按输入框：不吞事件 + 抬手后聚焦 + 光标落在手指处")
    router = scene.router
    scene.edit.clearFocus()
    scene.edit.setCursorPosition(0)
    scene.Flush()
    point = scene.edit.mapToGlobal(QPoint(scene.edit.width() - 4, scene.edit.height() // 2))
    handled, ev = Press(router, scene.viewport, point)
    Check(handled is False, "按下不吞事件(Qt 才能合成鼠标)")
    Check(not ev.isAccepted(), "按下没有 accept")
    Check(router.Inputs == 1, "登记了一次输入框按下")
    Release(router, scene.viewport, point)
    scene.Flush()
    Check(scene.edit.hasFocus(), "抬手后输入框拿到了焦点")
    Check(scene.edit.cursorPosition() == len("abcdef"), "光标落在手指位置(行尾)")
    Check(router._seqs == {}, "抬手后没有残留序列")


def TestNoDoubleFocus(scene):
    print("\n[3] 已聚焦时不再动光标(不会变成双击选词/覆盖内容)")
    router = scene.router
    scene.edit.setFocus()
    scene.edit.setCursorPosition(2)
    scene.Flush()
    point = scene.edit.mapToGlobal(QPoint(scene.edit.width() - 4, scene.edit.height() // 2))
    Press(router, scene.viewport, point)
    Release(router, scene.viewport, point)
    scene.Flush()
    Check(scene.edit.cursorPosition() == 2, "光标没被兜底逻辑挪走")
    Check(not scene.edit.hasSelectedText(), "没有产生选区(下次输入不会覆盖原内容)")


def TestDragOnInput(scene):
    print("\n[4] 在输入框上滑动：不聚焦、不动光标(防误触)")
    router = scene.router
    scene.edit.clearFocus()
    scene.edit.setCursorPosition(1)
    scene.Flush()
    start = scene.edit.mapToGlobal(QPoint(20, scene.edit.height() // 2))
    Press(router, scene.viewport, start)
    Move(router, scene.viewport, QPoint(start.x(), start.y() - 140))
    Release(router, scene.viewport, QPoint(start.x(), start.y() - 140))
    scene.Flush()
    Check(not scene.edit.hasFocus(), "滑动没有把焦点给输入框")
    Check(scene.edit.cursorPosition() == 1, "滑动没有移动光标")
    Check(router.Drags >= 1, "滑动被识别成滚动(Drags+1)")


def TestClaimedSeqDoesNotStarve(scene):
    print("\n[5] 表里已有被认领的触点时，输入框的触控仍然不被吞")
    router = scene.router
    router.Reset()
    scene.edit.clearFocus()
    scene.Flush()
    # 第一根手指落在勾选框上(会被认领，accept 掉)
    checkPoint = CenterOf(scene.check)
    handled1, ev1 = Press(router, scene.viewport, checkPoint, pid=0)
    Check(handled1 is True and ev1.isAccepted(), "勾选框按下被认领(防误触的既有行为)")
    # 第二根手指落在输入框上：旧实现 handled=bool(_seqs)=True -> 事件被吞，输入框永远不聚焦
    editPoint = CenterOf(scene.edit)
    handled2, ev2 = Press(router, scene.viewport, editPoint, pid=1)
    Check(handled2 is False, "输入框按下不被别的触点连累(旧实现是 True)")
    Check(not ev2.isAccepted(), "输入框按下没有 accept")
    Release(router, scene.viewport, editPoint, pid=1)
    Release(router, scene.viewport, checkPoint, pid=0)
    scene.Flush()
    Check(router._seqs == {}, "两个触点都收尾了")


def TestStaleSeq(scene):
    print("\n[6] 残留序列(抬手丢了)按 id 重建，不会把输入框永久饿死")
    router = scene.router
    router.Reset()
    scene.edit.clearFocus()
    scene.Flush()
    import time as _time
    router._seqs[7] = {"id": 7, "widget": scene.check, "mode": "activate",
                       "press": QPointF(0, 0), "last": QPointF(0, 0), "moved": False,
                       "bar": None, "conn": None, "claimed": True,
                       "tick": _time.monotonic() - 60.0}
    point = CenterOf(scene.edit)
    handled, ev = Press(router, scene.viewport, point, pid=7)
    Check(router.Stales == 1, "旧的残留序列被丢弃")
    Check(handled is False, "重建后的输入框按下不吞事件")
    Release(router, scene.viewport, point, pid=7)
    scene.Flush()
    Check(scene.edit.hasFocus(), "输入框仍然能拿到焦点")
    Check(router._seqs == {}, "没有残留")


def TestReadOnly(scene):
    print("\n[7] 只读文本框：点按不聚焦、不弹输入法(选中仍由长按门卫负责)")
    router = scene.router
    scene.edit.clearFocus()
    scene.Flush()
    point = CenterOf(scene.readonly)
    handled, _ev = Press(router, scene.viewport, point)
    Release(router, scene.viewport, point)
    scene.Flush()
    Check(handled is False, "只读文本框不吞事件(交给 Qt 原生/长按门卫)")
    Check(not scene.readonly.hasFocus(), "只读文本框没有被兜底聚焦")


def TestMouseUnchanged(scene):
    print("\n[8] 鼠标点按行为不变")
    router = scene.router
    scene.edit.clearFocus()
    scene.Flush()
    before = router.Inputs
    QTest.mouseClick(scene.edit, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, QPoint(12, scene.edit.height() // 2))
    scene.Flush()
    Check(scene.edit.hasFocus(), "鼠标点击仍然能聚焦")
    Check(router.Inputs == before, "鼠标事件不进触控路由")


def TestNonInputKeepsFocus(scene):
    print("\n[9] 点非输入区域不会把焦点抢到输入框")
    router = scene.router
    scene.edit.clearFocus()
    scene.Flush()
    point = CenterOf(scene.label)
    handled, _ev = Press(router, scene.viewport, point)
    Release(router, scene.viewport, point)
    scene.Flush()
    Check(handled is True, "普通标签的点按仍由路由认领(和以前一致)")
    Check(not scene.edit.hasFocus(), "输入框没有被误聚焦")
    Check(not scene.edit2.hasFocus(), "另一个输入框也没有被误聚焦")


def main():
    app = QApplication(sys.argv)
    scene = Scene(app)
    TestClassify(scene)
    TestTapFocus(scene)
    TestNoDoubleFocus(scene)
    TestDragOnInput(scene)
    TestClaimedSeqDoesNotStarve(scene)
    TestStaleSeq(scene)
    TestReadOnly(scene)
    TestMouseUnchanged(scene)
    TestNonInputKeepsFocus(scene)
    print("")
    if Failures:
        print("FAIL: {} 项没通过".format(len(Failures)))
        for item in Failures:
            print("  - {}".format(item))
        return 1
    print("OK: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
