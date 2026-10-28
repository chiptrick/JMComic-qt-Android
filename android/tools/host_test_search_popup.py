# coding:utf-8
""" 宿主自检：搜索记录弹层"超出显示范围 + 点不动 + 布局变了不跟手"

真机现象(0.52)：
  1. 搜索框获得焦点后弹出的"搜索记录"列表**超出屏幕**，右侧内容被切掉；
  2. 列表里的记录**点了没反应**，选不到输入框里。

真机现象(0.65，IME 相关)：
  3. 点输入框弹 IME，窗口被 adjustResize 缩短、页面重新布局之后，已经打开的
     弹层停在旧位置：和输入框错开，或者下半截落在可见窗口外；
  4. 分屏/小窗/旋转同理；输入框被滚动条带走时弹层不跟随。

根因(见 docs/mobile_touch_and_recents_fix_plan.md)：
  * 弹层是 `setWindowFlags(Qt.ToolTip)` 的**第二个顶层窗口** —— Android 上这种窗口
    不激活、收不到触摸事件，手指落在列表上，事件其实给了下面那个窗口，
    `clicked` 永远不发；它还是本项目 eglSurface 死锁 abort 的同源路径。
  * 几何写死 `resize(max(500, self.width()), 高度=窗口一半)`：竖屏逻辑宽只有 480，
    500 必然溢出，且没做任何屏幕夹紧。
  * 另外 `QLabel("asdasdasdasd")` + 第二次 `QHBoxLayout` 挂在已有布局的 widget 上，
    会留下一个游离的调试标签。
  * 几何只在 Show 时算一次，之后宿主窗口/输入框/滚动区域怎么变都不重算。

现在两端共用 component/line_edit/popup_list.py：手机端是主窗口里的**子控件**，
几何夹在宿主内，点按走触控路由 -> `clicked` -> `setText`；弹层可见期间由
_PopupTracker 跟踪宿主窗口/输入框/祖先/滚动条变化，按当前布局重新锚定。

用法：python android/tools/host_test_search_popup.py
（Windows 上没有 `python` 时用 `py android/tools/host_test_search_popup.py`）
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import (QApplication, QLabel, QLineEdit, QScrollArea,
                                   QVBoxLayout, QWidget)
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


def PrepareEdit(edit):
    edit.cacheWords = list(Words)
    edit.SetCacheWord()


def WaitOpen():
    # 弹层用 OutQuint 做 geometry 展开；等动画到位后再量几何/点条目，
    # 否则读到的是起始帧的 2px 高度，触点也落不到真正的列表行上。
    QTest.qWait(popup_list.PopupOpenMs + 40)


def WaitReanchor():
    """ 等事件路径(processEvents 后的 0ms 合并) + 120ms 兜底定时器各跑一次 """
    QTest.qWait(popup_list.PopupReanchorMs + 40)


def CheckInside(widget, host, label):
    geometry = widget.geometry()
    Check(geometry.left() >= 0 and geometry.top() >= 0
          and geometry.right() <= host.width() - 1
          and geometry.bottom() <= host.height() - 1,
          "{} 完全在宿主内: {} 宿主 {}x{}".format(
              label, geometry, host.width(), host.height()))


def ExpectedBelowY(edit, host):
    """ 期望的弹层 top：贴着输入框下沿 +2（和 Show 的规则一致） """
    return edit.mapTo(host, QPoint(0, edit.height())).y() + 2


class Host:
    """ 带布局的普通页面（A/B/C 用；和真机页面一样由布局摆位置） """

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
        PrepareEdit(self.edit)
        app.processEvents()

    def Close(self):
        self.page.hide()
        self.page.deleteLater()
        self.app.processEvents()


class ManualHost:
    """ 手动摆位置的页面：用于"宿主缩放但输入框不动"这类精确场景 """

    def __init__(self, app, width=480, height=800, editRect=(20, 40, 240, 40)):
        self.app = app
        self.page = QWidget()
        self.page.resize(width, height)
        self.edit = ProbeEdit(self.page)
        self.edit.setGeometry(*editRect)
        self.page.show()
        PrepareEdit(self.edit)
        app.processEvents()

    def Close(self):
        self.page.hide()
        self.page.deleteLater()
        self.app.processEvents()


class ScrollHost:
    """ 输入框在 QScrollArea 里：滚动时 edit 会跟着内容控件一起移动 """

    def __init__(self, app, width=480, height=600):
        self.app = app
        self.page = QWidget()
        self.page.resize(width, height)
        outer = QVBoxLayout(self.page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.area = QScrollArea(self.page)
        self.area.setWidgetResizable(True)
        outer.addWidget(self.area)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        top = QLabel("顶部占位", content)
        top.setFixedHeight(300)
        lay.addWidget(top)
        self.edit = ProbeEdit(content)
        lay.addWidget(self.edit)
        bottom = QLabel("底部占位", content)
        bottom.setFixedHeight(700)
        lay.addWidget(bottom)
        self.area.setWidget(content)
        self.page.show()
        PrepareEdit(self.edit)
        app.processEvents()
        self.scroll = self.area.verticalScrollBar()

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
    WaitOpen()
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
    WaitOpen()
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
    WaitOpen()
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
    WaitOpen()
    Check(not popup_list.IsHidden(edit), "先确认弹层是打开的")
    # 点页面底部空白处：弹层只覆盖到输入框下方一小段，底部一定在弹层/输入框外
    # （不能点 host.other：它被弹层盖住了，命中测试会把事件送给弹层，算"点在里面"）
    QTest.mouseClick(host.page, Qt.LeftButton, Qt.NoModifier,
                     QPoint(host.page.width() // 2, host.page.height() - 20))
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
        # 桌面弹层现在也完整夹进屏幕可用区域
        Check(geometry.top() >= screen.top() and geometry.bottom() <= screen.bottom(),
              "浮层纵向也在屏幕内: y={} h={} 屏幕高={}".format(
                  geometry.top(), geometry.height(), screen.height()))
        host.Close()
    finally:
        popup_list._IsAndroid = original
    return True


def TestHostResizeWhileVisible(app):
    """ E. 弹层可见时宿主窗口缩放（IME/分屏/小窗）：重新锚定，且完全在宿主内 """
    print("\n[E] 弹层可见时宿主窗口缩放：重新锚定 + 完全夹在宿主内")
    host = ManualHost(app, editRect=(20, 300, 240, 40))
    edit = host.edit
    page = host.page
    edit.ShowListView()
    app.processEvents()
    WaitOpen()
    widget = edit.widget
    before = widget.geometry()
    Check(before.top() == ExpectedBelowY(edit, page),
          "初始贴在输入框下方: 弹层 top={} 输入框底={}(+2)".format(
              before.top(), before.top() - 2))

    # 1) 只缩窗口、不动输入框 = IME adjustResize 最坏情况：
    #    弹层原来算好的下方空间被吃掉，必须整体重算
    page.resize(480, 420)
    app.processEvents()                     # QTimer(0) 合并后的事件路径
    CheckInside(widget, page, "宿主缩到 480x420 后")
    Check(widget.geometry().bottom() <= page.height() - 1,
          "宿主变矮后弹层底边仍在新窗口内: bottom={} 宿主高={}".format(
              widget.geometry().bottom(), page.height()))
    Check(widget.geometry().top() != before.top() or widget.geometry().bottom() <= 420,
          "宿主变矮后弹层位置重新算过(原来 top={} bottom={})".format(
              before.top(), before.bottom()))

    # 2) 再缩窄：120ms 兜底定时器路径也要保证完全在内部
    page.resize(300, 420)
    app.processEvents()
    WaitReanchor()
    CheckInside(widget, page, "宿主变窄到 300x420 后")
    Check(widget.width() <= page.width() - 1,
          "宿主变窄后弹层宽度同步收缩: 宽={} 宿主宽={}".format(
              widget.width(), page.width()))

    # 3) 放大回去：要恢复"贴着输入框下方"
    page.resize(480, 800)
    app.processEvents()
    WaitReanchor()
    CheckInside(widget, page, "宿主放大回 480x800 后")
    Check(widget.geometry().top() == ExpectedBelowY(edit, page),
          "宿主放大后重新贴回输入框下方: top={} 期望={}".format(
              widget.geometry().top(), ExpectedBelowY(edit, page)))
    host.Close()
    return True


def TestEditMoveFollows(app):
    """ F. 输入框移动（布局变化/滚动）时弹层跟随，不做动画 """
    print("\n[F] 输入框移动时弹层跟随")
    host = ManualHost(app, editRect=(20, 40, 240, 40))
    edit = host.edit
    page = host.page
    edit.ShowListView()
    app.processEvents()
    WaitOpen()
    widget = edit.widget
    Check(widget.geometry().top() == ExpectedBelowY(edit, page),
          "初始贴在输入框下方: top={}".format(widget.geometry().top()))

    edit.setGeometry(40, 360, 260, 40)
    app.processEvents()
    WaitReanchor()
    Check(widget.geometry().top() == ExpectedBelowY(edit, page),
          "输入框下移后弹层跟随: top={} 期望={}".format(
              widget.geometry().top(), ExpectedBelowY(edit, page)))
    CheckInside(widget, page, "输入框移动后")

    # 往上移回：下方空间又够了，必须回到下方
    edit.setGeometry(20, 40, 240, 40)
    app.processEvents()
    WaitReanchor()
    Check(widget.geometry().top() == ExpectedBelowY(edit, page),
          "输入框移回上方后弹层也跟随: top={}".format(widget.geometry().top()))
    host.Close()
    return True


def TestScrollAreaFollow(app):
    """ F2. QScrollArea 滚动：弹层跟随；输入框滚出可视区后收起 """
    print("\n[F2] QScrollArea 滚动：弹层跟随输入框，滚出可视区后收起")
    host = ScrollHost(app)
    edit = host.edit
    page = host.page
    scroll = host.scroll
    Check(scroll.maximum() > 100,
          "滚动区域有可滚动范围: max={}".format(scroll.maximum()))
    edit.ShowListView()
    app.processEvents()
    WaitOpen()
    widget = edit.widget
    Check(not popup_list.IsHidden(edit), "滚动前弹层是打开的")
    Check(widget.geometry().top() == ExpectedBelowY(edit, page),
          "初始贴在输入框下方: top={}".format(widget.geometry().top()))

    scroll.setValue(scroll.value() + 80)
    app.processEvents()
    WaitReanchor()
    Check(not popup_list.IsHidden(edit), "滚动后弹层仍在")
    Check(widget.geometry().top() == ExpectedBelowY(edit, page),
          "滚动后弹层跟随输入框: top={} 期望={}".format(
              widget.geometry().top(), ExpectedBelowY(edit, page)))
    CheckInside(widget, page, "滚动后")

    # 输入框只露出一部分（还看得见一点）时不能收起，要重锚到可见窗口内
    # （IME 把窗口挤小、页面又把输入框推到边缘就是这种状态）
    scroll.setValue(320)
    app.processEvents()
    WaitReanchor()
    Check(not popup_list.IsHidden(edit),
          "输入框只露出一部分时弹层仍在(不能误收起): visibleRegion 非空")
    Check(widget.geometry().top() == ExpectedBelowY(edit, page),
          "部分露出时弹层跟随到输入框下沿: top={} 期望={}".format(
              widget.geometry().top(), ExpectedBelowY(edit, page)))
    CheckInside(widget, page, "输入框部分露出后")

    # 滚到输入框完全离开可视区 -> 弹层没有可见锚点，立即收起
    scroll.setValue(scroll.maximum())
    app.processEvents()
    WaitReanchor()
    Check(popup_list.IsHidden(edit), "输入框滚出可视区后弹层收起")
    host.Close()
    return True


def TestTinyHostClamp(app):
    """ G. 宿主缩得很小：弹层仍完全在宿主内（clamp + 列表内部滚动） """
    print("\n[G] 宿主缩到 150x130：弹层仍完全在宿主内")
    host = ManualHost(app, width=150, height=130, editRect=(10, 40, 120, 30))
    edit = host.edit
    page = host.page
    edit.ShowListView()
    app.processEvents()
    WaitOpen()
    widget = edit.widget
    CheckInside(widget, page, "150x130 宿主")
    Check(widget.width() >= 1 and widget.height() >= 1,
          "弹层没有被夹成 0 尺寸: {}x{}".format(widget.width(), widget.height()))
    Check(widget.height() <= page.height() - 2,
          "弹层高度 <= 宿主高度: h={} 宿主高={}".format(
              widget.height(), page.height()))
    # 高度装不下内容时，列表自己限高，靠内部滚动看剩下的行
    Check(edit.listView.maximumHeight() <= widget.height(),
          "列表限高到弹层高度内(内容装不下时内部滚动): listMax={} 弹层高={}".format(
              edit.listView.maximumHeight(), widget.height()))
    # 再缩到极限，也不能出现 0 或负尺寸
    # （先把输入框挪进 40x40 范围内：否则输入框自己就在窗口外，弹层按规则会收起）
    edit.setGeometry(2, 2, 20, 20)
    app.processEvents()
    page.resize(40, 40)
    app.processEvents()
    WaitReanchor()
    CheckInside(widget, page, "40x40 宿主")
    Check(widget.width() >= 1 and widget.height() >= 1,
          "极小程序下弹层尺寸仍 >=1: {}x{}".format(widget.width(), widget.height()))
    host.Close()
    return True


def TestBothSidesInsufficient(app):
    """ J. 上下都放不下完整内容：收缩高度贴到空间较大的一侧，不允许压住输入框

    真机证据：wm size 900x1600 且 IME 打开(adjustResize)后宿主窗口只剩约
    300x222dp，而搜索记录内容高约 190dp —— 上下都放不下。旧逻辑保留完整高度再
    夹 y，结果弹层被压回输入框上，看起来像"没跟着输入框走"。
    """
    print("\n[J] 上下空间都不够：收缩高度贴边，不压住输入框")
    # 1) 上方空间更大 -> 翻到上方，底边距输入框顶边 2px
    host = ManualHost(app, width=300, height=250, editRect=(20, 120, 100, 30))
    edit = host.edit
    page = host.page
    edit.ShowListView()
    app.processEvents()
    WaitOpen()
    widget = edit.widget
    contentHeight = edit._jmPopup.get("contentHeight", 0)
    CheckInside(widget, page, "300x250 宿主(上方更大)")
    Check(widget.height() < contentHeight,
          "内容装不下时收缩了弹层高度: 高={} 内容高={}".format(
              widget.height(), contentHeight))
    Check(widget.geometry().bottom() < edit.geometry().top(),
          "弹层整体在输入框上方(不压住输入框): 弹层bottom={} 输入框top={}".format(
              widget.geometry().bottom(), edit.geometry().top()))
    Check(edit.geometry().top() - (widget.geometry().bottom() + 1) == 2,
          "弹层底边(不含)与输入框顶边间隔 2px: 实际={}".format(
              edit.geometry().top() - (widget.geometry().bottom() + 1)))
    Check(edit.listView.maximumHeight() <= widget.height(),
          "列表限高在收缩后的弹层内(内部滚动): listMax={} 弹层高={}".format(
              edit.listView.maximumHeight(), widget.height()))
    host.Close()

    # 2) 下方空间更大 -> 贴下方，顶边距输入框底边 2px
    host = ManualHost(app, width=300, height=250, editRect=(20, 50, 100, 30))
    edit = host.edit
    page = host.page
    edit.ShowListView()
    app.processEvents()
    WaitOpen()
    widget = edit.widget
    CheckInside(widget, page, "300x250 宿主(下方更大)")
    Check(widget.geometry().top() > edit.geometry().bottom(),
          "弹层整体在输入框下方(不压住输入框): 弹层top={} 输入框bottom={}".format(
              widget.geometry().top(), edit.geometry().bottom()))
    Check(widget.geometry().top() - (edit.geometry().bottom() + 1) == 2,
          "弹层顶边与输入框底边(不含)间隔 2px: 实际={}".format(
              widget.geometry().top() - (edit.geometry().bottom() + 1)))
    host.Close()
    return True


def TestHideOnEditHide(app):
    """ H. 输入框隐藏/宿主窗口隐藏时弹层立即收起；重新打开能恢复 """
    print("\n[H] 输入框隐藏时弹层收起，重新显示能再打开")
    host = ManualHost(app, editRect=(20, 40, 240, 40))
    edit = host.edit
    page = host.page
    edit.ShowListView()
    app.processEvents()
    WaitOpen()
    Check(not popup_list.IsHidden(edit), "先确认弹层是打开的")

    edit.hide()
    app.processEvents()
    Check(popup_list.IsHidden(edit), "输入框 hide() 后弹层立即收起(不等收起动画)")

    edit.show()
    app.processEvents()
    edit.ShowListView()
    app.processEvents()
    WaitOpen()
    Check(not popup_list.IsHidden(edit), "输入框重新显示后能再次打开")
    CheckInside(edit.widget, page, "重新打开后")

    page.hide()
    app.processEvents()
    Check(popup_list.IsHidden(edit), "宿主窗口隐藏后弹层也收起")
    host.Close()
    return True


def TestReanchorApi(app):
    """ I. 对外 Reanchor() 能手动触发一次无动画重排 """
    print("\n[I] Reanchor() 手动重排接口")
    host = ManualHost(app, editRect=(20, 40, 240, 40))
    edit = host.edit
    page = host.page
    edit.ShowListView()
    app.processEvents()
    WaitOpen()
    widget = edit.widget
    # 只改几何但不给 Qt 事件循环机会（模拟"外壳自己知道布局变了"）
    edit.setGeometry(30, 420, 240, 40)
    rect = popup_list.Reanchor(edit)
    Check(rect is not None, "Reanchor() 返回新几何")
    Check(widget.geometry().top() == ExpectedBelowY(edit, page),
          "Reanchor() 后弹层贴到新的输入框下方: top={} 期望={}".format(
              widget.geometry().top(), ExpectedBelowY(edit, page)))
    Check(rect == widget.geometry(), "返回的矩形就是实际应用的矩形")
    CheckInside(widget, page, "Reanchor() 后")
    host.Close()
    return True


def Main():
    app = QApplication.instance() or QApplication(sys.argv)
    # 宿主不是 Android：把平台判定钉成 True，才能验证"手机端"那条分支
    popup_list._IsAndroid = lambda: True
    TestOverlayGeometry(app)
    TestClickApplies(app)
    TestOutsideHides(app)
    TestDesktopPath(app)
    TestHostResizeWhileVisible(app)
    TestEditMoveFollows(app)
    TestScrollAreaFollow(app)
    TestTinyHostClamp(app)
    TestBothSidesInsufficient(app)
    TestHideOnEditHide(app)
    TestReanchorApi(app)
    if Failures:
        print("\nFAIL: {} 项未通过".format(len(Failures)))
        for item in Failures:
            print("  - {}".format(item))
        return 1
    print("\nOK: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(Main())
