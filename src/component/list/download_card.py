# coding:utf-8
""" 下载列表卡片（方案 A）

原来下载页是 11 列宽表：竖屏 478px 下只能把 id/速度/转换章节/转换耗时 4 列隐藏，
标题被压到 2~3 个字（「[萧…」），表头也被主题里的 `padding: 0 20px` 裁掉半个字。
这里把「一行」改成「一张卡片」，同一个屏幕宽度内放得下全部字段：

    【标题】最多两行，超出末尾省略（完整标题进 tooltip）
    #422231 · 2026-10-26 19:07
    下载 163/163    章节 1/1    速度 1.2 MB/s          [下载完成]
    转换 163/163    章节 1/1    耗时 12s              [转换完成]
    ── 2px 进度条（只有下载中的卡片才出现）

三个要点：
1. 标签和值分组（下载组 / 转换组），组内三列用同一套固定比例，卡片之间自然对齐；
2. 状态是右对齐的徽章，不再占用一整列的宽度，也不再靠表头文字解释；
3. 卡片整体鼠标穿透（WA_TransparentForMouseEvents）：点击/长按/滑动全部落到
   底下的 QTableWidget 上，选择、右键菜单、双击、QScroller 都和原来一模一样。
"""
import time

from PySide6.QtCore import QCoreApplication, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QSizePolicy,
                               QVBoxLayout, QWidget)


def Tr(text):
    """ 本页新增文案统一走 translate(和 ui_download.py 一样)，方便以后补英文 """
    return QCoreApplication.translate("Download", text, None)

PadH = 12
PadTop = 8
PadBottom = 9

ColorText = "#E8EBEE"
ColorMinor = "#94A0AA"
ColorKey = "#9AA3AC"
ColorValue = "#DDE3E9"
ColorDim = "#78828C"
ColorLine = "#3E434A"
ColorSelected = "#80501F"

# 状态 -> (文字色, 底色 alpha 百分比, 描边 alpha 百分比)
StateColors = {
    "ok": "#6CC99A",
    "run": "#F0A05C",
    "err": "#EC7A6D",
    "wait": "#98A2AC",
    "pause": "#CFAE72",
}

MaxTitleLines = 2


def ElideLines(text, metrics, width, maxLines=MaxTitleLines):
    """ 把一段文字折成最多 maxLines 行、最后一行末尾省略

    Qt 的 QLabel 只有单行省略(elidedText)，折行 + 省略要自己算：
    逐行二分找"放得下的最长前缀"，最后一行交给 elidedText 保证有省略号。
    """
    text = " ".join(str(text or "").split())
    if not text or width <= 16:
        return text
    lines = []
    rest = text
    for index in range(max(1, maxLines)):
        if not rest:
            break
        if metrics.horizontalAdvance(rest) <= width:
            lines.append(rest)
            rest = ""
            break
        if index == maxLines - 1:
            lines.append(metrics.elidedText(rest, Qt.TextElideMode.ElideRight, width))
            rest = ""
            break
        low, high = 1, len(rest)
        while low < high:
            mid = (low + high + 1) // 2
            if metrics.horizontalAdvance(rest[:mid]) <= width:
                low = mid
            else:
                high = mid - 1
        lines.append(rest[:low])
        rest = rest[low:]
    return "\n".join(lines)


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


