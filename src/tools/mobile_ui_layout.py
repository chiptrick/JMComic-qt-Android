# coding:utf-8
""" 竖屏排版重排（并排改上下、拆行、折行、压扁、封面尺寸） """
from functools import partial

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QIcon
from PySide6.QtWidgets import (QAbstractScrollArea, QBoxLayout, QComboBox, QCommandLinkButton,
                               QGridLayout, QLabel, QSizePolicy, QTabWidget, QToolButton, QWidget)
from tools.log import Log
from tools.mobile_ui_base import *  # noqa: F401,F403
from tools.mobile_ui_base import (_SelfAndChildren)
from tools import mobile_ui


# ---------------------------------------------------------------------------
# 长文本标签：按宽度中间省略(否则整行最小宽度会把页面撑到屏幕外)
# ---------------------------------------------------------------------------

class _ElideOnResize(QObject):
    """ 标签尺寸变化时重算省略文本(见 ElideText) """

    def __init__(self, label, parent=None):
        super().__init__(parent)
        self._label = label

    def eventFilter(self, obj, event):
        try:
            if event.type() == QEvent.Type.Resize:
                self.Apply()
        except Exception:
            pass
        return False

    def Apply(self):
        label = self._label
        if label is None:
            return
        text = getattr(label, "_jmFullText", "")
        try:
            width = label.width()
            if width < 24:
                # 布局还没跑到(或这一行给它分到的宽度是 0)：**保持原样**，别写成空串。
                # 之前这里按 width<=8 写全文、否则写省略串，结果"路径标签被压成 0 宽"
                # 时直接显示空白 —— 用户看到的就是"设置页看不到当前下载/缓存目录"。
                return
            metrics = QFontMetrics(label.font())
            elided = metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, max(0, width - 2))
            if not elided:
                # 宽度连省略号都放不下：宁可显示后面那一段，也不要变成空白
                elided = text[-12:] if len(text) > 12 else text
            QLabel.setText(label, elided)
            # 真机上"看不到当前目录"只能靠这行判断是宽度问题还是文本问题
            Log.Warn("portrait: 省略标签 {} -> {!r} (宽 {}px, 原文 {} 字符)".format(
                label.objectName() or "?", elided, width, len(text)))
        except Exception:
            try:
                QLabel.setText(label, text)
            except Exception:
                pass
        return


def ElideText(label, text):
    """ 让标签只画"放得下"的那一段(中间省略)，完整值进 tooltip 与 _jmFullText

    真机现象："设置页/漫画详情页宽度超出范围"。QLabel 的 sizeHint 就是整段文本宽度，
    路径(`/storage/emulated/0/Android/data/.../commies`)或书名一长，那一行的
    **最小宽度**就超过屏幕，Qt 只能把整页撑宽(用户看到右边被切掉、页面还能横向拖)。

    水平策略必须是 Ignored：qSmartMinSize 对 Preferred/Expanding 都会取 sizeHint，
    光把 minimumWidth 设成 0 没用。
    """
    if label is None:
        return
    if not IsEnabled():
        # 桌面端保持原样(整条路径直接显示，放得下就放得下)
        try:
            QLabel.setText(label, str(text or ""))
        except Exception:
            pass
        return
    try:
        label._jmFullText = str(text or "")
        # 先把全文放上去：省略只在"宽度已知"时才做，而这一行往往在页面建好之后才
        # 填字(SetDownloadLabel)，那时标签已经布局完了、不会再有 Resize 事件 ——
        # 只依赖 resize 去算省略的结果就是**一直是空的**(真机现象：设置页看不到
        # 当前下载/缓存目录)。先放全文，随后的 Resize/QTimer 再把它省略成一行。
        QLabel.setText(label, label._jmFullText)
        policy = label.sizePolicy()
        label.setSizePolicy(QSizePolicy.Policy.Ignored, policy.verticalPolicy())
        label.setMinimumWidth(0)
        label.setMaximumHeight(label.fontMetrics().height() + 6)
        # 单行显示：路径一长就折行的话，这一行会被撑成十几行高(真机见过 250px 高)，
        # 而且折行后按宽度省略算出来是空串 —— 目录就"看不见"了
        label.setWordWrap(False)
        label.setToolTip(label._jmFullText)
        # 让这一行的多余宽度都归它：Ignored + 没有 stretch 时，行里只要有按钮就会把它
        # 压到 0 宽(真机现象：只剩"下载 [打开目录]"，中间是空白)。
        # 注意必须找**真正装着这个标签的那个横向布局**：parentWidget().layout() 是外层
        # 竖向布局，indexOf 找不到它(第一版就是这么空转的)。
        holder = label.parentWidget()
        if holder is not None:
            for row in holder.findChildren(QBoxLayout):
                index = row.indexOf(label)
                if index >= 0:
                    row.setStretch(index, 1)
                    break
    except Exception as es:
        Log.Error(es)
        return
    filter = getattr(label, "_jmElideFilter", None)
    if filter is None:
        filter = _ElideOnResize(label, label)
        label._jmElideFilter = filter
        label.installEventFilter(filter)
    filter.Apply()
    # 布局跑完后的真实宽度要再算一次(第一次调用时控件还没被布局)
    QTimer.singleShot(0, filter.Apply)
    QTimer.singleShot(150, filter.Apply)
    QTimer.singleShot(600, filter.Apply)
    return


def FullText(label):
    """ 标签的完整文本(被 ElideText 处理过时返回原文) """
    return getattr(label, "_jmFullText", "") or (label.text() if label is not None else "")




