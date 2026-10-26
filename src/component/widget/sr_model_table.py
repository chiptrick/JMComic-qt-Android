# coding:utf-8
""" 超分模型列表（3 列 + 算法分组 + 吸顶分组条）

为什么要重写：原实现是 4 列定宽 200/150/100/100=550，加上弹窗内边距后约 578，
而手机逻辑宽只有 480 —— 右侧列永远在屏幕外；当时的"补丁"是把「耗时」列
setColumnHidden 掉，等于用信息缺失换宽度。

这里改成：
    * 3 列：模型名(stretch) / 耗时(56) / 描述(66)，总宽恒等于视口，**永不横向滚动**；
    * 模型名不再展示 MODEL_... 原始串，而是 `CUNET · 2× · 降噪 3` 这种能读的写法；
    * 算法升级成分组条（默认吸顶，滚动时始终知道当前在哪一组）；
    * 点「耗时」表头 → 平铺 + 按耗时升序，再点 → 降序，再点 → 回到分组；
    * 当前正在使用的模型整行高亮 + 左侧色条 + 「当前使用」角标。
"""
from PySide6.QtCore import QCoreApplication, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QTableWidget,
                               QTableWidgetItem)


def _Tr(text):
    """ 走一次 translate：以后进 .ts 就能翻，没装翻译器时原样返回 """
    return QCoreApplication.translate("SrModelTable", text)

# 算法顺序：与旧表一致(Waifu2x → Real-CUGAN → Real-ESRGAN)
Algorithms = ("Waifu2x", "Real-CUGAN", "Real-ESRGAN")

# 各算法的分组色点
AlgoColors = {
    "Waifu2x": QColor(0x57, 0xA9, 0xA1),
    "Real-CUGAN": QColor(0x8F, 0x83, 0xD6),
    "Real-ESRGAN": QColor(0xD3, 0xA0, 0x3C),
}

# 模型族 → 展示名（只影响可读性，不影响 MODEL_ 串的生成）
FamilyNames = {
    "CUNET": "CUNET", "ANIME": "Anime", "PHOTO": "Photo",
    "PRO": "Pro", "SE": "SE",
    "ANIMAVIDEOV3": "AnimaVideoV3", "X4PLUS": "X4Plus", "X4PLUSANIME": "X4PlusAnime",
}

