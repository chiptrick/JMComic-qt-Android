# coding:utf-8
""" 首页/列表封面尺寸（一行 N 个的自动装箱与自校正） """
from PySide6.QtCore import QTimer
from tools.log import Log
from tools import platform_mobile
from tools.mobile_ui_base import *  # noqa: F401,F403
from tools.mobile_ui_base import (_SelfAndChildren)
from tools import mobile_ui



def GridCoverWidth(isCategory=False):
    """ 竖屏下封面该多宽：让一行正好放得下 GridColumns 个

    ComicItemWidget 原来按桌面写死 250x340(rate=100)，384px 的竖屏一行只能放下
    1 个封面(用户要求每行 2 本)。这里按**列表视口的真实宽度**反算封面宽度，
    宽高比保持桌面原样。self-correct 定下来的宽度优先(见 ApplyGridCoverSize)。
    """
    if mobile_ui._gridCoverFinal > 0:
        return mobile_ui._gridCoverFinal
    avail = mobile_ui._gridAvail
    if avail < 120:
        # 还不知道视口宽：退回"页面宽 - 列表边距"
        width = 0
        if mobile_ui._mainView is not None:
            width = mobile_ui.PortraitWidth(mobile_ui._mainView)
        if width < 200:
            screen = platform_mobile.GetScreenSize()
            width = int(screen[0] or 0)
        if width < 200:
            width = mobile_ui._limit
        if width < 200:
            width = MinWidthLimit
        avail = max(120, width - GridItemOverhead)
    return max(GridCoverMin, min(GridCoverMax, int((avail - GridItemOverhead) / max(1, GridColumns))))


def MeasureGridAvail(root):
    """ 量出列表真正能用的宽度(QListWidget 视口宽)

    必须**空列表也能量**：首页的漫画是异步加载的，等 item 出现再算就晚了
    (真机上就是这一步踩空，首屏 60 个 item 全按旧的宽封面建好，一行只放 1 个)。
    """
    try:
        from PySide6.QtWidgets import QListWidget
        # 列表还没被布局时(ComicListWidget.__init__ 里写死的 resize(800, 600)、
        # 或者窗口还没被 Android 拉成竖屏尺寸)视口会报出一个远大于页面的宽度，
        # 拿它当"可用宽"会把封面宽 freeze 在 GridCoverMax(240px) -> 一行只放 1 个。
        # 页面宽度是列表宽度的上限，超过它的一律按页面宽度算。
        pageWidth = mobile_ui.PortraitWidth(mobile_ui._mainView) if mobile_ui._mainView is not None else 0
        worst = 0
        for view in _SelfAndChildren(root, QListWidget):
            # 只量**真的露出来**的列表：隐藏页里的列表视口是"没布局过"的假宽度
            # (QTabWidget 只给当前页排几何，真机实测隐藏分区里的列表报 790px，
            # 而被页宽上限夹到 366px)。拿它算出来的封面宽对真实视口(330px)来说太宽，
            # 真机现象就是"切到别的分区还是一行 1 个，进一次设置页返回才变 2 个"。
            if not view.isVisible():
                continue
            viewport = view.viewport()
            width = viewport.width() if viewport is not None else view.width()
            if pageWidth >= 200 and width > pageWidth:
                width = pageWidth
            if width >= 120 and (worst == 0 or width < worst):
                worst = width
        if worst:
            mobile_ui._gridAvail = worst
    except Exception as es:
        Log.Error(es)
    return mobile_ui._gridAvail


def ResetGridCover():
    """ 尺寸/设置变化后重新反算封面宽(self-correct 的缓存要作废) """
    mobile_ui._gridCoverFinal = 0
    mobile_ui._gridAvail = 0
    mobile_ui._gridCoverAvail = 0
    return