def RelaxMinSizes(root, limit):
    """ 递归放宽写死的过宽最小尺寸(macOS/桌面端不受影响) """
    if root is None:
        return
    try:
        if isinstance(root, QWidget):
            if root.minimumWidth() > limit:
                root.setMinimumWidth(limit)
            if root.minimumHeight() > 0 and root.minimumWidth() > 0:
                pass
            for child in root.findChildren(QWidget):
                if child.minimumWidth() > limit:
                    child.setMinimumWidth(limit)
        else:
            for child in root.findChildren(QWidget):
                if child.minimumWidth() > limit:
                    child.setMinimumWidth(limit)
    except Exception as es:
        Log.Error(es)
    return


def StackBookInfo(view):
    """ 漫画详情：封面/信息 由左右并排改为上下堆叠 """
    try:
        if view is None or getattr(view, "_jmStacked", False):
            return
        hLayout = getattr(view, "horizontalLayout", None)
        infoLayout = getattr(view, "verticalLayout_2", None)
        grid = getattr(view, "gridLayout_3", None)
        picture = getattr(view, "picture", None)
        if hLayout is None or infoLayout is None or grid is None:
            return
        if hLayout.indexOf(infoLayout) < 0:
            return
        item = hLayout.takeAt(hLayout.indexOf(infoLayout))
        grid.addLayout(infoLayout, grid.rowCount(), 0, 1, 1)
        if picture is not None:
            picture.setMinimumWidth(0)
            picture.setMinimumHeight(0)
            # 封面必须是**固定尺寸**，不能只放宽策略：
            #   * 只 Ignored -> 布局把它压成 0 宽(真机现象：详情页封面缩成小方块)
            #   * 不设固定 -> QLabel 带 pixmap 时 minimumSizeHint 就是 pixmap 尺寸，
            #     会把整页最小宽度顶回封面宽度(真机现象：整页比屏幕宽、右边被裁)
            # 给一个"放得下又有面子"的固定 4:3 竖版尺寸，页面宽度就只由文字行决定。
            width = min(300, max(200, mobile_ui.CurrentLimit()))
            picture.setFixedSize(width, int(width * 4 / 3))
            picture.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        view._jmStacked = True
        Log.Warn("book info layout stacked for portrait")
    except Exception as es:
        Log.Error(es)
    return


def CompactTabBar(mainView):
    """ 顶部分页按钮在窄屏下压缩，避免溢出屏幕 """
    try:
        buttons = getattr(mainView, "toolButtons", None) or []
        for button in buttons:
            if isinstance(button, QToolButton):
                button.setMinimumWidth(0)
                font = button.font()
                if font.pointSize() > 0:
                    font.setPointSize(max(7, font.pointSize() - 2))
                    button.setFont(font)
    except Exception as es:
        Log.Error(es)
    return


def _NavLayoutButtons(layout):
    """ 这个布局是不是"只有一个标题按钮(或几个功能按钮)+弹簧"的导航列

    设置页是 QCommandLinkButton x4 + 弹簧；分流设置页(login_new 的 tab_4)是
    QCommandLinkButton x1 + 弹簧。返回按钮列表，不是导航列则返回 None。
    """
    if not isinstance(layout, QBoxLayout):
        return None
    buttons = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        if item.spacerItem() is not None:
            continue
        widget = item.widget()
        if widget is None:
            # 导航列里再嵌布局的形态没见过，保守起见当它不是导航列
            return None
        if widget.isHidden():
            continue
        if not isinstance(widget, QCommandLinkButton):
            return None
        buttons.append(widget)
    return buttons or None


def _CompressNavButtons(buttons):
    """ 导航按钮从"竖排大块"压成"横排一行小按钮"

    QCommandLinkButton 默认是"图标 + 标题 + 说明"的竖块，横排里必须压扁。
    水平策略必须用 Ignored：qSmartMinSize 对 Expanding 会取 sizeHint，
    4 个按钮加起来最小宽度 664px，横排到 384px 的屏幕上照样"放不下"。
    """
    for widget in buttons:
        widget.setDescription("")
        widget.setIcon(QIcon())
        widget.setMinimumWidth(0)
        widget.setMaximumWidth(WidgetSizeMax)
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        font = widget.font()
        if font.pointSize() > 0:
            font.setPointSize(max(8, font.pointSize() - 2))
            widget.setFont(font)
        widget.setMinimumHeight(0)
    return


def StackSettingNav(view):
    """ 设置页专用收尾(方向已经由 StackSideNavs 改好)

    这里只补设置页自己的细节：目录行里的路径标签最小宽 150px，竖屏下会把"打开目录"
    按钮挤出去；而且路径本身很长，QLabel 的 sizeHint 是整段路径宽度 —— 整行的最小
    宽度因此远超屏幕，页面被撑宽(真机现象："设置页宽度超出范围")。
    做法：路径标签改成按宽度中间省略(tooltip 里保留完整路径)。
    """
    try:
        if view is None:
            return
        FitSettingRows(view)
    except Exception as es:
        Log.Error(es)
    return


