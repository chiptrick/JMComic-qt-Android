# coding:utf-8
""" 宿主自检：下载列表「卡片式」排版（方案 A）

真机上"标题只剩两个字 / 表头被裁 / 4 列被隐藏"全靠肉眼发现，其实都能量出来，
所以搬到宿主上用真 Qt 量（离屏渲染，不需要真机）：

  * 一行 = 一张卡片，表格只剩 1 列且表头隐藏（不再有被裁切的表头）
  * 卡片里 10 个字段全部有值（id/标题/下载进度/章节/速度/状态/转换进度/章节/耗时/状态）
  * 长标题折成 2 行、超长才省略；短标题 1 行
  * 480 宽下卡片高度合理（<= 130px），且同一份数据行高一致
  * 状态徽章右边缘对齐成一条竖线
  * 「下载中」才有 2px 进度条
  * 排序下拉能重排行、行号不串
  * 卡片鼠标穿透（点击必须落到表格上，否则选择/右键菜单会失效）

用法：python android/tools/host_test_download_card.py
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt, QPoint  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402
except Exception as es:                      # pragma: no cover
    print("SKIP: 本机没有 PySide6 ({})".format(es))
    sys.exit(0)

import images_rc  # noqa: E402,F401

Failures = []


def Check(condition, message):
    if condition:
        print("  ok  {}".format(message))
    else:
        Failures.append(message)
        print("  FAIL {}".format(message))


def MakeItem(bookId, title, dl, eps, speed, status, cv, cvEps, tick, cvStatus):
    """ 造一条下载记录（字段与真机一致：章节项里存图片进度） """
    from view.download.download_item import DownloadItem, DownloadEpsItem
    item = DownloadItem()
    item.bookId = bookId
    item.title = title
    item.speedStr = speed
    item.status = status
    item.convertStatus = cvStatus
    item.cvTick = tick
    item.epsIds = [1001]
    item.curDownloadEpsId = 1001
    item.curConvertEpsId = 1001
    info = DownloadEpsItem()
    info.bookId = bookId
    info.epsId = 1001
    info.epsTitle = "第1话"
    info.picCnt = eps[1]
    info.curPreDownloadIndex = dl[0]
    info.curPreConvertId = cv[0]
    item.epsInfo = {1001: info}
    return item


def BuildView():
    from view.download.download_view import DownloadView
    view = DownloadView()
    view.resize(480, 900)
    # 清掉数据库里可能存在的行，只留本次造的数据
    view.downloadDict.clear()
    view.tableWidget.setRowCount(0)
    return view


def Install(view, items):
    for item in items:
        row = view.tableWidget.rowCount()
        item.tableRow = row
        view.downloadDict[item.bookId] = item
        view.tableWidget.insertRow(row)
        view.UpdateTableItem(item)
    view.UpdateCount()


def TestLayout(app, view):
    from view.download.download_item import DownloadItem
    items = [
        MakeItem("422231", "【蕭敬騰】163話 完整版合集（含番外・全彩）",
                 (163, 163), (163, 163), "1.2 MB/s", DownloadItem.Success,
                 (163, 163), (1, 1), 12, DownloadItem.ConvertSuccess),
        MakeItem("422188", "【合集】短篇作品集 188話",
                 (188, 188), (188, 188), "", DownloadItem.Success,
                 (188, 188), (1, 1), 8, DownloadItem.ConvertSuccess),
        MakeItem("422355", "[Pixiv] 作者精选合集 84話（含特典・全彩・中文翻译，专门用来测试两行折行）",
                 (62, 84), (84, 84), "866.1 KB/s", DownloadItem.Downloading,
                 (40, 84), (1, 1), 0, DownloadItem.Converting),
        MakeItem("421776", "【禁】31話",
                 (31, 31), (31, 31), "", DownloadItem.Success,
                 (28, 31), (1, 1), 0, DownloadItem.Error),
    ]
    Install(view, items)

    table = view.tableWidget
    app.processEvents()

    Check(table.columnCount() == 1, "表格只剩 1 列（不再是 11 列宽表）")
    Check(not table.horizontalHeader().isVisible(), "表头已隐藏（不再有被裁半个字的表头）")
    Check(not table.verticalHeader().isVisible(), "行号表头已隐藏")
    Check(table.rowCount() == 4, "4 条记录 -> 4 行")

    card = table.cellWidget(0, 0)
    Check(card is not None, "第 1 行挂着卡片控件")
    Check(card.testAttribute(Qt.WA_TransparentForMouseEvents),
          "卡片鼠标穿透（点击落到表格上，选择/右键菜单/双击照旧）")

    # 10 个字段
    Check(card.idLabel.text() == "#422231", "漫画 ID 可见: {}".format(card.idLabel.text()))
    Check(card.timeLabel.text().startswith("· 20"), "时间可见: {}".format(card.timeLabel.text()))
    Check(card.kvDl.valueLabel.text() == "163/163", "下载进度: {}".format(card.kvDl.valueLabel.text()))
    Check(card.kvEps.valueLabel.text() == "1/1", "下载章节: {}".format(card.kvEps.valueLabel.text()))
    Check(card.kvSpeed.valueLabel.text() == "1.2 MB/s", "下载速度: {}".format(card.kvSpeed.valueLabel.text()))
    Check("完成" in card.stateDl.text(), "下载状态徽章: {}".format(card.stateDl.text()))
    Check(card.kvCv.valueLabel.text() == "163/163", "转换进度: {}".format(card.kvCv.valueLabel.text()))
    Check(card.kvCvEps.valueLabel.text() == "1/1", "转换章节: {}".format(card.kvCvEps.valueLabel.text()))
    Check(card.kvCvTime.valueLabel.text() == "12s", "转换耗时: {}".format(card.kvCvTime.valueLabel.text()))
    Check(card.stateCv.isVisible() and card.stateCv.text(), "转换状态徽章: {}".format(card.stateCv.text()))

    # 标题折行：短标题 1 行、长标题 2 行、超长才有省略号
    heights = [table.rowHeight(r) for r in range(table.rowCount())]
    titles = [table.cellWidget(r, 0).titleLabel.text() for r in range(3)]
    Check("\n" not in titles[1], "短标题保持一行: {!r}".format(titles[1]))
    Check(titles[2].count("\n") == 1, "长标题折成两行")
    Check(all(60 <= h <= 140 for h in heights), "行高在合理区间: {}".format(heights))
    Check(len(set(heights)) <= 3, "同一屏行高基本一致（不会忽高忽低）: {}".format(heights))

    # 徽章右边缘对齐成一条竖线
    right = []
    for row in range(table.rowCount()):
        c = table.cellWidget(row, 0)
        right.append(c.stateDl.mapTo(c, c.stateDl.rect().topRight()).x())
        right.append(c.stateCv.mapTo(c, c.stateCv.rect().topRight()).x())
    Check(max(right) - min(right) <= 1, "状态徽章右边缘对齐: {}".format(right))

    # 进度条只给下载中的
    Check(not table.cellWidget(0, 0).bar.isVisible(), "已完成的卡片没有进度条")
    Check(table.cellWidget(2, 0).bar.isVisible(), "下载中的卡片有 2px 进度条")
    Check(table.cellWidget(2, 0).bar.height() == 2, "进度条高度 = 2px")

    # 错误态用红色
    Check(table.cellWidget(3, 0).stateCv.text(), "转换失败状态有文字")
    Check("236" in table.cellWidget(3, 0).stateCv.styleSheet(), "转换失败用红色")


def TestSelection(app, view):
    table = view.tableWidget
    table.selectRow(1)
    app.processEvents()
    Check(table.cellWidget(1, 0)._selected, "选中第 2 行 -> 卡片高亮")
    Check(not table.cellWidget(0, 0)._selected, "未选中的卡片不高亮")
    table.clearSelection()
    app.processEvents()
    Check(not table.cellWidget(1, 0)._selected, "取消选中 -> 高亮消失")


def TestSort(app, view):
    table = view.tableWidget
    order = [table.item(r, 0).text() for r in range(table.rowCount())]
    view.sortCombo.setCurrentIndex(1)   # 按标题
    app.processEvents()
    after = [table.item(r, 0).text() for r in range(table.rowCount())]
    Check(after != [] and len(after) == len(order), "排序后行数不变")
    titles = [view.downloadDict[b].title for b in after]
    Check(titles == sorted(titles, key=lambda t: t.lower()), "按标题升序: {}".format(after))
    Check([view.downloadDict[b].tableRow for b in after] == list(range(len(after))),
          "排序后 tableRow 与行号一致（不会串行）")


def TestExtreme(app, view):
    from view.download.download_item import DownloadItem
    item = MakeItem("1234567890",
                    "【测试】这是一个非常非常长的标题，用来验证两行截断、换行与三列对齐在各种长度下是否依然稳定"
                    "（第 12 卷 特装版 + 全彩番外 + 中文翻译 + 连载中 + 作者精选，继续加长到必须省略为止）",
                    (12345, 12345), (12345, 12345), "1023.4 MB/s", DownloadItem.Success,
                    (12345, 12345), (999, 999), 4321, DownloadItem.ConvertSuccess)
    Install(view, [item])
    app.processEvents()
    row = view.tableWidget.rowCount() - 1
    card = view.tableWidget.cellWidget(row, 0)
    text = card.titleLabel.text()
    Check(text.count("\n") == 1 and text.split("\n")[-1].endswith("…"),
          "超长标题折两行且末尾省略: {!r}".format(text))
    Check(card.kvDl.valueLabel.text() == "12345/12345", "5 位数字不丢")
    Check(card.kvSpeed.valueLabel.text() == "1023.4 MB/s", "超大速度不丢")
    Check(view.tableWidget.rowHeight(row) <= 140, "极端数据下卡片高度仍受控: {}".format(
        view.tableWidget.rowHeight(row)))


def TestFilter(app, view):
    table = view.tableWidget
    view.comboBox.setCurrentIndex(1)      # 未完成
    app.processEvents()
    visible = [r for r in range(table.rowCount()) if not table.isRowHidden(r)]
    Check(all(view.downloadDict[table.item(r, 0).text()].status != view.downloadDict[
        table.item(r, 0).text()].Success for r in visible), "「未完成」只留未完成的: {}".format(visible))
    Check(view.countLabel.text().startswith("共 ") and "显示" in view.countLabel.text(),
          "过滤后计数带「显示 N 项」: {}".format(view.countLabel.text()))
    view.comboBox.setCurrentIndex(0)
    app.processEvents()
    Check(all(not table.isRowHidden(r) for r in range(table.rowCount())), "切回「全部」全部可见")


def TestDelete(app, view):
    table = view.tableWidget
    before = table.rowCount()
    bookId = table.item(0, 0).text()
    view.RemoveRecord(bookId)
    app.processEvents()
    Check(table.rowCount() == before - 1, "删除一条 -> 行数 {}".format(table.rowCount()))
    Check(bookId not in view.downloadDict, "删除后 downloadDict 里也没有了")
    rows = [view.downloadDict[table.item(r, 0).text()].tableRow for r in range(table.rowCount())]
    Check(rows == list(range(len(rows))), "删除后 tableRow 重排正确: {}".format(rows))
    Check(view.countLabel.text().startswith("共 {}".format(table.rowCount())),
          "删除后计数同步: {}".format(view.countLabel.text()))


def TestResize(app, view):
    table = view.tableWidget
    wide = [c.width() for c in [table.cellWidget(r, 0) for r in range(table.rowCount())] if c]
    view.resize(800, 900)
    app.processEvents()
    view.SyncCardHeights()
    app.processEvents()
    wide2 = [c.width() for c in [table.cellWidget(r, 0) for r in range(table.rowCount())] if c]
    Check(wide2 and wide2[0] > (wide[0] if wide else 0), "窗口变宽 -> 卡片跟着变宽 {} -> {}".format(
        wide[:1], wide2[:1]))
    card = table.cellWidget(0, 0)
    Check(card.titleLabel.width() > 300, "标题拿到更宽的可用宽度: {}".format(card.titleLabel.width()))
    Check(table.rowHeight(0) < 120, "变宽后行高仍然受控: {}".format(table.rowHeight(0)))
    view.resize(480, 900)
    app.processEvents()


def TestRender(app, view, path):
    view.resize(480, 900)
    app.processEvents()
    pix = view.grab()
    pix.save(path)
    print("  ..  渲染快照: {}".format(path))


def ApplyTheme(app):
    from PySide6.QtGui import QFont
    try:
        app.setFont(QFont("Microsoft YaHei", 10))
    except Exception:
        pass
    path = os.path.join(ROOT, "res", "theme", "dark_orange.qss")
    try:
        with io.open(path, encoding="utf-8") as f:
            qss = f.read()
        # 主题里写死 font-family: Roboto（安卓有系统级 CJK 回退，Windows 没有 ->
        # 全变方块），宿主渲染时换成雅黑，只为看图，不影响真机
        app.setStyleSheet(qss.replace("Roboto", "Microsoft YaHei"))
    except Exception as es:
        print("  ..  跳过主题({})".format(es))


def Main():
    app = QApplication.instance() or QApplication(sys.argv)
    from tools.str import Str
    Str.Reload()   # 真机上由 main_view 调；宿主里补一次，否则状态文案取到空串
    ApplyTheme(app)
    view = BuildView()
    view.show()
    app.processEvents()

    print("[1] 布局与字段")
    TestLayout(app, view)
    print("[2] 选中同步")
    TestSelection(app, view)
    print("[3] 排序")
    TestSort(app, view)
    print("[4] 极端数据")
    TestExtreme(app, view)
    print("[5] 分组过滤")
    TestFilter(app, view)
    print("[6] 删除重排")
    TestDelete(app, view)
    print("[7] 旋转/变宽")
    TestResize(app, view)
    print("[8] 渲染")
    TestRender(app, view, os.path.join(HERE, "..", "build_logs", "download_cards_host.png"))

    if Failures:
        print("\n{} 项未通过:".format(len(Failures)))
        for f in Failures:
            print("  - " + f)
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(Main())
