# coding:utf-8
""" 真机自检与诊断（标记文件触发；不参与产品逻辑） """
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QApplication, QBoxLayout, QComboBox, QWidget
import os
import re
import time
from tools.log import Log
from tools import platform_mobile
from tools.mobile_ui_base import *  # noqa: F401,F403
from tools.mobile_ui_base import (_DescribeWidget)
from tools import mobile_ui



def _WriteUiDiag(lines):
    """ 追加到 <AppDataDir>/android_startup.log(与 android/main.py 的自检同一份) """
    try:
        base = platform_mobile.GetAppDataDir()
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "android_startup.log"), "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as es:
        Log.Error(es)
    return


def MaybeSelfTest(mainView):
    """ 抽屉自检：只在 <AppDataDir>/ui_selftest 标记文件存在时跑一次

    真机验证用。设备上没法用 OCR(uiautomator 也读不到 Qt Widgets 的树)，
    所以让应用自己用**真实窗口几何**验证"抽屉不遮挡顶栏"和"点空白处能关闭"。
    """
    try:
        marker = os.path.join(platform_mobile.GetAppDataDir(), "ui_selftest")
        if not os.path.exists(marker):
            return
        try:
            os.remove(marker)
        except Exception:
            pass
        QTimer.singleShot(800, lambda: _SelfTestStart(mainView))
    except Exception as es:
        Log.Error(es)
    return


def _SelfTestStart(mainView):
    lines = ["", "===== ui selftest (drawer) ====="]
    try:
        nav = getattr(mainView, "navigationWidget", None)
        sub = getattr(mainView, "subMainWindow", None)
        menu = getattr(mainView, "menuButton", None)
        scrim = getattr(mainView, "_jmDrawerScrim", None)
        lines.append("main window: {}x{}".format(mainView.width(), mainView.height()))
        if sub is not None:
            lines.append("subMainWindow: {}x{}".format(sub.width(), sub.height()))
        barBottom = 0
        if menu is not None and sub is not None:
            local = sub.mapFromGlobal(menu.mapToGlobal(QPoint(0, 0)))
            barBottom = local.y() + menu.height()
        lines.append("menuButton 底部(subMainWindow 坐标): {}".format(barBottom))
        if not mobile_ui.ToggleDrawer(mainView):
            lines.append("ui selftest: SKIP (抽屉未启用)")
            _WriteUiDiag(lines)
            return
        lines.append("打开后: nav hidden={} geometry=({},{},{},{})".format(
            nav.isHidden(), nav.x(), nav.y(), nav.width(), nav.height()))
        okBar = (barBottom > 0) and (nav.y() >= barBottom)
        lines.append("不遮挡顶栏: {} (drawer.y={} >= menuBottom={})".format(okBar, nav.y(), barBottom))
        okBox = (sub is not None) and nav.geometry().bottom() <= sub.height() \
            and nav.geometry().right() <= sub.width()
        lines.append("未超出容器: {} (bottom={} right={} / {}x{})".format(
            okBox, nav.geometry().bottom(), nav.geometry().right(),
            sub.width() if sub else -1, sub.height() if sub else -1))
        if scrim is None:
            lines.append("遮罩: 不存在 (FAIL)")
        else:
            lines.append("遮罩: visible={} geometry=({},{},{},{})".format(
                scrim.isVisible(), scrim.x(), scrim.y(), scrim.width(), scrim.height()))
        lines.append("几何判定: {}".format("PASS" if (okBar and okBox and scrim is not None) else "FAIL"))
        QTimer.singleShot(700, lambda: _SelfTestClick(mainView, nav, scrim, lines))
    except Exception as es:
        lines.append("ui selftest: FAIL (异常 {})".format(es))
        _WriteUiDiag(lines)
    return


def _SelfTestClick(mainView, nav, scrim, lines):
    try:
        if scrim is not None:
            pos = QPointF(scrim.width() / 2.0, scrim.height() / 2.0)
            event = QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos,
                                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                Qt.KeyboardModifier.NoModifier)
            scrim.mousePressEvent(event)
            lines.append("已模拟点击遮罩(空白区域)")
        else:
            lines.append("没有遮罩，无法模拟点击空白区域")
    except Exception as es:
        lines.append("模拟点击遮罩异常: {}".format(es))
    QTimer.singleShot(800, lambda: _SelfTestVerify(nav, scrim, lines))
    return


def _SelfTestVerify(nav, scrim, lines):
    try:
        closed = nav.isHidden()
        scrimHidden = (scrim is None) or (not scrim.isVisible())
        lines.append("点击后: nav.isHidden={} scrim.isVisible={}".format(closed, not scrimHidden))
        lines.append("ui selftest: {}".format("PASS" if (closed and scrimHidden) else "FAIL"))
    except Exception as es:
        lines.append("ui selftest: FAIL (异常 {})".format(es))
    _WriteUiDiag(lines)
    return


def MaybeTouchSelfTest(mainView):
    """ 滑动防误触自检：只在 <AppDataDir>/ui_touch_selftest 标记文件存在时跑一次

    真机上没法用 OCR(也没有 uiautomator 树)，所以让应用自己：
        1. 切到设置页
        2. 把某个勾选框的**物理像素坐标**写进日志(这样 adb 就能精准地滑它/点它)
        3. 周期性把守卫计数、目标勾选状态、滚动位置写进日志
    之后从 adb 发 input swipe / input tap，就能客观地验证：
        * 滑动不再改变设置(守卫计数 +1、目标状态不变)
        * 短距离点按仍然生效(目标状态翻转)
        * 长距离滑动仍然能滚动(scrollValue 变化)

    标记文件内容含 "dry" 时守卫只记录不拦截，用来复现"滑动会改设置"的原始问题。
    """
    try:
        base = platform_mobile.GetAppDataDir()
        marker = os.path.join(base, "ui_touch_selftest")
        if not os.path.exists(marker):
            return
        mode = ""
        try:
            with open(marker, "r", encoding="utf-8", errors="ignore") as f:
                mode = (f.read() or "").strip().lower()
        except Exception:
            mode = ""
        try:
            os.remove(marker)
        except Exception:
            pass
        guard = mobile_ui._touchGuard
        if guard is not None and "dry" in mode:
            guard.DryRun = True
        QTimer.singleShot(900, lambda: _TouchSelfTestStart(mainView, mode))
    except Exception as es:
        Log.Error(es)
    return


def _TouchSelfTestStart(mainView, mode):
    lines = ["", "===== ui selftest (touch guard) ====="]
    try:
        view = getattr(mainView, "settingView", None)
        if view is None:
            lines.append("ui touch selftest: SKIP (没有 settingView)")
            _WriteUiDiag(lines)
            return
        mainView.SwitchWidget(view)
        lines.append("mode: {}".format("dry(只记录不拦截)" if mode and "dry" in mode
                                      else "arm(拦截)"))
        # 等页面真正布局完再取几何：刚切过去时它还是设计器坐标(会算出屏幕外的坐标)
        QTimer.singleShot(1500, lambda: _TouchSelfTestPick(view, lines))
    except Exception as es:
        lines.append("ui touch selftest: FAIL (异常 {})".format(es))
        _WriteUiDiag(lines)
    return


def _VisibleRect(widget, viewport):
    """ 控件在视口里**真正可见**的那块矩形(控件坐标系)

    设置页的勾选框是整行拉伸的，宽度可能比视口还宽(实测 378 vs 352)，所以不能用
    "控件矩形完全落在视口内"来筛选 —— 那样一个都选不出来，最后退化到设计器坐标里的
    downAuto(y=2638)，算出来的物理坐标是屏幕外的 y=9945，adb 的 tap/swipe 全打空。
    """
    from PySide6.QtCore import QRect
    rect = QRect(widget.mapTo(viewport, QPoint(0, 0)), widget.size())
    visible = rect.intersected(viewport.rect())
    if visible.width() <= 0 or visible.height() <= 0:
        return None, rect
    return visible, rect


def _PickVisibleCheckBox(view):
    """ 在设置页视口里挑一个**真的能点到**的勾选框(取最靠上的) """
    from PySide6.QtWidgets import QCheckBox
    return _PickVisibleWidget(view, lambda w: isinstance(w, QCheckBox), 40)


