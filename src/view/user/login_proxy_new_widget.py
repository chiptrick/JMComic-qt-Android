import json
import re
# 显式导入子模块：`import urllib` 不会加载 urllib.request，
# Init() 里的 urllib.request.getproxies() 会抛 AttributeError(真机上已复现)
import urllib.request
from functools import partial

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHeaderView, QLabel)

from component.list.proxy_node_card import (ProxyNodeCard, ScaledFont, ShortName,
                                            TagKind)
from config.global_config import GlobalConfig
from config.setting import Setting
from qt_owner import QtOwner
from server import req, Server
from tools.log import Log
from tools.str import Str


class _ViewportWatcher(QObject):
    """ 视口尺寸变化时回调（LoginProxyNewWidget 不是 QObject，不能自己当事件过滤器） """

    def __init__(self, callback, parent=None):
        QObject.__init__(self, parent)
        self.callback = callback

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            self.callback()
        return False


class IpItem(object):
    def __init__(self, index, j, ip, isProxy=False, isSelf=False):
        self.index = index
        self.tableRow = index
        self.j = j
        if isProxy:
            self.name = f"ProxyIP分流{j}"
        elif isSelf:
            self.name = f"自定义分流{j}"
        else:
            self.name = f"CDN分流{j}"
        self.ip = ip
        self.isProxy = False
        self.tags = []
        self.country = ""
        self.asn = ""
        self.delay = 0
        self.download = 0
        self.downloadDelay = 0
        self.isFail = False
        self.downloadFail = False
        self.st = ""
        self.downloadSt = ""
        self.isSelect = False

    def Copy(self, other):
        assert isinstance(other, IpItem)
        self.country = other.country
        self.asn = other.asn

    def __lt__(self, other):
        assert isinstance(other, IpItem)
        if self.isSelect == other.isSelect:
            leIsFail = self.isFail or self.downloadFail
            rtIsFail = other.isFail or other.downloadFail
            if leIsFail == rtIsFail:
                return self.delay*0.8 + self.downloadDelay*0.2 < other.delay*0.8 + other.downloadDelay*0.2
            else:
                if leIsFail:
                    return False
                else:
                    return True
        else:
            if self.isSelect:
                return True
            else:
                return False


