# coding:utf-8
""" 超分模型列表（3 列 + 算法分组 + 吸顶分组条 + 可用性校验）

为什么要重写：原实现是 4 列定宽 200/150/100/100=550，加上弹窗内边距后约 578，
而手机逻辑宽只有 480 —— 右侧列永远在屏幕外；当时的"补丁"是把「耗时」列
setColumnHidden 掉，等于用信息缺失换宽度。

这里改成：
    * 3 列：模型名(stretch) / 耗时(56) / 描述(66)，总宽恒等于视口，**永不横向滚动**；
    * 模型名展示完整原始 ID（`CUNET_UP2X_DENOISE3X`），等宽字体；
    * 算法升级成分组条（吸顶，滚动时始终知道当前在哪一组）；
    * 点「耗时」表头 → 平铺 + 升序，再点 → 降序，再点 → 回到分组；
    * 当前正在使用的模型整行高亮 + 左侧色条 + 「当前使用」角标。

可用性校验（ProbeModels）：
    * 只显示引擎里**真实存在**的模型（安卓端还要求 onnx 文件在 models 目录里）；
    * 引擎里有、但静态表里没有的 → 单独一组「自定义模型」，显示文件名去后缀；
    * 探测不可用（没装引擎/还没初始化）时**退回显示全部**，避免列表直接空掉。

真机两个顽疾的根因（都已在此文件/弹窗基类里修掉，改动前请先读这里）：
    1. **点哪行都没反应** —— 选中状态靠 `QTableWidgetItem.setBackground()` 表达，但主题
       qss 的 `QWidget{background-color}` / `QTableView::item` 规则会命中，
       QStyleSheetStyle 自己填面板背景，BackgroundRole 被完全忽略；而
       `palette().highlight()` 又被 `selection-background-color: rgba(...,0.2)`
       带了 20% alpha，拿它画文字等于画了个几乎透明的字。
       现在整行由 `SrModelDelegate` 自绘（底色 + 左侧色条 + 徽章 + 不透明强调色）。
    2. **滚动卡顿/不跟手** —— 弹窗内容控件上的 QGraphicsDropShadowEffect 会把整窗
       逐帧渲染进 pixmap 再模糊（宿主实测单帧重绘 1.5ms → 5.4ms）；再加上每帧
       两次 QPainter、每格 QFont/QPalette/QFontMetrics 现造。
       现在手机端不加阴影、字体/颜色/metrics 全部缓存、当前行下标缓存、吸顶条按需绘制。
"""
import os

from PySide6.QtCore import QCoreApplication, QEvent, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QStyledItemDelegate,
                               QTableWidget, QTableWidgetItem)


def _Tr(text):
    """ 走一次 translate：以后进 .ts 就能翻，没装翻译器时原样返回 """
    return QCoreApplication.translate("SrModelTable", text)


# 算法顺序：与旧表一致(Waifu2x → Real-CUGAN → Real-ESRGAN)，自定义模型永远在最后
Algorithms = ("Waifu2x", "Real-CUGAN", "Real-ESRGAN")
CustomGroup = "自定义模型"