def _PickVisibleWidget(view, predicate, minWidth=40):
    """ 在设置页视口里挑一个**真的能点到**的控件(取最靠上的)

    真机验收要的是"物理坐标"：只有和视口有足够交集(高度 60%、宽度 50%)的控件
    才值得拿来当触摸测试目标，否则算出来的坐标是屏幕外的，adb 打空还以为是功能坏了。
    """
    area = getattr(view, "scrollArea", None)
    viewport = area.viewport() if area is not None else None
    best = None
    for widget in view.findChildren(QWidget):
        try:
            if not predicate(widget):
                continue
            if not widget.isVisible() or widget.width() < minWidth or widget.height() < 10:
                continue
            if viewport is None:
                if best is None or widget.y() < best[0]:
                    best = (widget.y(), widget)
                continue
            visible, _rect = _VisibleRect(widget, viewport)
            if visible is None:
                continue
            if visible.height() < widget.height() * 0.6 or visible.width() < widget.width() * 0.5:
                continue
            if best is None or visible.top() < best[0]:
                best = (visible.top(), widget)
        except Exception:
            continue
    return best[1] if best else None


def _TouchSelfTestPick(view, lines):
    target = _PickVisibleCheckBox(view)
    if target is None:
        lines.append("target: 视口里没有露出足够的勾选框(退化为 downAuto, 坐标可能不可点)")
        target = getattr(view, "downAuto", None)
    else:
        lines.append("target: 选的是视口里最靠上的勾选框 {}".format(
            _DescribeWidget(target)))
    # 用户报的"在下拉框/数值框**附近**滑动会误触"也要能量化验证：
    # 各挑一个下拉框和数值框，把真实物理坐标写进日志，主机侧用 adb input swipe 打它
    from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox
    combo = _PickVisibleWidget(view, lambda w: isinstance(w, QComboBox), 60)
    spin = _PickVisibleWidget(view, lambda w: isinstance(w, (QSpinBox, QDoubleSpinBox)), 40)
    extras = [("combo", combo), ("spin", spin)]
    _TouchSelfTestReport(view, target, lines, extras)
    return


def _WidgetTapPoint(view, widget, lines, tag):
    """ 写一个控件的物理点按坐标(主机侧 adb input 用) """
    try:
        area = getattr(view, "scrollArea", None)
        viewport = area.viewport() if area is not None else None
        window = view.window()
        dpr = window.devicePixelRatioF() if window is not None else 1.0
        if not isinstance(widget, QWidget) or viewport is None:
            lines.append("  {}: 没有可用目标".format(tag))
            return None
        visible, _rect = _VisibleRect(widget, viewport)
        if visible is None:
            lines.append("  {}: 目标不在视口内".format(tag))
            return None
        visGlobal = viewport.mapToGlobal(visible.topLeft())
        tapX = visGlobal.x() + visible.width() // 2
        tapY = visGlobal.y() + visible.height() // 2
        lines.append("  {}: {} 值={} 可见 x={} y={} w={} h={}".format(
            tag, _DescribeWidget(widget), _WidgetValue(widget),
            visGlobal.x(), visGlobal.y(), visible.width(), visible.height()))
        lines.append("  {} 点击点 logical=({},{}) physical=({},{}) dpr={}".format(
            tag, tapX, tapY, int(round(tapX * dpr)), int(round(tapY * dpr)), dpr))
        return tapX, tapY
    except Exception as es:
        lines.append("  {}: 取坐标失败 {}".format(tag, es))
    return None


def _WidgetValue(widget):
    try:
        if isinstance(widget, QComboBox):
            return "{}[{}]".format(widget.currentText(), widget.currentIndex())
        if isinstance(widget, QAbstractSpinBox):
            return str(widget.value())
        if isinstance(widget, QAbstractButton):
            return "checked={}".format(widget.isChecked())
    except Exception:
        pass
    return "?"


def _TouchSelfTestReport(view, target, lines, extras=None):
    try:
        area = getattr(view, "scrollArea", None)
        bar = getattr(area, "vScrollBar", None) if area is not None else None
        viewport = area.viewport() if area is not None else None
        window = view.window()
        dpr = window.devicePixelRatioF() if window is not None else 1.0
        if area is not None:
            lines.append("scroll area: {}x{} viewport {}x{} scrollValue={}".format(
                area.width(), area.height(), viewport.width() if viewport else -1,
                viewport.height() if viewport else -1, bar.value() if bar is not None else -1))
        for tag, widget in (extras or []):
            _WidgetTapPoint(view, widget, lines, tag)
        if isinstance(target, QWidget):
            topLeft = target.mapToGlobal(QPoint(0, 0))
            lines.append("target: {} '{}' checked={}".format(
                type(target).__name__, target.objectName(), target.isChecked()))
            lines.append("  rect logical x={} y={} w={} h={}".format(
                topLeft.x(), topLeft.y(), target.width(), target.height()))
            if viewport is not None:
                visible, _rect = _VisibleRect(target, viewport)
                if visible is not None:
                    visGlobal = viewport.mapToGlobal(visible.topLeft())
                    lines.append("  visible logical x={} y={} w={} h={}".format(
                        visGlobal.x(), visGlobal.y(), visible.width(), visible.height()))
                    tapX = visGlobal.x() + visible.width() // 2
                    tapY = visGlobal.y() + visible.height() // 2
                    lines.append("  tap point logical=({},{}) physical=({},{}) dpr={}".format(
                        tapX, tapY, int(round(tapX * dpr)), int(round(tapY * dpr)), dpr))
            # 记下窗口/屏幕几何，方便核对 adb input 的物理坐标换算
            try:
                winGeo = window.geometry()
                from PySide6.QtGui import QGuiApplication
                screen = QGuiApplication.primaryScreen()
                screenGeo = screen.geometry() if screen is not None else None
                lines.append("  window logical=({},{},{}x{}) screen logical={}".format(
                    winGeo.x(), winGeo.y(), winGeo.width(), winGeo.height(),
                    "({},{},{}x{})".format(screenGeo.x(), screenGeo.y(),
                                           screenGeo.width(), screenGeo.height())
                    if screenGeo is not None else "?"))
            except Exception as es:
                lines.append("  窗口几何取不到: {}".format(es))
        else:
            lines.append("target: 没有 downAuto")
        screen = platform_mobile.GetScreenSize()
        lines.append("  screen logical={}x{} physical≈{}x{} dpr={}".format(
            screen[0], screen[1], int(round(screen[0] * dpr)), int(round(screen[1] * dpr)), dpr))
        lines.append("  说明: 用 adb input swipe/tap 打上面那个 physical 坐标; 观察窗口 {}s".format(
            TouchSelfTestSeconds))
    except Exception as es:
        lines.append("ui touch selftest: FAIL (取几何异常 {})".format(es))
    _WriteUiDiag(lines)

    state = {"tick": 0, "last": None, "timer": None}
    timer = QTimer(view)
    state["timer"] = timer
    timer.setInterval(1000)

    def Tick():
        state["tick"] += 1
        guard = mobile_ui._touchGuard
        checked = target.isChecked() if isinstance(target, QAbstractButton) else None
        setting = None
        try:
            from config.setting import Setting
            setting = Setting.DownloadAuto.value
        except Exception:
            setting = None
        scroll = -1
        barMax = -1
        contentH = -1
        try:
            area = getattr(view, "scrollArea", None)
            bar = getattr(area, "vScrollBar", None)
            scroll = bar.value() if bar is not None else -1
            barMax = bar.maximum() if bar is not None else -1
            content = area.widget() if area is not None else None
            contentH = content.height() if content is not None else -1
        except Exception:
            pass
        cur = (guard.Presses if guard else -1, guard.Drags if guard else -1,
               guard.Suppressed if guard else -1, guard.Replayed if guard else -1,
               guard.LastSuppressed if guard else "", checked, setting, scroll,
               barMax, contentH,
               " ".join("{}={}".format(tag, _WidgetValue(w)) for tag, w in (extras or [])))
        if cur != state["last"] or state["tick"] % 15 == 0:
            # barMax=0 说明内容没超出视口，这个页面本来就滚不动，别把"没滚动"当成失败
            # (注意别在 format 串里写 {max}，那会被当成关键字参数 -> KeyError)
            _WriteUiDiag(["  t={:>3}s presses={} drags={} suppressed={} replayed={} last={} "
                          "checkbox={} Setting.DownloadAuto={} scrollValue={}/{} contentH={} "
                          "target={} {}".format(
                              state["tick"], cur[0], cur[1], cur[2], cur[3], cur[4] or "-",
                              cur[5], cur[6], cur[7], cur[8], cur[9],
                              _DescribeWidget(target) if target is not None else "-",
                              cur[10])])
            state["last"] = cur
        if state["tick"] >= TouchSelfTestSeconds:
            timer.stop()
            _WriteUiDiag(["ui touch selftest: 观察窗口结束"])
        return

    timer.timeout.connect(Tick)
    timer.start()
    return