# (模型名, 算法, 放大倍数, 降噪等级(-1=无), 相对耗时%, 是否推荐)
# 数据与原 AllModelNames 完全一致，顺序即分组内的展示顺序
SrModels = (
    ("CUNET_UP1X_DENOISE0X", "Waifu2x", 1, 0, 100, False),
    ("CUNET_UP1X_DENOISE1X", "Waifu2x", 1, 1, 110, False),
    ("CUNET_UP1X_DENOISE2X", "Waifu2x", 1, 2, 110, False),
    ("CUNET_UP1X_DENOISE3X", "Waifu2x", 1, 3, 110, False),
    ("CUNET_UP2X", "Waifu2x", 2, -1, 300, False),
    ("CUNET_UP2X_DENOISE0X", "Waifu2x", 2, 0, 310, False),
    ("CUNET_UP2X_DENOISE1X", "Waifu2x", 2, 1, 310, False),
    ("CUNET_UP2X_DENOISE2X", "Waifu2x", 2, 2, 310, False),
    ("CUNET_UP2X_DENOISE3X", "Waifu2x", 2, 3, 310, True),
    ("ANIME_UP2X", "Waifu2x", 2, -1, 200, False),
    ("ANIME_UP2X_DENOISE0X", "Waifu2x", 2, 0, 210, False),
    ("ANIME_UP2X_DENOISE1X", "Waifu2x", 2, 1, 210, False),
    ("ANIME_UP2X_DENOISE2X", "Waifu2x", 2, 2, 210, False),
    ("ANIME_UP2X_DENOISE3X", "Waifu2x", 2, 3, 210, True),
    ("PHOTO_UP2X", "Waifu2x", 2, -1, 180, False),
    ("PHOTO_UP2X_DENOISE0X", "Waifu2x", 2, 0, 200, False),
    ("PHOTO_UP2X_DENOISE1X", "Waifu2x", 2, 1, 200, False),
    ("PHOTO_UP2X_DENOISE2X", "Waifu2x", 2, 2, 200, False),
    ("PHOTO_UP2X_DENOISE3X", "Waifu2x", 2, 3, 200, True),
    ("PRO_UP2X", "Real-CUGAN", 2, -1, 350, False),
    ("PRO_UP2X_CONSERVATIVE", "Real-CUGAN", 2, -1, 350, False),
    ("PRO_UP2X_DENOISE3X", "Real-CUGAN", 2, 3, 350, True),
    ("PRO_UP3X", "Real-CUGAN", 3, -1, 500, False),
    ("PRO_UP3X_CONSERVATIVE", "Real-CUGAN", 3, -1, 500, False),
    ("PRO_UP3X_DENOISE3X", "Real-CUGAN", 3, 3, 500, False),
    ("SE_UP2X", "Real-CUGAN", 2, -1, 300, False),
    ("SE_UP2X_CONSERVATIVE", "Real-CUGAN", 2, -1, 300, False),
    ("SE_UP2X_DENOISE1X", "Real-CUGAN", 2, 1, 300, False),
    ("SE_UP2X_DENOISE2X", "Real-CUGAN", 2, 2, 300, False),
    ("SE_UP2X_DENOISE3X", "Real-CUGAN", 2, 3, 300, True),
    ("SE_UP3X", "Real-CUGAN", 3, -1, 500, False),
    ("SE_UP3X_CONSERVATIVE", "Real-CUGAN", 3, -1, 500, False),
    ("SE_UP3X_DENOISE3X", "Real-CUGAN", 3, 3, 500, False),
    ("SE_UP4X", "Real-CUGAN", 4, -1, 400, False),
    ("SE_UP4X_CONSERVATIVE", "Real-CUGAN", 4, -1, 400, False),
    ("SE_UP4X_DENOISE3X", "Real-CUGAN", 4, 3, 400, False),
    ("ANIMAVIDEOV3_UP2X", "Real-ESRGAN", 2, -1, 200, True),
    ("ANIMAVIDEOV3_UP3X", "Real-ESRGAN", 3, -1, 300, False),
    ("ANIMAVIDEOV3_UP4X", "Real-ESRGAN", 4, -1, 400, False),
    ("X4PLUS_UP4X", "Real-ESRGAN", 4, -1, 600, False),
    ("X4PLUSANIME_UP4X", "Real-ESRGAN", 4, -1, 400, False),
)


def ModelFamily(modelId):
    """ CUNET_UP2X_DENOISE3X → CUNET """
    return modelId.split("_UP")[0]


def ModelVariant(modelId, denoise):
    """ 降噪等级的可读写法 """
    if denoise >= 0:
        return "降噪 {}".format(denoise)
    return "保守" if "CONSERVATIVE" in modelId else "无降噪"


def ShowModelLines(model):
    """ 两行写法：第一行模型族，第二行倍数 · 降噪

    单行拼起来("AnimaVideoV3 · 2× · 无降噪")在 340 逻辑宽下会顶到列宽边缘，
    拆两行后每行都只有一半宽，再窄的屏也不会被截断。
    """
    modelId, up, denoise = model[0], model[2], model[3]
    family = FamilyNames.get(ModelFamily(modelId), ModelFamily(modelId))
    return family, "{}× · {}".format(up, ModelVariant(modelId, denoise))


def ShowModelName(model):
    """ 单行写法（tooltip / 日志用），也不含 MODEL_ 前缀与 UP/DENOISE 原始 token """
    family, detail = ShowModelLines(model)
    return "{} · {}".format(family, detail)


