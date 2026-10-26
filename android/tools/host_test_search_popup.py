# coding:utf-8
""" 宿主自检：搜索记录弹层"超出显示范围 + 点不动"

真机现象(0.52)：
  1. 搜索框获得焦点后弹出的"搜索记录"列表**超出屏幕**，右侧内容被切掉；
  2. 列表里的记录**点了没反应**，选不到输入框里。

根因(见 docs/mobile_touch_and_recents_fix_plan.md)：
  * 弹层是 `setWindowFlags(Qt.ToolTip)` 的**第二个顶层窗口** —— Android 上这种窗口
    不激活、收不到触摸事件，手指落在列表上，事件其实给了下面那个窗口，
    `clicked` 永远不发；它还是本项目 eglSurface 死锁 abort 的同源路径。
  * 几何写死 `resize(max(500, self.width()), 高度=窗口一半)`：竖屏逻辑宽只有 480，
    500 必然溢出，且没做任何屏幕夹紧。
  * 另外 `QLabel("asdasdasdasd")` + 第二次 `QHBoxLayout` 挂在已有布局的 widget 上，
    会留下一个游离的调试标签。

现在两端共用 component/line_edit/popup_list.py：手机端是主窗口里的**子控件**，
几何夹在宿主内，点按走触控路由 -> `clicked` -> `setText`。

用法：python android/tools/host_test_search_popup.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import (QApplication, QLabel, QLineEdit, QVBoxLayout,
                                   QWidget)
    from PySide6.QtTest import QTest
except Exception as es:                      # pragma: no cover - 宿主没有 PySide6
    print("SKIP: 本机没有 PySide6 ({})".format(es))
    sys.exit(0)

import component.line_edit.popup_list as popup_list  # noqa: E402
import component.line_edit.search_line_edit as search_line_edit  # noqa: E402
import tools.mobile_ui_touch as touch  # noqa: E402

Failures = []
Words = ["全彩 人妻", "全彩 -人妻", "标签：纯爱", "作者：某某某", "jm123456"]


def Check(condition, message):
    if condition:
        print("  ok  {}".format(message))
    else:
        print("  FAIL {}".format(message))
        Failures.append(message)


class ProbeEdit(search_line_edit.SearchLineEdit):
    """ 把 Search() 换掉：宿主上没有 QtOwner().owner，真搜索会抛异常 """

    def __init__(self, parent=None):
        self.searched = []
        search_line_edit.SearchLineEdit.__init__(self, parent)

    def Search(self):
        self.searched.append(self.text())


class Host:
    def __init__(self, app, width=480, height=800):
        self.app = app
        self.page = QWidget()
        self.page.resize(width, height)
        lay = QVBoxLayout(self.page)
        self.edit = ProbeEdit(self.page)
        lay.addWidget(self.edit)
        self.other = QLabel("页面别处", self.page)
        lay.addWidget(self.other)
        lay.addStretch(1)
        self.page.show()
        self.edit.cacheWords = list(Words)
        self.edit.SetCacheWord()
        app.processEvents()

    def Close(self):
        self.page.hide()
        self.page.deleteLater()
        self.app.processEvents()


def TestOverlayGeometry(app):
    """ A. 手机端：子控件图层 + 几何夹在宿主窗口内 """
    print("\n[A] 手机端弹层：子控件图层，不超出宿主窗口")
    host = Host(app)
    edit = host.edit
    edit.ShowListView()
    app.processEvents()
    widget = edit.widget
    geometry = widget.geometry()

    Check(widget.isWindow() is False,
          "弹层不是顶层窗口(原来 Qt.ToolTip 顶层窗在 Android 上点不动)")
    Check(widget.parentWidget() is host.page, "弹层挂在主窗口里 -> {}".format(
        widget.parentWidget()))
    Check(geometry.left() >= 0 and geometry.right() <= host.page.width(),
          "弹层横向不溢出: x={} w={} 宿主宽={}".format(
              geometry.left(), geometry.width(), host.page.width()))
    Check(geometry.top() >= 0 and geometry.bottom() <= host.page.height(),
          "弹层纵向不溢出: y={} h={} 宿主高={}".format(
              geometry.top(), geometry.height(), host.page.height()))
    Check(geometry.width() <= host.page.width() - 4,
          "宽度 <= 宿主宽(原来写死 max(500,..)，480 的屏幕必然溢出) -> {}".format(
              geometry.width()))
    Check(geometry.height() >= popup_list.PopupMinHeight,
          "高度有下限(不会压成一条缝) -> {}".format(geometry.height()))
    # 条目文字用省略号，不允许把行撑高后互相顶开
    Check(edit.listView.textElideMode() == Qt.ElideRight, "列表文字右侧省略")
    host.Close()
    return True


def TestClickApplies(app):
    """ B. 点按列表项 -> 写回输入框(走真触控 + 触控路由 = 真机路径) """
    print("\n[B] 点搜索记录能应用回输入框")
    host = Host(app)
    edit = host.edit
    edit.ShowListView()
    app.processEvents()
    view = edit.listView
    # 触控路由：真机上"点按激活"就是这条链(见 mobile_ui_touch._ActivateItemView)
    touch.MakeScrollable(view)
    router = touch._TouchRouter()
    router.Enabled = True
    app.installEventFilter(router)
    device = QTest.createTouchDevice()

    index = view.model().index(2, 0)
    rect = view.visualRect(index)
    point = view.viewport().mapToGlobal(rect.center())
    seq = QTest.touchEvent(host.page.windowHandle(), device)
    seq.press(0, point).commit()
    app.processEvents()
    seq = QTest.touchEvent(host.page.windowHandle(), device)
    seq.release(0, point).commit()
    app.processEvents()

    Check(edit.text() == Words[2],
          "点第 3 条 -> 输入框变成 {!r}(实际 {!r})".format(Words[2], edit.text()))
    Check(edit.searched and edit.searched[-1] == Words[2],
          "点完就发起了搜索 -> {}".format(edit.searched[-1:]))

    # 换一条再点(确认不是"碰巧第一条")
    edit.clear()
    edit.ShowListView()
    app.processEvents()
    index = view.model().index(0, 0)
    point = view.viewport().mapToGlobal(view.visualRect(index).center())
    seq = QTest.touchEvent(host.page.windowHandle(), device)
    seq.press(0, point).commit()
    app.processEvents()
    seq = QTest.touchEvent(host.page.windowHandle(), device)
    seq.release(0, point).commit()
    app.processEvents()
    Check(edit.text() == Words[0],
          "点第 1 条 -> 输入框变成 {!r}(实际 {!r})".format(Words[0], edit.text()))

    app.removeEventFilter(router)
    host.Close()
    return True


def TestOutsideHides(app):
    """ C. 点到别处自动收起(子控件图层不抢焦点，focusOut 靠不住) """
    print("\n[C] 点页面别处，弹层自动收起")
    host = Host(app)
    edit = host.edit
    edit.ShowListView()
    app.processEvents()
    Check(not popup_list.IsHidden(edit), "先确认弹层是打开的")
    QTest.mouseClick(host.other, Qt.LeftButton)
    app.processEvents()
    Check(popup_list.IsHidden(edit), "点别处后收起")
    host.Close()
    return True


def TestDesktopPath(app):
    """ D. 桌面端保持原来的浮层窗口(桌面行为不变) """
    print("\n[D] 桌面端仍是输入框下方的浮层")
    original = popup_list._IsAndroid
    popup_list._IsAndroid = lambda: False
    try:
        host = Host(app)
        edit = host.edit
        edit.ShowListView()
        app.processEvents()
        widget = edit.widget
        Check(widget.isWindow() is True, "桌面端弹层仍是独立浮层")
        windowType = widget.windowFlags() & Qt.WindowType_Mask
        Check(windowType == Qt.WindowType.ToolTip, "桌面端窗口类型 ToolTip(原行为) -> {}".format(
            windowType))
        screen = QApplication.primaryScreen().availableGeometry()
        geometry = widget.geometry()
        Check(geometry.right() <= screen.right() and geometry.left() >= screen.left(),
              "浮层不伸出屏幕: x={} w={} 屏幕宽={}".format(
                  geometry.left(), geometry.width(), screen.width()))
        host.Close()
    finally:
        popup_list._IsAndroid = original
    return True


def Main():
    app = QApplication.instance() or QApplication(sys.argv)
    # 宿主不是 Android：把平台判定钉成 True，才能验证"手机端"那条分支
    popup_list._IsAndroid = lambda: True
    TestOverlayGeometry(app)
    TestClickApplies(app)
    TestOutsideHides(app)
    TestDesktopPath(app)
    if Failures:
        print("\nFAIL: {} 项未通过".format(len(Failures)))
        for item in Failures:
            print("  - {}".format(item))
        return 1
    print("\nOK: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(Main())