def FitSettingRows(view):
    """ 设置页四行"目录路径 + 打开目录"：路径中间省略 + 整页禁止横向滚动

    原来这里是 `label.setMinimumWidth(100)`，但 100px 根本不够显示路径，Qt 会按
    整段文本的 sizeHint 撑；`_jmElide` 之后行宽由屏幕决定，路径显示不下的部分用
    "…" 省略。
    """
    for name in ("downloadDir", "cacheDir", "chatDir", "waifu2xDir"):
        label = getattr(view, name, None)
        if label is not None:
            ElideText(label, FullText(label))
    # 路径行已经能自适应，剩下的横向溢出(某些语言/字号下)宁可裁掉也不要让整页
    # 可以横向拖动 —— 用户感知的"宽度超出范围"就是这种横向可拖动
    area = getattr(view, "scrollArea", None)
    if area is not None:
        try:
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        except Exception:
            pass
    return


def WrapBookInfoButtons(view):
    """ 漫画详情页的操作按钮行：一行放不下就自动折成多行

    真机现象："漫画详情页宽度超出范围"。`horizontalLayout_2` 里并排放了
    收藏/本地/评论/下载/上传/清理 6 个图标按钮 + "购买(Jcoin)" + "上次看到第N章第M页"
    两个文字按钮，最小宽度加起来 549px —— 竖屏 384px 下整页被撑宽。
    折行后：6 个图标按钮一行(约 270px)，两个文字按钮下一行(约 230px)，都放得下。
    """
    try:
        if view is None or getattr(view, "_jmButtonsWrapped", False):
            return
        layout = getattr(view, "horizontalLayout_2", None)
        parent = getattr(view, "verticalLayout_4", None)
        if layout is None or parent is None:
            return
        index = parent.indexOf(layout)
        if index < 0:
            return
        widgets = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widgets.append(widget)
        if len(widgets) < 3:
            return
        box = QWidget(view)
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        avail = max(200, mobile_ui.CurrentLimit())
        row = 0
        col = 0
        used = 0
        for widget in widgets:
            widget.setMinimumWidth(0)
            try:
                width = max(24, widget.sizeHint().width())
            except Exception:
                width = 40
            if used > 0 and used + width > avail:
                row += 1
                col = 0
                used = 0
            grid.addWidget(widget, row, col)
            col += 1
            used += width + 4
        for c in range(col):
            grid.setColumnStretch(c, 0)
        parent.removeItem(layout)
        layout.setParent(None)
        parent.insertWidget(index, box)
        view._jmButtonsWrapped = True
        # 详情页同样不需要横向滚动
        area = getattr(view, "scrollArea", None)
        if area is not None:
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        Log.Warn("portrait: 详情页操作按钮折成 {} 行".format(row + 1))
    except Exception as es:
        Log.Error(es)
    return


def StackSideNavs(root=None):
    """ 竖屏："左侧导航列 + 右侧滚动内容" 的左右并排 -> 上下堆叠

    原来这类页面的外层都是 QHBoxLayout: [ 竖排导航列 , QScrollArea ]。
    竖屏 384px 下导航列要占掉 100 多像素，内容区只剩 230 上下，而内容里大量 row 是
    "80px 标签 + 150px 数值 + 108px 按钮"≈365px，于是被压缩/裁掉(用户看到的就是
    "显示不全"、"还是双排")。

    竖屏改成：导航按钮横排在最上面，内容区独占整宽。
    QBoxLayout 可以直接改方向，不用重建布局(保留全部信号连接)。

    覆盖：设置页(horizontalLayout = 竖排4按钮 + scrollArea)、
          分流设置页(login_new.tab_4 的 horizontalLayout_14 = 竖排标题 + scrollArea_3)。
    """
    if root is None:
        root = getattr(mobile_ui._mainView, "subStackWidget", None) if mobile_ui._mainView is not None else None
    if root is None:
        return 0
    count = 0
    try:
        for layout in [root] + root.findChildren(QBoxLayout):
            try:
                if not isinstance(layout, QBoxLayout):
                    continue
                if layout.direction() not in (QBoxLayout.Direction.LeftToRight,
                                              QBoxLayout.Direction.RightToLeft):
                    continue
                if getattr(layout, "_jmNavStacked", False):
                    continue
                if layout.count() != 2:
                    continue
                navItem = layout.itemAt(0)
                area = layout.itemAt(1).widget()
                if navItem is None or not isinstance(area, QAbstractScrollArea):
                    continue
                nav = navItem.layout()
                buttons = _NavLayoutButtons(nav)
                if buttons is None:
                    continue
                layout.setDirection(QBoxLayout.Direction.TopToBottom)
                nav.setDirection(QBoxLayout.Direction.LeftToRight)
                for i in range(nav.count()):
                    item = nav.itemAt(i)
                    if item is None:
                        continue
                    spacer = item.spacerItem()
                    if spacer is not None:
                        # 竖排时的弹簧在横排里只会白占宽度
                        spacer.changeSize(0, 0, QSizePolicy.Policy.Minimum,
                                          QSizePolicy.Policy.Minimum)
                _CompressNavButtons(buttons)
                layout._jmNavStacked = True
                count += 1
                Log.Warn("portrait: 并排的导航列/内容改为上下 ({}.{} + {})".format(
                    type(layout.parent()).__name__ if layout.parent() else "?",
                    layout.objectName() or "?", area.objectName() or "?"))
            except Exception as es:
                Log.Error(es)
    except Exception as es:
        Log.Error(es)
    if count:
        Log.Warn("portrait: {} 个[左导航+右内容]页面改为上下堆叠".format(count))
    return count


