# coding:utf-8
""" 宿主自检：表格"滑动不跟手/单击漂移"

真机现象(0.52)：
  1. 超分模型选择表、下载列表**左右滑不跟手**，轻轻一滑就跳好几行/好几列；
     下载列表右侧列永远看不到。
  2. 表格里**单击漂移**，点第 3 行命中第 4 行、点第 2 列命中第 3 列。

根因(见 docs/mobile_touch_and_recents_fix_plan.md)：
  1. QScroller 的滑动闭环是"手指位移(px) -> QScrollEvent.contentPos ->
     scrollBar->setValue(contentPos)"，也就是**一个手指像素 = 一个滚动条单位**。
     而 QAbstractItemView 默认 `ScrollPerItem`(一个单位 = 一整行/列)，
     于是 8px 的位移 = 跳 8 行。`MakeScrollable()` 原来只设了垂直逐像素，
     `setHorizontalScrollMode` 全仓库从未设置过 —— 而这两张表的横向内容都超出竖屏，
     横向恰恰是用户最常滑的方向。
  2. `_ActivateItemView()` 把 `view.mapFromGlobal()` 得到的**表格坐标**喂给
     `indexAt()`，但 `QAbstractItemView::indexAt(point)` 要的是**视口坐标**：
     命中点被平移了"水平表头高度 + 边框 + 竖直表头宽度"，行高只有 23px 的表
     于是稳定错一行/一列。

这个自检分三组：
  A. 滚动计量单位：接管后两个方向都是 ScrollPerPixel；喂 QScrollEvent(37px)
     滚动条只走 37(**反证**：改回 ScrollPerItem 会走 37 行，证明断言测的是根因)
  B. 点按命中：`_ActivateItemView` 命中 (2,1)；端到端(触控路由 + 真触控)同样命中
  C. 兜底：`MakeItemViewsPixelScroll()` 对已接管的表也生效(幂等)

用法：python android/tools/host_test_table_touch.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QScrollEvent
    from PySide6.QtWidgets import (QAbstractItemView, QApplication, QTableWidget,
                                   QTableWidgetItem, QVBoxLayout, QWidget)
    from PySide6.QtTest import QTest
except Exception as es:                      # pragma: no cover - 宿主没有 PySide6
    print("SKIP: 本机没有 PySide6 ({})".format(es))
    sys.exit(0)

import tools.mobile_ui_touch as touch  # noqa: E402

Failures = []


def Check(condition, message):
    if condition:
        print("  ok  {}".format(message))
    else:
        print("  FAIL {}".format(message))
        Failures.append(message)


class Page:
    """ 一张"像真机那样"的表：可见的水平表头 + 可见的竖直表头 + 200 行 """

    def __init__(self, app, rows=200):
        self.app = app
        self.page = QWidget()
        self.page.resize(480, 800)
        lay = QVBoxLayout(self.page)
        self.table = QTableWidget(rows, 4)
        self.table.setHorizontalHeaderLabels(["模型名", "算法", "耗时", "描述"])
        # 真机上这两张表都是"表头可见"(水平 25px / 竖直 23px)，正是漂移的来源
        self.table.horizontalHeader().setVisible(True)
        self.table.verticalHeader().setVisible(True)
        self.table.verticalHeader().setDefaultSectionSize(23)
        for row in range(rows):
            for col in range(4):
                self.table.setItem(row, col, QTableWidgetItem("r{}c{}".format(row, col)))
        lay.addWidget(self.table)
        self.page.show()
        app.processEvents()

    def Cell(self, row, col):
        """ 单元格中心点的全局坐标(visualRect 是**视口**坐标) """
        index = self.table.model().index(row, col)
        rect = self.table.visualRect(index)
        return self.table.viewport().mapToGlobal(rect.center())

    def Close(self):
        self.page.hide()
        self.page.deleteLater()
        self.app.processEvents()


def ScrollEvent(dx, dy):
    return QScrollEvent(QPointF(dx, dy), QPointF(0, 0),
                        QScrollEvent.ScrollState.ScrollUpdated)


def TestScrollUnit(app):
    """ A. 滚动计量单位 = 像素(而不是"行") """
    print("\n[A] 滚动计量单位：手指像素 == 滚动条像素")
    page = Page(app)
    table = page.table
    # 前提(反证用)：裸表默认是按项滚动 —— 这才是"轻微一滑跳多行"的土壤
    Check(table.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerItem,
          "裸 QTableWidget 默认 ScrollPerItem(前提成立)")

    # 反证：按项模式下，喂 37px 会把滚动条推到 37 行(被夹到 199)，而不是 37px
    QApplication.sendEvent(table.viewport(), ScrollEvent(0, 37))
    app.processEvents()
    itemMode = table.verticalScrollBar().value()
    Check(itemMode >= 30, "ScrollPerItem 下 37px -> 滚动条走 {} (按行跳)".format(itemMode))
    table.verticalScrollBar().setValue(0)

    # 接管之后：两个方向都必须是逐像素
    touch.MakeScrollable(table)
    Check(table.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel,
          "接管后垂直 ScrollPerPixel")
    Check(table.horizontalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel,
          "接管后水平 ScrollPerPixel(原来漏了这条，横向就是按列跳)")

    # 1:1：37px 的 contentPos 只能让滚动条走 37
    QApplication.sendEvent(table.viewport(), ScrollEvent(0, 37))
    app.processEvents()
    vertical = table.verticalScrollBar().value()
    Check(abs(vertical - 37) <= 1, "垂直 37px -> 滚动条 {} (1:1 跟手)".format(vertical))

    # 宽表横向真的能滚(列宽合计 550 > 视口)，先把列宽摆成真机上那样
    table.setColumnWidth(0, 200)
    table.setColumnWidth(1, 150)
    table.setColumnWidth(2, 100)
    table.setColumnWidth(3, 100)
    app.processEvents()
    Check(table.horizontalScrollBar().maximum() > 0,
          "列宽 550 > 视口 {} -> 有横向滚动范围 {}".format(
              table.viewport().width(), table.horizontalScrollBar().maximum()))

    table.horizontalScrollBar().setValue(0)
    QApplication.sendEvent(table.viewport(), ScrollEvent(37, 0))
    app.processEvents()
    horizontal = table.horizontalScrollBar().value()
    Check(abs(horizontal - 37) <= 1,
          "水平 37px -> 滚动条 {} (1:1 跟手, 横向内容才滚得到中间)".format(horizontal))
    page.Close()
    return True


def TestTapIndex(app):
    """ B. 点按命中：视口坐标 vs 表格坐标 """
    print("\n[B] 点按命中：点第 3 行第 2 列就命中第 3 行第 2 列")
    page = Page(app)
    table = page.table
    touch.MakeScrollable(table)

    for row, col in ((2, 1), (5, 3), (0, 0)):
        table.clearSelection()
        table.setCurrentCell(-1, -1)
        touch._ActivateItemView(table, page.Cell(row, col))
        app.processEvents()
        current = table.currentIndex()
        Check((current.row(), current.column()) == (row, col),
              "点 ({},{}) -> currentIndex ({},{} )".format(row, col, current.row(), current.column()))

    # 反证：把命中点换回"表格坐标"(加回表头/边框偏移)就会错位 —— 证明断言有效
    headerY = table.horizontalHeader().height()
    headerX = table.verticalHeader().width()
    table.clearSelection()
    table.setCurrentCell(-1, -1)
    old = table.viewport().mapFromGlobal(page.Cell(3, 2))
    old.setX(old.x() + headerX)
    old.setY(old.y() + headerY)
    touched = table.indexAt(old)
    Check((touched.row(), touched.column()) != (3, 2),
          "旧坐标算法(表格坐标)确实错位 -> ({},{} )".format(touched.row(), touched.column()))

    # 端到端：真触控点按 -> 触控路由 -> clicked 信号 + 选中行
    router = touch._TouchRouter()
    router.Enabled = True
    app.installEventFilter(router)
    clicks = []
    table.clicked.connect(lambda index: clicks.append((index.row(), index.column())))
    device = QTest.createTouchDevice()
    table.scrollToItem(table.item(6, 2))
    app.processEvents()
    point = page.Cell(6, 2)
    seq = QTest.touchEvent(page.page.windowHandle(), device)
    seq.press(0, point).commit()
    app.processEvents()
    seq = QTest.touchEvent(page.page.windowHandle(), device)
    seq.release(0, point).commit()
    app.processEvents()
    current = table.currentIndex()
    Check((current.row(), current.column()) == (6, 2),
          "真触控点按 (6,2) -> currentIndex ({},{} )".format(current.row(), current.column()))
    Check(clicks and clicks[-1] == (6, 2), "clicked 信号带同一格 -> {}".format(clicks[-1:]))
    app.removeEventFilter(router)
    page.Close()
    return True


def TestPixelScrollFallback(app):
    """ C. 逐像素兜底：已接管的表也补得回来(幂等) """
    print("\n[C] 兜底：MakeItemViewsPixelScroll 对已接管的表同样生效")
    page = Page(app)
    table = page.table
    touch.MakeScrollable(table)
    # 模拟"某条历史路径把它改回按项"(或某张新表从没走过 MakeScrollable)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
    changed = touch.MakeItemViewsPixelScroll(page.page)
    Check(changed >= 1, "补了 {} 张表".format(changed))
    Check(table.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
          and table.horizontalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel,
          "两个方向都补成逐像素")
    Check(touch.MakeItemViewsPixelScroll(page.page) == 0, "再调一次不动(幂等)")
    page.Close()
    return True


def TestPortraitColumns(app):
    """ D. 竖屏列策略：11 列的下载列表要能"一屏看全关键列" """
    print("\n[D] 竖屏列宽：关键信息同屏，不再有看不见的列")
    import tools.mobile_ui_layout as layout
    page = Page(app, rows=3)
    table = page.table
    # 照抄 download_view 的竖屏策略(11 列 -> 隐藏 5 列)
    for col in range(11):
        if col >= table.columnCount():
            table.setColumnCount(11)
        table.setColumnWidth(col, 100)
    table.setColumnWidth(1, 200)
    table.setColumnWidth(2, 300)
    app.processEvents()
    before = table.horizontalScrollBar().maximum()
    table._jmPortraitRule = {
        "hide": (0, 1, 5, 8, 9),
        "stretch": 2,
        "fixed": {3: 66, 4: 58, 6: 74, 7: 66, 10: 74},
    }
    layout.FitTablesForPortrait(page.page)
    app.processEvents()
    Check(table.isColumnHidden(1) and table.isColumnHidden(5), "低信息量列已隐藏(时间/速度)")
    Check(not table.isColumnHidden(2), "标题列仍显示")
    Check(table.horizontalScrollBar().maximum() == 0,
          "原来要横滚 {}px，现在一屏装下(横向范围 0)".format(before))
    Check(table.columnWidth(2) >= layout.TableMinSection * 2,
          "标题列拿到剩余宽度 -> {}px".format(table.columnWidth(2)))
    Check(table.verticalHeader().isVisible() is False, "竖屏隐藏行号表头(省 30px)")
    page.Close()
    return True


def Main():
    app = QApplication.instance() or QApplication(sys.argv)
    TestScrollUnit(app)
    TestTapIndex(app)
    TestPixelScrollFallback(app)
    TestPortraitColumns(app)
    if Failures:
        print("\nFAIL: {} 项未通过".format(len(Failures)))
        for item in Failures:
            print("  - {}".format(item))
        return 1
    print("\nOK: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(Main())
