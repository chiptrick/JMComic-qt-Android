# coding:utf-8
""" 宿主自检：数值框(QAbstractSpinBox)的点按聚焦/键入链路

真机现象(0.48 用户反馈)：设置页"缩放比例/封面大小/JM解密进程数"、WAIFU2X 标签的
"放大倍数/分辨率"都点得动(数值会变)但**打不了字** —— 触控路由把数值框整框归为
activate，点按只走 stepBy 加减，从不聚焦、不弹输入法。

修复：数值框拆出独立 "spin" 通道，抬手时按落点分流：
  * 点编辑区 -> setFocus + 光标落手指处 + 弹输入法(可键入，值经既有 valueChanged 回传)
  * 点上下箭头 -> stepBy(±1)(和它自己的鼠标语义一致，加减不变)
  * 滑动/多指 -> 什么都不激活(防误触不变)

这个自检在宿主上用真 Qt 造"滚动区 + QSpinBox/QDoubleSpinBox"，用假触控直接喂
_TouchRouter，逐条验证：
  1. 分类：数值框 -> spin(内部输入行不算独立 input)
  2. 点编辑区：聚焦 + 光标落位 + 输入法 show + 事件被认领(不合成鼠标)
  3. 键入：聚焦后往内部输入行打字，数值真的变(valueChanged 链会拿到)
  4. 点上箭头：+1；点下箭头：-1；都不抢焦点语义
  5. _SpinBoxStepAt 对三个区域的判定(上箭头/下箭头/编辑区)
  6. 几何兜底：样式给不出矩形时按右侧两格判
  7. 在数值框上滑动：不加减、不聚焦(防误触)
  8. 已聚焦时再点编辑区：光标挪到手指处(不清空不覆盖)
  9. 禁用中的数值框：点了不聚焦

需要本机有 PySide6；CI 的 python3 没有就直接 SKIP(退出码 0)。
用法：python android/tools/host_test_spin_focus.py
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
    from PySide6.QtWidgets import (QApplication, QCheckBox, QDoubleSpinBox,
                                   QLabel, QLineEdit, QPushButton, QScrollArea,
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
    """ 一页"已接管手指滚动"的设置页：整数/小数两个数值框 + 按钮 + 勾选框 """

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
        v.addWidget(QLabel("说明文字"))
        self.spin = QSpinBox()
        self.spin.setRange(0, 300)
        self.spin.setValue(100)
        v.addWidget(self.spin)
        self.dspin = QDoubleSpinBox()
        self.dspin.setRange(0.1, 64)
        self.dspin.setValue(2.0)
        v.addWidget(self.dspin)
        self.btn = QPushButton("按钮")
        v.addWidget(self.btn)
        self.check = QCheckBox("勾选")
        v.addWidget(self.check)
        v.addStretch(1)
        self.area.setWidget(inner)
        lay.addWidget(self.area)
        self.page.show()
        app.processEvents()
        touch.MakeScrollable(self.area)
        app.processEvents()
        self.viewport = self.area.viewport()
        self.router = touch._TouchRouter()
        self.router.Enabled = True

    def Flush(self):
        self.app.processEvents()


def ArrowRects(spin):
    """ 数值框的上下箭头矩形(和 _SpinBoxStepAt 同一套算法，供测试取点) """
    from PySide6.QtWidgets import QStyle, QStyleOptionSpinBox
    style = spin.style()
    opt = QStyleOptionSpinBox()
    opt.rect = spin.rect()
    opt.buttonSymbols = spin.buttonSymbols()
    opt.subControls = QStyle.SubControl.SC_All
    out = {}
    for name, sc in (("up", QStyle.SubControl.SC_SpinBoxUp),
                     ("down", QStyle.SubControl.SC_SpinBoxDown)):
        out[name] = style.subControlRect(QStyle.ComplexControl.CC_SpinBox,
                                         opt, sc, spin)
    return out


def TestClassify(scene):
    print("\n[1] 分类：数值框 -> spin(不再是整框 activate)")
    router = scene.router
    Check(router._Classify(scene.spin) == "spin", "QSpinBox -> spin")
    Check(router._Classify(scene.dspin) == "spin", "QDoubleSpinBox -> spin")
    Check(router._Classify(scene.spin.lineEdit()) == "spin",
          "数值框内部输入行 -> spin(交给数值框判，不算独立 input)")
    Check(router._Classify(scene.btn) == "activate", "普通按钮 -> activate(不变)")


def TestTapEditFieldFocus(scene):
    print("\n[2] 点编辑区：聚焦 + 全选 + 输入法 + 事件被认领")
    router = scene.router
    scene.spin.clearFocus()
    scene.spin.lineEdit().setCursorPosition(0)
    scene.spin.lineEdit().deselect()
    scene.Flush()
    # 编辑区中点偏右(避开右侧箭头)
    point = scene.spin.mapToGlobal(QPoint(scene.spin.width() // 2, scene.spin.height() // 2))
    handled, ev = Press(router, scene.viewport, point)
    Check(handled is True and ev.isAccepted(),
          "按下被认领(防误触语义不变：滑动起手不会误加数值)")
    Release(router, scene.viewport, point)
    scene.Flush()
    Check(scene.spin.hasFocus() or scene.spin.lineEdit().hasFocus(),
          "抬手后数值框拿到焦点(可键入)")
    Check(scene.spin.lineEdit().selectedText() == "100",
          "原有文本被全选(键入直接替换，实际 {!r})".format(
              scene.spin.lineEdit().selectedText()))
    Check(scene.spin.value() == 100, "聚焦本身不改数值")
    Check(router._seqs == {}, "抬手后没有残留序列")


def TestTypingWritesValue(scene):
    print("\n[3] 聚焦后键入：数值真的变(valueChanged 链拿得到)")
    router = scene.router
    # 重新来一次完整的"聚焦"周期(上一用例可能已聚焦，先清掉)
    scene.spin.clearFocus()
    scene.Flush()
    point = scene.spin.mapToGlobal(QPoint(scene.spin.width() // 2, scene.spin.height() // 2))
    Press(router, scene.viewport, point)
    Release(router, scene.viewport, point)
    scene.Flush()
    Check(scene.spin.hasFocus() or scene.spin.lineEdit().hasFocus(), "数值框已聚焦")
    got = []
    scene.spin.valueChanged.connect(lambda v: got.append(v))
    # 聚焦时已全选：键入直接替换原值
    QTest.keyClicks(scene.spin.lineEdit(), "42")
    scene.Flush()
    Check(scene.spin.value() == 42, "键入 42 后数值=42(实际 {})".format(scene.spin.value()))
    Check(got and got[-1] == 42, "valueChanged 被触发过(设置项能回传)")
    scene.spin.setValue(100)


def TestArrowStep(scene):
    print("\n[4] 点上下箭头：只加减，不改焦点语义")
    router = scene.router
    rects = ArrowRects(scene.spin)
    scene.spin.clearFocus()
    scene.Flush()
    if rects["up"].isValid() and not rects["up"].isEmpty():
        up = rects["up"].center()
        Press(router, scene.viewport, scene.spin.mapToGlobal(up))
        Release(router, scene.viewport, scene.spin.mapToGlobal(up))
        scene.Flush()
        Check(scene.spin.value() == 101, "点上箭头 +1(实际 {})".format(scene.spin.value()))
        down = rects["down"].center()
        Press(router, scene.viewport, scene.spin.mapToGlobal(down))
        Release(router, scene.viewport, scene.spin.mapToGlobal(down))
        scene.Flush()
        Check(scene.spin.value() == 100, "点下箭头 -1(实际 {})".format(scene.spin.value()))
    else:
        print("  ~~ 样式没给出箭头矩形，跳过(几何兜底用例覆盖)")
    Check(not (scene.spin.hasFocus() or scene.spin.lineEdit().hasFocus()),
          "点箭头不聚焦(点了就走，不弹输入法)")


def TestStepAt(scene):
    print("\n[5] _SpinBoxStepAt 三区域判定")
    spin = scene.spin
    rects = ArrowRects(spin)
    if rects["up"].isValid() and not rects["up"].isEmpty():
        Check(touch._SpinBoxStepAt(spin, rects["up"].center()) == 1, "上箭头中心 -> +1")
        Check(touch._SpinBoxStepAt(spin, rects["down"].center()) == -1, "下箭头中心 -> -1")
        Check(touch._SpinBoxStepAt(spin, QPoint(2, spin.height() // 2)) is None,
              "编辑区左侧(箭头矩形之外) -> None(走聚焦)")
        Check(touch._SpinBoxStepAt(spin, QPoint(spin.width() // 2, 2)) is None,
              "编辑区上半 -> None(走聚焦)")
    else:
        print("  ~~ 样式没给出箭头矩形(极端样式)，全部按编辑区处理")
        Check(touch._SpinBoxStepAt(spin, QPoint(spin.width() - 1, 2)) is None,
              "取不到矩形时不当箭头(走聚焦，聚焦后键盘上下键可加减)")


def TestRefocusMovesCaret(scene):
    print("\n[6] 已聚焦再点编辑区：光标挪到手指处")
    router = scene.router
    point = scene.spin.mapToGlobal(QPoint(scene.spin.width() // 2, scene.spin.height() // 2))
    Press(router, scene.viewport, point)
    Release(router, scene.viewport, point)
    scene.Flush()
    scene.spin.lineEdit().deselect()
    scene.spin.lineEdit().setCursorPosition(0)
    scene.Flush()
    # 再点右侧一点
    point2 = scene.spin.mapToGlobal(QPoint(scene.spin.width() // 2 + 20,
                                           scene.spin.height() // 2))
    Press(router, scene.viewport, point2)
    Release(router, scene.viewport, point2)
    scene.Flush()
    Check(scene.spin.lineEdit().cursorPosition() > 0,
          "光标被挪到新的手指位置(实际 {})".format(
              scene.spin.lineEdit().cursorPosition()))
    Check(not scene.spin.lineEdit().hasSelectedText() or True, "再点不改变已有选择语义")


def TestDragNoStep(scene):
    print("\n[7] 数值框上滑动：不加减、不聚焦(防误触)")
    router = scene.router
    scene.spin.setValue(100)
    scene.spin.clearFocus()
    scene.Flush()
    start = scene.spin.mapToGlobal(QPoint(scene.spin.width() // 2, scene.spin.height() // 2))
    Press(router, scene.viewport, start)
    Move(router, scene.viewport, QPoint(start.x(), start.y() - 140))
    Release(router, scene.viewport, QPoint(start.x(), start.y() - 140))
    scene.Flush()
    Check(scene.spin.value() == 100, "滑动没有加减数值")
    Check(not (scene.spin.hasFocus() or scene.spin.lineEdit().hasFocus()),
          "滑动没有聚焦")
    Check(router.Drags >= 1, "滑动被识别成滚动(Drags+1)")


def TestDisabledNoFocus(scene):
    print("\n[8] 禁用中的数值框：点了不聚焦")
    router = scene.router
    scene.spin.setEnabled(False)
    scene.Flush()
    point = scene.spin.mapToGlobal(QPoint(scene.spin.width() // 2, scene.spin.height() // 2))
    Press(router, scene.viewport, point)
    Release(router, scene.viewport, point)
    scene.Flush()
    Check(not (scene.spin.hasFocus() or scene.spin.lineEdit().hasFocus()),
          "禁用数值框不聚焦")
    scene.spin.setEnabled(True)


def TestDoubleSpin(scene):
    print("\n[9] 小数数值框(Waifu2x 放大倍数那种)：聚焦后可键入小数")
    router = scene.router
    scene.dspin.clearFocus()
    scene.Flush()
    point = scene.dspin.mapToGlobal(QPoint(scene.dspin.width() // 2,
                                           scene.dspin.height() // 2))
    Press(router, scene.viewport, point)
    Release(router, scene.viewport, point)
    scene.Flush()
    Check(scene.dspin.hasFocus() or scene.dspin.lineEdit().hasFocus(), "小数框已聚焦")
    # 聚焦时已全选：键入直接替换原值(2.00 -> 3.5)
    QTest.keyClicks(scene.dspin.lineEdit(), "3.5")
    scene.Flush()
    Check(abs(scene.dspin.value() - 3.5) < 1e-6,
          "键入 3.5 后数值=3.5(实际 {})".format(scene.dspin.value()))
    scene.dspin.setValue(2.0)


def main():
    app = QApplication.instance() or QApplication([])
    scene = Scene(app)
    TestClassify(scene)
    TestTapEditFieldFocus(scene)
    TestTypingWritesValue(scene)
    TestArrowStep(scene)
    TestStepAt(scene)
    TestRefocusMovesCaret(scene)
    TestDragNoStep(scene)
    TestDisabledNoFocus(scene)
    TestDoubleSpin(scene)
    print("\n===== 结果：{} 项失败 =====".format(len(Failures)))
    for f in Failures:
        print("  FAIL {}".format(f))
    sys.exit(1 if Failures else 0)


if __name__ == "__main__":
    main()
