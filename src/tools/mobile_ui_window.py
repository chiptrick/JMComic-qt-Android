# coding:utf-8
""" 顶层窗口守卫（延后 show/hide/close + 子控件覆盖层）+ 返回键 """
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QDialog, QToolButton, QWidget
import time
from tools.log import Log
from tools.mobile_ui_base import *  # noqa: F401,F403
from tools.mobile_ui_base import (_DescribeWidget, _WidgetAlive, _WindowType)
from tools import mobile_ui



def MakeChildOverlay(widget, coverParent=True):
    """ 把"本来打算做顶层窗口"的控件改成主窗口里的**子控件覆盖层**

    真机实证(Android 16 + Qt 6.11.2)：**任何第二个顶层窗口**只要开始渲染就会
    撞上平台插件里的全局死锁保护器并直接 abort：

        Abort message: 'Failed to acquire deadlock protector for
                        QAndroidPlatformOpenGLWindow::eglSurface().'
        栈: QWidget::setVisible -> show_sys -> QPlatformWindow::setVisible
            -> flushWindowSystemEvents -> processExposeEvent -> paintAndFlush
            -> QBackingStoreRhiSupport::create -> QRhi::create
            -> QOpenGLContext::makeCurrent -> eglSurface -> qFatal

    提示条(每次改设置都弹)、加载框(每次切页都弹)、遮罩对话框都属于这一类，
    所以"延后 show"是不够的(延后之后照样在 sendPostedEvents 里创建第二个窗口)。
    改成子控件后所有内容都在**同一个平台窗口**里合成，彻底不会再走这条路。
    """
    if widget is None or not IsEnabled():
        return False
    try:
        if getattr(widget, "_jmChildOverlay", False):
            return True
        wasVisible = widget.isVisible()
        if wasVisible:
            widget.hide()
        widget.setWindowFlags(Qt.WindowType.Widget)
        widget._jmChildOverlay = True
        mobile_ui.ShowDeferralStats["overlays"] = mobile_ui.ShowDeferralStats.get("overlays", 0) + 1
        if coverParent:
            widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        if wasVisible:
            widget.show()
        return True
    except Exception as es:
        Log.Error(es)
    return False


def CoverParentGeometry(widget):
    """ 子控件覆盖层：对齐父窗口(父窗口 resize 后要再调一次) """
    try:
        if widget is None or not getattr(widget, "_jmChildOverlay", False):
            return
        parent = widget.parentWidget()
        if parent is None:
            return
        widget.setGeometry(0, 0, parent.width(), parent.height())
    except Exception as es:
        Log.Error(es)
    return


def IsChildOverlay(widget):
    try:
        return bool(getattr(widget, "_jmChildOverlay", False))
    except Exception:
        return False


class _MobileFilter(QObject):
    """ 全局事件过滤器：对话框尺寸自适应 + 可选按键/窗口事件诊断 """

    def eventFilter(self, obj, event):
        try:
            if mobile_ui._keyDiagEnabled:
                KeyDiag(obj, event)
            if event.type() == QEvent.Type.Show and isinstance(obj, QDialog):
                if isinstance(obj, QWidget) and getattr(obj, "widget", None) is not None:
                    # BaseMaskDialog：内部 widget 才是真正的对话框
                    mobile_ui.RelaxMinSizes(obj.widget, mobile_ui.CurrentLimit())
                    obj.widget.adjustSize()
                else:
                    mobile_ui.RelaxMinSizes(obj, mobile_ui.CurrentLimit())
        except Exception as es:
            Log.Error(es)
        return False


