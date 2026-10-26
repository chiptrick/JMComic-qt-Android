# coding:utf-8
""" 分流节点卡片（方案 A）

原先是 5 列宽表（名称 / IP / 地区 / ISP / 速度）+ 表头 `padding: 0 20px`：
竖屏 452px 内容宽下每列能放字的宽度不到 50px，于是

    名称  ->  「ProxyIP分流…」       （QCheckBox 的文本还要再让位给 24px 勾选框）
    IP    ->  「158.180.231…」       （15 字符 IPv4 就要 ~110px）
    地区  ->  「中国香港…」
    ISP   ->  「Oracle Corp…」
    IPv6  ->  9 个 32 字符的地址根本放不下

这里把「一行」改成「一张卡片」，同样的宽度内两行放下全部字段：

    ◉ 158.180.231.216                          152/210   (延迟/下载，右对齐等宽数字)
      ProxyIP 1 · 日本·东京 · Oracle Corporation

三个要点：
1. 第一行只有「IP + 速度」：IP 用等宽字体独占一行，32 字符 IPv6 在 360~520 宽下都完整；
2. 第二行「组别标签(定宽 64) + 地区 · ISP」：标签定宽保证每行文字左边界一致，
   地区和 ISP 变长时只在末尾省略（完整内容进 tooltip）；
3. 卡片整体鼠标穿透（WA_TransparentForMouseEvents）：点击/长按/滑动都落到下面的
   QTableWidget 上，选择、QScroller、右键菜单全沿用原行为（与 download_card 同一套做法）。
"""
from PySide6.QtCore import QCoreApplication, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from tools.str import Str


def Tr(text):
    return QCoreApplication.translate("LoginProxy", text, None)


# ---- 度量 ----
PadLeft = 34          # 12 + 22：左侧留给自绘的单选圆点
PadRight = 12
PadTop = 7
PadBottom = 7
PadDense = 4
SpeedWidth = 86       # 速度列固定宽（列头 colSpeedLabel 用同一个值）
TagWidth = 64         # 组别标签固定宽，保证第二行左边界逐行对齐
# 最长的一类 IP：IPv6 全写 32 字符。字号自适应按它算，各行才会得到同一个字号
IpRefText = "2606:4700:0:f920:12e9:bef7:bd1b:bf3"
IpMinPointSize = 6.5
DotX = 12

RowHeight = 62
RowHeightDense = 54

# ---- 颜色（与 download_card 同一套，深色底可读；选中行统一棕底） ----
ColorText = "#E8EBEE"
ColorMinor = "#94A0AA"
ColorDim = "#78828C"
ColorLine = "#3E434A"
ColorSelected = "#80501F"
ColorAccent = "#F0A05C"
ColorTag = {"proxy": "#E0955C", "self": "#B3BAC3", "cf": "#9DC0E0"}
ColorFail = "#EC7A6D"


def TagKind(item):
    """ 组别：proxy(ProxyIP 分流) / self(自定义) / cf(优选/CDN) """
    name = str(getattr(item, "name", "") or "")
    if name.startswith("ProxyIP"):
        return "proxy"
    if name.startswith("自定义"):
        return "self"
    return "cf"


def ShortName(item):
    """ 「ProxyIP分流3」-> 「ProxyIP 3」：组别 + 组内序号，宽度可控 """
    index = getattr(item, "j", 0)
    kind = TagKind(item)
    if kind == "proxy":
        return "ProxyIP {}".format(index)
    if kind == "self":
        return "自定义 {}".format(index)
    return "优选 {}".format(index)


def LatencyColor(delay):
    """ 延迟分档：<100 绿 / <250 黄 / 其余橘红 """
    try:
        delay = int(float(delay or 0))
    except (TypeError, ValueError):
        delay = 0
    if delay <= 0:
        return ColorDim
    if delay < 100:
        return "#6CC99A"
    if delay < 250:
        return "#E8B96A"
    return "#EC9A7D"


def SpeedParts(item):
    """ 拆出速度列的片段，便于逐段上色 + 单独测试

        [(文本, 'latency'|'muted'|'dim'|'fail'), ...]
        "152/210"   延迟/下载都有
        "152/—"     只测了延迟
        "连接超时"   整体失败
        "—"         还没测
    """
    delay = getattr(item, "delay", 0) or 0
    download = getattr(item, "downloadDelay", 0) or 0

    if getattr(item, "isFail", False):
        try:
            text = Str.GetStr(item.st)
        except Exception:
            text = ""
        return [(text or Tr("失败"), "fail")]
    if not delay and not download:
        return [("—", "dim")]

    parts = [(str(int(float(delay))), "latency"), ("/", "dim")]
    if download:
        parts.append((str(int(float(download))), "muted"))
    elif getattr(item, "downloadFail", False):
        try:
            text = Str.GetStr(item.downloadSt)
        except Exception:
            text = ""
        parts.append((text or Tr("下载失败"), "fail"))
    else:
        parts.append(("—", "dim"))
    return parts