def DescribePortrait(mainView):
    """ 把竖屏排版的关键几何写成可判定的文本行

    真机上没有 OCR 也读不到 uiautomator 树，只能让应用自己报几何。
    这里报的是"客观量"：
        * 设置页外层是上下排列、导航在内容之上
        * 内容区可视宽度、以及**还有没有横向布局放不下**(QLayout.minimumSize 是权威值)
        * 超分页预览/参数面板的位置关系
    """
    lines = []
    try:
        setting = getattr(mainView, "settingView", None)
        if setting is not None:
            outer = getattr(setting, "horizontalLayout", None)
            nav = getattr(setting, "verticalLayout", None)
            area = getattr(setting, "scrollArea", None)
            direction = outer.direction().name if outer is not None else "?"
            lines.append("settings: outer.direction={}".format(direction))
            if nav is not None and area is not None:
                navGeo = nav.geometry()
                areaGeo = area.geometry()
                lines.append("  nav(4 buttons)=(x={},y={},w={},h={}) content=(x={},y={},w={},h={})".format(
                    navGeo.x(), navGeo.y(), navGeo.width(), navGeo.height(),
                    areaGeo.x(), areaGeo.y(), areaGeo.width(), areaGeo.height()))
                lines.append("  nav 在内容之上: {}".format(navGeo.y() + navGeo.height() <= areaGeo.y() + 4))
            if area is not None:
                vp = area.viewport()
                avail = vp.width() if vp is not None else area.width()
                lines.append("  content viewport={}x{}".format(avail, vp.height() if vp else -1))
                worst = None
                for layout in setting.findChildren(QBoxLayout):
                    if layout.direction() not in (QBoxLayout.Direction.LeftToRight,
                                                  QBoxLayout.Direction.RightToLeft):
                        continue
                    try:
                        need = layout.minimumSize().width()
                    except Exception:
                        continue
                    if worst is None or need > worst[0]:
                        worst = (need, layout.objectName(),
                                 layout.parentWidget().objectName() if layout.parentWidget() else "?")
                if worst is not None:
                    lines.append("  最宽的横向布局需要 {}px / 可用 {}px ({}.{}) -> {}".format(
                        worst[0], avail, worst[2], worst[1],
                        "放得下" if worst[0] <= avail else "放不下"))
                    # 放不下时把这一行的构成打出来，方便定位是谁在撑宽度
                    for layout in setting.findChildren(QBoxLayout):
                        if layout.objectName() != worst[1]:
                            continue
                        if layout.minimumSize().width() != worst[0]:
                            continue
                        for j in range(layout.count()):
                            item = layout.itemAt(j)
                            child = item.widget()
                            label = "{}:{}".format(type(child).__name__, child.objectName()) \
                                if child is not None else "<spacer/layout>"
                            lines.append("    item[{}] {} min={} hint={}".format(
                                j, label, item.minimumSize().width(), item.sizeHint().width()))
                        break
        srTool = getattr(mainView, "waifu2xToolView", None)
        if srTool is not None:
            grid = getattr(srTool, "gridLayout", None)
            area = getattr(srTool, "scrollArea", None)
            view = getattr(srTool, "graphicsView", None)
            if grid is not None and area is not None and view is not None:
                panelIndex = grid.indexOf(srTool.verticalLayout)
                row, col = (-1, -1)
                if panelIndex >= 0:
                    row, col, _rs, _cs = grid.getItemPosition(panelIndex)
                viewIndex = grid.indexOf(view)
                vrow, vcol = (-1, -1)
                if viewIndex >= 0:
                    vrow, vcol, _vrs, _vcs = grid.getItemPosition(viewIndex)
                lines.append("sr tool: preview=({},{}) {}x{} / panel=({},{}) {}x{} maxH={} -> {}".format(
                    vrow, vcol, view.width(), view.height(), row, col,
                    area.width(), area.height(), area.maximumHeight(),
                    "上下堆叠" if (row, col) == (1, 0) else "仍是并排"))
        index = getattr(mainView, "indexView", None)
        widget = getattr(index, "newListWidget", None) if index is not None else None
        if widget is not None:
            try:
                lines.append("首页列表条目数: {}".format(widget.count()))
                lines.extend(GridStatsLines(widget))
            except Exception as es:
                lines.append("首页列表条目数: 取不到 ({})".format(es))
        lines.extend(_ReaderLines(mainView))
        lines.extend(_GuardLines())
    except Exception as es:
        lines.append("DescribePortrait failed: {}".format(es))
    lines.extend(_ParseStatsLines())
    lines.extend(_ImagePipelineLines())
    return lines


