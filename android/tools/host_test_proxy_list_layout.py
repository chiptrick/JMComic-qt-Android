# coding:utf-8
""" 宿主自检：分流节点列表（方案A 卡片化）排版

背景：分流页原来是「5 列宽表 + 表格 min-height 2560 + 竖直滚动条 AlwaysOff」，
竖屏 452px 内容宽下每列放不下字（名称被裁、IPv4 被裁、9 个 32 字符 IPv6 完全没戏），
整页内容高 3281px ≈ 3.3 屏。现在改成「一行一张两行卡片」，列表吃满剩余高度。

本脚本逐条断言改造后的排版契约：

  [1] 结构：代理通道 / 线路测速 / 节点列表 / 底栏都在，整页不再有滚动区
  [2] 列表：26 个 ProxyIP + 24 个优选（含 9 个 IPv6）全部建行，行高=卡片高，
          竖直滚动条没有被禁用，内容不越出卡片右边界
  [3] 数据长度：360 / 478 / 520 三种宽度下，所有 IP（含 32 字符 IPv6）都不被省略
  [4] 交互：分组筛选计数、排序、选中 -> 底栏状态、空分组占位
  [5] 截图：导出 PNG 方便人眼复核

用法：python android/tools/host_test_proxy_list_layout.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel, QWidget
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
    from component.list.proxy_node_card import TagKind
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
            # 失败项延迟归零（真机里 isFail 时 delay 只会是 0）
            item.isFail = True
            item.st = 1024
            item.delay = 0
            item.downloadDelay = 0
        items[index] = item
        index += 1
    assert [TagKind(items[i]) for i in items].count("proxy") == 26
    return items


# ---------------------------------------------------------------- 页面
class Owner(QWidget):
    """ 只借用 Ui_LoginNew 的控件集合，充当 LoginProxyNewWidget 的 owner """


def BuildPage(app, width, height=982):
    from interface.ui_login_new import Ui_LoginNew

    class Owner(QWidget, Ui_LoginNew):
        """ 只借用 Ui_LoginNew 的控件集合，充当 LoginProxyNewWidget 的 owner
            （和 LoginNewView 一样：setupUi 把控件挂到 self 上） """

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
    """ 直接调真实驱动的方法（跳过 __init__ 里的网络/设置副作用） """
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
    # 与 __init__ 一致：给代理模式单选组固定 id 0..3，并默认"无代理"
    for mode in range(4):
        page.radioProxyGroup.setId(getattr(page, "proxy_" + str(mode)), mode)
    page.proxy_0.setChecked(True)
    widget.InitCardTable()
    widget.InitUi()
    widget.RenderList()
    widget.UpdateAddrRow()          # 与 __init__ 一致：默认只显示"未启用代理"
    return widget


# ---------------------------------------------------------------- 断言
def TestStructure(app, page, widget):
    print("\n[1] 结构：四块固定区 + 列表吃满剩余高度，整页不再滚动")
    table = page.tableWidget

    Check(table.verticalScrollBarPolicy() != Qt.ScrollBarAlwaysOff,
          "列表竖直滚动条没有被禁用（旧代码是 AlwaysOff）")
    Check(table.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff,
          "列表不需要横向滚动")
    Check(table.columnCount() == 1, "表格退化成单列卡片容器({})".format(table.columnCount()))
    Check(not table.horizontalHeader().isVisible(), "表头已隐藏（标题改由每张卡片自己承担）")

    pageHeight = page.height()
    boxes = [page.proxyHeader, page.proxyModeBox, page.speedBox, page.proxyListBox, page.proxyFoot]
    bottom = 0
    for box in boxes:
        assert box.isVisible()
        bottom = max(bottom, box.y() + box.height())
    Check(bottom <= pageHeight, "五块内容都在一屏内（底边 {} <= 页高 {}）".format(bottom, pageHeight))

    listHeight = page.proxyListBox.height()
    Check(listHeight >= pageHeight * 0.5,
          "列表拿到一半以上高度（{}px / {}px）".format(listHeight, pageHeight))

    from PySide6.QtWidgets import QScrollArea
    areas = page.findChildren(QScrollArea)
    visible = [a for a in areas if a.isVisible() and a.verticalScrollBar().isVisible()]
    Check(not visible, "分流页不再有整页滚动区（旧版 scrollArea_3 已移除）")
    Check(page.proxyAdvPanel.isHidden(), "高级设置默认收起，不占列表高度")


def TestList(app, page, widget):
    print("\n[2] 列表：全部节点都建了行，行高=卡片高，卡片内容不越界")
    from component.list.proxy_node_card import ProxyNodeCard

    table = page.tableWidget
    total = len(widget.allItems)
    Check(table.rowCount() == total, "全部 {} 个节点都建了行（当前 {}）".format(total, table.rowCount()))

    bad_height = []
    bad_overflow = []
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
                bad_overflow.append((row, child.objectName() or child.text()[:8]))
    Check(not bad_height, "行高与卡片高度一致（异常行 {}）".format(bad_height[:5]))
    Check(not bad_overflow, "卡片内文字不越出右边界（异常 {}）".format(bad_overflow[:5]))

    # 可见高度 -> 同屏几项
    viewport = table.viewport().height()
    rowHeight = table.rowHeight(0)
    visible = viewport // rowHeight if rowHeight else 0
    Check(visible >= 8, "同屏至少 8 项（{}px / 行高 {} = {}）".format(viewport, rowHeight, visible))

    # 滚动到底能看到最后一项（旧版靠整页滚 3 屏）
    table.scrollToBottom()
    app.processEvents()
    Check(table.verticalScrollBar().value() > 0, "列表内部可滚动，末项可到达")


def TestLengths(app):
    print("\n[3] 数据长度：360 / 478 / 520 三种宽度，IP 一律不省略（含 32 字符 IPv6）")
    from component.list.proxy_node_card import ProxyNodeCard

    for width in (360, 478, 520):
        page = BuildPage(app, width)
        widget = BuildWidget(page)
        app.processEvents()
        page.grab()          # 强制视图排版/绘制：cellWidget 的宽度这一步才定下来
        app.processEvents()
        table = page.tableWidget
        elided = []
        ipv6 = 0
        for row in range(table.rowCount()):
            card = table.cellWidget(row, 0)
            if not isinstance(card, ProxyNodeCard):
                continue
            item = widget.rowItems[row]
            if ":" in item.ip:
                ipv6 += 1
            if card.ipLabel.text() != item.ip:
                elided.append((item.ip, card.ipLabel.text()))
        Check(not elided,
              "{}px：{} 项全部完整显示（IPv6 {} 个，被省略 {}）".format(
                  width, table.rowCount(), ipv6, len(elided)))
        if elided:
            print("       例: {}".format(elided[:2]))
        widths = set(table.cellWidget(r, 0).width() for r in range(table.rowCount()))
        Check(len(widths) == 1 and widths.pop() == table.viewport().width(),
              "{}px：卡片宽度贴合视口（{} vs {}）".format(
                  width, table.cellWidget(0, 0).width(), table.viewport().width()))
        if width == 478:
            page.grab().save(GrabPath())
        page.hide()
        page.deleteLater()
        app.processEvents()


def TestInteract(app, page, widget):
    print("\n[4] 交互：筛选计数 / 排序 / 选中状态 / 空分组占位")
    from component.list.proxy_node_card import TagKind

    widget.owner = page
    widget.RenderList()

    allText = page.proxyFilterAll.text()
    proxyText = page.proxyFilterProxy.text()
    cfText = page.proxyFilterCf.text()
    Check("全部 {}".format(len(widget.allItems)) == allText, "分组按钮带数量：{}".format(allText))
    Check("ProxyIP 26" == proxyText, "ProxyIP 分组计数正确（{}）".format(proxyText))
    Check("优选 24" == cfText, "优选分组计数正确（{}）".format(cfText))

    widget.filter = "cf"
    widget.RenderList()
    app.processEvents()
    kinds = set(TagKind(widget.rowItems[r]) for r in widget.rowItems)
    Check(page.tableWidget.rowCount() == 24 and kinds == {"cf"},
          "只看优选：24 行且全是优选（{}/{}）".format(page.tableWidget.rowCount(), kinds))

    widget.filter = "proxy"
    widget.RenderList()
    app.processEvents()
    Check(page.tableWidget.rowCount() == 26, "只看 ProxyIP：26 行（{}）".format(
        page.tableWidget.rowCount()))

    widget.filter = "all"
    widget.sortMode = "lat"
    widget.RenderList()
    delays = [widget.rowItems[r].delay for r in range(page.tableWidget.rowCount())]
    alive = [d for d in delays if d]
    bad = [i for i in range(1, len(alive)) if alive[i] < alive[i - 1]]
    Check(not bad, "按延迟排序：{}...（逆序位置 {}）".format(alive[:6], bad[:3]))

    # 选中第 3 行 -> 底栏状态 + 卡片高亮
    page.tableWidget.selectRow(2)
    app.processEvents()
    selected = widget.rowItems[2]
    Check(selected.isSelect, "点行即选中（{}）".format(selected.ip))
    Check(selected.ip in page.proxyStatusLabel.text(), "底栏显示已选节点（{}）".format(
        page.proxyStatusLabel.text().replace("\n", " / ")))
    from component.list.proxy_node_card import ProxyNodeCard
    card = page.tableWidget.cellWidget(2, 0)
    Check(isinstance(card, ProxyNodeCard) and card._selected, "选中卡片有高亮态")

    # 空分组：全部为空时显示占位而不是白板
    saved = widget.allItems
    widget.allItems = {}
    widget.RenderList()
    app.processEvents()
    Check(page.tableWidget.rowCount() == 0 and widget.emptyLabel.isVisible(),
          "没有节点时显示占位提示")
    widget.allItems = saved
    widget.RenderList()
    app.processEvents()

    # 代理模式 -> 地址行只留一个控件
    for mode, expect in ((0, "proxyHint"), (1, "httpLine"), (2, "sockEdit"), (3, "checkLabel")):
        button = getattr(page, "proxy_" + str(mode))
        button.setChecked(True)
        widget.OnProxyModeChanged(button)
        app.processEvents()
        shown = [name for name in ("proxyHint", "httpLine", "sockEdit", "proxyLabel", "checkLabel")
                 if getattr(page, name).isVisible()]
        Check(shown == [expect] or (mode == 3 and set(shown) <= {"proxyLabel", "checkLabel"}
                                    and expect in shown),
              "代理模式 {} 只显示 {}".format(mode, shown))

    # 密度：紧凑后行高变小、同屏更多
    before = page.tableWidget.rowHeight(0)
    widget.OnDensityClicked()
    app.processEvents()
    after = page.tableWidget.rowHeight(0)
    Check(after < before, "紧凑密度行高变小（{} -> {}）".format(before, after))
    widget.OnDensityClicked()

    # 高级面板展开后仍然不把底栏顶出屏幕
    widget.OnAdvClicked()
    app.processEvents()
    Check(page.proxyAdvPanel.isVisible(), "高级面板可展开")
    Check(page.proxyFoot.y() + page.proxyFoot.height() <= page.height(),
          "展开高级后底栏仍在屏内（{} <= {}）".format(
              page.proxyFoot.y() + page.proxyFoot.height(), page.height()))
    Check(page.proxyListBox.height() > 120, "展开高级后列表仍保留可用高度（{}px）".format(
        page.proxyListBox.height()))
    widget.OnAdvClicked()


def LoadRealFonts():
    """ 离屏环境常常一个字体族都没有（Qt 回退成"每字符固定 13px"的占位字体），
        在这种度量下算出来的"放不下"是假的。这里显式加载系统里的等宽字体，
        让测量接近真机。 """
    from PySide6.QtGui import QFontDatabase
    candidates = [
        r"C://Windows//Fonts//consola.ttf",
        r"C://Windows//Fonts//CascadiaMono.ttf",
        r"C://Windows//Fonts//cour.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
    ]
    for path in candidates:
        if os.path.exists(path) and QFontDatabase.addApplicationFont(path) >= 0:
            return path
    return ""


def GrabPath():
    return os.path.join(os.environ.get("TEMP", ROOT), "proxy_list_layout.png")


def main():
    app = QApplication([])
    print("PySide6 {} / offscreen".format(__import__("PySide6").__version__))
    fontPath = LoadRealFonts()
    print("字体源：{}".format(fontPath or "（无，度量可能失真）"))
    if not fontPath:
        print("注意：没有可用的真实字体，关于是否省略的断言仅供参考")

    page = BuildPage(app, 478)
    widget = BuildWidget(page)
    app.processEvents()

    TestStructure(app, page, widget)
    TestList(app, page, widget)
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