def StackSrTool(view, mainView=None):
    """ 图片超分页：预览/参数 左右并排 -> 上下堆叠(竖屏)

    原来 gridLayout 里 (0,0)=QGraphicsView 预览、(0,1)=参数面板(最大宽 300px)。
    竖屏 384px 下预览只剩 80 多像素，基本看不见图。
    竖屏改成预览在上(占大部分高度)、参数面板在下(整宽、限高，可滚动)。
    """
    try:
        if view is None or getattr(view, "_jmSrStacked", False):
            return
        grid = getattr(view, "gridLayout", None)
        panel = getattr(view, "verticalLayout", None)
        area = getattr(view, "scrollArea", None)
        if grid is None or panel is None:
            return
        if grid.indexOf(panel) < 0:
            return
        grid.takeAt(grid.indexOf(panel))
        grid.addLayout(panel, 1, 0, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        grid.setRowStretch(1, 0)
        grid.setRowStretch(0, 1)
        if area is not None:
            area.setMaximumWidth(WidgetSizeMax)
        view._jmSrStacked = True
        UpdateSrToolHeight(view, mainView)
        Log.Warn("waifu2x tool stacked for portrait")
    except Exception as es:
        Log.Error(es)
    return


def UpdateSrToolHeight(view, mainView=None):
    """ 参数面板限高，保证预览区还有足够高度(旋转屏幕后重算) """
    try:
        if view is None or not getattr(view, "_jmSrStacked", False):
            return
        area = getattr(view, "scrollArea", None)
        if area is None:
            return
        height = 0
        for source in (view, getattr(mainView, "subMainWindow", None), mainView):
            if source is None:
                continue
            if source.height() > height:
                height = source.height()
        if height <= 0:
            height = 700
        area.setMaximumHeight(max(190, int(height * 0.42)))
    except Exception as es:
        Log.Error(es)
    return


def PortraitWidth(mainView):
    """ 页面可用宽度(取页面栈的宽度；还没布局时退回主窗口 / 最小宽度上限) """
    width = 0
    stack = getattr(mainView, "subStackWidget", None)
    if stack is not None:
        width = stack.width()
    if width < 200:
        sub = getattr(mainView, "subMainWindow", None)
        if sub is not None:
            width = sub.width()
    if width < 200:
        width = mainView.width()
    if width < 200:
        width = mobile_ui._limit
    return width


def _PackRowIndexes(widths, available, spacing):
    """ 顺序装箱：一行的控件最小宽度之和不超过 available """
    rows = []
    current = []
    used = 0
    for index, width in enumerate(widths):
        extra = width + (spacing if current else 0)
        if current and used + extra > available:
            rows.append(current)
            current = []
            used = 0
            extra = width
        current.append(index)
        used += extra
    if current:
        rows.append(current)
    return rows


def _ReplaceNestedLayout(parent, old, new):
    """ 用 new 顶掉 parent 里的 old(保持原来的位置/跨行跨列) """
    try:
        from PySide6.QtWidgets import QGridLayout
        if isinstance(parent, QWidget):
            # old 是这个 widget 自己的顶层布局：Qt 不允许直接 setLayout 顶掉已有的布局，
            # 先把旧布局转交给一个临时 widget(它随临时 widget 一起销毁)，再装新的
            if parent.layout() is not old:
                return False
            holder = QWidget()
            holder.setLayout(old)
            parent.setLayout(new)
            holder.deleteLater()
            return True
        index = parent.indexOf(old)
        if index < 0:
            return False
        if isinstance(parent, QGridLayout):
            row, col, rowSpan, colSpan = parent.getItemPosition(index)
            parent.takeAt(index)
            parent.addLayout(new, row, col, rowSpan, colSpan)
            return True
        if isinstance(parent, QBoxLayout):
            parent.takeAt(index)
            parent.insertLayout(index, new)
            return True
    except Exception as es:
        Log.Error(es)
    return False


def _WrapOneRow(layout, available):
    """ 把一个放不下的横向行拆成多行；返回是否真的拆了 """
    items = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None or item.spacerItem() is not None:
            # 弹簧不参与装箱：每行末尾统一加一个，避免拆完出现大片空隙
            continue
        items.append(item)
    if len(items) < 2:
        return False
    widths = []
    for item in items:
        try:
            widths.append(max(0, item.minimumSize().width()))
        except Exception:
            widths.append(0)
    spacing = layout.spacing()
    if spacing < 0:
        spacing = WrapRowSpacing
    rows = _PackRowIndexes(widths, available, spacing)
    if len(rows) < 2:
        return False
    parent = layout.parent()
    if parent is None:
        return False
    # 先把 item 从旧布局里摘出来(旧布局变空)，再整体替换
    while layout.count():
        layout.takeAt(0)
    from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
    column = QVBoxLayout()
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(WrapRowSpacing)
    for group in rows:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(spacing)
        for index in group:
            row.addItem(items[index])
        row.addStretch(1)
        column.addLayout(row)
    if not _ReplaceNestedLayout(parent, layout, column):
        # 替换失败：把 item 放回去，别把界面搞空
        for index, item in enumerate(items):
            layout.addItem(item)
        return False
    try:
        layout.setParent(None)
    except Exception:
        pass
    return True


def _FlattenGridRows(grid, budget):
    """ 把放不下的 QGridLayout 压成单列(竖屏)

    帮助页里的版本/时间信息是一个 3 列 QGridLayout：每列本身都不宽，
    但列宽相加 524px，竖屏下放不下。压成单列后每个控件各占一行。
    压完还是放不下(有单个控件本身就超宽)就原样还原，绝不帮倒忙。
    """
    saved = []
    for i in range(grid.count()):
        item = grid.itemAt(i)
        if item is None:
            continue
        saved.append((grid.getItemPosition(i), item))
    if len(saved) < 2:
        return False
    # 弹簧在单列里只会平白占高度，丢掉
    keep = [(pos, item) for pos, item in saved if item.spacerItem() is None]
    if len(keep) < 2:
        return False
    keep.sort(key=lambda pair: (pair[0][0], pair[0][1]))
    try:
        while grid.count():
            grid.takeAt(0)
        for index, (_pos, item) in enumerate(keep):
            grid.addItem(item, index, 0, 1, 1)
        if grid.minimumSize().width() <= budget:
            return True
        # 还原
        while grid.count():
            grid.takeAt(0)
        for pos, item in saved:
            grid.addItem(item, pos[0], pos[1], pos[2], pos[3])
    except Exception as es:
        Log.Error(es)
    return False


def EnableLabelWrap(root, available):
    """ 竖屏下把"本身就放不下"的文字标签改成多行显示

    帮助页那种一整段说明文字的 QLabel，单行最小宽度就有 500 多像素，
    横向怎么排都放不下。给它打开 wordWrap 让文字折行，是最不破坏结构的做法。
    对长路径/长 URL 这种没有换行机会的文本，打开 wordWrap 也降不下来，就还原回去。
    """
    if root is None or available <= 0:
        return 0
    from PySide6.QtWidgets import QLabel
    budget = max(200, available - WrapSafetyMargin)
    count = 0
    for label in root.findChildren(QLabel):
        try:
            if label.wordWrap():
                continue
            if getattr(label, "_jmFullText", None) is not None:
                # 已经被 ElideText 接管(单行省略)：绝不能给它开折行，否则长路径会
                # 折成十几行、把整行撑高，省略显示也跟着算成空串
                continue
            before = label.minimumSizeHint().width()
            if before <= budget:
                continue
            label.setWordWrap(True)
            after = label.minimumSizeHint().width()
            if after >= before:
                label.setWordWrap(False)
                continue
            count += 1
        except Exception as es:
            Log.Error(es)
    if count:
        Log.Warn("portrait: {} 个过宽标签改为折行显示(可用 {}px)".format(count, budget))
    return count


def WrapWideRows(root, available):
    """ 把放不下的横向行拆成多行(竖屏)

    工具栏那一类行(详情页的收藏/下载/评论按钮、收藏/历史/本地收藏/分类/周榜的分页栏)
    在 384px 竖屏下放不下，Qt 只能把右侧控件裁掉 —— 用户看到的就是"显示不全"。
    这里按顺序装箱把它们拆成若干行：所有控件都保留、顺序不变、每行都放得下。

    天然幂等：拆完的行自己都放得下，不会再次被拆，所以不需要"只跑一次"的标记
    (窗口尺寸会变，用了标记反而会让第一次的判定被永久沿用)。
    只处理嵌套在其它布局里的行(最常见的形态)；顶层布局交给 RelaxMinSizes。
    """
    if root is None or available <= 0:
        return 0
    budget = max(200, available - WrapSafetyMargin)
    wrapped = 0
    for layout in root.findChildren(QBoxLayout):
        try:
            if layout.direction() not in (QBoxLayout.Direction.LeftToRight,
                                          QBoxLayout.Direction.RightToLeft):
                continue
            if layout.minimumSize().width() <= budget:
                continue
            if _WrapOneRow(layout, budget):
                wrapped += 1
        except Exception as es:
            Log.Error(es)
    if wrapped:
        Log.Warn("portrait: 拆分了 {} 个放不下的横向行(可用 {}px)".format(wrapped, budget))
    return wrapped


def FlattenWideGrids(root, available):
    """ 把放不下的 QGridLayout 压成单列(竖屏) """
    if root is None or available <= 0:
        return 0
    from PySide6.QtWidgets import QGridLayout
    budget = max(200, available - WrapSafetyMargin)
    flattened = 0
    for grid in root.findChildren(QGridLayout):
        try:
            if grid.minimumSize().width() <= budget:
                continue
            if _FlattenGridRows(grid, budget):
                flattened += 1
        except Exception as es:
            Log.Error(es)
    if flattened:
        Log.Warn("portrait: {} 个放不下的栅格改为单列(可用 {}px)".format(flattened, budget))
    return flattened


def ShrinkToFit(root, available):
    """ 最后一道保险：拆行之后仍放不下的横向行，把里面可压缩的文本控件压扁

    真机实测：设置页"模型"那一行 = QLabel(60) + QToolButton:downModelName(314) = 378px，
    而内容视口只有 352px。拆行本来能解决，但这一行的最小宽度是运行时(setText)才涨上去的，
    时机上不一定赶得上。这里按"最宽的控件先压"的顺序把整行压到放得下为止，
    保证竖向排列下**不存在**放不下的横向行(可压缩的只限于纯文本控件)。
    """
    if root is None or available <= 0:
        return 0
    from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton
    budget = max(200, available - WrapSafetyMargin)
    shrinkable = (QToolButton, QLabel, QPushButton, QLineEdit, QComboBox)
    count = 0
    for layout in root.findChildren(QBoxLayout):
        try:
            if layout.direction() not in (QBoxLayout.Direction.LeftToRight,
                                          QBoxLayout.Direction.RightToLeft):
                continue
            if layout.minimumSize().width() <= budget:
                continue
            items = []
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item is None or item.spacerItem() is not None:
                    continue
                items.append(item)
            items.sort(key=lambda it: it.minimumSize().width(), reverse=True)
            for item in items:
                if layout.minimumSize().width() <= budget:
                    break
                widget = item.widget()
                if widget is None or not isinstance(widget, shrinkable):
                    continue
                if getattr(widget, "_jmShrunk", False):
                    continue
                text = widget.text() if hasattr(widget, "text") else ""
                if text and hasattr(widget, "setToolTip") and not widget.toolTip():
                    widget.setToolTip(text)
                widget.setMinimumWidth(0)
                widget.setSizePolicy(QSizePolicy.Policy.Ignored,
                                     widget.sizePolicy().verticalPolicy())
                widget._jmShrunk = True
                count += 1
        except Exception as es:
            Log.Error(es)
    if count:
        Log.Warn("portrait: {} 个控件压扁以让横向行放得下(可用 {}px)".format(count, budget))
    return count


def _LogWideChildren(content, width, area):
    """ 记日志：这个页面的内容为什么比视口宽(真机上"详情页超宽"只能靠它定位)

    QScrollArea(widgetResizable) 会给内容 widget 取
    max(视口宽, content.minimumSizeHint().width()) —— 只要有一个子控件的
    minimumSizeHint 很宽，整页就跟着变宽、右边被裁掉。这里把最宽的几名列出来，
    就知道该收谁(真机日志里直接看 "最宽的控件: ...")。
    """
    try:
        rows = []
        for child in content.findChildren(QWidget):
            try:
                need = child.minimumSizeHint().width()
            except Exception:
                continue
            if need > width:
                rows.append((need, type(child).__name__, child.objectName() or "?"))
        if not rows:
            return
        rows.sort(reverse=True)
        text = ", ".join("{}({}px)".format(name or cls, need)
                         for need, cls, name in rows[:8])
        Log.Warn("portrait: {} 内容 {}px > 视口 {}px, 最宽的控件: {}".format(
            area.objectName() or "?", content.minimumSizeHint().width(), width, text))
    except Exception as es:
        Log.Error(es)
    return


def ClampPageWidth(root, available):
    """ 最后一道保险：页面内容不允许比视口宽

    拆行/压扁/折行都跑完还放不下的时候(某些语言、某些字号、运行时才填进去的超长
    文本)，Qt 会把整页撑得比屏幕宽 —— 用户看到的就是"页面宽度超出范围"、右边被切掉、
    而且整页还能横向拖。这里把 QScrollArea 的内容宽度夹在视口宽度上：
    横向滚动条直接关掉，多出来的部分宁可裁掉，也不要一个能拖出屏幕的页面。

    只处理 QScrollArea(它的 widget() 才是"内容");QAbstractItemView/QPlainTextEdit 的
    widget() 是视口本身，绝不能改它的最大宽度。
    """
    from PySide6.QtWidgets import QScrollArea
    if root is None or available <= 0:
        return 0
    count = 0
    for area in _SelfAndChildren(root, QScrollArea):
        try:
            if not isinstance(area, QScrollArea):
                continue
            viewport = area.viewport()
            width = viewport.width() if viewport is not None else 0
            if width <= 8:
                width = available
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            content = area.widget()
            if content is None:
                continue
            if content.minimumWidth() > width:
                content.setMinimumWidth(0)
            need = content.minimumSizeHint().width() > width
            clamped = bool(getattr(content, "_jmWidthClamped", False))
            if need:
                _LogWideChildren(content, width, area)
            if need and not clamped:
                content.setMaximumWidth(width)
                content._jmWidthClamped = True
                count += 1
            elif need and clamped:
                # 视口变宽/变窄(旋转屏幕)后跟着改
                if content.maximumWidth() != width:
                    content.setMaximumWidth(width)
            elif clamped:
                # 已经不溢出了：把最大宽度还给布局
                content.setMaximumWidth(16777215)
                content._jmWidthClamped = False
        except Exception as es:
            Log.Error(es)
    if count:
        Log.Warn("portrait: {} 个页面内容被夹到视口宽度(不再横向溢出)".format(count))
    return count


# ---------------------------------------------------------------------------
# 批量超分页：参数行改成居中表单
# ---------------------------------------------------------------------------

def _CenterBatchSrGroup(line, spacer, label, widget, contentWidth):
    """ 把"标签+控件"这一组按可见宽度居中(改左侧留白的宽度) """
    try:
        spacing = line.spacing() if line.spacing() >= 0 else WrapRowSpacing
        groupWidth = label.sizeHint().width() + widget.sizeHint().width() + spacing
        spacer.changeSize(max(0, (contentWidth - groupWidth) // 2), 0,
                          QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        # changeSize 不会自己触发布局：不 invalidate 的话旋转/改宽度后还是老缩进
        line.invalidate()
        line.activate()
    except Exception as es:
        Log.Error(es)
    return


def LayoutBatchSrTool(view, available=None):
    """ 批量超分页：参数行"一行放不下"时，把 放大倍数/转换格式 各自拆成居中一行

    原来 label_2|线|label_25|模型按钮|线|label_26|放大倍数|线|label_5|转换格式|线|弹簧
    是完整一行(最小宽 700px 以上)。窄屏放不下时，通用拆行只能按顺序装箱：
    放大倍数 spin 抱着 .ui 里 150px 的最小宽不放(半行被一个只显示 "2.0" 的框占掉)、
    转换格式 combo 被压到 60px 宽(弹窗跟着变窄，webp/apng 被硬切)、控件全部左对齐
    挤在行首。这里按页面语义把这两个控件各自拆成"标签+控件整体居中"的一行，
    spin 的最小宽收回自然宽度；模型那部分留在原行，通用拆行会把它变成
    "参数设置：模型："+"模型名"两行，名字照样完整显示。
    拆完每行都放得下，通用拆行/压扁就不再插手(combo 不被压扁 → 弹窗不裁字)。

    只在"这一行确实放不下"时才拆(桌面宽屏保持原来的一行式布局)；拆是一次性的，
    居中缩进每次重排都按当前宽度重算(旋转/改窗口大小之后仍然居中)。
    """
    try:
        if view is None:
            return False
        if available is None:
            available = mobile_ui._limit
        # 页面自身布局的左右边距要扣掉，居中才是相对"可见区域"而不是相对窗口
        margins = view.verticalLayout.contentsMargins() if hasattr(view, "verticalLayout") else None
        if margins is not None:
            contentWidth = max(0, available - margins.left() - margins.right())
        else:
            contentWidth = available
        rows = getattr(view, "_jmBatchSrRows", None)
        built = False
        if rows is None:
            rows = _BuildBatchSrForm(view, available)
            if rows is None:
                return False
            view._jmBatchSrRows = rows
            built = True
            Log.Warn("portrait: 批量超分参数行改为居中表单(放大倍数/转换格式各一行)")
        for line, spacer, label, widget in rows:
            _CenterBatchSrGroup(line, spacer, label, widget, contentWidth)
        return built
    except Exception as es:
        Log.Error(es)
        return False


def _BuildBatchSrForm(view, available):
    """ 把参数行里的 放大倍数/转换格式 拆成两行居中表单；返回 [(行, 左留白, 标签, 控件)]

    拆不了(桌面宽屏放得下 / 已经被通用拆行处理过)返回 None。
    """
    row = getattr(view, "horizontalLayout_5", None)
    if row is None or row.count() <= 0:
        return None
    # 和通用拆行用同一个预算(可用宽 - 安全余量)：判据不一致会出现"我不管、它去拆"
    # 的夹缝(实测主题字体下这一行最小宽 992，available=1000 时布局放得下、拆行却够呛)
    budget = max(200, available - WrapSafetyMargin)
    if row.minimumSize().width() <= budget:
        return None                           # 一行放得下(桌面/宽屏)：保持原样
    names = ("label_26", "coverScale", "line_3", "label_5", "fmtBox")
    widgets = [getattr(view, name, None) for name in names]
    if any(widget is None for widget in widgets):
        return None
    for widget in widgets:
        if row.indexOf(widget) < 0:
            return None                       # 已经被通用拆行处理过：不硬来
    for widget in widgets:                    # 从原行摘走(控件仍 parent 在页面上)
        row.takeAt(row.indexOf(widget))
    # 分组之间的竖线在堆叠表单里没有意义：隐藏即释放布局占位
    for name in ("line", "line_3", "line_4"):
        line = getattr(view, name, None)
        if line is not None:
            line.setVisible(False)
    # 放大倍数：150px 是桌面上的随手值，对"2.0 + 上下箭头"太富裕，收回自然宽度
    coverScale = getattr(view, "coverScale", None)
    if coverScale is not None:
        coverScale.setMinimumWidth(0)
    from PySide6.QtWidgets import QHBoxLayout, QSpacerItem, QVBoxLayout
    parent = row.parent()
    if parent is None:
        return None
    index = parent.indexOf(row)
    if index < 0:
        return None
    column = QVBoxLayout()
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(WrapRowSpacing)
    spacing = row.spacing() if row.spacing() >= 0 else WrapRowSpacing
    rows = []
    for labelName, widgetName in (("label_26", "coverScale"), ("label_5", "fmtBox")):
        label = getattr(view, labelName)
        widget = getattr(view, widgetName)
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(spacing)
        # 左侧留白用显式 spacer(注意 addSpacing 不返回对象，改不了宽度)
        spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        line.addItem(spacer)
        line.addWidget(label)
        line.addWidget(widget)
        line.addStretch(1)
        column.addLayout(line)
        rows.append((line, spacer, label, widget))
    parent.insertLayout(index + 1, column)
    return rows


# ---------------------------------------------------------------------------
# 下拉框弹窗：装得下最宽的选项
# ---------------------------------------------------------------------------

# 弹窗里每个选项除了文字本身，还占：视图左内边距(主题 QSS 15px) + 项边框(8px*2)
# + 菜单式弹窗里 QMenu::item 的左右内边距(Android 上实测约 20/25px) + 视图边框(2px*2)。
# 各平台样式差别很大(真机实测"文字区"只有弹窗宽的 4 成)，统一留 72px ——
# 宁可让弹窗比 combo 宽一点，也不能再裁字。
ComboPopupPadding = 72


def FitComboPopups(root):
    """ 让每个下拉框的弹窗至少装得下最宽的选项(不改 combo 自己的宽度)

    QComboBox 的弹窗宽度默认跟随 combo 自己(showPopup 里 listRect 取的是 combo
    的弹端子控件矩形，按内容加宽那条路只在特定风格下才走)，而竖屏拆行/压扁之后
    combo 常被压到 40~60px —— 弹窗跟着变窄，"webp/apng" 被硬切掉半个字
    (真机截图：webp→web、apng→apn)，既没有省略号也弹不出横向滚动条。
    弹窗容器最后会 expandedTo(container->minimumSize())，所以给**视图**设一个
    内容宽度下限，弹窗就会跟着放宽，combo 本身仍占原来的格子。
    """
    if root is None:
        return 0
    count = 0
    for combo in _SelfAndChildren(root, QComboBox):
        try:
            view = combo.view()
            if view is None:
                continue
            metrics = combo.fontMetrics()
            need = 0
            for index in range(combo.count()):
                need = max(need, metrics.horizontalAdvance(combo.itemText(index)))
            width = need + ComboPopupPadding
            if width > view.minimumWidth():
                view.setMinimumWidth(width)
                count += 1
        except Exception as es:
            Log.Error(es)
    if count:
        Log.Warn("portrait: {} 个下拉框的弹窗按内容加宽(不再裁字)".format(count))
    return count


def ReflowPortrait(root=None, available=None):
    """ 按当前宽度重排一次(幂等，可反复调用)

    为什么需要重复跑：页面上的文字是**运行时**才填的(例如设置页的下载路径
    `SetDownloadLabel` 在建好界面之后才 setText)，Apply 时量出来的行宽是"还没填字"的
    假值；真机上就出现过"Apply 时 10 行放得下，填完字之后有一行 378px > 可用 352px"。
    所以在页面切出来的时候再跑一遍。
    """
    if not IsEnabled():
        return 0
    if root is None:
        root = getattr(mobile_ui._mainView, "subStackWidget", None) if mobile_ui._mainView is not None else None
    if root is None:
        return 0
    if available is None:
        available = PortraitWidth(mobile_ui._mainView) if mobile_ui._mainView is not None else mobile_ui._limit
    # 页面自己的表单布局必须排在通用拆行之前：它按页面语义排好的行都放得下，
    # 通用拆行/压扁就不再插手(批量超分页的 combo 不被压扁，弹窗不裁字)。
    mainView = mobile_ui._mainView
    batchSr = getattr(mainView, "batchSrView", None) if mainView is not None else None
    count = LayoutBatchSrTool(batchSr, available) if batchSr is not None else 0
    count += StackSideNavs(root)
    count += EnableLabelWrap(root, available)
    count += WrapWideRows(root, available)
    count += FlattenWideGrids(root, available)
    count += ShrinkToFit(root, available)
    count += ClampPageWidth(root, available)
    # 弹窗宽度要在所有拆行/压扁之后按最终字体算一次(combo 可能已经被压窄)
    count += FitComboPopups(root)
    # 设置页的路径行：任何一次重排之后都重新省略一遍(标签文字是运行时才填的)
    FitSettingRows(root)
    return count


def InstallReflowHook(mainView):
    """ 页面切换 / 首屏文字填完之后再重排一次 """
    stack = getattr(mainView, "subStackWidget", None)
    if stack is None:
        return

    def OnPageChanged(index):
        page = stack.widget(index)
        if page is None:
            return
        if IsEnabled():
            # 真机上没有 OCR，只能靠这行知道用户停在哪个页面
            LogUiEvent("page -> {} (index {})".format(PageName(page), index))
        # 只重排刚显示出来的那一页(文字是切出来时才知道真实宽度的)，避免每次切页都全栈扫描
        def ReflowPage(p=page):
            try:
                StackSideNavs(p)
                ReflowPortrait(p)
                mobile_ui.ApplyGridCoverSize(p)
            except Exception as es:
                Log.Error(es)
        QTimer.singleShot(150, ReflowPage)
        # 详情页的标题/标签/按钮文字、设置页的路径都是**网络/配置回来之后**才 setText
        # 的，150ms 那一次量到的还是空文本。再补两次(总耗时 < 1s，页面已经静止)。
        QTimer.singleShot(650, ReflowPage)
        QTimer.singleShot(1500, ReflowPage)

    try:
        stack.currentChanged.connect(OnPageChanged)
    except Exception as es:
        Log.Error(es)
    # 首屏(下载路径之类的文字)是异步填的，隔一会儿再兜一次
    QTimer.singleShot(2500, ReflowPortrait)
    return


def OnTabPageChanged(tabs, index):
    """ QTabWidget 换页之后重排新页(封面是异步加的，这时也只能补一次) """
    if not IsEnabled():
        return
    try:
        page = tabs.widget(index)
    except Exception as es:
        Log.Error(es)
        return
    if page is None:
        return
    # 延后一点：先让 Qt 把新页的几何摆好，列表视口宽才是真的
    DeferCall(lambda p=page: mobile_ui.ReflowGridCoverForPage(p), TabReflowMs)
    return


def InstallTabReflowHook(mainView):
    """ 给所有 QTabWidget(首页的"分区"标签)装"换页后按真实视口重排网格"

    首页的分区页是隐藏的，而 Qt 只给 QTabWidget 的当前页排几何：隐藏页里的列表
    视口宽是一个"没布局过"的假值(真机实测 790px，被页宽夹成 366px)。往这些分区里
    加的封面就按偏大的尺寸建好了，等用户真的切过去时，一行只放得下 1 个 —— 而
    "进一次设置页再返回"会重排整个首页(那时列表已可见，量到的是真实宽度)，所以
    看起来"过一会儿自己好了"。这里把那次重排补在换页之后。
    """
    if not IsEnabled() or mainView is None:
        return 0
    count = 0
    for tabs in _SelfAndChildren(mainView, QTabWidget):
        if getattr(tabs, "_jmTabReflow", False):
            continue
        try:
            tabs.currentChanged.connect(partial(OnTabPageChanged, tabs))
            tabs._jmTabReflow = True
            count += 1
        except Exception as es:
            Log.Error(es)
    if count:
        Log.Warn("portrait: {} 个标签页装了换页重排(分区封面)".format(count))
    return count