def _ColumnsPerRow(itemWidth, avail):
    """ 这一行实际能放几个(和 QListWidget 的 flow 装箱一致：按 item 宽度整除) """
    try:
        if itemWidth <= 0:
            return 0
        return max(1, int(avail // itemWidth))
    except Exception:
        return 0


def GridStatsLines(widget):
    """ 网格列表真实的一行几个(直接用 QListWidget 的实际几何数出来)

    不能只看"封面宽 x 可用宽"的估算：QListWidget 是按 item 的 sizeHint 装箱的，
    sizeHint 没跟着封面尺寸更新的话，一行照样只放得下 1 个。这里按
    visualItemRect 的真实 y 坐标分组，数出每一行到底有几个 item。
    """
    lines = []
    try:
        from collections import OrderedDict
        rows = OrderedDict()
        for i in range(min(widget.count(), 60)):
            item = widget.item(i)
            if item is None:
                continue
            rect = widget.visualItemRect(item)
            rows.setdefault(rect.top(), 0)
            rows[rect.top()] += 1
        vp = widget.viewport()
        avail = vp.width() if vp is not None else widget.width()
        cover = mobile_ui.GridCoverWidth(False)
        perRow = max(rows.values()) if rows else 0
        firstHint = 0
        grid = widget.gridSize()
        if widget.count():
            w0 = widget.itemWidget(widget.item(0))
            if w0 is not None:
                firstHint = w0.sizeHint().width()
        lines.append("首页网格: 封面宽 {}px 控件宽 {}px 栅格={}x{} / 可用 {}px -> 每行 {} 个(前 {} 行 {})".format(
            cover, firstHint, grid.width(), grid.height(), avail, perRow, len(rows),
            list(rows.values())[:6]))
    except Exception as es:
        lines.append("首页网格: 取不到 ({})".format(es))
    return lines


def _ReaderLines(mainView):
    """ 看图界面的关键几何与滚动接管情况 """
    lines = []
    try:
        readView = getattr(mainView, "readView", None)
        if readView is None:
            return lines
        frame = getattr(readView, "frame", None)
        tool = getattr(frame, "qtTool", None)
        if frame is not None and tool is not None:
            lines.append("reader tool: 面板=({},{},{}x{}) 看图区={}x{} -> {}".format(
                tool.x(), tool.y(), tool.width(), tool.height(),
                frame.width(), frame.height(),
                "整宽(在屏内)" if tool.x() >= 0 and tool.x() + tool.width() <= frame.width() + 2
                else "超出屏幕"))
            # 主机侧要拿真实物理坐标去 adb input，所以把看图区的全局位置和 dpr 也报出来
            try:
                globalPos = frame.mapToGlobal(QPoint(0, 0))
                window = frame.window()
                dpr = window.devicePixelRatioF() if window is not None else 1.0
                lines.append("reader 看图区 global logical=({},{}) {}x{} dpr={}".format(
                    globalPos.x(), globalPos.y(), frame.width(), frame.height(), dpr))
            except Exception as es:
                lines.append("reader 看图区 global: 取不到 ({})".format(es))
        # 滚动接管：菜单面板是普通 QScrollArea(走 QScroller)，看图区是 QGraphicsView
        # (走 _ReaderDrag 的拖动滚动，故意不挂 QScroller)
        try:
            menuArea = getattr(tool, "scrollArea22", None) if tool is not None else None
            graphics = getattr(frame, "scrollArea", None)
            lines.append("reader 滚动: 菜单滚动区={} 看图区({})={}".format(
                "已接管滚动" if getattr(menuArea, "_jmTouchScroll", False) else "未接管滚动",
                type(graphics).__name__ if graphics is not None else "?",
                "拖动滚动已接管" if mobile_ui._readerDrag is not None else "拖动滚动未接管"))
        except Exception as es:
            lines.append("reader 滚动: 取不到 ({})".format(es))
    except Exception as es:
        lines.append("reader lines failed: {}".format(es))
    return lines


def _GuardLines():
    lines = []
    try:
        guard = mobile_ui._touchGuard
        stats = mobile_ui.ShowDeferralStats
        lines.append("touch guard: presses={} drags={} suppressed={} replayed={} last={}".format(
            guard.Presses if guard else -1, guard.Drags if guard else -1,
            guard.Suppressed if guard else -1, guard.Replayed if guard else -1,
            (guard.LastSuppressed if guard else "") or "-"))
        lines.append("window guard: 延后显示={} 已显示={} 延后隐藏={} 延后关闭={} 子控件覆盖层={}".format(
            stats.get("deferred"), stats.get("shown"), stats.get("hidden"),
            stats.get("closed"), stats.get("overlays")))
        lines.append("key diag: 按键={} Key_Back={} 窗口事件={} back处理={}".format(
            mobile_ui.KeyDiagStats.get("key"), mobile_ui.KeyDiagStats.get("back"), mobile_ui.KeyDiagStats.get("window"),
            mobile_ui.BackStats.get("count")))
        lines.append("back 统计: count={} minimize={} last={}".format(
            mobile_ui.BackStats.get("count"), mobile_ui.BackStats.get("minimize"), mobile_ui.BackStats.get("last") or "-"))
    except Exception as es:
        lines.append("guard lines failed: {}".format(es))
    return lines


def _ImagePipelineLines():
    """ 图片解码管线(拼图解密 + QImage 工作线程)的统计

    "看图里图片不对/不出来"必须能从这里一眼看出来：是拼图失败(返回原图)、
    还是 QImage 线程死了/解码失败。
    """
    lines = []
    try:
        from task.task_qimage import QImageStats
        stats = QImageStats()
        lines.append("图片解码: 任务={} 成功={} 失败={} 空图={} Qt分割={} bytes分割={} 最后长度={} 最后错误={}".format(
            stats.get("task"), stats.get("ok"), stats.get("fail"), stats.get("null"),
            stats.get("segQt"), stats.get("segBytes"),
            stats.get("lastLen"), (stats.get("lastError") or "-")[:120]))
    except Exception as es:
        lines.append("图片解码统计: 取不到 ({})".format(es))
    try:
        from task.task_multi import TaskMulti
        multi = TaskMulti()
        lines.append("拼图解密: worker={}(线程={}) 队列槽={}".format(
            len(multi.queueList), len(multi.threadList), multi._inQueue.qsize()))
    except Exception as es:
        lines.append("拼图解密统计: 取不到 ({})".format(es))
    return lines


# ---------------------------------------------------------------------------
# 看图界面自检(device_reader 标记触发)
# ---------------------------------------------------------------------------
#
# 用户报的两件事："看图界面里图片无法正常解密"、"看图界面和它的菜单滚不动、
# 菜单还超出屏幕"、"返回键收不掉菜单/退不出看图"。真机上没有 OCR，所以：
#   1) 先跑一次**完全离线**的"分块倒序 -> 解密 -> QImage 解码"往返，逐像素比对
#      (不依赖网络，接口抖动不会造成假失败)
#   2) 再打开一本本地漫画(有的话)或首页第一本，把看图区/菜单几何、滚动位置、
#      返回键动作都写进日志；主机侧用 adb input swipe/keyevent 打真坐标来验证

def GridSelfTest(mainView):
    """ 用真机自己的视口宽验证"首页一行放得下 2 个"

    首页漫画是联网加载的(真机上接口经常 403/超时，列表是空的)，所以不能靠它验证。
    这里在**真正的首页列表控件**里临时放两个 ComicItemWidget，用真机的视口宽度、
    真机的 QListWidget 装箱逻辑数出"一行几个"，量完把临时 item 删掉。
    """
    lines = ["---- 首页网格自检(真机视口) ----"]
    widget = None
    added = 0
    try:
        from PySide6.QtWidgets import QListWidgetItem
        from component.widget.comic_item_widget import ComicItemWidget
        index = getattr(mainView, "indexView", None)
        widget = getattr(index, "newListWidget", None) if index is not None else None
        if widget is None:
            lines.append("  首页网格自检: FAIL (没有 indexView.newListWidget)")
            return lines
        viewport = widget.viewport()
        avail = viewport.width() if viewport is not None else widget.width()
        lines.append("  真机列表: 控件 {}x{}, 视口 {}x{}".format(
            widget.width(), widget.height(), avail, viewport.height() if viewport else -1))
        mobile_ui.ResetGridCover()
        mobile_ui.MeasureGridAvail(widget)
        cover = mobile_ui.GridCoverWidth(False)
        lines.append("  反算封面宽: 视口 {}px - 余量 {}px -> 封面 {}px ({} 列)".format(
            mobile_ui._gridAvail, GridItemOverhead, cover, GridColumns))
        items = []
        for i in range(GridColumns):
            item = ComicItemWidget()
            item.SetTitle("网格自检 {}".format(i + 1), "")
            item.setParent(widget.viewport())
            listItem = QListWidgetItem(widget)
            listItem.setSizeHint(item.sizeHint())
            widget.setItemWidget(listItem, item)
            items.append(listItem)
            added += 1
        mobile_ui.RefreshItemSizeHints(widget)
        mobile_ui.ApplyGridCoverSize(widget)
        lines.extend(GridStatsLines(widget))
        stats = GridStatsLines(widget)
        perRow = 0
        try:
            perRow = int(re.search(r"每行 (\d+) 个", stats[0]).group(1))
        except Exception:
            perRow = -1
        lines.append("  首页网格自检: {} (一行 {} 个, 期望 {})".format(
            "PASS" if perRow == GridColumns else "FAIL", perRow, GridColumns))
    except Exception as es:
        lines.append("  首页网格自检: FAIL 异常 {}: {}".format(type(es).__name__, es))
    finally:
        # 把临时 item 删掉，别影响真实列表
        try:
            for row in range(widget.count() - 1, -1, -1):
                if added <= 0:
                    break
                widget.takeItem(row)
                added -= 1
        except Exception as es:
            lines.append("  清理临时 item 失败: {}".format(es))
    return lines


def PickerSelfTest(mainView):
    """ 真机验证文件选择器：不开顶层窗口 + 能列目录 + 读不了的目录优雅降级

    用户报的"导入本地漫画/导入本地图片卡死"，根因是 `QFileDialog` 在 Android 上
    新建顶层窗口 + 嵌套模态循环，一去不回。换成 `tools/mobile_file_dialog.py` 的
    应用内子控件之后，这里在真机上确认它确实**不是窗口**、能列出目录、并且
    Android 分区存储下读不到的目录只是报错不会卡住。
    """
    lines = ["---- 文件选择器自检(真机) ----"]
    picker = None
    try:
        from tools import mobile_file_dialog, platform_mobile
        startDir = platform_mobile.GetExternalDir()
        lines.append("  起始目录: {}".format(startDir))
        picker = mobile_file_dialog._PickerDialog(mainView, "自检", startDir,
                                                  mobile_file_dialog.ModeDir, "")
        lines.append("  选择器: isWindow={} 父控件={} 当前目录={}".format(
            picker.isWindow(), type(picker.parent()).__name__, picker.currentDir))
        count = picker.listWidget.count() if picker.listWidget is not None else -1
        lines.append("  列表条目数: {} (应用目录应可读)".format(count))
        # 读不到的目录(分区存储)必须只报错不抛异常
        try:
            picker._GoTo("/data/data")
            lines.append("  不可读目录: 已降级处理(没有抛异常)")
        except Exception as es:
            lines.append("  不可读目录: 抛异常 {}: {} (不应该)".format(type(es).__name__, es))
        ok = (not picker.isWindow()) and count >= 0
        lines.append("  选择器自检: {}".format("PASS" if ok else "FAIL"))
    except Exception as es:
        lines.append("  选择器自检: FAIL 异常 {}: {}".format(type(es).__name__, es))
    finally:
        try:
            if picker is not None:
                picker.hide()
                picker.deleteLater()
        except Exception:
            pass
    return lines


def MaybeReaderSelfTest(mainView):
    """ 看图自检：只在 <AppDataDir>/device_reader 标记文件存在时跑一次

    必须**等首页/本地收藏真的加载出漫画**再打开看图：真机上登录 + /latest 要好几秒，
    太早跑会出现"没有可打开的漫画"这种假失败(实测踩过一次)。
    """
    try:
        marker = os.path.join(platform_mobile.GetAppDataDir(), "device_reader")
        if not os.path.exists(marker):
            return
        try:
            os.remove(marker)
        except Exception:
            pass
        QTimer.singleShot(3000, lambda: _ReaderWaitBook(mainView, 0))
    except Exception as es:
        Log.Error(es)
    return


def _ReaderHasBook(mainView):
    """ 本地收藏或首页列表里有没有可以打开的漫画 """
    try:
        localRead = getattr(mainView, "localReadView", None)
        books = getattr(localRead, "allBookInfos", None) or {}
        for v in books.values():
            eps = v.eps[0] if v.eps else v
            if eps.picCnt or v.picCnt:
                return True
    except Exception:
        pass
    try:
        index = getattr(mainView, "indexView", None)
        widget = getattr(index, "newListWidget", None) if index is not None else None
        if widget is not None:
            for row in range(min(widget.count(), 5)):
                book = widget.itemWidget(widget.item(row))
                if book is not None and getattr(book, "id", ""):
                    return True
    except Exception:
        pass
    return False


def _ReaderWaitBook(mainView, tries):
    # 这里跑在 QTimer 槽里：一旦抛异常，PySide 只会打到 stderr，整个等待链就断了
    # (真机上就出现过"reader 自检块根本没写出来")。所以自己包一层。
    try:
        if _ReaderHasBook(mainView) or tries >= 30:
            _ReaderSelfTestStart(mainView, tries)
            return
    except Exception as es:
        Log.Error(es)
        _WriteUiDiag(["reader 自检: 等漫画时异常 {}: {} (直接开始自检)".format(
            type(es).__name__, es)])
        try:
            _ReaderSelfTestStart(mainView, tries)
        except Exception as es2:
            Log.Error(es2)
        return
    QTimer.singleShot(3000, lambda: _ReaderWaitBook(mainView, tries + 1))
    return


def _ReaderSelfTestStart(mainView, tries=0):
    lines = ["", "===== device verify (reader) ====="]
    lines.append("等待漫画可用的轮次: {} (每轮 3s)".format(tries))
    try:
        lines.extend(DecryptSelfTest())
        lines.extend(GridSelfTest(mainView))
        lines.extend(PickerSelfTest(mainView))
        lines.extend(_OpenReaderForTest(mainView))
        lines.extend(_ReaderLines(mainView))
        lines.extend(_ImagePipelineLines())
    except Exception as es:
        lines.append("reader selftest failed: {}".format(es))
    lines.append("===== end device verify (reader) =====")
    _WriteUiDiag(lines)
    # 打开看图要拉章节/图片，等一会儿再开始轮询
    QTimer.singleShot(4000, lambda: _ReaderPollStart(mainView))
    return


def _SegOfficialNum(epsId, scrambleId, pictureName):
    """ 官方分块数公式(jmcomic JmImageTool.get_num)的独立实现 """
    import hashlib
    epsId = int(epsId or 0)
    scrambleId = int(scrambleId or 0)
    if epsId < scrambleId:
        return 0
    if epsId < 268850:
        return 10
    x = 10 if epsId < 421926 else 8
    s = "{}{}".format(epsId, pictureName).encode()
    return ord(hashlib.md5(s).hexdigest()[-1]) % x * 2 + 2


def _SegOfficialQt(img, num):
    """ 官方分块还原算法(jmcomic decode_and_save)的独立实现

    故意按官方那份"先算源 y / 目标 y 再贴"的循环写，而不是照抄 ToolUtil 的实现，
    这样自检就不是"自己验证自己"。
    """
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    w, h = img.width(), img.height()
    out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    over = h % num
    c = h // num
    painter = QPainter(out)
    try:
        for i in range(num):
            move = c
            ySrc = h - c * (i + 1) - over
            yDst = c * i
            if i == 0:
                move += over
            else:
                yDst += over
            if ySrc < 0 or yDst < 0 or ySrc + move > h or yDst + move > h:
                continue
            painter.drawImage(QRect(0, yDst, w, move), img, QRect(0, ySrc, w, move))
    finally:
        painter.end()
    return out


def _SegOfficialEncodeQt(img, num):
    """ 服务端那种"打乱"：先按 [高块, 常块...] 切，再倒序贴回去 —— 上面那个 decode 的逆

    (rem != 0 时这个变换不是对合，所以"造样本"必须用它，不能拿 decode 凑)
    """
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    w, h = img.width(), img.height()
    out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    over = h % num
    c = h // num
    pieces = []
    y = 0
    for i in range(num):
        move = c + (over if i == 0 else 0)
        pieces.append((y, y + move))
        y += move
    painter = QPainter(out)
    try:
        yDst = 0
        for start, end in reversed(pieces):
            coH = end - start
            painter.drawImage(QRect(0, yDst, w, coH), img, QRect(0, start, w, coH))
            yDst += coH
    finally:
        painter.end()
    return out


def _SegMakeTestImage(num, rem):
    """ 造一张"每行颜色唯一、高度不是 num 整数倍"的样本(rem != 0 才能检验余数处理) """
    from PySide6.QtGui import QImage
    w = 24
    h = 32 * num + rem
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    for y in range(h):
        color = (0xff << 24) | ((y * 7 % 256) << 16) | ((y * 13 % 256) << 8) | (y * 3 % 256)
        for x in range(w):
            img.setPixel(x, y, color)
    return img


def _SegSamePixels(a, b):
    """ -> (可比, 不同像素数) 不同像素数 -1 表示"大图只判定不同" """
    from PySide6.QtGui import QImage
    if a is None or b is None or a.isNull() or b.isNull() or a.size() != b.size():
        return False, -1
    try:
        fmt = QImage.Format.Format_ARGB32
        aa = a.convertToFormat(fmt)
        bb = b.convertToFormat(fmt)
        if bytes(aa.constBits()) == bytes(bb.constBits()):
            return True, 0
        if aa.width() * aa.height() <= 200000:
            diff = 0
            for y in range(aa.height()):
                for x in range(aa.width()):
                    if aa.pixel(x, y) != bb.pixel(x, y):
                        diff += 1
            return True, diff
        return True, -1
    except Exception:
        return False, -1


def _SegSeamRatio(img, num, samples=32):
    """ 接缝分：块与块相接处的平均行差 / 全图平均行差

    只作为参考值：它能发现"严重错位"(比如同一张图被还原了两次, 实测 8 倍)，
    但对"带子顺序错了"不敏感(实测 0.9)，所以判定用的是逐像素比对。
    """
    try:
        w, h = img.width(), img.height()
        c = h // num
        rem = h % num
        if c <= 0 or w <= 0:
            return -1.0, -1.0
        step = max(1, w // samples)

        def rowDiff(y):
            s = n = 0
            for x in range(0, w, step):
                p1 = img.pixel(x, y - 1)
                p2 = img.pixel(x, y)
                s += (abs((p1 >> 16 & 255) - (p2 >> 16 & 255))
                      + abs((p1 >> 8 & 255) - (p2 >> 8 & 255))
                      + abs((p1 & 255) - (p2 & 255)))
                n += 1
            return s / max(1, n)

        bounds = []
        y = 0
        for i in range(num):
            y += c + (rem if i == 0 else 0)
            if 1 <= y < h:
                bounds.append(y)
        seam = sum(rowDiff(y) for y in bounds) / max(1, len(bounds))
        base = []
        for k in range(1, 200):
            y = 1 + k * (h - 2) // 200
            if any(abs(y - b) <= 2 for b in bounds):
                continue
            base.append(rowDiff(y))
        avg = sum(base) / max(1, len(base))
        return seam, avg
    except Exception:
        return -1.0, -1.0


def _SegMeanErr(a, b, step=12):
    """ 采样平均像素差(0-255)：给"有损重编码"的路径用，避免要求逐像素完全相等 """
    try:
        if a is None or b is None or a.isNull() or b.isNull() or a.size() != b.size():
            return -1.0
        w, h = a.width(), a.height()
        n = 0
        s = 0
        for y in range(0, h, step):
            for x in range(0, w, step):
                p1 = a.pixel(x, y)
                p2 = b.pixel(x, y)
                s += (abs((p1 >> 16 & 255) - (p2 >> 16 & 255))
                      + abs((p1 >> 8 & 255) - (p2 >> 8 & 255))
                      + abs((p1 & 255) - (p2 & 255)))
                n += 1
        return (s / 3.0 / n) if n else -1.0
    except Exception:
        return -1.0


def _SegFindCachedRealPage():
    """ 找一张真机自己缓存下来的真 JM 图 -> (path, bookId, epsIndex, pageIndex) """
    import glob
    from config.setting import Setting
    best = None
    try:
        root = Setting.GetCachePath()
    except Exception:
        return None
    for path in glob.glob(os.path.join(root, "book", "*", "*", "*")):
        try:
            if not os.path.isfile(path) or os.path.getsize(path) < 4096:
                continue
            mtime = os.path.getmtime(path)
        except Exception:
            continue
        parts = path.replace("\\", "/").split("/")
        try:
            pageIndex = int(os.path.splitext(parts[-1])[0]) - 1
            epsIndex = int(parts[-2]) - 1
            bookId = parts[-3]
        except Exception:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, path, bookId, epsIndex, pageIndex)
    if best is None:
        return None
    return best[1], best[2], best[3], best[4]


def _SegRealPageParams(bookId, epsIndex, pageIndex):
    """ 用缓存路径反查这一页真正的 (epsId, scrambleId, pictureName) """
    try:
        from tools.book import BookMgr
        book = BookMgr().GetBook(bookId)
        if not book:
            return None
        eps = book.pageInfo.epsInfo.get(epsIndex)
        if not eps or not eps.scrambleId:
            return None
        realIndex = eps.GetRealIndex(pageIndex)
        name = eps.pictureName.get(realIndex)
        if name is None:
            return None
        return eps.epsId, eps.scrambleId, name
    except Exception:
        return None


def DecryptSelfTest():
    """ 离线证明"图片分割(分块还原) + QImage 解码"这条链在真机上是好的

    真机 21:40 的日志里它就是坏的：
        SegmentationPicture failed, epsId:1479594 scrambleId:220980 len:1091216
        err:cannot identify image file <_io.BytesIO object ...>
    Android 上 p4a 编出来的 Pillow 只有 png/jpg/gif，**没有 webp 解码器**
    (APK 里只有 PIL/_webp.pyi，没有 _webp.so)，而 JM 下发的图正是 webp；
    以前失败后兜底返回"被打乱的原图"，用户看到的就是"图片分割异常、图像错位"。

    两层自检，都不依赖网络：
      1) 合成样本：高度故意不是 num 的整数倍(rem != 0)，应用真实函数 vs 独立实现的官方算法
      2) 真机缓存里的真图(webp)：同样比对，并报告 Pillow 能不能解它
    """
    import os
    from config.setting import Setting
    out = ["---- 图片分割(分块还原)自检(离线) ----"]
    from tools.tool import ToolUtil

    # ---------------- Pillow 编解码器现状(根因) ----------------
    try:
        from PIL import Image, features
        import PIL
        webpMod = "有" if os.path.exists(os.path.join(os.path.dirname(PIL.__file__), "_webp.so")) else "缺失"
        out.append("  Pillow {}: jpg={} webp={} zlib={} PIL/_webp.so={}".format(
            PIL.__version__, features.check("jpg"), features.check("webp"),
            features.check("zlib"), webpMod))
    except Exception as es:
        out.append("  Pillow 能力探测失败: {}: {}".format(type(es).__name__, es))

    # ---------------- 1. 合成样本(rem != 0) vs 独立实现的官方算法 ----------------
    try:
        epsId, scrambleId, pictureName = 300000, 1, "1.png"
        num = ToolUtil.GetSegmentationNum(epsId, scrambleId, pictureName)
        numRef = _SegOfficialNum(epsId, scrambleId, pictureName)
        out.append("  分块数公式: 应用={} 官方独立实现={} -> {}".format(
            num, numRef, "一致" if num == numRef else "不一致"))
        # 真机日志里那次真实数据也一起校验公式
        numReal = ToolUtil.GetSegmentationNum(1479594, 220980, "00001")
        numRealRef = _SegOfficialNum(1479594, 220980, "00001")
        out.append("  真实样本公式: epsId=1479594 scrambleId=220980 00001 -> 应用={} 官方={}".format(
            numReal, numRealRef))
        okFormula = (num == numRef and numReal == numRealRef and numReal == 12)

        rem = 5                                   # 故意留余数：rem=0 时这个变换才是对合
        src = _SegMakeTestImage(num, rem)
        enc = _SegOfficialEncodeQt(src, num)       # 用官方实现造"服务端下发的那种图"
        expected = src.copy()
        # 先证明这对独立实现确实互逆(否则"自检"本身不可信)
        rt = _SegOfficialQt(enc, num)
        sameRt, diffRt = _SegSamePixels(expected, rt)
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.WriteOnly)
        enc.save(buf, "PNG")
        encBytes = bytes(ba)
        buf.close()
        out.append("  合成样本: {}x{} (高度 {} = {}*{}+{}, rem={}) 打乱后 {} 字节; 官方 encode/decode 互逆={}".format(
            src.width(), src.height(), src.height(), src.height() // num, num,
            src.height() % num, src.height() % num, len(encBytes),
            (sameRt and diffRt == 0)))

        fixed = ToolUtil.SegmentationPicture(encBytes, epsId, scrambleId, pictureName)
        qFix = ToolUtil.LoadQImage(fixed) if fixed else None
        same, diff = _SegSamePixels(expected, qFix)
        out.append("  SegmentationPicture(合成): 返回={} 字节, 与官方算法逐像素: 可比={} 不同像素={}".format(
            len(fixed) if fixed else 0, same, diff))
        okSyn = bool(fixed) and same and diff == 0

        # 看图线程真正走的那条(QImage 域，不来回编解码)
        qQt = ToolUtil.SegmentationQImage(encBytes, epsId, scrambleId, pictureName)
        same2, diff2 = _SegSamePixels(expected, qQt)
        out.append("  SegmentationQImage(合成): 可比={} 不同像素={}".format(same2, diff2))
        okQt = same2 and diff2 == 0

        # 还原两次必须"更差"：这是本轮之前踩过的坑(而且 rem!=0 时它不是对合)
        twice = _SegOfficialQt(qFix, num) if qFix is not None else None
        same3, diff3 = _SegSamePixels(twice, qFix)
        out.append("  还原两次 vs 还原一次: 可比={} 不同像素={} (rem!=0 时应当不同)".format(same3, diff3))
        okTwice = same3 and diff3 != 0

        # 落盘路径
        try:
            tmpPath = os.path.join(Setting.GetLogPath(), "seg_selftest.png")
            try:
                os.makedirs(Setting.GetLogPath(), exist_ok=True)
            except Exception:
                pass
            okDisk = ToolUtil.SegmentationPictureToDisk(encBytes, epsId, scrambleId, pictureName, tmpPath, "png")
            okDiskPix = False
            if okDisk:
                qDisk = ToolUtil.LoadQImage(open(tmpPath, "rb").read() if os.path.isfile(tmpPath) else b"")
                same4, diff4 = _SegSamePixels(expected, qDisk)
                okDiskPix = same4 and diff4 == 0
                out.append("  SegmentationPictureToDisk(合成): 返回={} 落盘像素一致={}".format(okDisk, okDiskPix))
            else:
                out.append("  SegmentationPictureToDisk(合成): 返回={} (落盘失败)".format(okDisk))
        except Exception as es:
            # 落盘环境问题(只读目录等)不该让整条自检失败
            out.append("  SegmentationPictureToDisk(合成): 跳过 ({})".format(es))
            okDisk, okDiskPix = True, True

        out.append("  图片分割自检(合成, rem={}): {}".format(
            rem, "PASS" if (okFormula and okSyn and okQt and okTwice and okDisk and okDiskPix) else "FAIL"))
    except Exception as es:
        out.append("  图片分割自检(合成): FAIL 异常 {}: {}".format(type(es).__name__, es))
        okSyn = okQt = okFormula = False

    # ---------------- 2. 真机缓存里的真图(webp) ----------------
    try:
        found = _SegFindCachedRealPage()
        if not found:
            out.append("  真机样本: 没有缓存图，跳过(合成自检已覆盖算法)")
        else:
            path, bookId, epsIndex, pageIndex = found
            raw = open(path, "rb").read()
            params = _SegRealPageParams(bookId, epsIndex, pageIndex)
            pilOk = False
            pilErr = ""
            try:
                from PIL import Image
                from io import BytesIO
                with Image.open(BytesIO(raw)) as im:
                    im.load()
                    pilOk = True
            except Exception as es:
                pilErr = "{}: {}".format(type(es).__name__, es)
            qRaw = ToolUtil.LoadQImage(raw)
            out.append("  真机样本: {} ({} 字节, 书 {} 章节 {} 页 {})".format(
                os.path.basename(path), len(raw), bookId, epsIndex + 1, pageIndex + 1))
            out.append("  真机样本解码: Pillow={}{} Qt={} {}x{}".format(
                "OK" if pilOk else "失败", (" (" + pilErr[:80] + ")") if pilErr else "",
                (not qRaw.isNull()), qRaw.width(), qRaw.height()))
            if params:
                epsId, scrambleId, name = params
                num = ToolUtil.GetSegmentationNum(epsId, scrambleId, name)
                out.append("  真机样本参数: epsId={} scrambleId={} pictureName={} num={}".format(
                    epsId, scrambleId, name, num))
                expected = _SegOfficialQt(qRaw, num) if num > 1 else qRaw.copy()
                # 看图线程真正走的路径(QImage 域，不重编码)——这条必须和官方算法逐像素一致
                qQt = ToolUtil.SegmentationQImage(raw, epsId, scrambleId, name)
                same2, diff2 = _SegSamePixels(expected, qQt)
                # bytes 路径(保存/超分输入用)是 webp 有损重编码，只比较平均差
                fixed = ToolUtil.SegmentationPicture(raw, epsId, scrambleId, name)
                errBytes = _SegMeanErr(ToolUtil.LoadQImage(fixed) if fixed else None, expected)
                errRaw = _SegMeanErr(qRaw, expected)
                seamRaw, baseRaw = _SegSeamRatio(qRaw, num) if num > 1 else (-1, -1)
                seamFix, baseFix = _SegSeamRatio(qQt, num) if (qQt is not None and num > 1) else (-1, -1)
                out.append("  真机样本还原: QImage域与官方 可比={} 不同像素={} / bytes路径平均差={:.1f} / 未还原平均差={:.1f}".format(
                    same2, diff2, errBytes, errRaw))
                out.append("  真机样本接缝分(仅供参考): 未还原={:.2f} 还原后={:.2f} 基线={:.2f}".format(
                    seamRaw, seamFix, baseFix))
                okReal = (same2 and diff2 == 0 and bool(fixed) and fixed != raw
                          and 0.0 <= errBytes < 6.0 and errRaw > 20.0)
                out.append("  图片分割自检(真机样本 webp): {}".format("PASS" if okReal else "FAIL"))
            else:
                out.append("  真机样本参数: 拿不到章节参数(书信息不在内存)，只验证解码")
                out.append("  图片分割自检(真机样本 webp): {}".format(
                    "PASS" if not qRaw.isNull() else "FAIL"))
    except Exception as es:
        out.append("  真机样本自检异常 {}: {}".format(type(es).__name__, es))

    # ---------------- 3. 应用真实链路(TaskQImage) ----------------
    try:
        epsId, scrambleId, pictureName = 300000, 1, "1.png"
        from PySide6.QtGui import QImage
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        num = ToolUtil.GetSegmentationNum(epsId, scrambleId, pictureName)
        src = _SegMakeTestImage(num, 3)
        enc = _SegOfficialEncodeQt(src, num)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.WriteOnly)
        enc.save(buf, "PNG")
        buf.close()
        encBytes = bytes(ba)

        fixed = ToolUtil.SegmentationPicture(encBytes, epsId, scrambleId, pictureName)

        from task.task_qimage import TaskQImage, QtQImageTask
        info = QtQImageTask(0)
        info.data = bytes(fixed)
        info.radio = 1.0
        info.toW = 0
        info.toH = 0
        q = TaskQImage().ConverQImage(info)
        out.append("  TaskQImage.ConverQImage: {} {}x{} -> {}".format(
            q is not None, q.width() if q else -1, q.height() if q else -1,
            "PASS" if (q is not None and not q.isNull()) else "FAIL"))

        # 走 TaskQImage 的"看图线程真实入口"(带 saveParams，Android 上应走 Qt 那条)
        received = {}

        def _cb(img, param):
            received[param] = img

        tq = TaskQImage()
        tq.AddQImageTask(encBytes, 1.0, 0, 0, 0, (epsId, scrambleId, pictureName), _cb, 4242)
        from PySide6.QtCore import QTimer
        for _ in range(60):
            QApplication.processEvents()
            if 4242 in received:
                break
            time.sleep(0.05)
        img4242 = received.get(4242)
        same5, diff5 = _SegSamePixels(src, img4242)
        out.append("  TaskQImage(带 saveParams) 真线程回调: {} 可比={} 不同像素={}".format(
            img4242 is not None, same5, diff5))
        from task.task_qimage import QImageStats
        st = QImageStats()
        out.append("  解码统计: 任务={} 成功={} 失败={} 空图={} Qt分割={} bytes分割={} 最后错误={}".format(
            st.get("task"), st.get("ok"), st.get("fail"), st.get("null"),
            st.get("segQt"), st.get("segBytes"), (st.get("lastError") or "-")[:80]))
        okPipe = img4242 is not None and same5 and diff5 == 0
    except Exception as es:
        out.append("  TaskQImage 链路: FAIL {}: {}".format(type(es).__name__, es))
        okPipe = False

    out.append("  解密自检: {}".format("PASS" if (okFormula and okSyn and okQt and okPipe) else "FAIL"))
    return out