def KeyDiag(obj, event):
    """ 记录按键与窗口生命周期事件(仅诊断标记打开时) """
    try:
        eventType = event.type()
        if eventType in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            mobile_ui.KeyDiagStats["key"] += 1
            key = event.key()
            if key in (Qt.Key.Key_Back, Qt.Key.Key_Escape):
                mobile_ui.KeyDiagStats["back"] += 1
            Log.Warn("key diag: {} key={}({}) text={!r} accepted={} receiver={}".format(
                eventType.name, key, Qt.Key(key).name if hasattr(Qt.Key, "name") else "",
                event.text() if hasattr(event, "text") else "",
                event.isAccepted(), _DescribeWidget(obj)))
        elif eventType in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Close,
                           QEvent.Type.WindowStateChange, QEvent.Type.ApplicationStateChange):
            if isinstance(obj, QWidget) and obj.isWindow():
                mobile_ui.KeyDiagStats["window"] += 1
                Log.Warn("window diag: {} {} windowState={} visible={} active={}".format(
                    eventType.name, _DescribeWidget(obj),
                    obj.windowState().name if hasattr(obj.windowState(), "name") else "?",
                    obj.isVisible(), obj.isActiveWindow()))
    except Exception:
        pass
    return


def InstallAppFilter(mainView):
    if mobile_ui._filter is not None:
        return
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    mobile_ui._filter = _MobileFilter(app)
    app.installEventFilter(mobile_ui._filter)


def InstallShowDeferral(mainView=None):
    """ 全局：把顶层窗口的 show/hide 延后到当前输入事件处理结束

    只对**顶层窗口**动手(isWindow())：子控件的 show/hide 不创建平台窗口，
    也没有重入风险，保持原样最安全。
    """
    if not IsEnabled() or mobile_ui._showDeferralInstalled:
        return False
    try:
        origShow = QWidget.show
        origHide = QWidget.hide
        origClose = QWidget.close
        # 延后执行时要调用**原函数**：QWidget.close 已经被我们换掉了，
        # 再调 QWidget.close 会又进一次守卫 -> 无限延后，窗口永远关不掉(踩过)
        mobile_ui._showDeferralOrigin["show"] = origShow
        mobile_ui._showDeferralOrigin["hide"] = origHide
        mobile_ui._showDeferralOrigin["close"] = origClose

        def WaitShow(widget):
            mobile_ui.ShowDeferralStats["deferred"] += 1
            DeferCall(lambda w=widget: _SafeShow(w))

        def IsMainWindow(widget):
            return widget is mobile_ui._mainView or widget is getattr(mobile_ui._mainView, "subMainWindow", None)

        def WidgetShow(self):
            try:
                if self.isWindow() and not self.isVisible() and not IsMainWindow(self):
                    WaitShow(self)
                    return
            except Exception as es:
                Log.Error(es)
            origShow(self)

        def WidgetHide(self):
            try:
                if self.isWindow() and self.isVisible() and not IsMainWindow(self):
                    mobile_ui.ShowDeferralStats["hidden"] += 1
                    DeferCall(lambda w=self: _SafeHide(w))
                    return
            except Exception as es:
                Log.Error(es)
            origHide(self)

        def WidgetClose(self):
            # close() 内部同样会销毁平台窗口 -> 同一个 eglSurface 重入风险
            try:
                if self.isWindow() and self.isVisible() and not IsMainWindow(self):
                    mobile_ui.ShowDeferralStats["closed"] = mobile_ui.ShowDeferralStats.get("closed", 0) + 1
                    DeferCall(lambda w=self: _SafeClose(w))
                    return True
            except Exception as es:
                Log.Error(es)
            return origClose(self)

        QWidget.show = WidgetShow
        QWidget.hide = WidgetHide
        QWidget.close = WidgetClose
        mobile_ui._showDeferralInstalled = True
        Log.Warn("window guard: 顶层窗口 show/hide/close 已改为延后执行")
        return True
    except Exception as es:
        Log.Error(es)
    return False


def _SafeShow(widget):
    try:
        if _WidgetAlive(widget) and not widget.isVisible():
            # 直接调被套住的原函数会再进守卫，这里用 setVisible/原始函数跳过守卫
            QWidget.setVisible(widget, True)
            mobile_ui.ShowDeferralStats["shown"] += 1
    except Exception as es:
        Log.Error(es)
    return


