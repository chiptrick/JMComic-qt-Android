# coding:utf-8
""" 宿主自检：超分模型选择列表(三列 + 分组吸顶 + 可用性校验 + 当前使用高亮)

真机上这些问题只能靠肉眼：横向滚动条、列被藏、分组条吸顶时闪一下、当前选中项看不出、
以及"列出来的模型其实这台机器上没有"。它们在宿主上全是可量/可断言的状态关系：

  * 41 个静态模型 / 3 个算法分组 / 默认分组顺序
  * 模型列 == 完整原始 ID，可读写放在 tooltip
  * 340/360/412/480/673 五个宽度：列宽合计 == 视口、横向滚动条不可用、定宽列 56/66
  * 点表头「耗时」→ 平铺升序 → 降序 → 回分组（自定义模型恒排最后）
  * 分组条：吸顶 / 组自己露头时不重复绘制 / 交界处被顶上去
  * 点击行能选中（NoSelection 模式下必须自己接线，否则「确定」永远回旧值）
  * 可用性校验：只显示检测到的；引擎里有而静态表没有的 → 「自定义模型」组，
    显示文件名去后缀；探测不可信(没装引擎)时退回显示全部
  * 阅读页两段式(修改参数→保存)仍在

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
    from PySide6.QtCore import Qt  # noqa: E402
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


def UseProbe(smt, ok, names, customs=()):
    """ 替换探测结果（表在构造/Reload 时通过模块全局名调用 ProbeModels） """
    smt.ProbeModels = lambda: smt.Detected(ok, set(names), list(customs))


def Main():
    app = QApplication.instance() or QApplication(sys.argv)

    import component.widget.sr_model_table as smt
    from component.widget.sr_model_table import (SrModelTable, SrModels, Algorithms,
                                                 CustomGroup, FullModelName, ShowModelName,
                                                 FormatModelLabel)

    Current = "MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X"
    AllNames = [FullModelName(m) for m in SrModels]
    OriginalProbe = smt.ProbeModels

    # 默认：本机装了引擎、41 个模型全在
    UseProbe(smt, True, AllNames)
    table = SrModelTable()
    table.resize(460, 620)
    table.show()
    table.SetCurrentModel(Current)
    app.processEvents()

    print("[1] 数据 / 默认分组")
    Check(table.ModelCount() == 41, "41 个模型都在 (实际 {})".format(table.ModelCount()))
    Check(table.GroupCount() == 3, "3 个算法分组 (实际 {})".format(table.GroupCount()))
    Check(table.SortMode() == SrModelTable.SortGrouped, "进入页面默认按分组排序")
    Check(table._groupRows[0][1] == "Waifu2x", "第一组是 Waifu2x")
    Check(table._rowGroup[table._groupRows[0][0] + 1] == "Waifu2x", "分组行下面是本组模型")
    order = [r.algo for _, r in table._modelRows]
    Check(order == sorted(order, key=lambda a: Algorithms.index(a)), "分组内顺序与算法分段一致")

    print("[2] 模型 ID 完整显示")
    Check(all(table.item(r, 0).text() == rec.title for r, rec in table._modelRows),
          "模型列 == 完整模型 ID (如 ANIME_UP2X_DENOISE3X)")
    Check(all(not rec.title.startswith("MODEL_") for _, rec in table._modelRows),
          "不带 MODEL_ 前缀（前缀只是内部 key）")
    Check(all(table.item(r, 0).toolTip() == ShowModelName(SrModels[i])
              for i, (r, rec) in enumerate(table._modelRows)),
          "可读写法的 tooltip 与静态表一致")
    Check(table.item(table.RowOfModel(Current), 0).text() == "ANIME_UP2X_DENOISE3X",
          "当前模型显示为 ANIME_UP2X_DENOISE3X")
    Check(FormatModelLabel(Current) == "Waifu2x(anime) · 2× · 降噪 3",
          "入口按钮仍用可读短名 (实际 {})".format(FormatModelLabel(Current)))

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
    Check(table.columnWidth(1) == SrModelTable.CostWidth,
          "耗时列固定 {}px (实际 {})".format(SrModelTable.CostWidth, table.columnWidth(1)))
    Check(table.columnWidth(2) == SrModelTable.DescWidth,
          "描述列固定 {}px (实际 {})".format(SrModelTable.DescWidth, table.columnWidth(2)))

    print("[5] 长 ID 不被截断")
    for width in (480, 673):
        table.resize(width, 620)
        app.processEvents()
        metrics = QFontMetrics(table.item(table._modelRows[0][0], 0).font())
        widest = max(metrics.horizontalAdvance(rec.title) for _, rec in table._modelRows)
        longest = max((rec.title for _, rec in table._modelRows), key=len)
        Check(widest <= table.columnWidth(0) - 4,
              "宽 {}: 列宽 {} >= 最长 ID {}px ({})".format(
                  width, table.columnWidth(0), widest, longest))
    table.resize(340, 620)
    app.processEvents()
    Check(table.columnWidth(0) >= 200,
          "340 宽下列宽仍有 {}px（设备等宽字体下 21 字符约 168px）".format(table.columnWidth(0)))
    Check(table.textElideMode() == Qt.ElideRight, "再窄就右侧省略，不会撑破列")

    print("[6] 耗时表头排序")
    table.resize(460, 620)
    app.processEvents()
    Check(table.horizontalHeaderItem(1).text() == "耗时",
          "分组态表头没有多余字符 (实际 {!r})".format(table.horizontalHeaderItem(1).text()))
    table.OnHeaderClicked(1)
    app.processEvents()
    Check(table.SortMode() == SrModelTable.SortCostAsc, "点一次 → 平铺升序")
    Check(table.GroupCount() == 0, "平铺后没有分组行")
    costs = [rec.cost for _, rec in table._modelRows]
    Check(costs == sorted(costs), "升序真的按耗时排 (前 5: {})".format(costs[:5]))
    Check("↑" in table.horizontalHeaderItem(1).text(), "表头显示 ↑")
    table.OnHeaderClicked(1)
    app.processEvents()
    Check(table.SortMode() == SrModelTable.SortCostDesc, "点两次 → 降序")
    Check([r.cost for _, r in table._modelRows] == sorted(costs, reverse=True), "降序真的按耗时排")
    table.OnHeaderClicked(1)
    app.processEvents()
    Check(table.SortMode() == SrModelTable.SortGrouped, "点三次 → 回到分组")
    Check(table.GroupCount() == 3, "分组行回来了")

    print("[7] 分组条吸顶")
    groupRow = table._groupRows[0][0]
    ScrollToRow(table, groupRow + 4, app)
    Check(table.StickyGroup() == "Waifu2x", "滚到组中间：吸顶条是 Waifu2x (实际 {!r})".format(
        table.StickyGroup()))
    ScrollToRow(table, groupRow, app)
    Check(table.StickyGroup() == "", "分组行自己露在顶上时不重复绘制")
    ScrollToRow(table, table._groupRows[1][0] + 3, app)
    Check(table.StickyGroup() == table._groupRows[1][1], "滚到第二组中间：吸顶条跟着换")
    nextHeader = table._groupRows[1][0]
    ScrollToRow(table, nextHeader, app)
    bar = table.verticalScrollBar()
    bar.setValue(max(bar.minimum(), bar.value() - 10))
    app.processEvents()
    Check(table._StickyOffset() < 0,
          "下一组分组行进入吸顶区时，吸顶条上移 {}px".format(table._StickyOffset()))
    table.SetSortMode(SrModelTable.SortCostAsc)
    app.processEvents()
    Check(table.StickyGroup() == "", "平铺模式不画吸顶条")

    print("[8] 点击选中")
    table.SetSortMode(SrModelTable.SortGrouped)
    app.processEvents()
    target = FullModelName(SrModels[0])
    row = table.RowOfModel(target)
    table._OnCellClicked(row, 0)
    Check(table.SelectedModelName() == target,
          "点击行后 SelectedModelName 跟着变 (实际 {})".format(table.SelectedModelName()))
    groupRow = table._groupRows[0][0]
    table._OnCellClicked(groupRow, 0)
    Check(table.SelectedModelName() == target, "点分组行不会改选中")
    Check(table.RowOfModel(Current) >= 0, "换选之后当前使用行仍在")

    print("[9] 可用性校验")
    from view.setting.setting_sr_select_view import SettingSrSelectView
    keep = ["MODEL_WAIFU2X_CUNET_UP2X_DENOISE3X",
            "MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X",
            "MODEL_REALESRGAN_X4PLUS_UP4X"]
    custom = {"key": "MODEL_MY_SUPER_UP4X", "file": "my_super_4x.onnx",
              "title": "my_super_4x", "up": 4, "denoise": -1}
    UseProbe(smt, True, keep, [custom])
    filtered = SrModelTable()
    filtered.resize(460, 620)
    filtered.show()
    filtered.SetCurrentModel(Current)
    app.processEvents()
    Check(filtered.ModelCount() == 4,
          "只显示检测到的 3 个 + 1 个自定义 (实际 {})".format(filtered.ModelCount()))
    titles = [rec.title for _, rec in filtered._modelRows]
    Check(titles == ["CUNET_UP2X_DENOISE3X", "ANIME_UP2X_DENOISE3X",
                     "X4PLUS_UP4X", "my_super_4x"],
          "未检测到的模型没有出现 {}".format(titles))
    groups = [name for _, name, _ in filtered._groupRows]
    Check(groups == ["Waifu2x", "Real-ESRGAN", CustomGroup],
          "空组不显示，自定义模型单独成组 {}".format(groups))
    customRow = filtered.RowOfModel("MODEL_MY_SUPER_UP4X")
    Check(customRow >= 0, "自定义模型有自己的行")
    Check(filtered.item(customRow, 0).text() == "my_super_4x",
          "自定义模型显示文件名去后缀，不带 .onnx")
    Check(filtered.item(customRow, 1).text() == "—", "自定义模型没有耗时数据，显示 —")
    Check(filtered.RowOfModel("MODEL_REALESRGAN_X4PLUSANIME_UP4X") < 0,
          "没检测到的 X4PLUSANIME 确实不在列表里")
    smt._customTitles = None
    Check(FormatModelLabel("MODEL_MY_SUPER_UP4X") == "my_super_4x · 4×",
          "自定义模型选中后入口显示文件名，不露 MODEL_ 串 (实际 {})".format(
              FormatModelLabel("MODEL_MY_SUPER_UP4X")))

    UseProbe(smt, False, [])
    fallback = SrModelTable()
    fallback.resize(460, 620)
    fallback.show()
    fallback.SetCurrentModel(Current)
    app.processEvents()
    Check(fallback.ModelCount() == 41, "探测不可信时退回显示全部 41 个（不能空列表）")
    Check(fallback.DetectionOk() is False, "同时标记探测不可信，弹窗据此提示用户")
    fallbackView = SettingSrSelectView(None, Current)
    Check("未检测到" in fallbackView.label.text(),
          "弹窗顶部换成「未检测到引擎」的提示 (实际 {!r})".format(fallbackView.label.text()))

    UseProbe(smt, True, [])
    empty = SrModelTable()
    empty.resize(460, 620)
    empty.show()
    empty.SetCurrentModel(Current)
    app.processEvents()
    Check(empty.ModelCount() == 0, "一个都没检测到时不显示任何模型")
    Check(empty.item(0, 0) is not None and "未检测到" in empty.item(0, 0).text(),
          "给一行「未检测到可用的超分模型」提示")

    # 排序时自定义模型(无耗时)恒排最后
    UseProbe(smt, True, keep, [custom])
    sortedTable = SrModelTable()
    sortedTable.resize(460, 620)
    sortedTable.show()
    sortedTable.SetCurrentModel(Current)
    sortedTable.OnHeaderClicked(1)
    app.processEvents()
    lastAlgo = sortedTable._modelRows[-1][1].algo
    Check(lastAlgo == CustomGroup, "平铺升序时自定义模型排在最后 (实际 {})".format(lastAlgo))
    sortedTable.OnHeaderClicked(1)
    app.processEvents()
    Check(sortedTable._modelRows[-1][1].algo == CustomGroup, "降序也排在最后")

    print("[10] 弹窗接线")
    UseProbe(smt, True, AllNames)
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
    Check(narrow.widget.minimumWidth() == narrow.widget.width() == 464,
          "弹窗被 setFixedSize 钉在 {}px（布局不会把它压回 sizeHint）".format(narrow.widget.width()))
    Check(narrow.widget.height() == 660,
          "弹窗高度用满屏（880 高时取 {}px）".format(narrow.widget.height()))

    print("[11] 阅读页两段式仍在")
    readSrc = open(os.path.join(ROOT, "src", "view", "read", "read_tool.py"), encoding="utf-8").read()
    Check("def SetWaifu2xCancle(self, isVisibel=False)" in readSrc, "SetWaifu2xCancle 还在")
    Check("self.modelNameButton.setEnabled(isVisibel)" in readSrc, "锁/解锁仍由它控制")
    Check("FormatModelLabel(" in readSrc, "按钮文案走 FormatModelLabel")

    print("[12] 静态表自身一致性")
    import re
    pattern = re.compile(r"^MODEL_[A-Z0-9_]+$")
    Check(all(pattern.match(name) for name in AllNames),
          "每个模型名都符合 MODEL_[A-Z0-9_]+（拼接规则错一个就永远匹配不到引擎）")
    Check(len(set(AllNames)) == len(AllNames), "41 个名字没有重复")

    print("[13] 真实探测路径（假引擎 + 真文件系统）")
    import tempfile
    import shutil
    import tools.sr_backend as sr_backend

    # 前面 UseProbe() 把模块级 ProbeModels 换成了假函数，这里要测真实现
    smt.ProbeModels = OriginalProbe
    smt._customTitles = None

    class FakeEngine(object):
        """ 模仿 sr_qnn：MODEL_* 常量 + GetModelInfo(id) -> (file, scale, denoise, tile) """

        def __init__(self, entries, withInfo=True):
            self._infos = []
            for index, (name, info) in enumerate(entries):
                setattr(self, "MODEL_" + name, index)
                self._infos.append(info)
            if withInfo:
                self.GetModelInfo = self._GetModelInfo

        def _GetModelInfo(self, modelId):
            if isinstance(modelId, int) and 0 <= modelId < len(self._infos):
                return self._infos[modelId]
            return None

    modelDir = tempfile.mkdtemp(prefix="jm_sr_models_")
    oldDir = os.environ.get("JM_SR_MODELS")
    oldGet = sr_backend.GetSrModule
    try:
        os.environ["JM_SR_MODELS"] = modelDir
        for name in ("cunet.onnx", "my_custom.onnx"):
            open(os.path.join(modelDir, name), "wb").close()

        engine = FakeEngine([
            ("WAIFU2X_CUNET_UP2X_DENOISE3X", ("cunet.onnx", 2, 3, 192)),   # 文件在
            ("WAIFU2X_ANIME_UP2X_DENOISE3X", ("anime.onnx", 2, 3, 192)),   # 文件缺失
            ("MY_CUSTOM_UP4X", ("my_custom.onnx", 4, 1, 192)),             # 自定义
        ])
        sr_backend.GetSrModule = lambda: engine
        detected = smt.ProbeModels()
        Check(detected.ok, "引擎里有 MODEL_* 常量 → 探测可信")
        Check("MODEL_WAIFU2X_CUNET_UP2X_DENOISE3X" in detected.names, "文件存在的模型算可用")
        Check("MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X" not in detected.names,
              "models.txt 指向的文件不存在 → 不算可用")
        Check([c["key"] for c in detected.customs] == ["MODEL_MY_CUSTOM_UP4X"],
              "引擎里有、静态表没有 → 进自定义列表 {}".format(
                  [c["key"] for c in detected.customs]))
        Check(detected.customs[0]["title"] == "my_custom",
              "自定义模型名取文件名去后缀 (实际 {})".format(detected.customs[0]["title"]))
        Check(detected.customs[0]["up"] == 4 and detected.customs[0]["denoise"] == 1,
              "自定义模型的倍数/降噪从引擎读出来")

        # 桌面端：没有 GetModelInfo，常量在即认为可用
        os.environ.pop("JM_SR_MODELS", None)
        deskEngine = FakeEngine([("WAIFU2X_CUNET_UP2X_DENOISE3X", None),
                                 ("SOME_DESK_UP2X", None)], withInfo=False)
        sr_backend.GetSrModule = lambda: deskEngine
        desk = smt.ProbeModels()
        Check(desk.ok and "MODEL_WAIFU2X_CUNET_UP2X_DENOISE3X" in desk.names,
              "桌面端按 MODEL_* 常量判定可用")
        Check([c["title"] for c in desk.customs] == ["SOME_DESK_UP2X"],
              "桌面端自定义模型退回去掉 MODEL_ 前缀的名字")

        # 引擎缺失
        sr_backend.GetSrModule = lambda: None
        Check(smt.ProbeModels().ok is False, "没有引擎时 ok=False（调用方退回显示全部）")
    finally:
        sr_backend.GetSrModule = oldGet
        if oldDir is None:
            os.environ.pop("JM_SR_MODELS", None)
        else:
            os.environ["JM_SR_MODELS"] = oldDir
        shutil.rmtree(modelDir, ignore_errors=True)

    print("[14] 点选必须看得见（qss 会盖掉 item 背景 —— 真机「点哪行都没反应」的元凶）")
    # 必须套上真主题：主题里 QWidget/QTableView::item 的规则会让 QStyleSheetStyle 自己
    # 填面板背景，item.setBackground() 完全不生效。不加这一步的测试永远查不出这个 bug。
    app.setStyleSheet(open(os.path.join(ROOT, "res", "theme", "dark_orange.qss"),
                           encoding="utf-8").read())
    UseProbe(smt, True, AllNames)
    themed = SrModelTable()
    themed.resize(376, 660)
    themed.show()
    themed.SetCurrentModel(Current)
    app.processEvents()

    target2 = FullModelName(SrModels[0])
    targetRow = themed.RowOfModel(target2)
    themed.scrollToItem(themed.item(targetRow, 0), QAbstractItemView.PositionAtCenter)
    app.processEvents()
    rect = themed.visualRect(themed.model().index(targetRow, 0))
    before = themed.viewport().grab().toImage()
    themed.PickModel(target2)
    app.processEvents()
    after = themed.viewport().grab().toImage()
    diff = 0
    for x in range(rect.left() + 2, rect.right() - 2, 3):
        for y in range(rect.top() + 2, rect.bottom() - 2, 3):
            if before.pixel(x, y) != after.pixel(x, y):
                diff += 1
    Check(diff > 30, "点选后该行像素真的变了（{} 个采样点不同）".format(diff))
    Check(themed.item(targetRow, 2).text() == "已选",
          "描述列出现「已选」，和「当前使用」区分开 (实际 {!r})".format(
              themed.item(targetRow, 2).text()))
    Check(themed.SelectedModelName() == target2, "SelectedModelName 跟着变")

    # 真机点按是被 mobile_ui_touch 的路由认领的，它走 view.clicked.emit(index)
    other = FullModelName(SrModels[5])
    themed.clicked.emit(themed.model().index(themed.RowOfModel(other), 1))
    app.processEvents()
    Check(themed.SelectedModelName() == other,
          "触控路由 emit(clicked) 也能选中 (实际 {})".format(themed.SelectedModelName()))
    Check(themed.PickModel("Waifu2x(anime) · 2× · 降噪 3") is False,
          "列表外的名字（显示名/已失效模型）不会被当成选择结果写回设置")
    Check(themed.SelectedModelName() == other, "非法选择不改变已选")

    print("[15] 滚动重绘开销")
    import time
    bar = themed.verticalScrollBar()
    bar.setValue(bar.minimum())
    themed.viewport().repaint()
    frames = 30
    start = time.perf_counter()
    for _ in range(frames):
        bar.setValue(min(bar.value() + 4, bar.maximum()))
        themed.viewport().repaint()
    cost = (time.perf_counter() - start) / frames * 1000
    Check(cost < 12.0, "376x660 单帧重绘 {:.2f}ms（60fps 预算 16.6ms）".format(cost))

    print("[16] 手机端不给内容控件套阴影效果")
    from tools import platform_mobile
    oldAndroid = platform_mobile.IsAndroid
    platform_mobile.IsAndroid = lambda: True
    try:
        mobileView = SettingSrSelectView(None, Current)
        Check(mobileView.widget.graphicsEffect() is None,
              "没有 QGraphicsDropShadowEffect（它会把整窗逐帧渲染进 pixmap 再模糊）")
        Check(mobileView.tableWidget.AdoptTouchScroll() is True,
              "表格显示前就把手势接管好（不等手指按下去才补装）")
    finally:
        platform_mobile.IsAndroid = oldAndroid
    app.setStyleSheet("")

    print("[17] 反复开关不堆积弹窗")
    # 每次打开都是 new 一个（QtOwner.OpenSrSelectModel），父窗口是主窗口：
    # 不销毁就会一直挂着整张 40+ 行的表，反复开关几次后越用越钝
    import gc
    host = QWidget()
    host.resize(400, 800)
    host.show()
    for _ in range(4):
        opened = SettingSrSelectView(host, Current)
        opened.show()
        app.processEvents()
        opened.close()
        app.processEvents()
    gc.collect()
    Check(len(host.findChildren(SettingSrSelectView)) == 0,
          "关掉的弹窗被回收（父窗口里不再残留 {} 个）".format(
              len(host.findChildren(SettingSrSelectView))))

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
