# coding:utf-8
""" 宿主自检：分流设置页"在选项框附近滑动会误触选项框"

真机现象：在分流设置页(tab_4)里手指滑动，滑的过程中/松手时旁边的单选按钮、
勾选框被切掉，下拉选项框的值也被改掉。

根因：Qt 对"没人认领的触控"会**当场合成鼠标**(qguiapplication.cpp processTouchEvent)，
而这些选项框是在 mouseRelease 里切换状态的：

  * 合成鼠标的 press 落在选项框上，松手时手指**仍在它的矩形里** —— 分流页的
    QRadioButton/QCheckBox 被整行拉伸到 370~390px 宽、只有 17px 高，横着拖半个
    屏幕也还在里面，于是"滑动"被当成"点了一下"。
  * 触控路由(_TouchRouter)能拦住滚动区里被它认领的那部分，但它够不着的路径
    (Qt::Popup 里的下拉列表、还没被接管/不在滚动区里的控件、真机上 QScroller
    先把整条序列拿走的那几帧)照样会误触。

修复：选项框自己身上挂一道"点按门卫"(mobile_ui_touch._TapGate)，判据与路由同一套
(按下到松手含中途最远点的位移 > TouchSlopPx 就算滑动)，成立就吞掉这次 release。

这个自检分三组：
  A. 门卫本身(直接喂 source=MouseEventSynthesizedByQt 的鼠标事件，确定性最强)
     —— 合成鼠标的滑动不改选项、点按照常；**真鼠标**行为完全不变
  B. 真触控注入 + 触控路由(= 页面里的正常路径)
     —— 各种滑动形态都不改选项、点按生效、滑动仍被识别成滑动
  C. 下拉选项框：滑动不改值、点按能弹出列表

用法：python android/tools/host_test_tap_gate.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
                                   QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                                   QRadioButton, QScrollArea, QTableWidget, QVBoxLayout,
                                   QWidget)
    from PySide6.QtTest import QTest
except Exception as es:                      # pragma: no cover - CI 的宿主没有 PySide6
    print("SKIP: 本机没有 PySide6 ({})".format(es))
    sys.exit(0)

import tools.mobile_ui_touch as touch  # noqa: E402

# 反证用：JM_TAP_GATE_OFF=1 时把门卫关掉，A 组必须红(证明这组测的确实是这个 bug)
if os.environ.get("JM_TAP_GATE_OFF"):
    touch._WantsTapGate = lambda widget: False
    print("!! 门卫已按 JM_TAP_GATE_OFF 关闭(反证模式)")

Failures = []


def Check(condition, message):
    if condition:
        print("  ok  {}".format(message))
    else:
        Failures.append(message)
        print("  FAIL {}".format(message))


class Page:
    """ 一页分流设置页的缩样：滚动区 + 整行拉伸的单选/勾选 + 下拉框 + 表格勾选 """

    def __init__(self, app):
        self.app = app
        self.page = QWidget()
        self.page.resize(384, 720)
        lay = QVBoxLayout(self.page)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        inner = QWidget()
        inner.setMinimumHeight(2400)
        v = QVBoxLayout(inner)
        self.group = QButtonGroup(self.page)
        self.radios = []
        for i in range(4):
            h = QHBoxLayout()
            radio = QRadioButton("优先使用 ProxyIP 分流节点{}".format(i))  # 整行拉伸
            self.group.addButton(radio)
            h.addWidget(radio, 1)
            h.addWidget(QLabel("说明"))
            h.addWidget(QLineEdit("值%d" % i))
            v.addLayout(h)
            self.radios.append(radio)
        self.check = QCheckBox("启用 HTTP3（优先走 CDN 分流，失败再退回代理）")
        v.addWidget(self.check)
        self.edit = QLineEdit("abcdef")                     # 单行输入框
        v.addWidget(self.edit)
        self.text = QPlainTextEdit("多行输入框")             # 多行(鼠标事件落在 viewport)
        v.addWidget(self.text)
        self.combo = QComboBox()
        self.combo.addItems(["1", "2", "3", "4", "5", "6", "7", "8"])
        v.addWidget(self.combo)
        self.table = QTableWidget(5, 3)
        v.addWidget(self.table)
        v.addStretch(1)
        self.area.setWidget(inner)
        lay.addWidget(self.area)
        self.page.show()
        app.processEvents()
        self.cells = []
        for row in range(5):
            box = QCheckBox("节点%d" % row)
            self.table.setCellWidget(row, 0, box)
            self.cells.append(box)
        app.processEvents()
        self.device = QTest.createTouchDevice()
        self.radios[0].setChecked(True)
        app.processEvents()

    # -- 真触控注入 --------------------------------------------------------
    def Swipe(self, start, dx, dy, steps=8):
        seq = QTest.touchEvent(self.page.windowHandle(), self.device)
        seq.press(0, start).commit()
        self.app.processEvents()
        for i in range(1, steps + 1):
            seq = QTest.touchEvent(self.page.windowHandle(), self.device)
            seq.move(0, QPoint(start.x() + int(dx * i / steps),
                               start.y() + int(dy * i / steps))).commit()
            self.app.processEvents()
        seq = QTest.touchEvent(self.page.windowHandle(), self.device)
        seq.release(0, QPoint(start.x() + dx, start.y() + dy)).commit()
        self.app.processEvents()
        return self.State()

    def Tap(self, point):
        seq = QTest.touchEvent(self.page.windowHandle(), self.device)
        seq.press(0, point).commit()
        self.app.processEvents()
        seq = QTest.touchEvent(self.page.windowHandle(), self.device)
        seq.release(0, point).commit()
        self.app.processEvents()
        return self.State()

    # -- 直接喂"合成鼠标"(等价于 Qt 的未消费触控->鼠标合成) ----------------
    def MouseDrag(self, widget, dx, dy, steps=4, synthesized=True, x0=40):
        """ 直接喂鼠标事件；x0 是按下的横坐标(落在文案上，和手指落点一致)

        注意 QCheckBox/QRadioButton 的可点击矩形只有"指示器 + 文字"那么宽，
        按在文案上再横着拖个几十像素，松手时**还在**这个矩形里 —— 这就是真机上
        滑动被当成点击的几何前提(文案越长，误触窗口越宽)。
        """
        source = (Qt.MouseEventSource.MouseEventSynthesizedByQt if synthesized
                  else Qt.MouseEventSource.MouseEventNotSynthesized)
        y0 = widget.height() / 2.0
        start = QPointF(widget.mapToGlobal(QPoint(int(x0), int(y0))))
        if isinstance(widget, QPlainTextEdit):
            # 多行输入框的鼠标事件其实落在 viewport 上(和真机一致)
            widget = widget.viewport()
        self.SendMouse(QEvent.Type.MouseButtonPress, widget, QPointF(x0, y0), start, source)
        for i in range(1, steps + 1):
            pos = QPointF(x0 + dx * i / steps, y0 + dy * i / steps)
            glob = QPointF(start.x() + dx * i / steps, start.y() + dy * i / steps)
            self.SendMouse(QEvent.Type.MouseMove, widget, pos, glob, source)
        end = QPointF(x0 + dx, y0 + dy)
        globEnd = QPointF(start.x() + dx, start.y() + dy)
        self.SendMouse(QEvent.Type.MouseButtonRelease, widget, end, globEnd, source)
        self.app.processEvents()
        return self.State()

    def MouseTap(self, widget, synthesized=True, x0=40):
        return self.MouseDrag(widget, 0, 0, 0, synthesized, x0)

    def FocusState(self):
        return (self.edit.hasFocus(), self.text.hasFocus())

    def SendMouse(self, eventType, widget, local, glob, source):
        buttons = (Qt.MouseButton.NoButton if eventType == QEvent.Type.MouseButtonRelease
                   else Qt.MouseButton.LeftButton)
        event = QMouseEvent(eventType, local, QPointF(local), glob,
                            Qt.MouseButton.LeftButton, buttons,
                            Qt.KeyboardModifier.NoModifier, source)
        QApplication.sendEvent(widget, event)
        return

    # -- 工具 --------------------------------------------------------------
    def Center(self, widget, dx=0, dy=0):
        p = widget.mapToGlobal(widget.rect().center())
        return QPoint(p.x() + dx, p.y() + dy)

    def Reset(self):
        self.edit.clearFocus()
        self.edit.deselect()
        self.edit.setCursorPosition(0)
        self.text.clearFocus()
        self.radios[0].setChecked(True)
        self.check.setChecked(False)
        for box in self.cells:
            box.setChecked(False)
        self.combo.setCurrentIndex(0)
        self.area.verticalScrollBar().setValue(0)
        self.app.processEvents()

    def State(self):
        return ("".join("1" if r.isChecked() else "0" for r in self.radios),
                "1" if self.check.isChecked() else "0",
                "".join("1" if b.isChecked() else "0" for b in self.cells),
                self.combo.currentIndex())

    def EditState(self):
        """ 文本框这边关心的：聚焦 / 选区 / 光标 / 内容 """
        return (self.edit.hasFocus(), self.edit.selectedText(),
                self.edit.cursorPosition(), self.edit.text(),
                self.text.hasFocus(), self.text.textCursor().hasSelection())

    def Close(self):
        self.page.hide()
        self.page.deleteLater()
        self.app.processEvents()
        return


Baseline = ("1000", "0", "00000", 0)


def SwipeCases(page):
    """ 真机上"在选项框附近滑动"的各种形态 """
    radio = page.radios[1]
    wide = page.check
    box = page.cells[1]
    return [
        ("整行单选 横滑 40px", page.Center(radio), 40, 0),
        ("整行单选 横滑 90px", page.Center(radio), 90, 0),
        ("整行单选 斜滑 60/20", page.Center(radio), 60, 20),
        ("整行单选 上滑 160px", page.Center(radio), 0, -160),
        ("整行勾选 横滑 60px", page.Center(wide), 60, 0),
        ("整行勾选 斜滑 50/10", page.Center(wide), 50, 10),
        ("整行勾选 上滑 160px", page.Center(wide), 0, -160),
        ("表格勾选 横滑 40px", page.Center(box), 40, 0),
        ("表格勾选 上滑 160px", page.Center(box), 0, -160),
    ]


def TestGate(app):
    """ A. 门卫：合成鼠标的滑动不点击，点按照常，真鼠标不受影响 """
    print("\n[A] 点按门卫(直接喂合成鼠标事件)")
    page = Page(app)
    for widget in [page.check] + page.radios + page.cells + [page.combo]:
        touch.MarkTapClass(widget)
    app.processEvents()

    # 合成鼠标 + 拖动 = 滑动，不许切换(这些都是修复前会误触的形态)
    for name, dx, dy in (("整行勾选 横滑 30px", 30, 0),
                         ("整行勾选 横滑 60px", 60, 0),
                         ("整行勾选 斜滑 40/12", 40, 12),
                         ("整行勾选 回拖 -30px", -30, 0)):
        page.Reset()
        state = page.MouseDrag(page.check, dx, dy)
        Check(state == Baseline, "{} -> {}".format(name, state))
    for name, dx, dy in (("整行单选 横滑 30px", 30, 0),
                         ("整行单选 横滑 50px", 50, 0),
                         ("整行单选 斜滑 40/12", 40, 12)):
        page.Reset()
        state = page.MouseDrag(page.radios[1], dx, dy)
        Check(state == Baseline, "{} -> {}".format(name, state))
    page.Reset()
    state = page.MouseDrag(page.cells[1], 40, 0, x0=24)
    Check(state == Baseline, "表格勾选 横滑 40px -> {}".format(state))
    page.Reset()
    state = page.MouseDrag(page.radios[2], 20, 0)
    Check(state == Baseline, "单选 横滑 20px(刚过阈值) -> {}".format(state))

    # 合成鼠标 + 点按 = 正常点击
    page.Reset()
    state = page.MouseTap(page.radios[2])
    Check(state[0] == "0010", "合成鼠标点按单选 -> {}".format(state))
    page.Reset()
    state = page.MouseTap(page.check)
    Check(state[1] == "1", "合成鼠标点按勾选框 -> {}".format(state))
    page.Reset()
    state = page.MouseTap(page.cells[2])
    Check(state[2] == "00100", "合成鼠标点按表格勾选框 -> {}".format(state))

    # 真鼠标(桌面)：完全不走门卫，Qt 原生行为不变(按下不松手、在框内拖动再松开仍算点击)
    page.Reset()
    state = page.MouseDrag(page.check, 30, 0, synthesized=False)
    Check(state[1] == "1", "真鼠标在勾选框内拖动仍是点击(桌面行为不变) -> {}".format(state))
    page.Reset()
    state = page.MouseDrag(page.radios[1], 30, 0, synthesized=False)
    Check(state[0] == "0100", "真鼠标在单选上拖动仍是点击(桌面行为不变) -> {}".format(state))

    stats = touch.TapGateStats()
    Check(stats.get("suppressed", 0) >= 8, "门卫确实拦下了合成鼠标的滑动点击({} 次)".format(
        stats.get("suppressed")))
    page.Close()
    return True


def TestRouterPath(app):
    """ B. 真触控 + 触控路由(= 页面里的正常路径) """
    print("\n[B] 触控路由路径：滑动不改选项、点按照常")
    page = Page(app)
    touch.MakeScrollable(page.area)
    router = touch._TouchRouter()
    router.Enabled = True
    app.installEventFilter(router)
    app.processEvents()
    for widget in [page.check] + page.radios + page.cells + [page.combo]:
        touch.MarkTapClass(widget)          # 和 mobile_ui 的入口一致
    app.processEvents()

    for name, start, dx, dy in SwipeCases(page):
        page.Reset()
        state = page.Swipe(start, dx, dy)
        Check(state == Baseline, "{} -> {}".format(name, state))

    # 划出去再划回来(净位移≈0)：不许当成点按
    page.Reset()
    start = page.Center(page.radios[1])
    seq = QTest.touchEvent(page.page.windowHandle(), page.device)
    seq.press(0, start).commit()
    for i in list(range(1, 9)) + list(range(7, -1, -1)):
        seq = QTest.touchEvent(page.page.windowHandle(), page.device)
        seq.move(0, QPoint(start.x(), start.y() - 15 * i)).commit()
    seq = QTest.touchEvent(page.page.windowHandle(), page.device)
    seq.release(0, start).commit()
    app.processEvents()
    Check(page.State() == Baseline, "划远再划回原点不放选项 -> {}".format(page.State()))

    # 点按必须照常生效
    page.Reset()
    state = page.Tap(page.Center(page.radios[2]))
    Check(state[0] == "0010", "点按单选生效 -> {}".format(state))
    page.Reset()
    state = page.Tap(page.Center(page.check))
    Check(state[1] == "1", "点按勾选框生效 -> {}".format(state))
    page.Reset()
    state = page.Tap(page.Center(page.cells[2]))
    Check(state[2] == "00100", "点按表格勾选框生效 -> {}".format(state))

    # 滑动仍然被当成滑动(滚动交给 QScroller 完成；逐像素滚动由真机自检验)
    page.Reset()
    drags = router.Drags
    replayed = router.Replayed
    page.Swipe(page.Center(page.radios[3]), 0, -220)
    Check(router.Drags > drags, "在选项框上滑动被识别成滑动(Drags {} -> {})".format(
        drags, router.Drags))
    Check(router.Replayed == replayed, "滑动期间没有激活任何控件")

    # 滑动之后立刻点按：不许被上一次的惯性连累("滑完第一下点不动"是真机回归项)
    page.Reset()
    page.Swipe(page.Center(page.radios[3]), 0, -160)
    state = page.Tap(page.Center(page.check))
    Check(state[1] == "1", "滑动结束后立刻点按仍然生效 -> {}".format(state))
    page.Close()
    return True


def TestCombo(app):
    """ C. 下拉选项框：滑动不改值，点按能弹出列表 """
    print("\n[C] 下拉选项框")
    page = Page(app)
    touch.MakeScrollable(page.area)
    router = touch._TouchRouter()
    router.Enabled = True
    app.installEventFilter(router)
    for widget in [page.check] + page.radios + page.cells + [page.combo]:
        touch.MarkTapClass(widget)
    app.processEvents()

    page.Reset()
    page.Swipe(page.Center(page.combo), 60, 0)
    Check(page.combo.currentIndex() == 0, "横滑下拉框不改值 -> {}".format(
        page.combo.currentIndex()))
    page.Reset()
    page.Swipe(page.Center(page.combo), 0, -120)
    Check(page.combo.currentIndex() == 0 and not page.combo.view().isVisible(),
          "上滑下拉框不改值、不弹列表")

    # 合成鼠标路径(弹窗那种情形)：滑动不许改值
    page.Reset()
    page.MouseDrag(page.combo, 50, 0)
    Check(page.combo.currentIndex() == 0, "合成鼠标横滑下拉框不改值 -> {}".format(
        page.combo.currentIndex()))
    try:
        page.combo.hidePopup()
    except Exception:
        pass

    # 点按要能弹出列表
    page.Reset()
    page.Tap(page.Center(page.combo))
    Check(page.combo.view().isVisible(), "点按下拉框弹出列表")
    try:
        page.combo.hidePopup()
    except Exception:
        pass
    page.Close()
    return True


def TestInput(app):
    """ D. 文本框：滑动不聚焦/不弹键盘/不拖选；点按照常聚焦并落光标 """
    print("\n[D] 文本框(单行 + 多行)")
    page = Page(app)
    touch.MakeScrollable(page.area)
    router = touch._TouchRouter()
    router.Enabled = True
    app.installEventFilter(router)
    for widget in [page.check, page.edit, page.text] + page.radios + page.cells + [page.combo]:
        (touch.MarkTapGate(widget) if isinstance(widget, (QLineEdit, QPlainTextEdit))
         else touch.MarkTapClass(widget))
    app.processEvents()

    # 合成鼠标在文本框上滑动：不许聚焦、不许拖出选区、内容不变
    for name, widget, x0, dx in (("单行 横滑 60px", page.edit, 30, 60),
                                 ("单行 横滑 -40px", page.edit, 90, -40),
                                 ("单行 斜滑 30/14", page.edit, 30, 30),
                                 ("多行 横滑 60px", page.text, 30, 60),
                                 ("多行 竖滑 0/40", page.text, 30, 0)):
        page.Reset()
        before = page.EditState()
        if name.startswith("多行"):
            page.MouseDrag(widget, dx, (40 if name.endswith("0/40") else 0), x0=x0)
        else:
            page.MouseDrag(widget, dx, 14 if "斜滑" in name else 0, x0=x0)
        after = page.EditState()
        Check(after == before, "{} -> 聚焦/选区/内容都没变 {}".format(name, after))
    stats = touch.TapGateStats()
    Check(stats.get("input_suppressed", 0) >= 5,
          "门卫记下了 {} 次'滑动没落到输入框'".format(stats.get("input_suppressed")))

    # 点按：必须聚焦，且光标落在手指位置(点行尾 -> 光标在末尾)
    page.Reset()
    page.MouseTap(page.edit, x0=page.edit.width() - 6)
    Check(page.edit.hasFocus(), "合成鼠标点按单行框 -> 聚焦")
    Check(page.edit.cursorPosition() == len("abcdef"),
          "光标落在手指位置(行尾) -> {}".format(page.edit.cursorPosition()))
    Check(page.edit.selectedText() == "", "点按没有拖出选区")

    # 已聚焦时点按另一个位置：光标要跟着走(不是忽略)
    page.MouseTap(page.edit, x0=26)
    Check(not page.edit.hasFocus() and page.edit.cursorPosition() == 0
          or page.edit.cursorPosition() < 3,
          "已聚焦时点按更靠前的位置 -> 光标移过去({})".format(page.edit.cursorPosition()))

    # 多行框点按也要聚焦
    page.Reset()
    page.MouseTap(page.text, x0=20)
    Check(page.text.hasFocus(), "合成鼠标点按多行框 -> 聚焦")

    # 真鼠标：原生拖选行为完全不变
    page.Reset()
    page.edit.setFocus()
    page.edit.setCursorPosition(0)
    app.processEvents()
    page.MouseDrag(page.edit, 60, 0, x0=6, synthesized=False)
    Check(page.edit.selectedText() != "" or page.edit.cursorPosition() > 0,
          "真鼠标拖动仍然按 Qt 原生语义选字/移光标(桌面不变) selected={!r}".format(
              page.edit.selectedText()))

    # 触控路由路径：真触控在文本框上滑 -> 不聚焦；点按 -> 聚焦
    page.Reset()
    page.Swipe(page.Center(page.edit), 0, -160)
    Check(not page.edit.hasFocus(), "真触控在文本框上滑动 -> 没有聚焦(不弹键盘)")
    page.Reset()
    page.Tap(page.Center(page.edit))
    Check(page.edit.hasFocus(), "真触控点按文本框 -> 聚焦")
    page.Close()
    return True


def main():
    app = QApplication(sys.argv)
    TestGate(app)
    TestRouterPath(app)
    TestCombo(app)
    TestInput(app)
    print("\n门卫统计: 拦下 {} 次合成鼠标点击".format(touch.TapGateStats().get("suppressed")))
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
