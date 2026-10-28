# coding:utf-8
""" 宿主自检：分流节点列表（整页滚动版）

背景（真机截图反馈）：上一版把 6 条线路压成 2 行 chip，452px 宽下每格只剩 ~62px，
主题的单选指示器又要 24px，"连接超时 / 4.71MB/s" 全被裁掉；列表还是自己滚。

这一版的三条契约，逐条断言：

  [1] 结构：线路区恢复 4 列 × 6 行；表格不再自己滚（高度=内容）；
            底部「高级 / 测试 IP 分流」在滚动区之外，常驻可见
  [2] 列表：50 个节点全部建行、行高与卡片一致、卡片内容不越界
  [3] 数据长度：360 / 478 / 520 下 IPv4 / 32 字符 IPv6 一律不省略
  [4] 整页滚动：滚到页面底部后，底栏几何不变、行高不变；
            滚轮落在列表上会转发给页面（而不是被表格吃掉）
  [5] 高级面板：OutBack 曲线、从 0 长到内容高、展开后有描边、收起后隐藏且描边撤掉
  [6] 交互：分组筛选、排序、选中、空分组占位、密度、代理模式

用法：python android/tools/host_test_proxy_list_layout.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget
except Exception as es:                      # pragma: no cover
    print("SKIP: 本机没有 PySide6 ({})".format(es))
    sys.exit(0)

Failures = []


def Check(ok, message):
    if ok:
        print("  ok   {}".format(message))
    else:
        print("  FAIL {}".format(message))
        Failures.append(message)


# ---------------------------------------------------------------- 数据
def BuildItems():
    """ 用 GlobalConfig 里的真实节点 + 接近真机的测速结果（含 IPv6 / 长 ISP / 失败项） """
    from config.global_config import GlobalConfig
    from view.user.login_proxy_new_widget import IpItem

    countries = [
        ("日本·东京", "Oracle Corporation", 152, 210),
        ("澳大利亚·悉尼", "Micron21 Pty Ltd", 318, 402),
        ("中国香港", "Tencent Cloud LLC", 48, 96),
        ("美国·阿什本", "Oracle Corporation", 186, 240),
        ("美国·旧金山", "DigitalOcean, LLC", 132, 188),
        ("德国·法兰克福", "DigitalOcean, LLC", 276, 344),
        ("印度·孟买", "Microsoft Corporation", 0, 0),
        ("美国·纽约", "DigitalOcean, LLC", 168, 205),
        ("新加坡", "Tencent Cloud LLC", 62, 118),
        ("中国香港", "Tencent Cloud LLC", 44, 88),
        ("印度尼西亚·雅加达", "PT Beon Intermedia", 420, 0),
        ("美国·洛杉矶", "Zenlayer Inc", 388, 0),
        ("美国·洛杉矶", "ColoCrossing", 340, 0),
        ("日本·大阪", "Oracle Corporation", 118, 164),
        ("荷兰·阿姆斯特丹", "Packet Host, Inc.", 310, 0),
        ("美国·圣何塞", "Alibaba (US) Technology Co., Ltd.", 204, 268),
        ("美国·硅谷", "Alibaba Cloud LLC", 190, 254),
        ("日本·东京", "Oracle Corporation", 96, 142),
        ("芬兰·赫尔辛基", "Hetzner Online GmbH", 356, 0),
        ("加拿大·多伦多", "DigitalOcean, LLC", 212, 288),
        ("美国·洛杉矶", "ColoCrossing", 366, 0),
        ("德国·法兰克福", "Hetzner Online GmbH", 298, 372),
        ("德国·纽伦堡", "netcup GmbH", 322, 398),
        ("美国·芝加哥", "EGIHosting", 244, 306),
        ("美国·圣何塞", "Hurricane Electric LLC", 176, 228),
        ("英国·伦敦", "Iomart Cloud Services Ltd", 284, 350),
    ]

    items = {}
    index = 0
    for j, ip in enumerate(GlobalConfig.ProxyIpList.value):
        country, isp, delay, download = countries[j % len(countries)]
        item = IpItem(index, j + 1, ip, True, False)
        item.country, item.asn = country, isp
        item.delay, item.downloadDelay = delay, download
        if delay == 0:
            item.isFail = True
            item.st = 1021        # 连接超时
        items[index] = item
        index += 1

    for j, ip in enumerate(GlobalConfig.BestCfIpList.value):
        item = IpItem(index, j + 1, ip, False, False)
        item.country = "中国香港" if j % 3 else "美国·Anycast"
        item.asn = "Cloudflare, Inc."
        item.delay = 44 + j * 12
        item.downloadDelay = 90 + j * 18
        if j == 6:
            item.isFail = True
            item.st = 1024
            item.delay = 0
            item.downloadDelay = 0
        items[index] = item
        index += 1
    return items


# ---------------------------------------------------------------- 页面
def BuildPage(app, width=478, height=982):
    from interface.ui_login_new import Ui_LoginNew

    class Owner(QWidget, Ui_LoginNew):
        """ 只借用 Ui_LoginNew 的控件集合（和 LoginNewView 一样把控件挂到 self） """

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
    """ 调真实驱动的方法（跳过 __init__ 里的网络/设置副作用） """
    from view.user.login_proxy_new_widget import LoginProxyNewWidget
    widget = LoginProxyNewWidget.__new__(LoginProxyNewWidget)
    widget.owner = page
    widget.allItems = BuildItems()
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
    return widget


# ---------------------------------------------------------------- 断言
def TestStructure(app, page, widget):
    print("\n[1] 结构：线路恢复 4 列网格 / 表格不自滚 / 底栏在滚动区之外")
    table = page.tableWidget

    Check(isinstance(page.proxyScrollArea, QScrollArea), "存在整页滚动区 proxyScrollArea")
    Check(table.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff,
          "表格竖直滚动条已关闭（改由页面统一滚动）")
    Check(table.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff, "表格不需要横向滚动")
    Check(table.columnCount() == 1, "表格仍是单列卡片容器({})".format(table.columnCount()))

    content = page.proxyScrollContent
    Check(page.proxyScrollArea.widget() is content, "滚动区内容控件就位")
    pageH = content.sizeHint().height()
    viewH = page.proxyScrollArea.viewport().height()
    Check(pageH > viewH, "页面内容比视口高、确实需要整页滚动（{} > {}）".format(
        int(pageH), viewH))

    Check(not page.proxyScrollArea.isAncestorOf(page.proxyFoot),
          "底栏不在滚动区里（滚动时不会跟着跑）")
    Check(page.proxyFoot.isVisible(), "底栏可见")
    Check(page.testIpButton.isVisible(), "「测试 IP 分流」常驻可见")
    Check(page.proxyAdvButton.isVisible(), "「高级」常驻可见")

    rows = 0
    for i in (1, 2, 3, 4, 5, 6):
        if getattr(page, "radioButton_" + str(i)).isVisible():
            rows += 1
    Check(rows == 6, "线路网格 6 行都在（{}）".format(rows))
    Check(page.label_18.isVisible() and page.label_19.isVisible()
          and page.label_20.isVisible() and page.label_21.isVisible(),
          "网格表头 Api分流 / 延迟 / 图片分流 / 速度 都在")
    radio6 = page.radioButton_6
    Check("US反代分流" == radio6.text(), "最长的一项名字是「{}」".format(radio6.text()))
    Check(radio6.width() >= radio6.sizeHint().width(),
          "「US反代分流」没有被挤窄（{} >= {}）".format(
              radio6.width(), radio6.sizeHint().width()))


def TestList(app, page, widget):
    print("\n[2] 列表：全部节点建行、行高=卡片高、表格高度=内容")
    from component.list.proxy_node_card import ProxyNodeCard

    table = page.tableWidget
    total = len(widget.allItems)
    Check(table.rowCount() == total, "全部 {} 个节点都建了行".format(total))

    bad_height, bad_overflow = [], []
    for row in range(table.rowCount()):
        card = table.cellWidget(row, 0)
        if not isinstance(card, ProxyNodeCard):
            bad_height.append(row)
            continue
        if table.rowHeight(row) != card.RowHeight():
            bad_height.append(row)
        limit = card.width() - 1
        for child in card.findChildren(QLabel):
            if child.geometry().right() > limit + 1:
                bad_overflow.append((row, child.text()[:8]))
    Check(not bad_height, "行高与卡片高度一致（异常 {}）".format(bad_height[:5]))
    Check(not bad_overflow, "卡片内文字不越出右边界（异常 {}）".format(bad_overflow[:5]))

    expected = sum(table.rowHeight(r) for r in range(table.rowCount())) + 2
    Check(abs(table.height() - expected) <= 2,
          "表格高度=内容高度（{} ≈ {}）".format(table.height(), expected))
    Check(table.verticalScrollBar().maximum() == 0,
          "表格自身滚动范围为 0（不再有内部滚动）")


def TestLengths(app):
    print("\n[3] 数据长度：360 / 478 / 520，IP 一律不省略（含 32 字符 IPv6）")
    from component.list.proxy_node_card import ProxyNodeCard

    for width in (360, 478, 520):
        page = BuildPage(app, width)
        widget = BuildWidget(page)
        app.processEvents()
        page.grab()
        app.processEvents()
        table = page.tableWidget
        elided, ipv6 = [], 0
        for row in range(table.rowCount()):
            card = table.cellWidget(row, 0)
            if not isinstance(card, ProxyNodeCard):
                continue
            item = widget.rowItems[row]
            if ":" in item.ip:
                ipv6 += 1
            if card.ipLabel.text() != item.ip:
                elided.append(item.ip)
        Check(not elided, "{}px：{} 项全部完整显示（IPv6 {} 个，省略 {}）".format(
            width, table.rowCount(), ipv6, len(elided)))
        if width == 478:
            page.grab().save(GrabPath())
        page.hide()
        page.deleteLater()
        app.processEvents()


def TestPageScroll(app, page, widget):
    print("\n[4] 整页滚动：底栏固定、行高不变、滚轮转发给页面")
    area = page.proxyScrollArea
    bar = area.verticalScrollBar()
    table = page.tableWidget

    foot_before = page.proxyFoot.geometry()
    heights_before = [table.rowHeight(r) for r in range(table.rowCount())]

    # 先画一帧：QScrollArea 的滚动范围要等布局/绘制后才算出来（这里之前是 0）
    page.grab()
    app.processEvents()
    bar.SetSmooth(False)          # SmoothScrollBar 是 500ms 动画，测试里先关掉才能立刻跳
    bar.setValue(bar.maximum())
    app.processEvents()

    Check(bar.value() > 0, "页面滚到了底部（value={} / max={}）".format(bar.value(), bar.maximum()))
    Check(page.proxyFoot.geometry() == foot_before, "滚动后底栏几何完全不变（固定的）")
    Check([table.rowHeight(r) for r in range(table.rowCount())] == heights_before,
          "滚动后各行行高不变（表格布局没被滚动影响）")
    Check(page.proxyFoot.visibleRegion().boundingRect().height() >= page.proxyFoot.height() - 1,
          "滚到底后底栏仍然完整可见")

    # 滚轮落在列表上：应转发给页面，而不是被表格吃掉
    bar.setValue(0)
    app.processEvents()
    viewport = table.viewport()
    center = QPointF(viewport.rect().center())
    event = QWheelEvent(center, center, QPoint(0, 0), QPoint(0, -120), Qt.NoButton,
                        Qt.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(viewport, event)
    app.processEvents()
    Check(bar.value() > 0, "滚轮落在列表上 -> 页面滚动（value={}）".format(bar.value()))
    Check(table.verticalScrollBar().value() == 0, "表格自己没有跟着滚")
    bar.SetSmooth(True)


def TestAdvPanel(app, page, widget):
    print("\n[5] 高级面板：OutBack 曲线 / 从 0 长上去 / 描边 / 收起后隐藏")
    panel = page.proxyAdvPanel
    frame = page.proxyAdvFrame
    anim = widget.advAnim

    from PySide6.QtCore import QEasingCurve
    Check(anim.easingCurve().type() == QEasingCurve.OutBack,
          "缓动曲线是 OutBack（{}）".format(anim.easingCurve().type()))
    Check(not panel.isVisible(), "默认收起")
    Check(frame.styleSheet() == "", "收起时没有描边")

    widget.OnAdvClicked()
    app.processEvents()
    Check(panel.isVisible(), "点「高级」后面板可见")
    Check(anim.state() == anim.State.Running, "动画正在跑（不是瞬间弹出）")
    target = anim.endValue()
    Check(target > 100, "目标高度=内容高度（{}px）".format(target))

    # OutBack 曲线前半段低于目标、接近尾声会"过冲"超过目标再回落 —— 这两点合起来
    # 才证明它是非线性（线性曲线永远 h <= target）
    anim.setCurrentTime(int(anim.duration() * 0.30))
    app.processEvents()
    early = panel.height()
    Check(0 < early < target, "30% 处高度 {} 还没到目标 {}".format(early, target))

    anim.setCurrentTime(int(anim.duration() * 0.75))
    app.processEvents()
    overshoot = panel.height()
    Check(overshoot > target, "75% 处过冲到 {} > 目标 {}（OutBack 特征）".format(overshoot, target))

    anim.setCurrentTime(anim.duration())
    app.processEvents()
    Check(panel.height() == target, "结束时高度回到目标（{}）".format(panel.height()))
    Check("border" in frame.styleSheet().lower(), "展开后有 1px 描边")

    widget.OnAdvClicked()
    app.processEvents()
    widget.advAnim.setCurrentTime(widget.advAnim.duration())
    app.processEvents()
    Check(not panel.isVisible(), "再点一次收起后面板隐藏")
    Check(frame.styleSheet() == "", "收起后描边被撤掉（不留亮线）")
    Check(page.proxyAdvButton.text() == "高级", "按钮文案回到「高级」")


def TestInteract(app, page, widget):
    print("\n[6] 交互：分组计数 / 排序 / 选中 / 空分组 / 密度 / 代理模式")
    widget.RenderList()
    Check("全部 {}".format(len(widget.allItems)) == page.proxyFilterAll.text(),
          "分组按钮带数量：{}".format(page.proxyFilterAll.text()))

    widget.filter = "proxy"
    widget.RenderList()
    app.processEvents()
    Check(page.tableWidget.rowCount() == 26,
          "只看 ProxyIP：26 行（{}）".format(page.tableWidget.rowCount()))

    widget.filter = "all"
    widget.sortMode = "lat"
    widget.RenderList()
    alive = [widget.rowItems[r].delay for r in range(page.tableWidget.rowCount())
             if widget.rowItems[r].delay]
    bad = [i for i in range(1, len(alive)) if alive[i] < alive[i - 1]]
    Check(not bad, "按延迟排序（逆序位置 {}）".format(bad[:3]))

    page.tableWidget.selectRow(2)
    app.processEvents()
    Check(widget.rowItems[2].isSelect, "点行即选中（{}）".format(widget.rowItems[2].ip))
    Check(widget.rowItems[2].ip in page.proxyStatusLabel.text(), "底栏显示已选节点")

    saved = widget.allItems
    widget.allItems = {}
    widget.RenderList()
    app.processEvents()
    Check(page.tableWidget.rowCount() == 0 and widget.emptyLabel.isVisible(), "空分组显示占位")
    widget.allItems = saved
    widget.RenderList()
    app.processEvents()

    before = page.tableWidget.height()
    page.proxyDensityButton.click()
    app.processEvents()
    Check(page.tableWidget.height() < before,
          "紧凑密度后表格高度跟着变小（{} -> {}）".format(before, page.tableWidget.height()))
    page.proxyDensityButton.click()
    app.processEvents()

    for mode, expect in ((0, "proxyHint"), (1, "httpLine"), (2, "sockEdit"), (3, "checkLabel")):
        button = getattr(page, "proxy_" + str(mode))
        button.setChecked(True)
        widget.OnProxyModeChanged(button)
        app.processEvents()
        shown = [n for n in ("proxyHint", "httpLine", "sockEdit", "proxyLabel", "checkLabel")
                 if getattr(page, n).isVisible()]
        Check(shown == [expect], "代理模式 {} 只显示 {}".format(mode, shown))


def LoadRealFonts():
    """ 离屏环境常常一个字体族都没有（Qt 回退成"每字符固定 13px"的占位字体），
        那种度量下算出来的"放不下"是假象。显式加载系统等宽字体让测量接近真机。 """
    from PySide6.QtGui import QFontDatabase
    for path in (r"C://Windows//Fonts//consola.ttf",
                 r"C://Windows//Fonts//CascadiaMono.ttf",
                 r"C://Windows//Fonts//cour.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if os.path.exists(path) and QFontDatabase.addApplicationFont(path) >= 0:
            return path
    return ""


def GrabPath():
    return os.path.join(os.environ.get("TEMP", ROOT), "proxy_page_scroll.png")


def main():
    app = QApplication([])
    print("PySide6 {} / offscreen".format(__import__("PySide6").__version__))
    print("字体源：{}".format(LoadRealFonts() or "（无，度量可能失真）"))

    page = BuildPage(app, 478)
    widget = BuildWidget(page)
    app.processEvents()

    TestStructure(app, page, widget)
    TestList(app, page, widget)
    TestPageScroll(app, page, widget)
    TestAdvPanel(app, page, widget)
    TestInteract(app, page, widget)
    TestLengths(app)

    print("\n截图：{}".format(GrabPath()))
    if Failures:
        print("\n{} 项不通过：".format(len(Failures)))
        for message in Failures:
            print("  - {}".format(message))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
