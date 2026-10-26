# coding:utf-8
""" 宿主自检：超分模型选择列表(三列 + 分组吸顶 + 当前使用高亮 + 耗时排序)

真机上这些问题只能靠肉眼：横向滚动条、列被藏、分组条吸顶时闪一下、当前选中项看不出。
它们在宿主上全是可量的几何/状态关系，所以用真 Qt(offscreen) 量：

  * 41 个模型全在、算法分组为 3 组、默认是分组顺序
  * 任何单元格都不出现 MODEL_/DENOISE 这类原始串（完整 ID 不展示）
  * 340/360/412/480/673 五个宽度下：列宽合计 == 视口宽、横向滚动条不可用
  * 最长模型名在 340 宽下也放得下（不省略）
  * 点表头「耗时」→ 平铺升序；再点 → 降序；再点 → 回到分组
  * 分组条：滚到组中间时吸顶返回该组；组自己露在顶上时不重复绘制
  * 「当前使用」只出现在一个模型行上，且 SelectedModelName 与点击项一致
  * 阅读页两段式(修改参数→保存)仍在（源码级断言，避免误删）

需要本机有 PySide6；没有就 SKIP(退出码 0)。
用法：py -3.10 android/tools/host_test_sr_model_list.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QAbstractItemView, QWidget  # noqa: E402
    from PySide6.QtGui import QFontMetrics  # noqa: E402
except Exception as es:                      # pragma: no cover - CI 的宿主没有 PySide6
    print("SKIP: 本机没有 PySide6 ({})".format(es))
    sys.exit(0)

Failures = []


def Check(condition, message):
    if condition:
        print("  ok  {}".format(message))
    else:
        Failures.append(message)
        print("  FAIL {}".format(message))


def CellTexts(table):
    for row in range(table.rowCount()):
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item is not None and item.text():
                yield row, col, item.text()


def ScrollToRow(table, row, app):
    table.scrollToItem(table.item(row, 0), QAbstractItemView.PositionAtTop)
    app.processEvents()


def Main():
    app = QApplication.instance() or QApplication(sys.argv)

    from component.widget.sr_model_table import (SrModelTable, SrModels, Algorithms,
                                                 FullModelName, ShowModelName, ShowModelLines,
                                                 FormatModelLabel)

    Current = "MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X"
    table = SrModelTable()
    table.resize(460, 620)
    table.show()
    table.SetCurrentModel(Current)
    app.processEvents()

    print("[1] 数据 / 默认分组")
    Check(table.ModelCount() == 41, "41 个模型都在 (实际 {})".format(table.ModelCount()))
    Check(table.GroupCount() == 3, "3 个算法分组 (实际 {})".format(table.GroupCount()))
    Check(table.SortMode() == SrModelTable.SortGrouped, "进入页面默认按分组排序")
    firstGroup = table._groupRows[0]
    Check(firstGroup[1] == "Waifu2x", "第一组是 Waifu2x (实际 {})".format(firstGroup[1]))
    Check(table._rowGroup[firstGroup[0] + 1] == "Waifu2x", "分组行下面是本组模型")
    order = [m[1] for _, m in table._modelRows]
    Check(order == sorted(order, key=lambda a: Algorithms.index(a)), "分组内顺序与算法分段一致")

    print("[2] 完整 ID 不展示")
    bad = [(r, c, t) for r, c, t in CellTexts(table)
           if "MODEL_" in t or "DENOISE" in t or "CONSERVATIVE" in t or "_UP" in t]
    Check(not bad, "没有单元格出现原始模型串 {}".format(bad[:3]))
    Check(all("\n".join(ShowModelLines(m)) == table.item(r, 0).text() for r, m in table._modelRows),
          "模型列是可读写法(第一行模型族 / 第二行倍数·降噪)")
    Check(FormatModelLabel(Current) == "Waifu2x(anime) · 2× · 降噪 3",
          "入口文案同样不露完整 ID (实际 {})".format(FormatModelLabel(Current)))

    print("[3] 当前使用高亮")
    row = table.RowOfModel(Current)
    Check(row >= 0, "当前模型能找到对应行")
    Check(table.item(row, 2).text() == "当前使用",
          "当前行描述列是「当前使用」(实际 {})".format(table.item(row, 2).text()))
    badges = [1 for _, _, t in CellTexts(table) if t == "当前使用"]
    Check(len(badges) == 1, "「当前使用」只出现在一行 (实际 {})".format(len(badges)))
    Check(table.item(row, 0).font().bold(), "当前行加粗")

    print("[4] 不横向滚动")
    for width in (340, 360, 412, 480, 673):
        table.resize(width, 620)
        app.processEvents()
        total = sum(table.columnWidth(c) for c in range(3))
        viewport = table.viewport().width()
        Check(total <= viewport and table.horizontalScrollBar().maximum() == 0,
              "宽 {}: 列宽合计 {} <= 视口 {}，横向滚动条不可用".format(width, total, viewport))
    # .ui 里的 defaultSectionSize 会在 setupUi 时把定宽列冲成 80，必须守住
    Check(table.columnWidth(1) == SrModelTable.CostWidth,
          "耗时列固定 {}px (实际 {})".format(SrModelTable.CostWidth, table.columnWidth(1)))
    Check(table.columnWidth(2) == SrModelTable.DescWidth,
          "描述列固定 {}px (实际 {})".format(SrModelTable.DescWidth, table.columnWidth(2)))

    print("[5] 最长名称不省略")
    table.resize(340, 620)
    app.processEvents()
    colWidth = table.columnWidth(0)
    worst, worstText = 0, ""
    for row, model in table._modelRows:
        fm = QFontMetrics(table.item(row, 0).font())
        for line in ShowModelLines(model):
            advance = fm.horizontalAdvance(line)
            if advance > worst:
                worst, worstText = advance, line
    Check(worst <= colWidth - 4,
          "340 宽下列宽 {} >= 最长一行 {}px ({})".format(colWidth, worst, worstText))

    print("[6] 耗时表头排序")
    table.resize(460, 620)
    app.processEvents()
    table.OnHeaderClicked(1)
    app.processEvents()
    Check(table.SortMode() == SrModelTable.SortCostAsc, "点一次 → 平铺升序")
    Check(table.GroupCount() == 0, "平铺后没有分组行")
    costs = [m[4] for _, m in table._modelRows]
    Check(costs == sorted(costs), "升序真的按耗时排 (前 5: {})".format(costs[:5]))
    Check("↑" in table.horizontalHeaderItem(1).text(), "表头显示 ↑")
    table.OnHeaderClicked(1)
    app.processEvents()
    Check(table.SortMode() == SrModelTable.SortCostDesc, "点两次 → 降序")
    Check([m[4] for _, m in table._modelRows] == sorted(costs, reverse=True), "降序真的按耗时排")
    table.OnHeaderClicked(1)
    app.processEvents()
    Check(table.SortMode() == SrModelTable.SortGrouped, "点三次 → 回到分组")
    Check(table.GroupCount() == 3, "分组行回来了")

    print("[7] 分组条吸顶")
    groupRow = table._groupRows[0][0]
    inner = groupRow + 4
    ScrollToRow(table, inner, app)
    Check(table.StickyGroup() == "Waifu2x", "滚到组中间：吸顶条是 Waifu2x (实际 {!r})".format(
        table.StickyGroup()))
    ScrollToRow(table, groupRow, app)
    Check(table.StickyGroup() == "", "分组行自己露在顶上时不重复绘制")
    ScrollToRow(table, table._groupRows[1][0] + 3, app)
    Check(table.StickyGroup() == table._groupRows[1][1], "滚到第二组中间：吸顶条跟着换 (实际 {!r})".format(
        table.StickyGroup()))
    table.SetSortMode(SrModelTable.SortCostAsc)
    app.processEvents()
    Check(table.StickyGroup() == "", "平铺模式不画吸顶条")

    print("[8] 选中项")
    table.SetSortMode(SrModelTable.SortGrouped)
    app.processEvents()
    target = FullModelName(SrModels[0])
    table.PickModel(target)
    Check(table.SelectedModelName() == target, "PickModel 后 SelectedModelName 一致")

    print("[9] 弹窗接线")
    from view.setting.setting_sr_select_view import SettingSrSelectView
    view = SettingSrSelectView(None, Current)
    view.tableWidget.PickModel(target)
    got = []
    view.Close.connect(got.append)
    view._ClickButton()
    Check(got == [target], "确定按钮回传完整模型名 {}".format(got))
    Check(view.tableWidget.SortMode() == SrModelTable.SortGrouped, "弹窗默认也是分组")

    parent = QWidget()
    parent.resize(480, 880)
    narrow = SettingSrSelectView(parent, Current)
    Check(narrow.widget.width() <= 464,
          "手机宽 480 时弹窗夹到 {}px (<= 464)".format(narrow.widget.width()))
    Check(narrow.widget.minimumWidth() == 0, "弹窗最小宽不再写死 500")

    print("[10] 阅读页两段式仍在")
    readSrc = open(os.path.join(ROOT, "src", "view", "read", "read_tool.py"), encoding="utf-8").read()
    Check("def SetWaifu2xCancle(self, isVisibel=False)" in readSrc, "SetWaifu2xCancle 还在")
    Check("self.modelNameButton.setEnabled(isVisibel)" in readSrc, "锁/解锁仍由它控制")
    Check("FormatModelLabel(" in readSrc, "按钮文案走 FormatModelLabel")

    print("")
    if Failures:
        print("FAILED {} 项:".format(len(Failures)))
        for item in Failures:
            print("  - {}".format(item))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(Main())