class _ThinBar(QWidget):
    """ 2px 下载进度条 """

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self._value = 0.0
        self._color = QColor(StateColors["run"])
        self.setFixedHeight(2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def SetValue(self, value, color=None):
        value = max(0.0, min(1.0, float(value or 0.0)))
        if color is not None:
            self._color = QColor(color)
        if abs(value - self._value) < 0.004:
            return
        self._value = value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        painter.fillRect(rect, QColor(ColorLine))
        width = int(rect.width() * self._value)
        if width > 0:
            painter.fillRect(0, 0, width, rect.height(), self._color)
        painter.end()


class _KV(QWidget):
    """ 一个「标签 + 值」单元 """

    def __init__(self, key, parent=None):
        QWidget.__init__(self, parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.keyLabel = QLabel(key, self)
        self.valueLabel = QLabel("", self)
        self.keyLabel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.valueLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.keyLabel, 0)
        layout.addWidget(self.valueLabel, 1)

    def SetValue(self, text):
        if self.valueLabel.text() != text:
            self.valueLabel.setText(text)


class DownloadCard(QWidget):
    """ 一行下载记录 = 一张卡片 """

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.bookId = ""
        self._title = ""
        self._selected = False
        self._lineWidth = -1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PadH, PadTop, PadH, PadBottom)
        layout.setSpacing(0)

        base = self.font()

        self.titleLabel = QLabel("", self)
        self.titleLabel.setFont(ScaledFont(base, 1.6, True))
        self.titleLabel.setWordWrap(False)
        self.titleLabel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.titleLabel.setStyleSheet("color:{};".format(ColorText))
        layout.addWidget(self.titleLabel)

        # 第二行：ID · 时间
        meta = QHBoxLayout()
        meta.setContentsMargins(0, 1, 0, 0)
        meta.setSpacing(5)
        self.idLabel = QLabel("", self)
        self.idLabel.setFont(ScaledFont(base, -1.6))
        self.idLabel.setStyleSheet("color:{};".format(ColorMinor))
        self.timeLabel = QLabel("", self)
        self.timeLabel.setFont(ScaledFont(base, -1.6))
        self.timeLabel.setStyleSheet("color:{};".format(ColorMinor))
        # 不能是 Ignored：后面跟着 stretch，Ignored 会被压成 0 宽 —— 时间整条看不见
        self.timeLabel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        meta.addWidget(self.idLabel, 0)
        meta.addWidget(self.timeLabel, 0)
        meta.addStretch(1)
        layout.addLayout(meta)

        # 指标网格：下载组 / 转换组，各占一行，三列固定比例 + 右侧状态徽章
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 5, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(1)
        self.grid.setColumnStretch(0, 104)
        self.grid.setColumnStretch(1, 76)
        self.grid.setColumnStretch(2, 104)
        self.grid.setColumnStretch(3, 0)

        self.kvDl = _KV(Tr("下载"), self)
        self.kvEps = _KV(Tr("章节"), self)
        self.kvSpeed = _KV(Tr("速度"), self)
        self.kvCv = _KV(Tr("转换"), self)
        self.kvCvEps = _KV(Tr("章节"), self)
        self.kvCvTime = _KV(Tr("耗时"), self)
        self.stateDl = QLabel("", self)
        self.stateCv = QLabel("", self)
        for badge in (self.stateDl, self.stateCv):
            badge.setFont(ScaledFont(base, -1.8))
            badge.setAlignment(Qt.AlignCenter)
            badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.grid.addWidget(self.kvDl, 0, 0)
        self.grid.addWidget(self.kvEps, 0, 1)
        self.grid.addWidget(self.kvSpeed, 0, 2)
        self.grid.addWidget(self.stateDl, 0, 3, Qt.AlignRight | Qt.AlignVCenter)
        self.grid.addWidget(self.kvCv, 1, 0)
        self.grid.addWidget(self.kvCvEps, 1, 1)
        self.grid.addWidget(self.kvCvTime, 1, 2)
        self.grid.addWidget(self.stateCv, 1, 3, Qt.AlignRight | Qt.AlignVCenter)
        layout.addLayout(self.grid)

        for kv in (self.kvDl, self.kvEps, self.kvSpeed, self.kvCv, self.kvCvEps, self.kvCvTime):
            kv.keyLabel.setFont(ScaledFont(base, -1.4))
            kv.keyLabel.setStyleSheet("color:{};".format(ColorKey))
            kv.valueLabel.setFont(ScaledFont(base, 0.2))
            kv.valueLabel.setStyleSheet("color:{};".format(ColorValue))

        self.bar = _ThinBar(self)
        layout.addSpacing(4)
        layout.addWidget(self.bar)
        self.bar.setVisible(False)

        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    # -- 数据 -------------------------------------------------------------
    @staticmethod
    def _Kind(value, success, running, error, pause):
        """ 状态数值 -> 颜色档位（按常量判，不依赖翻译文案） """
        if value == success:
            return "ok"
        if value == running:
            return "run"
        if value == error:
            return "err"
        if value == pause:
            return "pause"
        return "wait"

    def Update(self, info):
        self.bookId = str(getattr(info, "bookId", "") or "")
        oldTitle = self._title
        self._title = str(getattr(info, "title", "") or "")
        self.idLabel.setText("#" + self.bookId)

        try:
            timeText = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info.tick))
        except Exception:
            timeText = ""
        self.timeLabel.setText(("· " + timeText) if timeText else "")
        self.timeLabel.setVisible(bool(timeText))

        self._SetValue(self.kvDl, "{}/{}".format(info.curDownloadPic, info.maxDownloadPic))
        self._SetValue(self.kvEps, "{}/{}".format(info.curDownloadEps, info.epsCount))
        self._SetValue(self.kvSpeed, str(getattr(info, "speedStr", "") or "—"))
        self._SetValue(self.kvCv, "{}/{}".format(info.curConvertCnt, info.convertCnt))
        self._SetValue(self.kvCvEps, "{}/{}".format(info.curConvertEps, info.convertEpsCnt))
        # convertTick 已经是 "12s" 这种带单位的串（0 时显示占位）
        try:
            tick = str(info.convertTick or "")
        except Exception:
            tick = ""
        self._SetValue(self.kvCvTime, tick if tick not in ("", "0", "0s") else "—")

        self._SetBadge(self.stateDl, info.GetStatusMsg(),
                       self._Kind(info.status, info.Success, info.Downloading, info.Error, info.Pause))
        self._SetBadge(self.stateCv, info.GetConvertStatusMsg(),
                       self._Kind(info.convertStatus, info.ConvertSuccess, info.Converting, info.Error, info.Pause))

        # 下载中的才显示进度条（已完成/暂停的没有意义）
        running = info.status == info.Downloading and info.maxDownloadPic > 0
        self.bar.setVisible(bool(running))
        if running:
            self.bar.SetValue(float(info.curDownloadPic) / float(info.maxDownloadPic))

        # 每秒都会刷新一次：标题没变就别重算折行/tooltip
        if oldTitle != self._title:
            self.setToolTip(self._title)
            self._lineWidth = -1
        self.RelayoutFor(self.width() or 320)

    @staticmethod
    def _SetValue(kv, text):
        text = str(text or "")
        if kv.valueLabel.text() == text:
            return
        kv.valueLabel.setText(text)
        # 没有值(—)用暗色，避免一屏里一堆亮色横杠
        kv.valueLabel.setStyleSheet("color:{};".format(ColorDim if text in ("—", "") else ColorValue))

    def _SetBadge(self, badge, text, kind):
        text = str(text or "")
        if badge.text() != text or badge.property("jmKind") != kind:
            badge.setText(text)
            badge.setProperty("jmKind", kind)
            self._StyleBadge(badge)
            badge.adjustSize()
        badge.setVisible(bool(text))

    def _StyleBadge(self, badge):
        """ 选中行是棕底：徽章改用白色系，否则绿字压在棕底上几乎看不清 """
        kind = badge.property("jmKind") or "wait"
        color = StateColors.get(kind, StateColors["wait"])
        rgb = QColor(color)
        if self._selected:
            badge.setStyleSheet(
                "color:#FFFFFF;background-color:rgba(0,0,0,22%);"
                "border:1px solid rgba(255,255,255,45%);border-radius:2px;padding:0 4px;")
        else:
            badge.setStyleSheet(
                "color:{color};"
                "background-color:rgba({r},{g},{b},16%);"
                "border:1px solid rgba({r},{g},{b},42%);"
                "border-radius:2px;padding:0 4px;".format(
                    color=color, r=rgb.red(), g=rgb.green(), b=rgb.blue()))

    def SetSelected(self, selected):
        selected = bool(selected)
        if selected == self._selected:
            return
        self._selected = selected
        self._StyleBadge(self.stateDl)
        self._StyleBadge(self.stateCv)
        self.update()

    # -- 布局 -------------------------------------------------------------
    def RelayoutFor(self, width):
        """ 按给定宽度重算标题的折行/省略（行高随之变化） """
        width = int(width or 0)
        if width <= 0 or width == self._lineWidth:
            return
        self._lineWidth = width
        metrics = self.titleLabel.fontMetrics()
        text = ElideLines(self._title, metrics, max(40, width - PadH * 2 - 2), MaxTitleLines)
        if self.titleLabel.text() != text:
            self.titleLabel.setText(text)
        lines = max(1, text.count("\n") + 1)
        self.titleLabel.setFixedHeight(lines * metrics.lineSpacing())

    def Relayout(self):
        self._lineWidth = -1
        width = self.width()
        if width <= 0 and self.parentWidget() is not None:
            width = self.parentWidget().width()
        self.RelayoutFor(width)

    def HeightForWidth(self, width):
        self.RelayoutFor(width)
        return self.sizeHint().height()

    def sizeHint(self):
        return QSize(max(120, self.width()), self.layout().sizeHint().height())

    def resizeEvent(self, event):
        QWidget.resizeEvent(self, event)
        self.RelayoutFor(self.width())

    # -- 绘制 -------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect()
        if self._selected:
            painter.fillRect(rect, QColor(ColorSelected))
        painter.setPen(QPen(QColor(ColorLine), 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        painter.end()