class LoginProxyNewWidget(object):
    """ 分流设置页驱动

    列表从「5 列宽表」换成「一行一张卡片」（component/list/proxy_node_card.py）：
    页面结构见 ui_login_new.ui 的 tab_4 —— 代理通道 / 线路测速 / 节点列表 / 高级 / 底栏
    五块固定高度 + 列表吃满剩余高度，整页不再需要滚动。
    """

    def __init__(self, owner):
        from view.user.login_new_view import LoginNewView
        assert isinstance(owner, LoginNewView)
        self.owner = owner

        self.speedTest = []
        self.speedPingNum = 0
        self.speedDownNum = 0

        self.pingBackNumCnt = {}
        self.pingBackNumDict = {}
        self.needBackNum = 0

        self.owner.radioApiGroup.setId(self.owner.radioButton_1, 1)
        self.owner.radioApiGroup.setId(self.owner.radioButton_2, 2)
        self.owner.radioApiGroup.setId(self.owner.radioButton_3, 3)
        self.owner.radioApiGroup.setId(self.owner.radioButton_4, 4)
        self.owner.radioApiGroup.setId(self.owner.radioButton_5, 5)
        self.owner.radioApiGroup.setId(self.owner.radioButton_6, 6)

        self.owner.radioImgGroup.setId(self.owner.radio_img_1, 1)
        self.owner.radioImgGroup.setId(self.owner.radio_img_2, 2)
        self.owner.radioImgGroup.setId(self.owner.radio_img_3, 3)
        self.owner.radioImgGroup.setId(self.owner.radio_img_4, 4)
        self.owner.radioImgGroup.setId(self.owner.radio_img_5, 5)
        self.owner.radioImgGroup.setId(self.owner.radio_img_6, 6)

        self.owner.radioProxyGroup.setId(self.owner.proxy_0, 0)
        self.owner.radioProxyGroup.setId(self.owner.proxy_1, 1)
        self.owner.radioProxyGroup.setId(self.owner.proxy_2, 2)
        self.owner.radioProxyGroup.setId(self.owner.proxy_3, 3)

        self.systemProxyValue = ""
        self.isInitProxy = False
        self.dense = False
        self.filter = "all"
        self.sortMode = "smart"
        self.rowItems = {}
        self.allItems = {}
        self.maxSpeedIpCnt = 0
        self.maxSpeedImgCnt = 0
        self.maxNum = 7
        self.cdnIndex = 5
        self.lastResult = {}
        self.allApiUrl = []
        self.checkDohUrl = ""
        self.checkResult = None

        self.InitCardTable()
        self.InitUi()
        self.LoadSetting()

        self.otherProxyIps = Setting.ProxyIpLastList.value.split(",")
        if not self.otherProxyIps:
            self.otherProxyIps = GlobalConfig.ProxyIpList.value[:]

        self.ShowAllItem()
        self.LoadHistory()
        self.RenderList()
        self.UpdateAddrRow()

        self.owner.dohLine.SetWordData(GlobalConfig.DohUrlList.value[:])
        self.owner.cdnLinkButton.clicked.connect(self.OpenUrl)
        self.owner.dohLine.editingFinished.connect(self.CheckDohReq)

    # ---------------- 列表（一行一张卡片） ----------------
    def InitCardTable(self):
        """ 表格退化成单列卡片容器：去掉表头/网格，行高由卡片决定，滚动条要留出来 """
        table = self.owner.tableWidget
        table.setColumnCount(1)
        table.horizontalHeader().setVisible(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        table.verticalHeader().setMinimumSectionSize(1)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setFrameShape(QFrame.NoFrame)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 旧代码把竖直滚动条也关掉了 —— 列表比可视区高时根本滚不动，
        # 这正是"后面的节点看不到"的另一半原因
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # 主题里 QTableWidget 有边框、item 有 padding，卡片自己有留白，这里清掉
        table.setStyleSheet("QTableWidget{background:transparent;border:none;}"
                            "QTableWidget::item{border:none;padding:0;}"
                            "QTableWidget::item:selected{background:transparent;}")
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setStretchLastSection(True)
        table.itemSelectionChanged.connect(self.OnRowSelected)
        self.emptyLabel = QLabel("当前分组暂无节点", table.viewport())
        self.emptyLabel.setAlignment(Qt.AlignCenter)
        self.emptyLabel.setStyleSheet("color:#7C858E;background:transparent;")
        self.emptyLabel.hide()
        self.viewportWatcher = _ViewportWatcher(self.UpdateEmpty, table.viewport())
        table.viewport().installEventFilter(self.viewportWatcher)

    def InitUi(self):
        """ 接上新布局上的筛选 / 排序 / 密度 / 高级面板 / 速度格子 """
        owner = self.owner
        for col in range(6):
            owner.speedGrid.setColumnStretch(col, 1)
        small = ScaledFont(owner.font(), -1.8)
        for i in range(1, self.maxNum):
            for name in ("label_api_" + str(i), "label_img_" + str(i)):
                label = getattr(owner, name, None)
                if isinstance(label, QLabel):
                    label.setFont(small)
                    label.setAlignment(Qt.AlignCenter)

        # 主题里 QPushButton 是 34px 高 + 左右 16px 内边距（桌面尺寸），塞进这几条紧凑栏
        # 会把行撑胖、把"测速/≡"这类窄按钮的文字挤掉。这里只覆盖度量，配色仍走主题。
        self.CompactButton(owner.proxyFilterAll, 24, 8, -2.2)
        self.CompactButton(owner.proxyFilterProxy, 24, 8, -2.2)
        self.CompactButton(owner.proxyFilterCf, 24, 8, -2.2)
        self.CompactButton(owner.proxySortButton, 22, 6, -2.2)
        self.CompactButton(owner.proxyDensityButton, 22, 0, 0.6, maxWidth=30)
        self.CompactButton(owner.testSpeedButton, 30, 2, -1.0)
        self.CompactLink(owner.cdnLinkButton, 22, 6, -2.0)
        owner.proxyStatusLabel.setWordWrap(True)

        owner.proxyFilterGroup.buttonClicked.connect(self.OnFilterClicked)
        owner.proxySortButton.clicked.connect(self.OnSortClicked)
        owner.proxyDensityButton.clicked.connect(self.OnDensityClicked)
        owner.proxyAdvButton.clicked.connect(self.OnAdvClicked)
        owner.testIpButton.clicked.connect(self.StartTestIp)
        owner.testSpeedButton.clicked.connect(self.SpeedTest)
        owner.radioProxyGroup.buttonClicked.connect(self.OnProxyModeChanged)
        self.SyncFilterText()

    @staticmethod
    def CompactButton(widget, height, padding, fontDelta, maxWidth=None):
        """ 只改高度/内边距/字号，不动颜色（颜色继续由主题 QSS 给） """
        widget.setFont(ScaledFont(widget.font(), fontDelta))
        widget.setStyleSheet(
            "QPushButton{{height:{h}px;min-height:{h}px;max-height:{h}px;padding:0 {p}px;}}".format(
                h=height, p=padding))
        if maxWidth:
            widget.setFixedWidth(maxWidth)

    @staticmethod
    def CompactLink(widget, height, padding, fontDelta):
        """ QCommandLinkButton（"说明"）按紧凑文字链接处理 """
        widget.setFont(ScaledFont(widget.font(), fontDelta))
        widget.setIcon(QIcon())
        widget.setStyleSheet(
            "QCommandLinkButton{{height:{h}px;min-height:{h}px;max-height:{h}px;"
            "padding:0 {p}px;background:transparent;border:none;}}".format(h=height, p=padding))

    def RenderList(self):
        """ 按当前分组/排序重建行（只重建行，不重建控件） """
        table = self.owner.tableWidget
        for item in self.allItems.values():
            item.tableRow = -1

        items = [item for item in self.allItems.values() if self.MatchFilter(item)]
        self.SortItems(items)
        self.rowItems = {}

        table.blockSignals(True)
        table.setRowCount(0)
        for row, item in enumerate(items):
            item.tableRow = row
            table.insertRow(row)
            self.rowItems[row] = item
            self.UpdateRow(item)
            table.setRowHeight(row, self.RowHeight(item))
        table.blockSignals(False)

        self.SyncTableSelection()
        self.UpdateCount()
        self.UpdateEmpty()

    def SortItems(self, items):
        """ 三种排序：智能(默认，选中优先 + 延迟*0.8+下载*0.2) / 按延迟 / 按下载

            后两种只把"失败项"沉到最后，其余严格按数值排，选中的节点不再被顶到第一行
            —— 否则用户点一下第 40 行，列表顺序会跟着变。
        """
        if self.sortMode == "lat":
            items.sort(key=lambda it: (1 if (it.isFail or it.downloadFail) else 0,
                                       it.delay or 10 ** 9))
        elif self.sortMode == "dl":
            items.sort(key=lambda it: (1 if (it.isFail or it.downloadFail) else 0,
                                       it.downloadDelay or 10 ** 9))
        else:
            items.sort()

    def MatchFilter(self, item):
        assert isinstance(item, IpItem)
        kind = TagKind(item)
        if self.filter == "proxy":
            return kind in ("proxy", "self")
        if self.filter == "cf":
            return kind == "cf"
        return True

    def RowHeight(self, item):
        card = self.owner.tableWidget.cellWidget(item.tableRow, 0)
        if isinstance(card, ProxyNodeCard):
            return card.RowHeight()
        return 62

    def UpdateRow(self, info):
        """ 刷新一行：表格里只放卡片，文本全部由卡片负责 """
        assert isinstance(info, IpItem)
        table = self.owner.tableWidget
        row = info.tableRow
        if row < 0 or row >= table.rowCount():
            return
        card = table.cellWidget(row, 0)
        if not isinstance(card, ProxyNodeCard):
            card = ProxyNodeCard(table.viewport())
            card.SetDense(self.dense)
            table.setCellWidget(row, 0, card)
            card.SetSelected(self.IsRowSelected(row))
        card.Update(info)
        height = card.RowHeight()
        if table.rowHeight(row) != height:
            table.setRowHeight(row, height)

    def ShowAllItem(self):
        """ 重建数据源：ProxyIP 列表 + 自定义 IP + 内置优选 IP """
        oldItems = {item.ip: item for item in self.allItems.values()}
        self.allItems = {}
        index = 0
        allips = set()

        for j, ip in enumerate(self.otherProxyIps):
            if not ip or ip in allips:
                continue
            allips.add(ip)
            item = IpItem(index, j + 1, ip, True, False)
            item.isSelect = ip == Setting.ProxyIpValue.value
            self.allItems[index] = item
            if ip in oldItems:
                item.Copy(oldItems[ip])
            index += 1

        for j, ip in enumerate(re.split(r'[、，；;,\s]\s*', Setting.PreferCDNList.value)):
            if not ip or ip in allips:
                continue
            allips.add(ip)
            item = IpItem(index, j + 1, ip, False, True)
            item.isSelect = ip == Setting.ProxyIpValue.value
            self.allItems[index] = item
            if ip in oldItems:
                item.Copy(oldItems[ip])
            index += 1

        for j, ip in enumerate(GlobalConfig.BestCfIpList.value):
            if not ip:
                continue
            item = IpItem(index, j + 1, ip, False, False)
            item.isSelect = ip == Setting.ProxyIpValue.value
            self.allItems[index] = item
            if ip in oldItems:
                item.Copy(oldItems[ip])
            index += 1

    def Sort(self):
        self.RenderList()

    # ---------------- 选中 / 计数 / 状态 ----------------
    def IsRowSelected(self, row):
        for index in self.owner.tableWidget.selectedIndexes():
            if index.row() == row:
                return True
        return False

    def SyncCardSelection(self):
        table = self.owner.tableWidget
        selected = set(index.row() for index in table.selectedIndexes())
        for row in range(table.rowCount()):
            card = table.cellWidget(row, 0)
            if isinstance(card, ProxyNodeCard):
                card.SetSelected(row in selected)

    def SyncTableSelection(self):
        """ item.isSelect -> 表格行选中 -> 卡片高亮 """
        table = self.owner.tableWidget
        target = None
        for row, item in self.rowItems.items():
            if item.isSelect:
                target = row
                break
        table.blockSignals(True)
        if target is not None and target < table.rowCount():
            table.selectRow(target)
        else:
            table.clearSelection()
        table.blockSignals(False)
        self.SyncCardSelection()
        self.UpdateStatus()

    def OnRowSelected(self):
        model = self.owner.tableWidget.selectionModel()
        rows = model.selectedRows() if model is not None else []
        if not rows:
            self.SyncCardSelection()
            return
        item = self.rowItems.get(rows[0].row())
        if item is None:
            return
        self.SelectItem(item)
        self.SyncCardSelection()
        self.UpdateStatus()

    def SelectItem(self, item):
        """ 单选语义：原来是表格里的 QCheckBox + QButtonGroup，现在由行选中承担 """
        assert isinstance(item, IpItem)
        for other in self.allItems.values():
            other.isSelect = other is item
        Setting.ProxyIpValue.SetValue(item.ip)
        try:
            # 宿主自检/单元测试里没有主界面，这里要能安静跳过
            if getattr(QtOwner(), "_owner", None) is not None:
                QtOwner().UpdateProxyName()
        except Exception as es:
            Log.Error(es)

    def SelectIp(self, ip):
        """ 按 IP 选中（被分组筛掉的项也要能选中） """
        for item in self.allItems.values():
            item.isSelect = item.ip == ip
        self.SyncTableSelection()

    def UpdateCount(self):
        items = list(self.allItems.values())
        shown = [item for item in items if self.MatchFilter(item)]
        available = len([item for item in shown if item.delay])
        self.owner.proxyCountLabel.setText(
            "共 {} 项 · 可用 {}".format(len(shown), available) if available else
            "共 {} 项".format(len(shown)))
        self.owner.proxyFilterAll.setText("全部 {}".format(len(items)))
        self.owner.proxyFilterProxy.setText("ProxyIP {}".format(
            len([item for item in items if TagKind(item) in ("proxy", "self")])))
        self.owner.proxyFilterCf.setText("优选 {}".format(
            len([item for item in items if TagKind(item) == "cf"])))

    def UpdateStatus(self):
        selected = [item for item in self.allItems.values() if item.isSelect]
        if not selected:
            self.owner.proxyStatusLabel.setText("未选择节点")
            return
        item = selected[0]
        speed = "{} ms".format(int(float(item.delay))) if item.delay else "未测速"
        self.owner.proxyStatusLabel.setText("已选 {} · {}\n{} · {}".format(
            ShortName(item), item.ip, speed, item.country or "未知地区"))

    def UpdateEmpty(self):
        count = self.owner.tableWidget.rowCount()
        self.emptyLabel.setVisible(count == 0)
        self.emptyLabel.setGeometry(self.owner.tableWidget.viewport().rect())

    # ---------------- 分组 / 排序 / 密度 / 高级 ----------------
    def SyncFilterText(self):
        self.owner.proxyFilterAll.setChecked(self.filter == "all")
        self.owner.proxyFilterProxy.setChecked(self.filter == "proxy")
        self.owner.proxyFilterCf.setChecked(self.filter == "cf")
        self.owner.proxySortButton.setText({"smart": "智能排序 ▾", "lat": "按延迟 ▾",
                                            "dl": "按下载 ▾"}.get(self.sortMode, "智能排序 ▾"))

    def OnFilterClicked(self, button):
        text = button.text()
        if text.startswith("ProxyIP"):
            self.filter = "proxy"
        elif text.startswith("优选"):
            self.filter = "cf"
        else:
            self.filter = "all"
        self.SyncFilterText()
        self.RenderList()
        self.owner.tableWidget.scrollToTop()

    def OnSortClicked(self):
        self.sortMode = {"smart": "lat", "lat": "dl", "dl": "smart"}[self.sortMode]
        self.SyncFilterText()
        self.RenderList()
        self.owner.tableWidget.scrollToTop()

    def OnDensityClicked(self):
        self.dense = not self.dense
        for row in range(self.owner.tableWidget.rowCount()):
            card = self.owner.tableWidget.cellWidget(row, 0)
            if isinstance(card, ProxyNodeCard):
                card.SetDense(self.dense)
                self.owner.tableWidget.setRowHeight(row, card.RowHeight())

    def OnAdvClicked(self):
        panel = self.owner.proxyAdvPanel
        panel.setVisible(not panel.isVisible())
        self.owner.proxyAdvButton.setText("收起" if panel.isVisible() else "高级")

    def OnProxyModeChanged(self, *args):
        self.UpdateAddrRow()

    def UpdateAddrRow(self):
        """ 代理模式 -> 地址行只显示当前模式需要的那一个控件 """
        mode = self.owner.radioProxyGroup.checkedId()
        if mode < 0:
            # 配置异常/还没 LoadSetting 时别把整行都藏掉，按"无代理"处理
            mode = 0
        owner = self.owner
        owner.label_13.setText("系统代理" if mode == 3 else "代理地址")
        owner.label_13.setVisible(mode != 0)
        owner.proxyHint.setVisible(mode == 0)
        owner.httpLine.setVisible(mode == 1)
        owner.sockEdit.setVisible(mode == 2)
        owner.proxyLabel.setVisible(mode == 3 and bool(self.systemProxyValue))
        owner.checkLabel.setVisible(mode == 3 and not self.systemProxyValue)

    # ---------------- 初始化 ----------------
    def __InitSetting(self):
        self.owner.radioApiGroup.buttonClicked.connect(
            partial(QtOwner().settingView.ButtonClickEvent, Setting.ProxySelectIndex))
        self.owner.radioImgGroup.buttonClicked.connect(
            partial(QtOwner().settingView.ButtonClickEvent, Setting.ProxyImgSelectIndex))
        self.owner.radioProxyGroup.buttonClicked.connect(
            partial(QtOwner().settingView.ButtonClickEvent, Setting.IsHttpProxy))
        self.owner.httpLine.editingFinished.connect(
            partial(QtOwner().settingView.LineEditEvent, Setting.HttpProxy, self.owner.httpLine))
        self.owner.sockEdit.editingFinished.connect(
            partial(QtOwner().settingView.LineEditEvent, Setting.Sock5Proxy, self.owner.sockEdit))
        self.owner.echBox.clicked.connect(
            partial(QtOwner().settingView.CheckButtonEvent, Setting.EnableEch, self.owner.echBox))
        self.owner.http3Box.clicked.connect(
            partial(QtOwner().settingView.CheckButtonEvent, Setting.IsOpenHTTP3, self.owner.http3Box))
        self.owner.ipListEdit.editingFinished.connect(
            partial(QtOwner().settingView.LineEditEvent, Setting.PreferCDNList, self.owner.ipListEdit))
        self.owner.proxyIpEdit.editingFinished.connect(
            partial(QtOwner().settingView.LineEditEvent, Setting.ProxyIpCountry, self.owner.proxyIpEdit))

        self.owner.dohLine.editingFinished.connect(
            partial(QtOwner().settingView.LineEditEvent, Setting.DohAddress, self.owner.dohLine))

        self.owner.radioApiGroup.buttonClicked.connect(QtOwner().UpdateProxyName)
        self.owner.radioImgGroup.buttonClicked.connect(QtOwner().UpdateProxyName)
        self.LoadHistory()

    def LoadHistory(self):
        try:
            if Setting.LastProxyResult.value:
                for k, v in Setting.LastProxyResult.value.items():
                    if hasattr(self.owner, k):
                        widget = getattr(self.owner, k)
                        if isinstance(widget, QLabel):
                            widget.setText(str(v))
            if Setting.LastIpResult.value:
                for item in self.allItems.values():
                    assert isinstance(item, IpItem)
                    if item.ip in Setting.LastIpResult.value:
                        item.country = Setting.LastIpResult.value[item.ip].get('country', "")
                        item.asn = Setting.LastIpResult.value[item.ip].get('asn', "")
                        item.delay = Setting.LastIpResult.value[item.ip].get('delay', 0)
                        item.downloadDelay = Setting.LastIpResult.value[item.ip].get('downloadDelay', 0)
                        item.isFail = Setting.LastIpResult.value[item.ip].get('isFail', "")
                        item.downloadFail = Setting.LastIpResult.value[item.ip].get('downloadFail', "")
                        item.st = Setting.LastIpResult.value[item.ip].get('st', "")
                        item.downloadSt = Setting.LastIpResult.value[item.ip].get('downloadSt', "")

        except Exception as es:
            Log.Error(es)

    def SaveHistory(self):
        Setting.LastProxyResult.SetValue(dict(self.lastResult))

    def Init(self):
        if not self.isInitProxy:
            self.isInitProxy = True
            self.__InitSetting()
        self.LoadSetting()
        proxy = urllib.request.getproxies()
        if isinstance(proxy, dict) and proxy.get("http"):
            self.systemProxyValue = proxy.get("http", "")
            self.owner.proxyLabel.setText(self.systemProxyValue)
        else:
            self.systemProxyValue = ""
            self.owner.proxyLabel.setText("")
        self.UpdateAddrRow()
        self.CheckDohReq()

    def SetEnabled(self, enabled):
        self.owner.testSpeedButton.setEnabled(enabled)
        self.owner.proxy_0.setEnabled(enabled)
        self.owner.proxy_1.setEnabled(enabled)
        self.owner.proxy_2.setEnabled(enabled)
        self.owner.proxy_3.setEnabled(enabled)
        self.owner.httpLine.setEnabled(enabled)
        self.owner.sockEdit.setEnabled(enabled)
        self.owner.radioButton_1.setEnabled(enabled)
        self.owner.radioButton_2.setEnabled(enabled)
        self.owner.radioButton_3.setEnabled(enabled)
        self.owner.radioButton_4.setEnabled(enabled)
        self.owner.radioButton_5.setEnabled(enabled)
        self.owner.radioButton_6.setEnabled(enabled)
        self.owner.radio_img_1.setEnabled(enabled)
        self.owner.radio_img_2.setEnabled(enabled)
        self.owner.radio_img_3.setEnabled(enabled)
        self.owner.radio_img_4.setEnabled(enabled)
        self.owner.radio_img_5.setEnabled(enabled)
        self.owner.radio_img_6.setEnabled(enabled)
        self.owner.echBox.setEnabled(enabled)
        self.owner.http3Box.setEnabled(enabled)
        self.owner.dohLine.setEnabled(enabled)

    def LoadSetting(self):
        self.owner.httpLine.setText(Setting.HttpProxy.value)
        self.owner.sockEdit.setText(Setting.Sock5Proxy.value)
        button = getattr(self.owner, "radioButton_{}".format(Setting.ProxySelectIndex.value), None)
        if button:
            button.setChecked(True)
        button = getattr(self.owner, "proxy_{}".format(int(Setting.IsHttpProxy.value)), None)
        if button:
            button.setChecked(True)
        button = getattr(self.owner, "radio_img_{}".format(int(Setting.ProxyImgSelectIndex.value)), None)
        if button:
            button.setChecked(True)
        self.owner.apiTimeout.setCurrentIndex(Setting.ApiTimeOut.value)
        self.owner.imgTimeout.setCurrentIndex(Setting.ImgTimeOut.value)
        self.owner.echBox.setChecked(bool(Setting.EnableEch.value))
        self.owner.dohLine.setText(Setting.DohAddress.value)
        self.owner.http3Box.setChecked(bool(Setting.IsOpenHTTP3.value))
        self.owner.ipListEdit.setText(Setting.PreferCDNList.value)
        self.owner.proxyIpEdit.setText(Setting.ProxyIpCountry.value)

    def SaveSetting(self):
        Setting.IsHttpProxy.SetValue(int(self.owner.radioProxyGroup.checkedId()))
        Setting.Sock5Proxy.SetValue(self.owner.sockEdit.text())
        Setting.HttpProxy.SetValue(self.owner.httpLine.text())
        Setting.ProxySelectIndex.SetValue(self.owner.radioApiGroup.checkedId())
        Setting.ProxyImgSelectIndex.SetValue(self.owner.radioImgGroup.checkedId())
        Setting.ApiTimeOut.SetValue(self.owner.apiTimeout.currentIndex())
        Setting.ImgTimeOut.SetValue(self.owner.imgTimeout.currentIndex())
        Setting.EnableEch.SetValue(bool(self.owner.echBox.isChecked()))
        Setting.DohAddress.SetValue((self.owner.dohLine.text()))
        Setting.IsOpenHTTP3.SetValue(bool(self.owner.http3Box.isChecked()))
        # 用户重新选/保存代理就重新相信这两个选项：之前运行时因为失败把它们关了，
        # 现在给个机会再试(比如换了网络/换了 IP)。
        req.ResetHttp3EchFallback()
        QtOwner().ShowMsg(Str.GetStr(Str.SaveSuc))
        return

    def CheckDohReq(self):
        self.checkResult = None
        self.checkDohUrl = self.owner.dohLine.text()
        self.SetDohIcon()
        url = GlobalConfig().Url2List.value[0]
        request = req.DnsOverHttpsReq(url, self.checkDohUrl)
        self.owner.AddHttpTask(request, self.CheckDohBack, self.checkDohUrl)

    def CheckDohBack(self, raw, url):
        data = raw["data"]
        st = raw["st"]
        Log.Warn(f"check_doh, {url}, st:{st}, data:{data}")
        if url != self.checkDohUrl:
            return
        if st == Str.Ok and raw.get("Answer"):
            self.checkResult = True
        else:
            self.checkResult = False
        self.SetDohIcon()

    def SetDohIcon(self):
        icon2 = QIcon()
        if self.checkResult == True:
            icon2.addFile(u":/png/icon/right.svg", QSize(), QIcon.Normal, QIcon.Off)
        elif self.checkResult == False:
            icon2.addFile(u":/png/icon/error.svg", QSize(), QIcon.Normal, QIcon.Off)
        self.owner.dohTool.setStyleSheet(u"background-color:transparent;")
        self.owner.dohTool.setMinimumSize(QSize(0, 40))
        self.owner.dohTool.setFocusPolicy(Qt.NoFocus)
        self.owner.dohTool.setIcon(icon2)
        self.owner.dohTool.setIconSize(QSize(20, 20))

    def OpenUrl(self):
        QtOwner().owner.helpView.OpenProxyUrl()

    # ---------------- IP 分流测速（网络逻辑沿用原实现） ----------------
    def StartTestIp(self):
        self.owner.testIpButton.setEnabled(False)
        self.StartGetProxyIp()

    def StartGetProxyIp(self):
        request = req.GetProxyIpInfoReq(self.owner.proxyIpEdit.text())
        self.owner.AddHttpTask(request, self.GetProxyIpBack)

    def GetProxyIpBack(self, raw):
        st = raw["st"]
        if st == Str.Ok:
            ipList = raw.get("list", [])
            self.otherProxyIps = ipList

            self.owner.proxyIpLabel.setText(f"<font color=#d71345>成功获取{len(ipList)}个节点</font>")
            Setting.ProxyIpLastList.SetValue(",".join(self.otherProxyIps))
        else:

            self.owner.proxyIpLabel.setText("<font color=#d71345>{}</font>".format(Str.GetStr(st)))
            Setting.ProxyIpLastList.SetValue("")
        if not self.otherProxyIps:
            self.otherProxyIps = GlobalConfig.ProxyIpList.value[:]
        self.StartTestIp2()

    def StartTestIp2(self):
        self.ShowAllItem()
        self.RenderList()
        self.owner.testIpButton.setEnabled(False)
        url = GlobalConfig.CdnApiUrl.value
        self.maxSpeedIpCnt = len(self.allItems)
        for item in self.allItems.values():
            request = req.SpeedTestPingReq(url)
            request.SetProxy(0, "", "")
            request.SetIndex(0, 0, GlobalConfig.CdnApiUrl.value, GlobalConfig.CdnImgUrl.value)
            request.SetCurlOpt(self.owner.http3Box.isChecked(), self.owner.echBox.isChecked(), QtOwner().echConfig, item.ip)
            self.owner.AddHttpTask(request, self.StartTestIpBack, backParam=item.index)

            if not item.country or not item.asn:
                request = req.GetIpInfoReq(item.ip)
                request.SetProxy(0, "", "")
                request.SetIndex(0, 0)
                request.SetCurlOpt(False, False, "")
                self.owner.AddHttpTask(request, self.GetIpInfo, backParam=item.index)
        return

    def CheckSelectBox(self):
        if not self.allItems:
            return
        isHave = False
        selectIp = Setting.ProxyIpValue.value
        for item in self.allItems.values():
            assert isinstance(item, IpItem)
            if item.ip == selectIp:
                isHave = True
                item.isSelect = True
            else:
                item.isSelect = False
        if not isHave:
            firstItem = sorted(self.allItems.values())[0]
            firstItem.isSelect = True
            Setting.ProxyIpValue.SetValue(firstItem.ip)
        self.SyncTableSelection()

    def StartTestImgIp(self):
        url = GlobalConfig.CdnImgUrl.value
        self.maxSpeedImgCnt = 0
        for item in self.allItems.values():
            if item.isFail:
                continue
            self.maxSpeedImgCnt += 1
            request = req.SpeedTestPing2Req(url)
            request.SetProxy(0, "", "")
            request.SetIndex(0, 0, GlobalConfig.CdnApiUrl.value, GlobalConfig.CdnImgUrl.value)
            request.SetCurlOpt(self.owner.http3Box.isChecked(), self.owner.echBox.isChecked(), QtOwner().echConfig, item.ip)
            self.owner.AddHttpTask(request, self.StartTestImgBack, backParam=item.index)
        return

    def GetIpInfo(self, raw, v):
        index = v
        data = raw.get("data", "")
        st = raw["st"]
        item = self.allItems.get(index)
        if not item:
            return
        assert isinstance(item, IpItem)
        if st == Str.Ok:
            try:
                data2 = json.loads(data)
                if data2.get("code") == 200:
                    country = data2.get('data',{}).get("country", "")
                    province = data2.get('data', {}).get("province", "")
                    isp = data2.get('data', {}).get("isp", "")
                    item.country = f"{country}·{province}"
                    item.asn = isp
                    self.UpdateRow(item)
            except Exception as es:
                Log.Error(es)

    def StartTestIpBack(self, raw, v):
        index = v
        data = raw["data"]
        st = raw["st"]
        item = self.allItems.get(index)
        if not item:
            return

        self.maxSpeedIpCnt -= 1
        assert isinstance(item, IpItem)
        if float(data) > 0.0:
            item.delay = int(float(data))
        else:
            item.delay = 0
            item.isFail = True
            item.st = st
        self.UpdateRow(item)
        if self.maxSpeedIpCnt == 0:
            self.Sort()
            self.StartTestImgIp()

    def StartTestImgBack(self, raw, v):
        index = v
        data = raw["data"]
        st = raw["st"]
        item = self.allItems.get(index)
        if not item:
            return

        self.maxSpeedImgCnt -= 1
        assert isinstance(item, IpItem)
        if float(data) > 0.0:
            item.downloadDelay = int(float(data))
        else:
            item.downloadDelay = 0
            item.downloadFail = True
            item.downloadSt = st
        self.UpdateRow(item)
        if self.maxSpeedImgCnt <= 0:
            self.Sort()
            self.owner.testIpButton.setEnabled(True)
            self.CheckSelectBox()
            history = {}
            for item in self.allItems.values():
                assert isinstance(item, IpItem)
                history[item.ip] = {}
                history[item.ip]['country'] = item.country
                history[item.ip]['asn'] = item.asn
                history[item.ip]['delay'] = item.delay
                history[item.ip]['downloadDelay'] = item.downloadDelay
                history[item.ip]['isFail'] = item.isFail
                history[item.ip]['downloadFail'] = item.downloadFail
                history[item.ip]['st'] = item.st
                history[item.ip]['downloadSt'] = item.downloadSt
            Setting.LastIpResult.SetValue(history)
            self.UpdateCount()

    def GetProxyName(self):
        for item in self.allItems.values():
            if item.isSelect:
                return item.name
        return Setting.ProxyIpValue.value

    # ---------------- 线路测速（逻辑未改） ----------------
    def SpeedTest(self):
        self.speedPingNum = 0
        self.speedTest = []
        self.SetEnabled(False)
        for i in range(1, self.maxNum):
            if i == self.cdnIndex:
                continue
            label = getattr(self.owner, "label_api_" + str(i))
            label.setText("")
            label = getattr(self.owner, "label_img_" + str(i))
            label.setText("")
            img = GlobalConfig.GetImgUrl2(i)
            api = GlobalConfig.GetApiUrl2(i)
            request = req.SpeedTestPingReq(api)
            request.SetIndex(i, i, api, img)
            request.SetCurlOpt(Setting.IsOpenHTTP3.value, Setting.EnableEch.value, QtOwner().echConfig)
            self.speedPingNum += 1
            self.owner.AddHttpTask(request, self.SpeedTestPingBack, backParam=i)

    def SpeedTestPingBack(self, raw, v):
        i = v
        data = raw.get("data", "")
        st = raw["st"]
        label = getattr(self.owner, "label_api_" + str(i))
        try:
            delay = float(data)
        except (TypeError, ValueError):
            # 回包不是数字时不要抛(float('') 会 ValueError)：以前会把这次回调整个
            # 抛掉，任务表残留、后面几个 ping 的结果再也回不来，测速一直转。
            delay = 0.0
        if delay > 0.0:
            text = "<font color=#7fb80e>{}</font>".format(str(int(delay)) + "ms")
            label.setText(text)
        else:
            text = "<font color=#d71345>{}</font>".format(Str.GetStr(st))
            label.setText(text)
        objectName = "label_api_" + str(i)
        self.lastResult[objectName] = text
        self.speedPingNum -= 1
        if self.speedPingNum == 0:
            self.speedDownNum = 0
            self.StartSpeedTest()

    def StartSpeedTest(self):
        self.speedDownNum += 1
        if self.speedDownNum >= self.maxNum:
            self.SetEnabled(True)
            self.SaveHistory()
            return
        if self.speedDownNum == self.cdnIndex:
            self.StartSpeedTest()
            return
        i = self.speedDownNum
        label = getattr(self.owner, "label_img_" + str(i))
        label.setText("")
        img = GlobalConfig.GetImgUrl2(i)
        api = GlobalConfig.GetApiUrl2(i)
        request = req.SpeedTestReq()
        request.SetIndex(i, i, api, img)
        request.SetCurlOpt(Setting.IsOpenHTTP3.value, Setting.EnableEch.value, QtOwner().echConfig)
        self.owner.AddHttpTask(lambda x: Server().TestSpeed(request, x), self.SpeedTestBack, i)
        return

    def SpeedTestBack(self, raw, i):
        data = raw["data"]
        st = raw["st"]
        if not data:
            data = "<font color=#d71345>{}</font>".format(Str.GetStr(st))
        else:
            data = "<font color=#7fb80e>{}</font>".format(data)
        objectName = "label_img_" + str(i)
        label = getattr(self.owner, "label_img_" + str(i))
        label.setText(data)
        self.lastResult[objectName] = data
        self.StartSpeedTest()
        return