def _SafeHide(widget):
    try:
        if _WidgetAlive(widget) and widget.isVisible():
            QWidget.setVisible(widget, False)
    except Exception as es:
        Log.Error(es)
    return


def _SafeClose(widget):
    try:
        if _WidgetAlive(widget):
            orig = mobile_ui._showDeferralOrigin.get("close")
            if orig is not None:
                orig(widget)
            else:
                QWidget.setVisible(widget, False)
    except Exception as es:
        Log.Error(es)
    return


# 兼容旧调用名
def InstallWindowGuard(mainView=None):
    return InstallShowDeferral(mainView)


def WindowGuardStats():
    return mobile_ui.ShowDeferralStats


def _VisibleTopWindow(mainView):
    """ 找一个盖在主窗口上面的对话框窗口(加载框/遮罩对话框)

    只看 Dialog/Sheet：提示条(MsgLabel 是 Qt::Tool)、弹出列表(Qt::Popup)不算，
    它们要么自动消失，要么有自己的关闭路径。
    """
    closeTypes = (Qt.WindowType.Dialog, Qt.WindowType.Sheet, Qt.WindowType.Drawer)
    try:
        for widget in QApplication.topLevelWidgets():
            if widget is mainView or widget is getattr(mainView, "subMainWindow", None):
                continue
            if not isinstance(widget, QWidget) or not widget.isVisible():
                continue
            if not widget.isWindow():
                continue
            if _WindowType(widget) not in closeTypes:
                continue
            if widget.width() <= 1 or widget.height() <= 1:
                continue
            return widget
    except Exception as es:
        Log.Error(es)
    return None


def MinimizeToDesktop(mainView):
    """ 根页面按返回：**不能**用 showMinimized()

    真机实测(Android 16 + Qt6.11.2)：`showMinimized()` 只把 Qt 窗口隐藏了，
    Activity 仍然是 `topResumedActivity`、窗口 `mViewVisibility=VISIBLE` ——
    Android 那边还停在前台，但 Qt 已经不再绘制，屏幕上就是一片空白：
    **这正是用户报的"白屏"**。真正的"退到桌面"要调 Android 的
    `moveTaskToBack(true)`，而这个包调不到：

      * pyjnius 不可用：`jnius.so` 在真机上 dlopen 失败
        (cannot locate symbol "WebView_AndroidGetJNIEnv"，bootstrap=qt 没有那个符号)
      * PySide6 6.11 没有绑定 QJniObject / QAndroidJniObject

    所以这里**保持窗口可见**，只给一句提示，让用户用系统的手势/Home 回桌面
    (这也是 Android 的标准做法)，至少不会留下白屏。
    """
    mobile_ui.BackStats["minimize"] += 1
    Log.Warn("back: 根页面(不退到后台, 见 MinimizeToDesktop 注释) windowState={} visible={}".format(
        mainView.windowState().name if hasattr(mainView.windowState(), "name") else "?",
        mainView.isVisible()))
    try:
        if not getattr(mainView, "_jmBackHintShown", False):
            mainView._jmBackHintShown = True
            QtOwner().ShowMsgOne("已在首页：用系统手势或 Home 返回桌面")
    except Exception as es:
        Log.Error(es)
    return "stay"