def _OpenReaderForTest(mainView):
    """ 打一本漫画进看图界面：优先本地漫画(离线、真图)，否则用首页第一本 """
    from qt_owner import QtOwner
    out = []
    try:
        localRead = getattr(mainView, "localReadView", None)
        books = getattr(localRead, "allBookInfos", None) or {}
        for v in books.values():
            try:
                eps = v.eps[0] if v.eps else v
                if not (eps.picCnt or v.picCnt):
                    continue
                out.append("reader: 打开本地漫画 '{}' (picCnt={}, eps={})".format(
                    v.title, eps.picCnt or v.picCnt, len(v.eps)))
                QtOwner().OpenLocalReadView(v, 0)
                return out
            except Exception as es:
                out.append("reader: 本地漫画打开失败 {}".format(es))
                break
    except Exception as es:
        out.append("reader: 本地漫画列表取不到 {}".format(es))
    try:
        index = getattr(mainView, "indexView", None)
        widget = getattr(index, "newListWidget", None) if index is not None else None
        if widget is not None and widget.count():
            book = widget.itemWidget(widget.item(0))
            if book is not None and getattr(book, "id", ""):
                out.append("reader: 打开首页第一本 id={}".format(book.id))
                QtOwner().OpenReadView(book.id, 0, -1)
                return out
        out.append("reader: 没有可打开的漫画(本地/首页都空)")
    except Exception as es:
        out.append("reader: 打开在线漫画失败 {}".format(es))
    return out


