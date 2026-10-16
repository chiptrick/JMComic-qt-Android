# coding:utf-8
""" 竖屏排版重排（并排改上下、拆行、折行、压扁、封面尺寸） """
from functools import partial

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QAbstractScrollArea, QBoxLayout, QComboBox, QCommandLinkButton, QSizePolicy, QTabWidget, QToolButton, QWidget
from tools.log import Log
from tools.mobile_ui_base import *  # noqa: F401,F403
from tools.mobile_ui_base import (_SelfAndChildren)
from tools import mobile_ui



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
            picture.setMaximumWidth(mobile_ui.CurrentLimit())
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


def StackSettingNav(view):
    """ 设置页专用收尾(方向已经由 StackSideNavs 改好)

    这里只补设置页自己的细节：目录行里的路径标签最小宽 150px，竖屏下会把"打开目录"
    按钮挤出去。
    """
    try:
        if view is None:
            return
        for name in ("downloadDir", "cacheDir", "chatDir", "waifu2xDir"):
            label = getattr(view, name, None)
            if label is not None:
                label.setMinimumWidth(100)
    except Exception as es:
        Log.Error(es)
    return


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
    count = StackSideNavs(root)
    count += EnableLabelWrap(root, available)
    count += WrapWideRows(root, available)
    count += FlattenWideGrids(root, available)
    count += ShrinkToFit(root, available)
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