def ScheduleGridCoverSize(root):
    """ 刚往列表里加完一批漫画 -> 去抖之后再对一次"一行 2 个"

    首页的漫画是网络回来后**一条条 AddBookItem** 的，控件宽度在建的时候就被封面宽
    定死了；而 ApplyGridCoverSize 原来只在窗口 shown / 切页时才跑，所以首屏那批
    item 建完之后没有任何时机纠正它 —— 真机表现就是"打开首页一行 1 个，进设置页
    再返回首页才变一行 2 个"(切页触发了那次重排)。

    这里在每次添加之后排一次重排(80ms 去抖，把一批添加合并成一次)。
    ApplyGridCoverSize 内部有 `_jmGridSized == width` 短路，重复调用只处理新 item，
    所以翻页/连续加载时不会有额外开销。
    """
    if not IsEnabled() or root is None:
        return
    try:
        if root not in mobile_ui._gridPending:
            mobile_ui._gridPending.append(root)
        if mobile_ui._gridTimer is None:
            timer = QTimer()
            timer.setSingleShot(True)
            timer.setInterval(GridScheduleMs)
            timer.timeout.connect(_FlushGridPending)
            mobile_ui._gridTimer = timer
        # 一批添加只排一次(不 restart)，保证首屏能及时收敛
        if not mobile_ui._gridTimer.isActive():
            mobile_ui._gridTimer.start()
    except Exception as es:
        Log.Error(es)
    return


def _FlushGridPending():
    """ 把攒下来的列表各重排一次 """
    if not mobile_ui._gridPending:
        return
    pending, mobile_ui._gridPending = mobile_ui._gridPending, []
    for root in pending:
        try:
            ApplyGridCoverSize(root)
        except Exception as es:
            Log.Error(es)
    return


def ApplyGridCoverSize(root):
    """ 把已经建好的封面控件改成竖屏尺寸，并同步 QListWidgetItem 的 sizeHint

    只改控件尺寸是不够的：QListWidget 是按 item 的 sizeHint 装箱的，sizeHint 还是
    添加时的旧值的话，一行照样只放得下 1 个。
    """
    if root is None:
        return 0
    try:
        from component.widget.comic_item_widget import ComicItemWidget
    except Exception:
        return 0
    count = 0
    try:
        # 先量视口宽(空列表也能量)：首页的 item 是异步加的，等它们出现再算就晚了
        MeasureGridAvail(root)
        # 视口宽变了(旋转/改窗口大小/换页面)，之前定下来的封面宽要作废重算，
        # 否则横屏(或在窗口还没定型时)量出来的宽会被拿到竖屏用 -> 一行只放得下 1 个
        if mobile_ui._gridAvail and mobile_ui._gridAvail != mobile_ui._gridCoverAvail:
            if mobile_ui._gridCoverAvail:
                Log.Warn("portrait: 列表视口 {}px -> {}px，重算封面宽".format(
                    mobile_ui._gridCoverAvail, mobile_ui._gridAvail))
            mobile_ui._gridCoverFinal = 0
        width = GridCoverWidth(False)
        for attempt in range(4):
            for widget in _SelfAndChildren(root, ComicItemWidget):
                if getattr(widget, "_jmGridSized", 0) == width:
                    continue
                try:
                    widget.ResizeCover(width)
                    widget._jmGridSized = width
                    count += 1
                except Exception as es:
                    Log.Error(es)
            if count:
                RefreshItemSizeHints(root)
            # 只改封面尺寸不一定够：item widget 还有自己的边距/标签，
            # 真实 sizeHint 可能刚好超过"可用宽度 / 列数" -> QListWidget 又变回一行 1 个。
            # 这里按真实 sizeHint 反推需要再收多少，最多迭代几次。
            over = _GridOverflow(root)
            if over <= 0:
                break
            width = max(GridCoverMin, width - over - 2)
            Log.Warn("portrait: 封面还宽 {}px，收到 {}px 再试".format(over, width))
        else:
            Log.Warn("portrait: 封面宽度自校正未收敛(最后一轮仍超宽)")
        mobile_ui._gridCoverFinal = width
        mobile_ui._gridCoverAvail = mobile_ui._gridAvail
    except Exception as es:
        Log.Error(es)
    if count:
        Log.Warn("portrait: {} 个封面改为一行 {} 个(封面宽 {}px)".format(
            count, GridColumns, mobile_ui._gridCoverFinal or GridCoverWidth(False)))
    return count