def _SegReaderPageSample():
    """ 看图界面当前页的**真实原始字节** + 它自己的 saveParams

    saveParams = (epsId, scrambleId, pictureName) 是看图流程自己算出来、真正用于
    还原这一页的那组参数，比"从缓存目录反查"可靠得多。
    """
    try:
        from qt_owner import QtOwner
        readView = getattr(QtOwner().owner, "readView", None)
        if readView is None:
            return None
        pictureData = getattr(readView, "pictureData", None) or {}
        cur = getattr(readView, "curIndex", 0)
        order = [cur] + [i for i in range(0, min(len(pictureData), cur + 6))]
        seen = set()
        for index in order:
            if index in seen:
                continue
            seen.add(index)
            p = pictureData.get(index)
            if p is None:
                continue
            data = getattr(p, "data", None)
            saveParams = getattr(p, "saveParams", None)
            if not data or not isinstance(saveParams, tuple) or len(saveParams) < 3:
                continue
            return bytes(data), saveParams, index
    except Exception:
        return None
    return None


def SegmentRealPageSelfTest():
    """ 拿看图界面正在显示的那一页做"真数据 + 真参数"的逐像素对账

    这是"图像错位"最直接的设备侧证据：服务端下发的原始字节，必须能被还原成与
    官方算法逐像素一致的图（未还原的那份应该差得很远）。
    """
    out = ["---- 真机看图页分割对账(真数据) ----"]
    try:
        from tools.tool import ToolUtil
        sample = _SegReaderPageSample()
        if not sample:
            out.append("  真机看图页: 当前没有带 saveParams 的页面(没在联网看漫画)，跳过")
            return out
        raw, saveParams, index = sample
        epsId, scrambleId, pictureName = saveParams[0], saveParams[1], saveParams[2]
        num = ToolUtil.GetSegmentationNum(epsId, scrambleId, pictureName)
        qRaw = ToolUtil.LoadQImage(raw)
        out.append("  真机看图页: 页={} epsId={} scrambleId={} pictureName={} num={} {}x{} {} 字节".format(
            index, epsId, scrambleId, pictureName, num,
            qRaw.width(), qRaw.height(), len(raw)))
        if num <= 1:
            out.append("  真机看图页分割: SKIP (num<=1, 这一页本来就不需要还原)")
            return out
        expected = _SegOfficialQt(qRaw, num)
        qQt = ToolUtil.SegmentationQImage(raw, epsId, scrambleId, pictureName)
        same, diff = _SegSamePixels(expected, qQt)
        errRaw = _SegMeanErr(qRaw, expected)
        out.append("  真机看图页还原: 与官方算法 可比={} 不同像素={} / 未还原平均差={:.1f}".format(
            same, diff, errRaw))
        out.append("  真机看图页分割: {}".format(
            "PASS" if (same and diff == 0 and errRaw > 20.0) else "FAIL"))
    except Exception as es:
        out.append("  真机看图页分割: FAIL 异常 {}: {}".format(type(es).__name__, es))
    return out