# 各算法/分组的分组色点
AlgoColors = {
    "Waifu2x": QColor(0x57, 0xA9, 0xA1),
    "Real-CUGAN": QColor(0x8F, 0x83, 0xD6),
    "Real-ESRGAN": QColor(0xD3, 0xA0, 0x3C),
    CustomGroup: QColor(0x8C, 0x94, 0x9E),
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


# ---------------------------------------------------------------------- 静态表
def ModelFamily(modelId):
    """ CUNET_UP2X_DENOISE3X → CUNET """
    return modelId.split("_UP")[0]


def ModelVariant(modelId, denoise):
    """ 降噪等级的可读写法 """
    if denoise >= 0:
        return "降噪 {}".format(denoise)
    return "保守" if "CONSERVATIVE" in modelId else "无降噪"


def ShowModelName(model):
    """ 可读写法（tooltip 用）：CUNET · 2× · 降噪 3 """
    modelId, up, denoise = model[0], model[2], model[3]
    family = FamilyNames.get(ModelFamily(modelId), ModelFamily(modelId))
    return "{} · {}× · {}".format(family, up, ModelVariant(modelId, denoise))


def FullModelName(model):
    """ 静态表条目 → 传给 sr_vulkan / Setting 的完整模型名 """
    return "MODEL_{}_{}".format(model[1].replace("-", "").upper(), model[0])


def FormatModelLabel(fullName, fallback=""):
    """ 阅读页/批量页的入口文案：短名 + 倍数 + 降噪

    自定义模型没有短名，用"文件名去后缀"（与列表里一致），不要退回 MODEL_ 原始串。
    """
    if not fullName:
        return fallback
    for model in SrModels:
        if FullModelName(model) == fullName:
            from tools.tool import ToolUtil
            return "{} · {}× · {}".format(
                ToolUtil.GetShowModelName(fullName), model[2], ModelVariant(model[0], model[3]))
    custom = _CustomTitles().get(fullName)
    if custom:
        title, up = custom
        return "{} · {}×".format(title, up) if up else title
    from tools.tool import ToolUtil
    return ToolUtil.GetShowModelName(fullName) or fallback


_customTitles = None


def _CustomTitles():
    """ {完整模型名: (显示名, 倍数)}，只缓存探测成功的结果 """
    global _customTitles
    if _customTitles is None:
        detected = ProbeModels()
        if not detected.ok:
            return {}
        _customTitles = {item["key"]: (item["title"], item.get("up", 0))
                         for item in detected.customs}
    return _customTitles


# ------------------------------------------------------------------ 可用性探测
class ModelRecord(object):
    """ 列表里的一行（静态模型与自定义模型统一用这个） """

    __slots__ = ("key", "algo", "up", "denoise", "cost", "recommend", "title", "custom")

    def __init__(self, key, algo, up, denoise, cost, recommend, title, custom=False):
        self.key = key              # 完整模型名 MODEL_XXX
        self.algo = algo            # 分组名（含「自定义模型」）
        self.up = up                # 放大倍数，未知为 0
        self.denoise = denoise      # 降噪等级，未知为 -1
        self.cost = cost            # 相对耗时%，未知为 None
        self.recommend = recommend
        self.title = title          # 列表第一列显示的文字
        self.custom = custom


class Detected(object):
    """ 一次探测的结果 """

    __slots__ = ("ok", "names", "customs")

    def __init__(self, ok=False, names=None, customs=None):
        self.ok = ok
        self.names = names or set()
        self.customs = customs or []


def _ModelDir():
    """ 安卓端模型目录（有没有都能返回，取不到就空串） """
    try:
        from tools import platform_mobile
        return os.environ.get("JM_SR_MODELS") or platform_mobile.GetAndroidModelDir()
    except Exception:
        return os.environ.get("JM_SR_MODELS", "")


def _FileStem(path):
    name = os.path.basename(path or "")
    stem = os.path.splitext(name)[0]
    return stem or name


def ProbeModels():
    """ 从当前超分引擎探测可用模型

    返回 Detected：
        ok=False        引擎不可用/还没初始化 —— 调用方应退回"显示全部"
        names           真实可用的完整模型名集合
        customs         引擎里有、静态表里没有的模型（自定义模型）

    安卓端（sr_qnn）除了模型名还要核对 onnx 文件真的在 models 目录里：C++ 模型表是
    "内置表 + models.txt 覆盖"，条目可能指向一个没放进去的文件，这种模型选中后必然
    跑到一半失败，所以不能出现在列表里。
    """
    try:
        from tools import sr_backend
        module = sr_backend.GetSrModule()
    except Exception:
        module = None
    if module is None:
        return Detected(False)

    engineNames = [name for name in dir(module) if name.startswith("MODEL_")]
    if not engineNames:
        return Detected(False)

    getInfo = getattr(module, "GetModelInfo", None)
    modelDir = _ModelDir() if getInfo is not None else ""
    statics = set(FullModelName(m) for m in SrModels)
    names = set()
    customs = []

    for name in engineNames:
        info = None
        if getInfo is not None:
            try:
                info = getInfo(getattr(module, name, None))
            except Exception:
                info = None
        if info:
            path = info[0] or ""
            # 有文件信息就一定要核对文件；核对不了（拿不到目录）时按"可用"处理
            if modelDir and path and not os.path.exists(os.path.join(modelDir, path)):
                continue
            if name not in statics:
                customs.append({
                    "key": name,
                    "file": path,
                    # 要求：自定义模型显示"完整不带后缀的模型文件名"
                    "title": _FileStem(path) or name[len("MODEL_"):],
                    "up": int(info[1] or 0),
                    "denoise": int(info[2]) if info[2] is not None else -1,
                })
        elif name not in statics:
            # 桌面端没有 GetModelInfo：常量在即认为可用，展示名去掉 MODEL_ 前缀
            customs.append({
                "key": name, "file": "", "title": name[len("MODEL_"):],
                "up": 0, "denoise": -1,
            })
        names.add(name)

    customs.sort(key=lambda item: item["key"])
    return Detected(True, names, customs)


def BuildCatalog(detected):
    """ 把静态表 + 探测结果拼成展示用的记录列表

    detected.ok 为 False 时**不隐藏任何模型**：这种情况下"检测"本身不可信，
    藏掉反而会让用户在没装引擎时看到一个空列表。
    """
    records = []
    for algo in Algorithms:
        for model in SrModels:
            if model[1] != algo:
                continue
            key = FullModelName(model)
            if detected.ok and key not in detected.names:
                continue
            records.append(ModelRecord(key, algo, model[2], model[3], model[4],
                                       model[5], model[0]))
    for item in detected.customs:
        records.append(ModelRecord(item["key"], CustomGroup, item["up"], item["denoise"],
                                   None, False, item["title"], True))
    return records


class SrModelDelegate(QStyledItemDelegate):
    """ 逐行自绘：行底色 / 左侧色条 / 模型 ID / 耗时 / 徽章

    为什么不继续用 `QTableWidgetItem.setBackground()`：主题 qss 里有

        QWidget { background-color: #31363b; }
        QTableView::item { padding: 5px; min-height: 25px; ... }

    一旦命中 `::item` 规则，面板背景就由 QStyleSheetStyle 自己填充，**item 的
    BackgroundRole 被完全忽略**。真机现象就是"点哪一行都没有任何变化"（宿主上
    加载同一份 qss 后逐像素对比：选中前后该行颜色完全一致，都是 #31363b）。
    自绘还能顺带省掉每帧的 qss 规则匹配、每格一次字体切换，以及 qss 的 5px
    内边距（吃掉 10px 可用宽度，长 ID 更容易被省略）。
    """

    PadX = 5            # 文字左右留白（和主题 qss 的 padding:5px 对齐，不占掉额外宽度）
    BadgeWidth = 0      # 徽章不单独占宽，右对齐画在描述列里

    def __init__(self, table):
        QStyledItemDelegate.__init__(self, table)

    # -- 绘制小工具 ------------------------------------------------------
    @staticmethod
    def _DrawText(painter, rect, text, font, color, flags):
        if not text:
            return
        painter.setFont(font)
        painter.setPen(color)
        # 用 painter 自己的 fontMetrics：每格 new 一个 QFontMetrics 等于每帧多做
        # 42 次字体引擎查找（实测单帧多 0.4ms）
        metrics = painter.fontMetrics()
        avail = rect.width() - SrModelDelegate.PadX * 2
        if avail > 0 and metrics.horizontalAdvance(text) > avail:
            text = metrics.elidedText(text, Qt.ElideRight, avail)
        painter.drawText(rect.adjusted(SrModelDelegate.PadX, 0, -SrModelDelegate.PadX, 0),
                         flags, text)

    def paint(self, painter, option, index):
        table = self.parent()
        if table is None:
            return
        record = table._rowRecord.get(index.row())
        painter.save()
        try:
            if record is None:
                self._PaintGroup(painter, option.rect, table, index.row())
                return
            self._PaintModel(painter, option.rect, table, index.column(), record)
        finally:
            painter.restore()

    def _PaintGroup(self, painter, rect, table, row):
        painter.fillRect(rect, table.GroupColor())
        painter.setPen(QPen(table.BorderColor(), 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        algo, count = table._groupInfo.get(row, ("", 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(AlgoColors.get(algo, table.AccentColor()))
        painter.drawEllipse(QRect(rect.left() + 11, rect.center().y() - 3, 6, 6))
        painter.setPen(table.MutedColor())
        painter.setFont(table.GroupFont())
        text = "{}    {}".format(algo, count) if count else algo
        painter.drawText(rect.adjusted(24, 0, -8, 0), Qt.AlignLeft | Qt.AlignVCenter, text)

    def _PaintModel(self, painter, rect, table, column, record):
        highlight = table.AccentColor()
        current = bool(table._currentName) and record.key == table._currentName
        picked = (not current) and bool(table._pickedName) and record.key == table._pickedName
        if current:
            painter.fillRect(rect, table.CurrentFillColor())
        elif picked:
            painter.fillRect(rect, table.PickedFillColor())
        if column == 0 and (current or picked):
            # 色条只画在第一列的最左边：三列各画一次会变成三条竖线
            bar = highlight if current else table.PickedBarColor()
            painter.fillRect(QRect(rect.left(), rect.top(), table.BarWidth, rect.height()), bar)

        if column == 0:
            font = table.BoldNameFont() if current else table.NameFont()
            color = highlight if current else table.TextColor()
            self._DrawText(painter, rect, record.title, font, color,
                           Qt.AlignLeft | Qt.AlignVCenter)
        elif column == 1:
            text = "—" if record.cost is None else "{:.0f}%".format(record.cost)
            color = table.MutedColor() if record.cost is None else table.TextColor()
            self._DrawText(painter, rect, text, table.CostFont(), color,
                           Qt.AlignRight | Qt.AlignVCenter)
        else:
            badge, strong = table.BadgeOf(record)
            color = highlight if strong else table.MutedColor()
            self._DrawText(painter, rect, badge, table.DescFont(), color,
                           Qt.AlignRight | Qt.AlignVCenter)


class SrModelTable(QTableWidget):
    """ 模型列表：三列 + 分组条(吸顶) + 当前使用/已选高亮 """

    GroupHeight = 26
    RowHeight = 40
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
        self._currentRow = -1
        self._catalog = None
        self._groupRows = []        # [(row, algo, count)]
        self._groupRowSet = set()
        self._groupInfo = {}        # 分组行 → (algo, count)
        self._rowGroup = {}         # 模型行 → 算法
        self._modelRows = []        # [(row, record)]
        self._rowRecord = {}        # 模型行 → record
        self._touchAdopted = False
        self._InvalidateColors()

        # 字体只建一次：原来每行 3~4 个 QFont（84 行≈250 个），滚动时 delegate
        # 又要按格切换字体，白白付 QFontEngine 切换的钱
        self._nameFont = QFont(self.font())
        self._nameFont.setPointSizeF(10.0)
        self._nameFont.setFamily("monospace")
        self._boldNameFont = QFont(self._nameFont)
        self._boldNameFont.setBold(True)
        self._costFont = QFont(self.font())
        self._costFont.setPointSizeF(10.0)
        self._descFont = QFont(self.font())
        self._descFont.setPointSizeF(9.0)
        self._groupFont = QFont(self.font())
        self._groupFont.setPointSizeF(9.0)
        self._groupFont.setBold(True)
        self._headerFont = QFont(self.font())
        self._headerFont.setPointSizeF(9.0)

        self.setObjectName("srModelTable")
        self.setShowGrid(False)
        # 模型名是单行的原始 ID(等宽)，不换行；真放不下时右侧省略，完整值在 tooltip
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideRight)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSortingEnabled(False)
        # 行高固定 → 视图不必逐行问 sizeHint（qss 的 min-height 会让它反复算）
        self.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        # 列宽由 stretch + 两个定宽列决定，横向滚动条永远不需要
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(self.RowHeight)
        self.setItemDelegate(SrModelDelegate(self))

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
        # 接 QAbstractItemView.clicked 而不是 QTableWidget.cellClicked：
        # 真机上触控是被 mobile_ui_touch 的路由认领的，点按走 `view.clicked.emit(index)`
        # 这条链（cellClicked 由它转发，但直接接 clicked 少一层、也不依赖列号换算）
        self.clicked.connect(self._OnClicked)
        self._UpdateHeader()

    # ------------------------------------------------------------------ 字体
    def NameFont(self):
        return self._nameFont

    def BoldNameFont(self):
        return self._boldNameFont

    def CostFont(self):
        return self._costFont

    def DescFont(self):
        return self._descFont

    def GroupFont(self):
        return self._groupFont

    # ------------------------------------------------------------------ 颜色
    def _InvalidateColors(self):
        self._mutedColor = None
        self._groupColor = None
        self._textColor = None
        self._highlightColor = None
        self._accentColor = None
        self._borderColor = None
        self._currentFill = None
        self._pickedFill = None
        self._pickedBar = None

    def changeEvent(self, event):
        # 换主题/换调色板时把缓存颜色作废（原来每格都现取一次 palette，等于每帧 42 次拷贝）
        if event.type() in (QEvent.PaletteChange, QEvent.StyleChange, QEvent.FontChange):
            self._InvalidateColors()
        QTableWidget.changeEvent(self, event)

    def HighlightColor(self):
        if self._highlightColor is None:
            self._highlightColor = self.palette().highlight().color()
        return self._highlightColor

    def AccentColor(self):
        """ 不透明强调色

        主题里 `selection-background-color: rgba(255,123,0,0.2)` 会被 Qt 解析进
        Highlight 角色，`palette().highlight()` 拿到的就是**带 20% alpha** 的颜色。
        直接拿它画文字/色条等于画了个几乎透明的东西（原来是"当前使用那行看不清"的
        另一半原因：底色被 qss 盖掉 + 文字本身只有两成不透明度）。
        """
        if self._accentColor is None:
            color = QColor(self.HighlightColor())
            color.setAlpha(255)
            self._accentColor = color
        return self._accentColor

    def TextColor(self):
        if self._textColor is None:
            self._textColor = self.palette().text().color()
        return self._textColor

    def BorderColor(self):
        if self._borderColor is None:
            color = QColor(self.TextColor())
            color.setAlpha(28)
            self._borderColor = color
        return self._borderColor

    def CurrentFillColor(self):
        if self._currentFill is None:
            color = QColor(self.AccentColor())
            color.setAlpha(38)
            self._currentFill = color
        return self._currentFill

    def PickedFillColor(self):
        if self._pickedFill is None:
            color = QColor(self.AccentColor())
            color.setAlpha(64)
            self._pickedFill = color
        return self._pickedFill

    def PickedBarColor(self):
        if self._pickedBar is None:
            color = QColor(self.AccentColor())
            color.setAlpha(170)
            self._pickedBar = color
        return self._pickedBar

    def MutedColor(self):
        if self._mutedColor is None:
            color = QColor(self.TextColor())
            color.setAlpha(160)
            self._mutedColor = color
        return self._mutedColor

    def GroupColor(self):
        if self._groupColor is None:
            color = self.palette().base().color()
            self._groupColor = color.lighter(118) if color.lightness() < 128 else color.darker(106)
        return self._groupColor

    def BadgeOf(self, record):
        """ 描述列文案：(文字, 是否强色)

        「当前使用」= 正在生效的，「已选」= 本次点选、还没点确定的 —— 两者必须能分开，
        否则用户点完一行看到的还是"当前使用"，会以为没选中。
        """
        if record is None:
            return "", False
        if bool(self._currentName) and record.key == self._currentName:
            return _Tr("当前使用"), True
        if bool(self._pickedName) and record.key == self._pickedName:
            return _Tr("已选"), True
        if record.recommend:
            return _Tr("推荐"), False
        return "", False

    # ------------------------------------------------------------------ 触控
    def showEvent(self, event):
        QTableWidget.showEvent(self, event)
        self.AdoptTouchScroll()

    def AdoptTouchScroll(self):
        """ 第一次显示就把手势接管好，别等手指按下去

        mobile_ui_touch 的兜底逻辑是"手指按下时才发现这个滚动区没接管"，
        而那一刻触控序列已经被路由认领 → QScroller 拿不到这一条手势，
        表现就是"第一次滑动没反应/明显延迟"。建好就接管可以彻底避开这一点。
        """
        if self._touchAdopted:
            return False
        self._touchAdopted = True
        try:
            from tools import platform_mobile
            if not platform_mobile.IsAndroid():
                return False
            from tools import mobile_ui
            return bool(mobile_ui.MakeScrollable(self))
        except Exception:
            return False

    # ------------------------------------------------------------------ 数据
    def SetCurrentModel(self, fullName):
        """ 标记"当前使用"（来自 Setting 的完整模型名） """
        self._currentName = self._KnownName(fullName)
        if not self._pickedName:
            self._pickedName = self._currentName
        self.Reload()
        self.ScrollToCurrent()

    def _KnownName(self, fullName):
        """ 只认列表里真实存在的模型名

        调用方传进来的可能是显示名、也可能是已经被过滤掉的模型（文件被删/引擎变了）。
        这种名字当成"当前使用"会谁都匹配不上（高亮永远不出现），还会被当成
        "已选"结果写回设置 —— 所以直接归空。
        """
        if not fullName:
            return ""
        for record in self.Catalog():
            if record.key == fullName:
                return fullName
        return ""

    def CurrentModelName(self):
        return self._currentName

    def SelectedModelName(self):
        return self._pickedName

    def PickModel(self, fullName):
        """ 点选一个模型（不落设置，等「确定」） """
        fullName = fullName or ""
        if fullName and self.RowOfModel(fullName) < 0:
            return False
        old = self._pickedName
        self._pickedName = fullName
        for name in (old, fullName):
            if name:
                self._RefreshRow(name)
        return True

    def _RowRect(self, row):
        """ 一行的视口矩形（看不见时返回空矩形，update 会自动忽略） """
        left = self.visualRect(self.model().index(row, 0))
        right = self.visualRect(self.model().index(row, 2))
        return left.united(right)

    def _RefreshRow(self, fullName):
        """ 只重绘被动到的那一行（原来点击后整屏 update） """
        row = self.RowOfModel(fullName)
        if row < 0:
            return
        record = self._rowRecord.get(row)
        desc = self.item(row, 2)
        if desc is not None:
            desc.setText(self.BadgeOf(record)[0])
        nameItem = self.item(row, 0)
        if nameItem is not None and record is not None:
            nameItem.setFont(self._boldNameFont if record.key == self._currentName
                             else self._nameFont)
        self.viewport().update(self._RowRect(row))

    def _OnClicked(self, index):
        self._OnCellClicked(index.row(), index.column())

    def _OnCellClicked(self, row, column=0):
        record = self._rowRecord.get(row)
        if record is not None:
            self.PickModel(record.key)

    def RowOfModel(self, fullName):
        for row, record in self._modelRows:
            if record.key == fullName:
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
        # 只用 ↑/↓（GB2312 里就有，任何中文字体都不会变方块）；分组态不加图标，
        # 否则真机上 ↕(U+2195) 会渲染成豆腐块(截图里那个"口")。
        marks = {self.SortGrouped: "", self.SortCostAsc: " ↑", self.SortCostDesc: " ↓"}
        titles = ["模型", "耗时" + marks[self._sortMode], "描述"]
        align = [Qt.AlignLeft, Qt.AlignRight, Qt.AlignRight]
        font = self._headerFont
        for col, title in enumerate(titles):
            item = self.horizontalHeaderItem(col)
            if item is None:
                item = QTableWidgetItem()
                self.setHorizontalHeaderItem(col, item)
            item.setText(title)
            item.setFont(font)
            item.setTextAlignment(align[col] | Qt.AlignVCenter)

    # ------------------------------------------------------------------ 目录
    def Catalog(self, refresh=False):
        """ 当前可用模型（按需探测一次） """
        if self._catalog is None or refresh:
            detected = ProbeModels()
            self._detectedOk = detected.ok
            self._catalog = BuildCatalog(detected)
        return self._catalog

    def DetectionOk(self):
        """ 探测是否可信（False = 没有超分引擎，列表退回了"全部模型"） """
        self.Catalog()
        return bool(getattr(self, "_detectedOk", False))

    def RefreshCatalog(self):
        self._catalog = None
        self.Reload()

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

    def _Rows(self):
        """ 按当前排序模式排出 [(kind, payload)] """
        catalog = self.Catalog()
        rows = []
        if self._sortMode == self.SortGrouped:
            for algo in Algorithms + (CustomGroup,):
                group = [r for r in catalog if r.algo == algo]
                if not group:
                    continue
                rows.append(("group", algo, group))
                rows.extend(("model", record, None) for record in group)
            return rows

        reverse = self._sortMode == self.SortCostDesc
        # 自定义模型没有耗时数据，无论升降序都排在最后
        ordered = sorted(catalog,
                         key=lambda r: (r.cost is None, r.cost if r.cost is not None else 0),
                         reverse=False)
        withCost = [r for r in ordered if r.cost is not None]
        withoutCost = [r for r in ordered if r.cost is None]
        if reverse:
            withCost.reverse()
        rows.extend(("model", record, None) for record in withCost + withoutCost)
        return rows

    def Reload(self):
        rows = self._Rows()

        self.setUpdatesEnabled(False)
        self.clearSpans()
        self.clearContents()
        self.setRowCount(len(rows))
        self._groupRows = []
        self._groupRowSet = set()
        self._groupInfo = {}
        self._rowGroup = {}
        self._modelRows = []
        self._rowRecord = {}

        if not rows:
            self.setRowCount(1)
            self._currentRow = -1
            item = QTableWidgetItem(_Tr("未检测到可用的超分模型"))
            item.setForeground(self.MutedColor())
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(Qt.ItemIsEnabled)
            self.setItem(0, 0, item)
            self.setSpan(0, 0, 1, 3)
            self.setRowHeight(0, self.GroupHeight + 10)
            self.setUpdatesEnabled(True)
            self.ApplyColumnWidths()
            self.viewport().update()
            return

        for row, (kind, payload, extra) in enumerate(rows):
            if kind == "group":
                algo, group = payload, extra
                # 文本只作为无障碍/测试用的载体，真正绘制在 delegate 里（带圆点）
                item = QTableWidgetItem(algo)
                item.setFlags(Qt.ItemIsEnabled)
                self.setItem(row, 0, item)
                self.setSpan(row, 0, 1, 3)
                self.setRowHeight(row, self.GroupHeight)
                self._groupRows.append((row, algo, len(group)))
                self._groupRowSet.add(row)
                self._groupInfo[row] = (algo, len(group))
                continue

            record = payload
            isCurrent = bool(self._currentName) and record.key == self._currentName

            # 显示完整模型 ID(等宽)：用户按 ID 对日志/配置，缩写反而认不出；
            # 自定义模型没有可读 ID，显示文件名去后缀(完整、不截断)
            nameItem = QTableWidgetItem(record.title)
            nameItem.setData(Qt.UserRole, record.key)
            nameItem.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            nameItem.setFont(self._boldNameFont if isCurrent else self._nameFont)
            if record.custom:
                nameItem.setToolTip(_Tr("自定义模型：{}").format(record.title))
            else:
                nameItem.setToolTip(ShowModelName(_RecordAsTuple(record)))

            costItem = QTableWidgetItem(
                "—" if record.cost is None else "{:.0f}%".format(record.cost))
            costItem.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            costItem.setFont(self._costFont)

            descItem = QTableWidgetItem(self.BadgeOf(record)[0])
            descItem.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            descItem.setFont(self._descFont)

            self.setItem(row, 0, nameItem)
            self.setItem(row, 1, costItem)
            self.setItem(row, 2, descItem)
            self.setRowHeight(row, self.RowHeight)
            self._modelRows.append((row, record))
            self._rowRecord[row] = record
            self._rowGroup[row] = record.algo

        self._currentRow = self.RowOfModel(self._currentName)
        self.setUpdatesEnabled(True)
        self.ApplyColumnWidths()
        self.viewport().update()

    def _GroupColor(self):
        return self.GroupColor()

    def _MutedColor(self):
        return self.MutedColor()

    def ScrollToCurrent(self):
        if self._currentRow < 0:
            self._currentRow = self.RowOfModel(self._currentName)
        if self._currentRow >= 0:
            self.scrollToItem(self.item(self._currentRow, 0), QAbstractItemView.PositionAtCenter)

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
        """ 只额外画吸顶分组条（行底色/左侧色条都在 delegate 里）

        以前这里每帧还要 RowOfModel() 全表扫一遍找当前行、再开第二个 QPainter 画竖条；
        现在当前行是缓存的下标、竖条随行画，滚动路径上只剩"画一个吸顶条"这一件事。
        """
        QTableWidget.paintEvent(self, event)
        if self._sortMode != self.SortGrouped or not self._groupRows:
            return
        algo = self.StickyGroup()
        if not algo:
            return
        painter = QPainter(self.viewport())
        try:
            self._PaintStickyGroup(painter, algo, self._StickyOffset())
        finally:
            painter.end()

    def _StickyOffset(self):
        """ 下一个分组行顶到吸顶区时，把当前分组条一起顶上去

        不这样做的话，滚到两组交界处会同时看到"吸顶的上一组"和"行内的下一组"
        两条分组条叠在一起(真机截图里像是一个空组)。
        """
        topRow = self.rowAt(0)
        if topRow < 0:
            return 0
        for row, _, _ in self._groupRows:
            if row <= topRow:
                continue
            y = self.rowViewportPosition(row)
            if y < self.GroupHeight:
                return y - self.GroupHeight
            break
        return 0

    def _PaintStickyGroup(self, painter, algo, top=0):
        width = self.viewport().width()
        rect = QRect(0, top, width, self.GroupHeight)
        painter.fillRect(rect, self.GroupColor())
        border = self.palette().text().color()
        border.setAlpha(28)
        painter.setPen(QPen(border, 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        color = AlgoColors.get(algo, self.palette().highlight().color())
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        dot = 6
        painter.drawEllipse(QRect(12, top + (self.GroupHeight - dot) // 2, dot, dot))

        painter.setFont(self._groupFont)
        painter.setPen(self.MutedColor())
        text = "{}    {}".format(algo, self.GroupCountOf(algo))
        painter.drawText(rect.adjusted(24, 0, -12, -1), Qt.AlignLeft | Qt.AlignVCenter, text)


def _RecordAsTuple(record):
    """ ShowModelName 认的是静态表那种 (id, algo, up, dn, cost, rec) 元组 """
    return (record.key[len("MODEL_"):] if record.custom else _StaticId(record.key),
            record.algo, record.up, record.denoise, record.cost, record.recommend)


def _StaticId(fullName):
    """ MODEL_WAIFU2X_CUNET_UP2X_DENOISE3X → CUNET_UP2X_DENOISE3X """
    for model in SrModels:
        if FullModelName(model) == fullName:
            return model[0]
    return fullName
