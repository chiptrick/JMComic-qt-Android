# coding:utf-8
""" 输入框候选列表图层（搜索记录 / 提示词候选）

两个输入框组件(`SearchLineEdit`、`TipLineEdit`)原来各自写了一份"输入框下方弹一个
Qt.ToolTip 独立窗口"的实现，三处问题一模一样：

    1. **Android 上点不动**：Qt.ToolTip 是**第二个顶层窗口**，平台侧不激活、不接收
       触摸事件 —— 手指落在列表上，事件其实给了下面那个窗口，`clicked` 永远不发。
       本项目里"第二个顶层窗口"还有 eglSurface 死锁 abort 的历史
       (见 mobile_ui_window.MakeChildOverlay)，所以手机端统一改成**主窗口里的子控件**。
    2. **宽度溢出**：`resize(max(500, self.width()), ...)` 把下限写死 500px，
       而竖屏逻辑宽只有 480(小屏 360~412) —— 右侧直接被切掉。
    3. **位置/高度没用屏幕夹紧**：高度恒为窗口一半，与条目数无关。

现在两端共用这一套几何：优先"和输入框同宽、贴着它下方、夹在宿主窗口内"，
桌面端保留原来的浮层窗口(窗口小的场景也不再多出屏幕)。
"""
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

from tools.log import Log


# 弹层最小宽度/最小高度(逻辑像素)
PopupMinWidth = 200
PopupMinHeight = 96
# 列表里预估的行高(取不到真实 sizeHintForRow 时用)
PopupRowHeight = 44
# 标题("搜索记录")+边距占掉的高度
PopupChromeHeight = 40


def _IsAndroid():
    try:
        from tools import platform_mobile
        return platform_mobile.IsAndroid()
    except Exception:
        return False


class _OutsideHider(QObject):
    """ 手指/鼠标点到弹层和输入框以外时收起弹层

    子控件图层不会抢焦点，所以原来的 `focusOutEvent -> hide()` 在手机上不再触发
    (触摸不经过焦点系统)，必须自己判"点的是谁"。
    """

    def __init__(self, edit, widget, parent=None):
        super().__init__(parent)
        self.edit = edit
        self.widget = widget

    def eventFilter(self, obj, event):
        try:
            if event.type() not in (QEvent.Type.TouchBegin, QEvent.Type.MouseButtonPress):
                return False
            if not isinstance(obj, QWidget):
                return False
            if not self.widget.isVisible():
                return False
            if obj is self.edit or obj is self.widget or self.widget.isAncestorOf(obj):
                return False
            hide = getattr(self.edit, "HideListView", None)
            if callable(hide):
                hide()
        except Exception:
            pass
        return False


def Install(edit, widget, listView):
    """ 把候选列表图层装到输入框上；返回状态字典(存在 edit._jmPopup) """
    mobile = _IsAndroid()
    state = {"widget": widget, "listView": listView, "mobile": mobile, "filter": None}
    try:
        if mobile:
            # 子控件图层：不再是顶层窗口(见模块头)。objectName+样式表给一个边框，
            # 否则浮在页面上分不清边界(桌面端 ToolTip 窗口自带阴影/边框)
            widget.setWindowFlags(Qt.Widget)
            widget.setObjectName("jmPopupList")
            widget.setAttribute(Qt.WA_StyledBackground, True)
            widget.setStyleSheet("QWidget#jmPopupList{border:1px solid palette(mid);}")
            widget.hide()
            listView.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            listView.setTextElideMode(Qt.ElideRight)
            listView.setUniformItemSizes(True)
            # 逐像素 + QScroller：列表才能 1:1 跟手滚动，也才会被触控路由当成
            # "已接管的滚动区域"来认领点按(见 mobile_ui_touch._InTouchArea)
            from tools import mobile_ui
            mobile_ui.MakeScrollable(listView)
            app = QApplication.instance()
            if app is not None:
                state["filter"] = _OutsideHider(edit, widget, app)
                app.installEventFilter(state["filter"])
        else:
            widget.setParent(edit, Qt.Popup)
            widget.setFocusProxy(edit)
            widget.setWindowFlags(Qt.ToolTip)
    except Exception as es:
        Log.Error(es)
    edit._jmPopup = state
    return state