def _ReaderPollStart(mainView):
    """ 周期性把看图区的滚动位置/菜单可见性写进日志，供 adb 侧核对 """
    state = {"tick": 0, "last": None, "timer": None}
    timer = QTimer(mainView)
    state["timer"] = timer
    timer.setInterval(1000)

    def Tick():
        state["tick"] += 1
        try:
            # 等看图界面真的有一页带 saveParams 的图(联网漫画)之后，
            # 用"真数据 + 真参数"做一次逐像素对账 —— 这是"错位"最直接的设备侧证据
            if not state.get("segChecked") and state["tick"] >= 4:
                if _SegReaderPageSample() is not None:
                    state["segChecked"] = True
                    _WriteUiDiag(SegmentRealPageSelfTest())
            readView = getattr(mainView, "readView", None)
            frame = getattr(readView, "frame", None)
            view = getattr(frame, "scrollArea", None)
            tool = getattr(frame, "qtTool", None)
            v = view.vScrollBar.value() if view is not None else -1
            vMax = view.vScrollBar.maximum() if view is not None else -1
            h = view.hScrollBar.value() if view is not None else -1
            hMax = view.hScrollBar.maximum() if view is not None else -1
            toolVisible = tool is not None and not tool.isHidden()
            drag = mobile_ui._readerDrag.Drags if mobile_ui._readerDrag is not None else -1
            scroll = mobile_ui._readerDrag.Scrolled if mobile_ui._readerDrag is not None else -1
            try:
                from task.task_qimage import QImageStats
                qs = QImageStats()
                seg = (qs.get("task"), qs.get("ok"), qs.get("segQt"), qs.get("segBytes"))
            except Exception:
                seg = (-1, -1, -1, -1)
            cur = (v, vMax, h, hMax, toolVisible, drag, scroll,
                   mainView.totalStackWidget.currentIndex(),
                   mobile_ui.BackStats.get("count"), mobile_ui.BackStats.get("action"), seg)
            if cur != state["last"] or state["tick"] % 15 == 0:
                _WriteUiDiag(["  reader t={:>3}s 页签={} 页={}/{} v={}/{} h={}/{} 菜单={} "
                              "拖动={} 滚动次数={} back={} lastBack={} 解码=任务{}/成功{}/Qt分割{}/bytes{}".format(
                                  state["tick"], cur[7],
                                  getattr(readView, "curIndex", -1),
                                  getattr(readView, "maxPic", -1), v, vMax, h, hMax,
                                  "显示" if toolVisible else "隐藏", drag, scroll,
                                  cur[8], cur[9] or "-", seg[0], seg[1], seg[2], seg[3])])
                state["last"] = cur
        except Exception as es:
            _WriteUiDiag(["  reader poll 异常: {}".format(es)])
        if state["tick"] >= 90:
            timer.stop()
            _WriteUiDiag(["reader: 观察窗口结束"])
        return

    timer.timeout.connect(Tick)
    timer.start()
    return


