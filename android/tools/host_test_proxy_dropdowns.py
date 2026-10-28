# coding:utf-8
""" 宿主自检：高级设置里的两个下拉（获取地区 / DOH 地址）

背景（真机反馈）：`获取地区` 点开是空的、`DOH` 点得开但点不中、自定义 DOH 无处可填。
这一份只测"下拉行为"本身，逐条断言：

  [0] 只读：DOH / 获取地区不能键入，但仍可点开下拉、程序写回仍生效；
            「添加 DOH 地址」的独立输入框仍然可编辑
  [1] 地区候选：来自已获取节点的国家，去重排序，第一项是「全部地区」；
                选中 -> 写回输入框 + 写 Setting + 立刻重新取节点（子域参数是二字代码）
  [2] DOH 列表：点输入框能开（已聚焦也能开）；点条目写回输入框并收起
  [3] 添加 DOH：未点「＋」之前是按钮不是输入框；点开后才能输入；
                非法地址不保存、合法地址进候选表并应用到输入框
  [4] 动画：展开/收起走 geometry 动画、曲线是 OutQuint、时长 200/120ms
  [5] 点外面才收起：落点在弹层里 / 输入框里都不收（按坐标判，不看事件接收者）

用法：python android/tools/host_test_proxy_dropdowns.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QEvent, QEasingCurve, QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except Exception as es:                      # pragma: no cover
    print("SKIP: 本机没有 PySide6 ({})".format(es))
    sys.exit(0)

# 手机端分支（子控件图层 + 坐标判定的 OutsideHider + 展开动画）在 Windows 宿主上
# 也要能测：把平台判定改成 Android，走的就是真机那条代码路。
from tools import platform_mobile
platform_mobile.IsAndroid = lambda: True

Failures = []


def Check(ok, message):
    if ok:
        print("  ok   {}".format(message))
    else:
        print("  FAIL {}".format(message))
        Failures.append(message)


class FakePoint(object):
    def __init__(self, x, y):
        self._pos = QPointF(x, y)

    def globalPosition(self):
        return self._pos


class FakeTouch(object):
    """ 够用的 TouchBegin 替身：只提供 type() 和 points() """

    def __init__(self, x, y):
        self.x, self.y = x, y

    def type(self):
        return QEvent.Type.TouchBegin

    def points(self):
        return [FakePoint(self.x, self.y)]


# ---------------------------------------------------------------- 建页面
def BuildPage(app, width=478, height=982):
    from interface.ui_login_new import Ui_LoginNew
    from PySide6.QtWidgets import QWidget

    class Owner(QWidget, Ui_LoginNew):
        def __init__(self):
            QWidget.__init__(self)
            Ui_LoginNew.__init__(self)
            self.setupUi(self)

    page = Owner()
    page.resize(width, height)
    page.show()
    page.tabWidget.setCurrentIndex(3)
    app.processEvents()
    return page


def BuildWidget(page):
    from view.user.login_proxy_new_widget import LoginProxyNewWidget
    import host_test_proxy_list_layout as Layout

    widget = LoginProxyNewWidget.__new__(LoginProxyNewWidget)
    widget.owner = page
    widget.allItems = Layout.BuildItems()
    widget.filter = "all"
    widget.sortMode = "smart"
    widget.dense = False
    widget.rowItems = {}
    widget.maxNum = 7
    widget.cdnIndex = 5
    widget.lastResult = {}
    widget.systemProxyValue = ""
    widget.isInitProxy = False
    for mode in range(4):
        page.radioProxyGroup.setId(getattr(page, "proxy_" + str(mode)), mode)
    page.proxy_0.setChecked(True)
    widget.InitCardTable()
    widget.InitUi()
    widget.RenderList()
    widget.UpdateAddrRow()
    from config.global_config import GlobalConfig
    page.dohLine.SetWordData(GlobalConfig.DohUrlList.value[:])   # __init__ 里做过
    widget.InitDropdowns()          # __init__ 里会调，这里手动补上
    return widget


def Settle(app, ms=300):
    from PySide6.QtCore import QElapsedTimer
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()


# ---------------------------------------------------------------- [0] 只读
def TestReadOnly(app, page, widget):
    print("\n[0] DOH / 获取地区只读：不能键入，但仍能下拉与写回")
    from tools import mobile_ui_touch as touch

    region = page.proxyIpEdit
    doh = page.dohLine
    Check(region.isReadOnly(), "获取地区是只读状态")
    Check(doh.isReadOnly(), "DOH 地址是只读状态")
    Check(region.isEnabled() and doh.isEnabled(), "只读不等于禁用（仍然可以点开候选）")
    Check(touch._TouchRouter._Classify(region) == "input",
          "只读地区框仍走 input 通道（点按能唤出弹层）")
    Check(touch._TouchRouter._Classify(doh) == "input",
          "只读 DOH 框仍走 input 通道（点按能唤出弹层）")

    region.setText("日本")
    region.setFocus()
    QTest.keyClicks(region, "zzz")
    app.processEvents()
    Check(region.text() == "日本", "键盘输入不会改掉地区内容（{}）".format(region.text()))

    text = "https://doh.pub/dns-query"
    doh.setText(text)
    doh.setFocus()
    QTest.keyClicks(doh, "zzz")
    app.processEvents()
    Check(doh.text() == text, "键盘输入不会改掉 DOH 内容（{}）".format(doh.text()))

    # 程序写回仍要走（下拉选中/加载设置/添加自定义地址都靠它）
    region.setText("美国")
    doh.setText("https://dns.alidns.com/dns-query")
    Check(region.text() == "美国" and doh.text() == "https://dns.alidns.com/dns-query",
          "setText 仍能正常写回/显示内容")

    # 聚焦只读框会按设计展开候选；收回去，后面的用例从“初始收起”开始
    doh.HideListView()
    Settle(app, 180)


# ---------------------------------------------------------------- [1] 地区
def TestRegion(app, page, widget):
    print("\n[1] 获取地区：候选来自节点 / 选中即生效 / 子域用代码")
    from view.user.login_proxy_new_widget import AllRegion
    from tools.region_code import RegionToCode

    region = page.proxyIpEdit
    words = region.words
    Check(words and words[0] == AllRegion, "第一项是「{}」".format(AllRegion))
    Check("美国" in words and "日本" in words, "候选里出现节点地区（{} 项）".format(len(words)))
    Check(len(words) == len(set(words)), "候选没有重复")

    page.testIpButton.setEnabled(False)      # 避免选中后真的去发网络请求
    region.setText("美国")
    Check(widget.RegionParam() == "us", "「美国」-> 子域参数 us（{}）".format(widget.RegionParam()))
    region.setText("中国香港")
    Check(widget.RegionParam() == "hk", "「中国香港」-> 子域参数 hk")
    region.setText(AllRegion)
    Check(widget.RegionParam() == "", "「全部地区」-> 不带子域")
    region.setText("US")
    Check(widget.RegionParam() == "us", "手敲代码 US 也认（小写成 us）")

    # 选中一项：走 wordSelected -> OnRegionPicked
    region.SetWordData(words)
    index = region.listView.model().index(words.index("日本"), 0)
    region.listView.clicked.emit(index)
    app.processEvents()
    from config.setting import Setting
    Check(region.text() == "日本", "点条目写回输入框（{}）".format(region.text()))
    Check(Setting.ProxyIpCountry.value == "日本", "写进 Setting.ProxyIpCountry")
    Check(widget.RegionParam() == "jp", "子域参数同步为 jp")

    # 节点里学到一个新地区 -> 候选自动刷新
    before = len(region.words)
    item = list(widget.allItems.values())[0]
    item.country = "巴西·圣保罗"
    widget.RefreshRegionWords()
    Check("巴西" in region.words and len(region.words) == before + 1,
          "新地区自动补进候选（{} -> {}）".format(before, len(region.words)))
    Check(RegionToCode("巴西·圣保罗") == "br", "带省份的名字也能映射（巴西·圣保罗 -> br）")


# ---------------------------------------------------------------- [2] 弹层
def TestPopover(app, page, widget):
    print("\n[2] 弹层：点得开（已聚焦也能开）/ 点条目即应用并收起")
    from component.line_edit import popup_list

    doh = page.dohLine
    popup = doh._jmPopup["widget"]
    Check(popup is not None and popup.isHidden(), "初始是收起的")

    doh.setFocus()
    app.processEvents()
    doh.Popover()                      # 已聚焦时再点一次（原来这里什么都不发生）
    Settle(app, 60)
    Check(not popup_list.IsHidden(doh), "已聚焦时点一下仍能展开")

    anim = doh._jmPopup.get("anim")
    Check(anim is not None, "展开走 geometry 动画")
    if anim is not None:
        Check(anim.easingCurve().type() == QEasingCurve.OutQuint, "曲线是 OutQuint")
        Check(anim.duration() == popup_list.PopupOpenMs, "时长 {}ms".format(popup_list.PopupOpenMs))
        anim.setCurrentTime(anim.duration())
        app.processEvents()
        end = anim.endValue()
        Check(abs(popup.height() - end.height()) <= 1,
              "动画结束高度={}（目标 {}）".format(popup.height(), end.height()))
        Check(popup.width() >= popup_list.PopupMinWidth, "宽度不小于 {}（{}）".format(
            popup_list.PopupMinWidth, popup.width()))

    model = doh.listView.model()
    text = model.data(model.index(2, 0))
    doh.listView.clicked.emit(model.index(2, 0))
    app.processEvents()
    Check(doh.text() == text, "点条目写回输入框（{}）".format(text))
    Hide = doh._jmPopup.get("anim")
    Settle(app, 200)
    Check(popup_list.IsHidden(doh), "选完自动收起")


# ---------------------------------------------------------------- [3] 添加
def TestAddDoh(app, page, widget):
    print("\n[3] 添加 DOH：「＋」之前不可输入 / 校验 / 保存并应用")
    from config.global_config import GlobalConfig

    doh = page.dohLine
    Check(doh.addButton is not None, "列表底部有「添加 DOH 地址」一栏")
    if doh.addButton is None:
        return
    Check(doh.addButton.isVisible() or not doh.addButton.isHidden(), "未解锁时显示的是按钮")
    Check(doh.addEdit.isHidden(), "未解锁时输入框是藏着的（点不到 = 不会触发输入）")

    doh.Popover()
    Settle(app, 60)
    doh.addButton.click()
    app.processEvents()
    Check(not doh.addEdit.isHidden() and doh.addEdit.isEnabled(), "点「＋」后换成可输入的真输入框")
    Check(not doh.addEdit.isReadOnly(), "自定义 DOH 输入框不受主 DOH 框只读影响")
    Check(doh.addButton.isHidden(), "按钮让位给输入框")

    count = len(doh.words)
    doh.addEdit.setText("doh.example.com/dns-query")     # 没有 https://
    doh._CommitAdd()
    app.processEvents()
    Check(len(doh.words) == count, "非法地址不保存（候选仍是 {} 条）".format(len(doh.words)))
    Check(not doh.addEdit.isHidden(), "非法地址时保持编辑态")

    url = "https://doh.example/dns-query"
    doh.addEdit.setText(url)
    doh._CommitAdd()
    app.processEvents()
    Check(doh.words and doh.words[0] == url, "合法地址进入候选首位")
    Check(doh.text() == url, "并应用到输入框")
    Check(GlobalConfig.DohUrlList.value[0] == url, "记进 GlobalConfig.DohUrlList")
    Check(doh.addEdit.isHidden() and not doh.addButton.isHidden(), "保存后回到「＋」按钮态")


# ---------------------------------------------------------------- [4] 点外面
def TestOutside(app, page, widget):
    print("\n[4] 只有真点在弹层/输入框外面才收起（按坐标判，不看事件接收者）")
    from component.line_edit import popup_list

    doh = page.dohLine
    state = doh._jmPopup
    hider = state.get("filter")
    Check(hider is not None, "手机端装了 OutsideHider")
    if hider is None:
        return

    doh.Popover()
    Settle(app, 220)
    popup = state["widget"]
    Check(not popup.isHidden(), "弹层已展开")

    center = popup.mapToGlobal(popup.rect().center())
    hider.eventFilter(page, FakeTouch(center.x(), center.y()))       # 接收者是宿主页，位置在弹层里
    app.processEvents()
    Check(not popup.isHidden(), "按在弹层里 -> 不收（原来这里会被判成点外面）")

    rect = doh.rect()
    inside = doh.mapToGlobal(rect.center())
    hider.eventFilter(page, FakeTouch(inside.x(), inside.y()))
    app.processEvents()
    Check(not popup.isHidden(), "按在输入框里 -> 也不收")

    hider.eventFilter(page, FakeTouch(2, 2))
    Settle(app, 200)
    Check(popup.isHidden(), "按在别处 -> 收起")


def main():
    app = QApplication([])
    print("PySide6 {} / offscreen".format(__import__("PySide6").__version__))

    page = BuildPage(app, 478)
    widget = BuildWidget(page)
    app.processEvents()

    TestReadOnly(app, page, widget)
    TestRegion(app, page, widget)
    TestPopover(app, page, widget)
    TestAddDoh(app, page, widget)
    TestOutside(app, page, widget)

    if Failures:
        print("\n{} 项不通过：".format(len(Failures)))
        for message in Failures:
            print("  - {}".format(message))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