def HandleBackKey(mainView):
    """ 返回键统一处理；返回 True 表示已接管(事件必须 accept，不能再往下传)

    优先级(和桌面端语义一致，只是补上了菜单/根页面两档)：
        1. 看图界面的工具菜单(是子控件，不是窗口)
        2. 盖在上面的顶层窗口(提示条/对话框/加载框)
        3. 导航抽屉
        4. 看图中 -> 退出看图回到上级(书详情等)
        5. 页面栈回退一层
        6. 根页面 -> 退到后台(回桌面)
    """
    now = time.time() * 1000.0
    if now - mobile_ui._backLastTick < BackDebounceMs:
        # Android 会给按下和抬起两个事件，同一按不能处理两次
        return True
    mobile_ui._backLastTick = now
    mobile_ui.BackStats["count"] += 1
    try:
        # 0. 弹出窗口(下拉框列表/右键菜单)
        popup = QApplication.activePopupWidget()
        if popup is not None and popup.isVisible():
            try:
                popup.close()
            except Exception as es:
                Log.Error(es)
            return _BackDone("close-popup:{}".format(_DescribeWidget(popup)))

        # 1. 看图界面的工具菜单
        readView = getattr(mainView, "readView", None)
        if _readToolVisible(readView):
            _hideReadTool(readView)
            return _BackDone("close-read-tool")

        # 2. 顶层窗口(提示条/对话框)
        top = _VisibleTopWindow(mainView)
        if top is not None:
            try:
                top.close()
            except Exception as es:
                Log.Error(es)
            return _BackDone("close-window:{}".format(_DescribeWidget(top)))

        # 3. 抽屉
        if mobile_ui.IsDrawerOpen(mainView):
            mobile_ui.CloseDrawer(mainView)
            return _BackDone("close-drawer")

        # 4. 看图 -> 退出看图
        if getattr(mainView, "totalStackWidget", None) is not None \
                and mainView.totalStackWidget.currentIndex() == 1 and readView is not None:
            readView.Close()
            return _BackDone("close-reader")

        # 5. 页面栈回退
        stack = getattr(mainView, "subStackWidget", None)
        subList = getattr(mainView, "subStackList", None) or []
        index = stack.currentIndex() if stack is not None else -1
        if index in subList and subList.index(index) > 0:
            before = CurrentPageName(mainView)
            mainView.SwitchWidgetLast()
            Log.Warn("back: 页面回退 {} -> {}".format(before, CurrentPageName(mainView)))
            return _BackDone("switch-widget-last")

        # 6. 根页面
        if mobile_ui.IsDrawerOpen(mainView):
            mobile_ui.CloseDrawer(mainView)
            return _BackDone("close-drawer")
        MinimizeToDesktop(mainView)
        return _BackDone("root-page")
    except Exception as es:
        Log.Error(es)
        return _BackDone("error")


def _BackDone(action):
    mobile_ui.BackStats["action"] = action
    mobile_ui.BackStats["last"] = "{} @ {}".format(action, CurrentPageName(mobile_ui._mainView) if mobile_ui._mainView else "?")
    Log.Warn("back: {} (页面 {})".format(action, CurrentPageName(mobile_ui._mainView) if mobile_ui._mainView else "?"))
    return True


def _readToolVisible(readView):
    try:
        tool = getattr(getattr(readView, "frame", None), "qtTool", None)
        return tool is not None and not tool.isHidden()
    except Exception:
        return False


def _hideReadTool(readView):
    try:
        readView.frame.qtTool.hide()
    except Exception as es:
        Log.Error(es)
    return


def SetupBackButton(mainView):
    """ 手机端在顶栏加一个"返回"按钮

    真机实测(Qt 6.11.2 + Android 16)：Android 的返回键**根本到不了** Qt 窗口
    (应用日志里 `key diag` 一次 Key_Back 都没有)，所以 `main_view.keyPressEvent`
    里的返回逻辑在真机上等于没接线。除了保留按键处理(某些机型/焦点状态下会到)，
    再给一个看得见、一定可用的返回入口。
    """
    try:
        if not IsEnabled() or getattr(mainView, "_jmBackButton", None) is not None:
            return False
        layout = getattr(mainView, "menuLayout", None)
        if layout is None:
            return False
        button = QToolButton(mainView.subMainWindow)
        button.setObjectName("jmBackButton")
        button.setText("返回")
        button.setToolTip("返回上一级")
        button.setAutoRaise(True)
        button.clicked.connect(lambda: HandleBackKey(mobile_ui._mainView))
        layout.insertWidget(0, button)
        mainView._jmBackButton = button
        Log.Warn("mobile ui: 顶栏加了返回按钮(真机返回键到不了 Qt)")
        return True
    except Exception as es:
        Log.Error(es)
    return False