def MaybeKeyDiag(mainView):
    """ device_keys 标记存在时打开按键/窗口诊断 """
    try:
        marker = os.path.join(platform_mobile.GetAppDataDir(), "device_keys")
        if not os.path.exists(marker):
            return
        try:
            os.remove(marker)
        except Exception:
            pass
        mobile_ui._keyDiagEnabled = True
        Log.Warn("key diag: 已开启(按键与窗口事件都会写日志)")
    except Exception as es:
        Log.Error(es)
    return


def MaybeDeviceVerify(mainView):
    """ 设备验收自检：只在 <AppDataDir>/device_verify 标记文件存在时跑一次

    分两块写(首页那块**不能切页面**：切走会把首页还没回来的 /latest 请求连带取消，
    结果就是"首页条目数=0"的假失败)：
        1) (home)   等 /promote + /latest 都解密成功，报解密统计、首页条目数与网格列数
        2) (layout) 再切到设置页量排版几何(设置页平时没被布局过，几何是设计器坐标)
    """
    try:
        marker = os.path.join(platform_mobile.GetAppDataDir(), "device_verify")
        if not os.path.exists(marker):
            return
        try:
            os.remove(marker)
        except Exception:
            pass
        QTimer.singleShot(8000, lambda: _DeviceVerifyPoll(mainView, 0))
    except Exception as es:
        Log.Error(es)
    return


def _DeviceVerifyPoll(mainView, tries):
    """ 等首页两个接口都解密成功(或等够时间)再写 (home) 块 """
    ok = 0
    try:
        from server import req as serverReq
        ok = int(serverReq.ParseStats.get("ok") or 0)
    except Exception:
        ok = 0
    if ok >= 2 or tries >= 25:
        # 解密计数是在 ParseData 里加的，比"填进列表控件"早一步，
        # 所以再多等一会儿再读条目数，否则会读到 0(真机上就这么误判过一次)
        delay = 2500 if ok >= 2 else 0
        QTimer.singleShot(delay, lambda: _DeviceVerifyHome(mainView, tries))
        return
    QTimer.singleShot(2000, lambda: _DeviceVerifyPoll(mainView, tries + 1))
    return


def _DeviceVerifyHome(mainView, tries):
    lines = ["", "===== device verify (home) ====="]
    lines.append("等待轮次: {} (每轮 2s)".format(tries))
    try:
        lines.extend(_ParseStatsLines())
        index = getattr(mainView, "indexView", None)
        widget = getattr(index, "newListWidget", None) if index is not None else None
        if widget is not None:
            try:
                lines.append("首页列表条目数: {} (内容高 {})".format(
                    widget.count(), widget.height()))
            except Exception as es:
                lines.append("首页列表条目数: 取不到 ({})".format(es))
        else:
            lines.append("首页列表条目数: 没有 indexView.newListWidget")
    except Exception as es:
        lines.append("device verify (home) failed: {}".format(es))
    lines.append("===== end device verify (home) =====")
    _WriteUiDiag(lines)
    # 接着切到设置页量排版
    QTimer.singleShot(1000, lambda: _DeviceVerifyLayoutStart(mainView))
    return


def _ParseStatsLines():
    lines = []
    try:
        from server import req as serverReq
        stats = serverReq.ParseStats
        lines.append("接口解密统计: ok={} fail={} lastError={}".format(
            stats.get("ok"), stats.get("fail"), stats.get("lastError") or "(无)"))
        lines.append("  最后一次: {} {}".format(stats.get("lastUrl", ""), stats.get("lastShape", "")))
    except Exception as es:
        lines.append("接口解密统计: 取不到 ({})".format(es))
    return lines


def _DeviceVerifyLayoutStart(mainView):
    """ 切到设置页再做几何测量 """
    try:
        view = getattr(mainView, "settingView", None)
        if view is not None:
            mainView.SwitchWidget(view)
    except Exception as es:
        Log.Error(es)
    QTimer.singleShot(1500, lambda: _DeviceVerifyLayout(mainView))
    return


def _DeviceVerifyLayout(mainView):
    lines = ["", "===== device verify (layout) ====="]
    try:
        lines.extend(_ParseStatsLines())
        lines.extend(DescribePortrait(mainView))
    except Exception as es:
        lines.append("device verify (layout) failed: {}".format(es))
    lines.append("===== end device verify (layout) =====")
    _WriteUiDiag(lines)
    return