def ScaledFont(base, delta, bold=False):
    """ 以应用字体为基准加减字号（跟随"字体大小"设置，不写死像素） """
    font = QFont(base)
    if font.pointSizeF() > 0:
        font.setPointSizeF(max(5.0, font.pointSizeF() + delta))
    else:
        size = font.pixelSize()
        if size <= 0:
            size = 13
        font.setPixelSize(max(9, int(round(size + delta * 1.34))))
    font.setBold(bold)
    return font


class ProxyNodeCard(QWidget):
    """ 一行节点 = 一张两行卡片（整卡鼠标穿透，选中/滚动交给表格） """

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.ip = ""
        self.tagKind = "cf"
        self.delay = 0
        self._selected = False
        self._dense = False
        self._parts = []
        self._geoText = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PadLeft, PadTop, PadRight, PadBottom)
        layout.setSpacing(1)

        base = self.font()
        fixed = QFontDatabase.systemFont(QFontDatabase.FixedFont)

        # 第一行：IP + 速度
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self.ipLabel = QLabel("", self)
        self._ipBaseFont = QFont(fixed)
        ipFont = QFont(fixed)
        pointSize = base.pointSizeF()
        if pointSize > 0:
            ipFont.setPointSizeF(max(6.0, pointSize + 0.4))
        else:
            ipFont.setPixelSize(max(10, int(base.pixelSize() * 1.05) if base.pixelSize() > 0 else 13))
        self.ipLabel.setFont(ipFont)
        self._ipPointSize = ipFont.pointSizeF()
        self.ipLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.speedLabel = QLabel("", self)
        speedFont = ScaledFont(base, 0.0)
        self.speedLabel.setFont(speedFont)
        self.speedLabel.setTextFormat(Qt.RichText)
        # 速度列宽度随字体走："9999/9999" 这种最宽组合必须放得下（列宽按参照串算，
        # 所以同一字号下每行完全一致）
        self._speedWidth = max(SpeedWidth, QFontMetrics(speedFont).horizontalAdvance("9999/9999") + 12)
        self.speedLabel.setFixedWidth(self._speedWidth)
        self.speedLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.ipLabel, 1)
        top.addWidget(self.speedLabel, 0)
        layout.addLayout(top)

        # 第二行：组别标签 + 地区 · ISP
        sub = QHBoxLayout()
        sub.setContentsMargins(0, 0, 0, 0)
        sub.setSpacing(6)
        self.tagLabel = QLabel("", self)
        tagFont = ScaledFont(base, -2.2)
        self.tagLabel.setFont(tagFont)
        # 标签列同理：按 "ProxyIP 00" 算，字号调大也不会把 "ProxyIP 10" 裁掉
        self._tagWidth = max(TagWidth, QFontMetrics(tagFont).horizontalAdvance("ProxyIP 00") + 12)
        self.tagLabel.setFixedWidth(self._tagWidth)
        self.tagLabel.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.geoLabel = QLabel("", self)
        self.geoLabel.setFont(ScaledFont(base, -1.2))
        self.geoLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        sub.addWidget(self.tagLabel, 0)
        sub.addWidget(self.geoLabel, 1)
        layout.addLayout(sub)

        self._StyleText()
        self._PaintSpeed()

        # 整张卡片（含子控件）鼠标穿透，交互全部留给底下的 QTableWidget
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    # -- 数据 -------------------------------------------------------------
    def Update(self, item):
        ip = str(getattr(item, "ip", "") or "")
        if self.ip != ip:
            self.ip = ip
            self.setToolTip(ip)

        self.delay = getattr(item, "delay", 0) or 0
        self.tagKind = TagKind(item)
        tag = ShortName(item)
        if self.tagLabel.text() != tag:
            self.tagLabel.setText(tag)

        geo = str(getattr(item, "country", "") or "")
        isp = str(getattr(item, "asn", "") or "")
        self._geoText = " · ".join([part for part in (geo, isp) if part]) or "—"
        self.geoLabel.setToolTip(self._geoText)

        parts = SpeedParts(item)
        if parts != self._parts:
            self._parts = parts
            self._PaintSpeed()
        self._StyleText()
        self._Relayout()

    def SetSelected(self, selected):
        selected = bool(selected)
        if selected == self._selected:
            return
        self._selected = selected
        self._StyleText()
        self._PaintSpeed()
        self.update()

    def SetDense(self, dense):
        dense = bool(dense)
        if dense == self._dense:
            return
        self._dense = dense
        margin = PadDense if dense else PadTop
        self.layout().setContentsMargins(PadLeft, margin, PadRight, margin)
        self.layout().setSpacing(0 if dense else 1)
        self.update()

    def RowHeight(self):
        """ 建议行高：跟随字体设置，但不小于设计值 """
        floor = RowHeightDense if self._dense else RowHeight
        return max(floor, self.layout().sizeHint().height())

    # -- 内部 -------------------------------------------------------------
    def _StyleText(self):
        if self._selected:
            self.ipLabel.setStyleSheet("color:#FFFFFF;")
            self.geoLabel.setStyleSheet("color:#F2D3B6;")
            self.tagLabel.setStyleSheet(
                "color:#FFFFFF;border:1px solid rgba(255,255,255,80);"
                "border-radius:2px;padding:0 3px;")
            return
        self.ipLabel.setStyleSheet("color:{};".format(ColorText))
        self.geoLabel.setStyleSheet("color:{};".format(ColorMinor))
        color = ColorTag.get(self.tagKind, ColorTag["cf"])
        rgb = QColor(color)
        self.tagLabel.setStyleSheet(
            "color:{color};border:1px solid rgba({r},{g},{b},90);"
            "border-radius:2px;padding:0 3px;".format(
                color=color, r=rgb.red(), g=rgb.green(), b=rgb.blue()))

    def _PaintSpeed(self):
        """ 组装「延迟/下载」，逐段上色（选中行改白，避免绿字压棕底看不清） """
        if self._selected:
            palette = {"latency": "#FFFFFF", "muted": "#F6E2CD", "dim": "#D9B795", "fail": "#FFFFFF"}
        else:
            palette = {"latency": LatencyColor(self.delay), "muted": "#B6BEC6",
                       "dim": ColorDim, "fail": ColorFail}
        html = "".join('<span style="color:{};">{}</span>'.format(palette.get(kind, "#B6BEC6"), text)
                       for text, kind in self._parts)
        if self.speedLabel.text() != html:
            self.speedLabel.setText(html)

    def _Relayout(self):
        """ 按卡片宽度算 IP / 地区可用宽度并做尾部省略（完整内容留在 tooltip）

            不能拿子 QLabel 的 width()：resizeEvent 触发时布局还没把子控件摆好，
            拿到的是上一轮的旧宽度，IPv6 会被多省略一截（宿主自检里实测到过）。
        """
        width = self.width()
        if width <= 0:
            # 还没进布局：先放原文，等 resizeEvent 再省略
            if self.ipLabel.text() != self.ip:
                self.ipLabel.setText(self.ip)
            if self.geoLabel.text() != self._geoText:
                self.geoLabel.setText(self._geoText)
            return

        inner = width - PadLeft - PadRight
        ipWidth = max(40, inner - self._speedWidth - 8)
        self._FitIpFont(ipWidth)
        metrics = self.ipLabel.fontMetrics()
        self.ipLabel.setText(metrics.elidedText(self.ip, Qt.TextElideMode.ElideRight, ipWidth))

        geoWidth = max(40, inner - self._tagWidth - 6)
        geoMetrics = self.geoLabel.fontMetrics()
        self.geoLabel.setText(geoMetrics.elidedText(self._geoText, Qt.TextElideMode.ElideRight,
                                                    geoWidth))

    def _FitIpFont(self, ipWidth):
        """ 按可用宽度自适 IP 字号（下限 6.5pt）

            参照的是"最长的一类 IP(32 字符)"而不是本行文字，所以同一宽度下每一行
            得到的字号完全相同 —— 不会出现"这行大那行小"。IPv6 永远不省略；
            只有用户把系统字号调到极端值、连下限都放不下时才退化成末尾省略。
        """
        if self._ipPointSize <= 0:
            return
        size = self._ipPointSize
        font = QFont(self._ipBaseFont)
        while size > IpMinPointSize:
            font.setPointSizeF(size)
            if QFontMetrics(font).horizontalAdvance(IpRefText) <= ipWidth:
                break
            size -= 0.5
        if abs(self.ipLabel.font().pointSizeF() - size) > 0.01:
            font.setPointSizeF(size)
            self.ipLabel.setFont(font)

    def sizeHint(self):
        return QSize(max(160, self.width()), self.layout().sizeHint().height())

    def resizeEvent(self, event):
        QWidget.resizeEvent(self, event)
        self._Relayout()

    # -- 绘制 -------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect()
        if self._selected:
            painter.fillRect(rect, QColor(ColorSelected))
            painter.fillRect(0, 0, 3, rect.height(), QColor(ColorAccent))

        # 左端单选圆点：和原表格里的勾选框同一语义，画出来不占控件
        centerY = self.ipLabel.geometry().center().y()
        if centerY <= 0:
            centerY = rect.height() // 2
        centerX = DotX + 7
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(ColorAccent if self._selected else "#6D747D"), 1.5))
        painter.drawEllipse(centerX - 7, centerY - 7, 14, 14)
        if self._selected:
            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(centerX - 3, centerY - 3, 6, 6)

        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(QPen(QColor(ColorLine), 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right() - 1, rect.bottom())
        painter.end()