def FullModelName(model):
    """ 传给 sr_vulkan / Setting 的完整模型名 """
    return "MODEL_{}_{}".format(model[1].replace("-", "").upper(), model[0])


def FormatModelLabel(fullName, fallback=""):
    """ 阅读页/批量页的入口文案：短名 + 倍数 + 降噪，同样不展示完整 ID """
    if not fullName:
        return fallback
    for model in SrModels:
        if FullModelName(model) == fullName:
            from tools.tool import ToolUtil
            return "{} · {}× · {}".format(
                ToolUtil.GetShowModelName(fullName), model[2], ModelVariant(model[0], model[3]))
    from tools.tool import ToolUtil
    return ToolUtil.GetShowModelName(fullName) or fallback


class SrModelTable(QTableWidget):
    """ 模型列表：三列 + 分组条(吸顶) + 当前使用高亮 """

    GroupHeight = 26
    RowHeight = 46
    CostWidth = 56
    DescWidth = 66
    BarWidth = 3

    SortGrouped = 0
    SortCostAsc = 1
    SortCostDesc = 2

    def __init__(self, parent=None):
        # 必须先把列数定下来：列数为 0 时 setHorizontalHeaderItem 会越界
        QTableWidget.__init__(self, 0, 3, parent)
        self._sortMode = self.SortGrouped
        self._currentName = ""
        self._pickedName = ""
        self._groupRows = []        # [(row, algo, count)]
        self._groupRowSet = set()
        self._rowGroup = {}         # 模型行 → 算法
        self._modelRows = []        # [(row, model)]

        self.setObjectName("srModelTable")
        self.setShowGrid(False)
        # 模型名是两行(模型族 / 倍数·降噪)，必须允许换行；单行文本不会自己折
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideRight)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSortingEnabled(False)
        # 列宽由 stretch + 两个定宽列决定，横向滚动条永远不需要
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(self.RowHeight)

        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionsClickable(True)
        header.setMinimumSectionSize(40)
        header.setFixedHeight(30)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.setColumnWidth(1, self.CostWidth)
        self.setColumnWidth(2, self.DescWidth)
        header.sectionClicked.connect(self.OnHeaderClicked)
        self._UpdateHeader()

    # ------------------------------------------------------------------ 数据
    def SetCurrentModel(self, fullName):
        """ 标记"当前使用"（来自 Setting 的完整模型名） """
        self._currentName = fullName or ""
        if not self._pickedName:
            self._pickedName = self._currentName
        self.Reload()
        self.ScrollToCurrent()

    def CurrentModelName(self):
        return self._currentName

    def SelectedModelName(self):
        return self._pickedName

    def PickModel(self, fullName):
        self._pickedName = fullName or ""
        self._ApplyRowStyles()
        self.viewport().update()

    def RowOfModel(self, fullName):
        for row, model in self._modelRows:
            if FullModelName(model) == fullName:
                return row
        return -1

    def ModelCount(self):
        return len(self._modelRows)

    def GroupCount(self):
        return len(self._groupRows)

    def SortMode(self):
        return self._sortMode

    # ------------------------------------------------------------------ 排序
    def OnHeaderClicked(self, section):
        if section == 1:
            if self._sortMode == self.SortGrouped:
                self.SetSortMode(self.SortCostAsc)
            elif self._sortMode == self.SortCostAsc:
                self.SetSortMode(self.SortCostDesc)
            else:
                self.SetSortMode(self.SortGrouped)
        elif section == 0 and self._sortMode != self.SortGrouped:
            # 点「模型」= 回到分组（给一个不用连点两次的退路）
            self.SetSortMode(self.SortGrouped)

    def SetSortMode(self, mode):
        if mode == self._sortMode and self._modelRows:
            return
        self._sortMode = mode
        self._UpdateHeader()
        self.Reload()

    def _UpdateHeader(self):
        marks = {self.SortGrouped: "↕", self.SortCostAsc: "↑", self.SortCostDesc: "↓"}
        titles = ["模型", "耗时 {}".format(marks[self._sortMode]), "描述"]
        align = [Qt.AlignLeft, Qt.AlignRight, Qt.AlignRight]
        font = self.font()
        font.setPointSizeF(9.0)
        for col, title in enumerate(titles):
            item = self.horizontalHeaderItem(col)
            if item is None:
                item = QTableWidgetItem()
                self.setHorizontalHeaderItem(col, item)
            item.setText(title)
            item.setFont(font)
            item.setTextAlignment(align[col] | Qt.AlignVCenter)

    # ------------------------------------------------------------------ 构建
    def ApplyColumnWidths(self):
        """ 定宽列必须**每次**重新声明

        .ui 里 horizontalHeaderDefaultSectionSize=80 会在 setupUi 时把所有 section
        重置成 80（构造函数里设的 56/66 被覆盖），不补这一手就变成 3 个 80px 列。
        """
        self.setColumnWidth(1, self.CostWidth)
        self.setColumnWidth(2, self.DescWidth)

    def resizeEvent(self, event):
        QTableWidget.resizeEvent(self, event)
        self.ApplyColumnWidths()

    def Reload(self):
        rows = []
        if self._sortMode == self.SortGrouped:
            for algo in Algorithms:
                group = [m for m in SrModels if m[1] == algo]
                if not group:
                    continue
                rows.append(("group", algo, group))
                rows.extend(("model", m, None) for m in group)
        else:
            reverse = self._sortMode == self.SortCostDesc
            ordered = sorted(enumerate(SrModels), key=lambda pair: (pair[1][4], pair[0]),
                             reverse=reverse)
            rows.extend(("model", pair[1], None) for pair in ordered)

        self.setUpdatesEnabled(False)
        self.clearSpans()
        self.clearContents()
        self.setRowCount(len(rows))
        self._groupRows = []
        self._groupRowSet = set()
        self._rowGroup = {}
        self._modelRows = []

        groupFont = self.font()
        groupFont.setPointSizeF(9.0)
        groupFont.setBold(True)
        spaces = max(1, round(12 / max(1, self.fontMetrics().horizontalAdvance(" "))))

        for row, (kind, payload, extra) in enumerate(rows):
            if kind == "group":
                algo, group = payload, extra
                item = QTableWidgetItem("{}{}    {}".format(" " * spaces, algo, len(group)))
                item.setFont(groupFont)
                item.setForeground(self._MutedColor())
                item.setBackground(self._GroupColor())
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                item.setFlags(Qt.ItemIsEnabled)
                self.setItem(row, 0, item)
                self.setSpan(row, 0, 1, 3)
                self.setRowHeight(row, self.GroupHeight)
                self._groupRows.append((row, algo, len(group)))
                self._groupRowSet.add(row)
                continue

            model = payload
            fullName = FullModelName(model)

            nameItem = QTableWidgetItem("\n".join(ShowModelLines(model)))
            nameItem.setData(Qt.UserRole, fullName)
            nameItem.setToolTip(ShowModelName(model))
            nameItem.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            nameFont = self.font()
            nameFont.setPointSizeF(10.0)
            nameItem.setFont(nameFont)

            costItem = QTableWidgetItem("{:.0f}%".format(model[4]))
            costItem.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            costFont = self.font()
            costFont.setPointSizeF(10.0)
            costItem.setFont(costFont)

            badge = ""
            if fullName == self._currentName:
                badge = _Tr("当前使用")
            elif model[5]:
                badge = _Tr("推荐")
            descItem = QTableWidgetItem(badge)
            descItem.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            descFont = self.font()
            descFont.setPointSizeF(9.0)
            descItem.setFont(descFont)

            self.setItem(row, 0, nameItem)
            self.setItem(row, 1, costItem)
            self.setItem(row, 2, descItem)
            self.setRowHeight(row, self.RowHeight)
            self._modelRows.append((row, model))
            self._rowGroup[row] = model[1]

        self.setUpdatesEnabled(True)
        self.ApplyColumnWidths()
        self._ApplyRowStyles()
        self.viewport().update()

    def _ApplyRowStyles(self):
        highlight = self.palette().highlight().color()
        current = QColor(highlight.red(), highlight.green(), highlight.blue(), 38)
        picked = QColor(highlight.red(), highlight.green(), highlight.blue(), 54)
        blank = QColor(0, 0, 0, 0)
        for row, model in self._modelRows:
            fullName = FullModelName(model)
            isCurrent = bool(self._currentName) and fullName == self._currentName
            isPicked = bool(self._pickedName) and fullName == self._pickedName and not isCurrent
            for col in range(3):
                item = self.item(row, col)
                if item is None:
                    continue
                item.setBackground(picked if isPicked else (current if isCurrent else blank))
            nameItem = self.item(row, 0)
            if nameItem is not None:
                font = nameItem.font()
                font.setBold(isCurrent)
                nameItem.setFont(font)
                if isCurrent:
                    nameItem.setForeground(highlight)
                else:
                    nameItem.setForeground(self.palette().text().color())

    def _GroupColor(self):
        color = self.palette().base().color()
        return color.lighter(118) if color.lightness() < 128 else color.darker(106)

    def _MutedColor(self):
        color = self.palette().text().color()
        color.setAlpha(160)
        return color

    def ScrollToCurrent(self):
        row = self.RowOfModel(self._currentName)
        if row >= 0:
            self.scrollToItem(self.item(row, 0), QAbstractItemView.PositionAtCenter)

    # ------------------------------------------------------------- 吸顶分组条
    def StickyGroup(self):
        """ 视口顶部应该显示哪个分组条（空串 = 不画）

        分组行自己露在顶上时返回空：交给它自己绘制，避免"盖两层"。
        """
        if self._sortMode != self.SortGrouped:
            return ""
        row = self.rowAt(0)
        if row < 0 or row in self._groupRowSet:
            return ""
        return self._rowGroup.get(row, "")

    def GroupCountOf(self, algo):
        for _, name, count in self._groupRows:
            if name == algo:
                return count
        return 0

    def paintEvent(self, event):
        QTableWidget.paintEvent(self, event)
        painter = QPainter(self.viewport())
        try:
            self._PaintCurrentBar(painter)
            algo = self.StickyGroup()
            if algo:
                self._PaintStickyGroup(painter, algo)
        finally:
            painter.end()

    def _PaintCurrentBar(self, painter):
        row = self.RowOfModel(self._currentName)
        if row < 0:
            return
        y = self.rowViewportPosition(row)
        height = self.rowHeight(row)
        if height <= 0 or y + height <= 0 or y >= self.viewport().height():
            return
        painter.fillRect(QRect(0, y, self.BarWidth, height), self.palette().highlight().color())

    def _PaintStickyGroup(self, painter, algo):
        width = self.viewport().width()
        rect = QRect(0, 0, width, self.GroupHeight)
        painter.fillRect(rect, self._GroupColor())
        border = self.palette().text().color()
        border.setAlpha(28)
        painter.setPen(QPen(border, 1))
        painter.drawLine(0, self.GroupHeight - 1, width, self.GroupHeight - 1)

        color = AlgoColors.get(algo, self.palette().highlight().color())
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        dot = 6
        painter.drawEllipse(QRect(12, (self.GroupHeight - dot) // 2, dot, dot))

        font = self.font()
        font.setPointSizeF(9.0)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self._MutedColor())
        text = "{}    {}".format(algo, self.GroupCountOf(algo))
        painter.drawText(rect.adjusted(24, 0, -12, -1), Qt.AlignLeft | Qt.AlignVCenter, text)