def _HostWidth(widget):
    try:
        window = widget.window()
        if window is not None:
            return max(1, window.width())
    except Exception:
        pass
    return 0


def Show(edit):
    """ 在输入框下方显示候选列表(几何全部夹在宿主范围内) """
    state = getattr(edit, "_jmPopup", None)
    if state is None:
        return False
    widget = state["widget"]
    listView = state["listView"]
    if widget is None or not widget.isHidden():
        return False
    try:
        rows = 0
        model = listView.model()
        if model is not None:
            rows = model.rowCount()
        if state["mobile"]:
            host = edit.window()
            if host is None:
                return False
            if widget.parentWidget() is not host:
                widget.setParent(host)
            # 贴着输入框下方；x 夹在窗口内(原来直接沿用输入框左边，宽 500 就冲出右边界)
            topLeft = edit.mapTo(host, QPoint(0, edit.height()))
            x = max(0, min(topLeft.x(), max(0, host.width() - PopupMinWidth)))
            availW = max(PopupMinWidth, host.width() - x - 4)
            width = max(PopupMinWidth, min(max(edit.width(), PopupMinWidth), availW))
            rowHeight = listView.sizeHintForRow(0) if rows > 0 else 0
            if rowHeight <= 0:
                rowHeight = PopupRowHeight
            contentHeight = rows * rowHeight + PopupChromeHeight
            availH = host.height() - topLeft.y() - 8
            height = max(PopupMinHeight, min(contentHeight, max(PopupMinHeight, availH)))
            widget.setGeometry(x, topLeft.y(), width, height)
            widget.raise_()
            widget.show()
        else:
            # 桌面：仍然是输入框下方的浮层，但不许伸出屏幕
            topLeft = edit.mapToGlobal(QPoint(0, edit.height()))
            screen = QGuiApplication.screenAt(topLeft) or QGuiApplication.primaryScreen()
            if screen is not None:
                rect = screen.availableGeometry()
            else:
                rect = QRect(topLeft.x(), topLeft.y(), 1920, 1080)
            width = max(edit.width(), 320)
            width = min(width, max(240, rect.width() - 8))
            x = max(rect.x(), min(topLeft.x(), rect.right() - width))
            height = max(PopupMinHeight, rect.height() // 3)
            height = min(height, max(PopupMinHeight, rect.bottom() - topLeft.y() - 8))
            widget.move(x, topLeft.y())
            widget.resize(width, height)
            widget.show()
        return True
    except Exception as es:
        Log.Error(es)
    return False


def Hide(edit):
    state = getattr(edit, "_jmPopup", None)
    if state is None:
        return
    widget = state["widget"]
    try:
        if widget is not None and not widget.isHidden():
            widget.hide()
    except Exception as es:
        Log.Error(es)


def IsHidden(edit):
    state = getattr(edit, "_jmPopup", None)
    if state is None or state["widget"] is None:
        return True
    try:
        return state["widget"].isHidden()
    except Exception:
        return True


def CheckClick(edit, pos):
    """ 页面别处被点了一下：收起弹层(桌面端由 MainView.mousePressEvent 调)

    注意不能只靠 `clearFocus()`：手机端子控件图层不抢焦点，输入框可能本来就没焦点，
    clearFocus() 是空操作，focusOutEvent 也就不会来(原来"点了别处弹层还在"的一个来源)。
    """
    if IsHidden(edit):
        return
    Hide(edit)
    clear = getattr(edit, "clearFocus", None)
    if callable(clear):
        clear()