def _GridOverflow(root):
    """ item 实际宽度超出"可用宽/列数"多少像素(<=0 表示一行放得下 GridColumns 个) """
    try:
        from PySide6.QtWidgets import QListWidget
        worst = 0
        for view in _SelfAndChildren(root, QListWidget):
            # 隐藏页的视口是假宽度(见 MeasureGridAvail)，量出来的"可用宽/列数"偏大，
            # 就永远发现不了"item 对真实视口来说太宽"
            if not view.isVisible():
                continue
            viewport = view.viewport()
            avail = viewport.width() if viewport is not None else view.width()
            if avail <= 0 or not view.count():
                continue
            per = max(1, avail // max(1, GridColumns))
            for row in range(min(view.count(), 8)):
                widget = view.itemWidget(view.item(row))
                if widget is None:
                    continue
                worst = max(worst, widget.sizeHint().width() - per)
        return worst
    except Exception as es:
        Log.Error(es)
    return 0


def ReflowGridCoverForPage(page):
    """ 某个标签页/页面**刚露出来**时，按它现在的真实视口宽重排一次网格

    首页的"分区"是 QTabWidget 的标签页，而 Qt 只给当前页排几何：隐藏页里的列表
    视口宽是一个"没布局过"的假值(真机实测 790px)。用假值算封面宽/栅格都会偏大，
    真机现象就是"切到别的分区依然一行 1 个封面，进一次设置页再返回才变一行 2 个"
    (返回时重排了整个首页，那时列表已经可见，量到的是真实宽度)。所以切页之后要等
    新页真的可见了再量一次。
    """
    if page is None:
        return 0
    count = ApplyGridCoverSize(page)
    # 封面宽没变时 ApplyGridCoverSize 内部会短路(不调 RefreshItemSizeHints)，
    # 但这个列表在隐藏期间根本没按真实视口定过栅格，这里必须补一次。
    RefreshItemSizeHints(page)
    return count


def RefreshItemSizeHints(root):
    """ 重新按控件自身尺寸刷新列表项尺寸(封面尺寸变化后必须调)

    只改 item 的 sizeHint 是不够的：QListView 的"一行几个"是上一次排版算出来的，
    必须显式让它重排，否则真机上会出现"尺寸改了但还是一行 1 个"。
    """
    try:
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QListWidget
        for view in _SelfAndChildren(root, QListWidget):
            try:
                widgets = []
                for row in range(view.count()):
                    item = view.item(row)
                    widget = view.itemWidget(item)
                    if widget is None:
                        continue
                    item.setSizeHint(widget.sizeHint())
                    widgets.append(widget)
                if widgets:
                    # 显式给栅格尺寸 + 固定宽度：一行几个就确定了。
                    # 只 setGridSize 不够：QListView 的装箱仍会看 item 的 sizeHint，
                    # 而 sizeHint 会被 item 内部布局(封面+标签+边距)撑大；真机上因此
                    # 出现过"item 163 < 330/2 却仍然一行 1 个"。
                    # 把 item widget 的宽度也固定成栅格宽，sizeHint 就跟着栅格走。
                    cellW = max(w.sizeHint().width() for w in widgets)
                    cellH = max(w.sizeHint().height() for w in widgets)
                    viewport = view.viewport()
                    avail = viewport.width() if viewport is not None else view.width()
                    per = max(60, avail // max(1, GridColumns)) if avail > 0 else 0
                    if per > 0 and cellW > per:
                        cellW = per
                        for w in widgets:
                            try:
                                w.setFixedWidth(cellW)
                            except Exception as es:
                                Log.Error(es)
                    view.setGridSize(QSize(cellW, cellH))
                # 强制重排(顺序：先更新几何再重排 items)
                for name in ("updateGeometries", "doItemsLayout"):
                    func = getattr(view, name, None)
                    if func is None:
                        continue
                    try:
                        func()
                    except Exception:
                        pass
            except Exception as es:
                Log.Error(es)
    except Exception as es:
        Log.Error(es)
    return
