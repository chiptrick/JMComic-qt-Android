# coding:utf-8
""" 顶层窗口守卫（延后 show/hide/close + 子控件覆盖层）+ 返回键 """
import os
import shutil
import time
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QDialog, QToolButton, QWidget
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
            eventType = event.type()
            if isinstance(obj, QDialog) and eventType in (QEvent.Type.Show, QEvent.Type.Resize):
                inner = getattr(obj, "widget", None)
                if inner is not None:
                    # BaseMaskDialog：内部 widget 才是真正的对话框
                    if eventType == QEvent.Type.Show:
                        mobile_ui.RelaxMinSizes(inner, mobile_ui.CurrentLimit())
                        # 内容宽度不能超过窗口：模型选择表(4 列固定宽 550)、登录页这些
                        # 桌面上按设计尺寸写的对话框，在 480 宽的竖屏上会被 adjustSize()
                        # 撑出屏幕，右侧内容永远看不到(真机"信息显示不完整"的来源之一)
                        ClampInnerWidth(obj)
                        inner.adjustSize()
                    else:
                        # resize 里只夹宽度、不 adjustSize：adjustSize 会再触发 resize，
                        # 在事件过滤器里递归是最容易写出"窗口抖动/卡死"的写法
                        ClampInnerWidth(obj)
                elif eventType == QEvent.Type.Show:
                    mobile_ui.RelaxMinSizes(obj, mobile_ui.CurrentLimit())
        except Exception as es:
            Log.Error(es)
        return False


def ClampInnerWidth(dialog):
    """ 把遮罩对话框的内容层宽度夹到窗口内(竖屏防溢出，桌面端窗口够宽时无效果) """
    try:
        inner = getattr(dialog, "widget", None)
        if inner is None:
            return
        width = dialog.width()
        if width <= 1:
            return
        limit = max(240, width - 16)
        if inner.minimumWidth() > limit:
            inner.setMinimumWidth(limit)
        if inner.maximumWidth() > limit:
            inner.setMaximumWidth(limit)
        if inner.width() > limit:
            inner.resize(limit, inner.height())
    except Exception as es:
        Log.Error(es)
    return


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


def _VisibleMaskDialog(mainView):
    """ 找一个盖在主窗口上的遮罩对话框(登录/收藏夹/模型选择/目录选择等)

    这类对话框(BaseMaskDialog)在手机端都改成了主窗口里的**子控件覆盖层**
    (见 MakeChildOverlay：第二个顶层窗口一渲染就会 abort)，所以
    _VisibleTopWindow 找不到它们；但返回键必须能把它们收掉，否则会退到
    对话框下面的页面去。加载框(LoadingDialog)不算 —— 它自动消失，且对触摸透明。
    """
    try:
        from component.dialog.base_mask_dialog import BaseMaskDialog
        for widget in mainView.findChildren(BaseMaskDialog):
            if widget.isVisible():
                return widget
    except Exception as es:
        Log.Error(es)
    return None


def GoHomePage(mainView):
    """ 第一级页面按返回：回到首页(与点抽屉里的"首页"按钮一致)

    清掉页面栈只留首页一档，避免"回首页"只是把首页压进栈里(那样再按一次
    返回又会回到原页面，来回翻倍)。
    """
    try:
        indexView = getattr(mainView, "indexView", None)
        stack = getattr(mainView, "subStackWidget", None)
        if indexView is None or stack is None:
            return False
        index = stack.indexOf(indexView)
        if index < 0 or stack.currentIndex() == index:
            return False
        before = CurrentPageName(mainView)
        mainView.SwitchWidgetAndClear(index)
        Log.Warn("back: 回首页 {} -> {}".format(before, CurrentPageName(mainView)))
        return True
    except Exception as es:
        Log.Error(es)
    return False


def QuitAppAndCleanup(mainView):
    """ 首页连按两次返回键：退出 app，并清理后台进程与临时缓存

    这里只做"快"的清理(发结束信号、清内存对象池、删临时缓存文件)：
    join 线程这类可能卡住的操作留给 start.Run() 里 app.exec() 返回后的
    main.Close()，否则退出前界面会先假停几秒(HTTP 线程可能正堵在一个请求里)。
    """
    mobile_ui.BackStats["quit"] += 1
    Log.Warn("back: 连按两次返回键，退出 app 并清理后台进程/临时缓存")
    try:
        # 1. 看图界面还开着：存阅读历史、清图片、停定时器
        readView = getattr(mainView, "readView", None)
        if readView is not None:
            try:
                if getattr(mainView, "totalStackWidget", None) is not None \
                        and mainView.totalStackWidget.currentIndex() == 1:
                    readView.Close()
                else:
                    readView.Stop()
            except Exception as es:
                Log.Error(es)
        # 2. 后台任务/worker 发结束信号(不 join，避免退出前卡界面)
        from task.task_multi import TaskMulti
        from task.task_qimage import TaskQImage
        from task.task_waifu2x import TaskWaifu2x
        for task in (TaskMulti(), TaskQImage(), TaskWaifu2x()):
            try:
                task.Stop()
            except Exception as es:
                Log.Error(es)
        # 3. 内存里的图片对象池清掉(退出后反正要重建)
        try:
            from view.read.read_pool import QtReadImgPoolManager
            pool = QtReadImgPoolManager()
            pool.proxyItem.clear()
            pool.pixMapItem.clear()
        except Exception as es:
            Log.Error(es)
        # 4. 临时缓存(看图图片/超分结果/NAS 临时文件等可再生数据)落盘清理
        ClearTempCache()
    except Exception as es:
        Log.Error(es)
    # 5. 退出事件循环：exec() 返回后 start.Run() 还会做一次完整的 Close()
    try:
        from qt_owner import QtOwner
        app = QtOwner().app
        if app is not None:
            app.quit()
    except Exception as es:
        Log.Error(es)
    return


def ClearTempCache():
    """ 清理临时缓存目录里的内容(看图图片/超分结果等可再生数据)

    只删目录里的条目、不删目录本身(下次启动 Setting.Init 会重建)；
    配置/数据/日志都在各自的目录里，不受影响。
    """
    try:
        from config.setting import Setting
        cachePath = Setting.GetCachePath()
        if not cachePath or not os.path.isdir(cachePath):
            return 0
        count = 0
        for name in os.listdir(cachePath):
            path = os.path.join(cachePath, name)
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
                count += 1
            except Exception as es:
                Log.Error(es)
        Log.Warn("back: 临时缓存已清理 {} ({} 项)".format(cachePath, count))
        return count
    except Exception as es:
        Log.Error(es)
    return 0


def CancelBackQuit():
    """ 主动切换页面(点抽屉/首页)后取消"连按两次返回键退出"的待退出状态

    否则"在首页按过一次返回(提示过)，又去点了导航，再按返回"会在没看到提示的
    情况下直接退出。返回键自己的分支在 HandleBackKey 开头已经清零，这里补上
    "不走返回键的导航"。
    """
    mobile_ui._backQuitTick = 0.0
    return


def HandleBackKey(mainView):
    """ 返回键统一处理；返回 True 表示已接管(事件必须 accept，不能再往下传)

    优先级(与顶栏左上角"返回"按钮走的是同一条逻辑)：
        0. 弹出窗口(下拉框列表/右键菜单) -> 关闭
        1. 看图界面的工具菜单 -> 收起菜单，回到看图界面
        2. 盖在上面的顶层窗口(提示条/对话框/加载框) -> 关闭
        3. 盖在上面的遮罩对话框(手机端是子控件覆盖层，不是顶层窗口) -> 关闭
        4. 导航抽屉 -> 收起
        5. 看图界面 -> 退出看图，回到漫画详情页
        6. 其余页面 -> 页面栈回退一层(复用左上角返回按钮的逻辑)
        7. 第一级页面 -> 回到首页
        8. 首页 -> 提示"再按一次返回键退出"；连按两次退出 app 并清理
           后台进程和临时缓存
    """
    if not IsEnabled():
        # 桌面端不接管返回键/Esc，保持原有行为
        return False
    now = time.time() * 1000.0
    if now - mobile_ui._backLastTick < BackDebounceMs:
        # Android 会给按下和抬起两个事件，同一按不能处理两次
        return True
    mobile_ui._backLastTick = now
    mobile_ui.BackStats["count"] += 1
    # "连按两次退出"只在连续两次走到首页分支时生效：中间任何一次其它返回
    # 动作都取消待退出状态(先取旧值再清零)
    quitTick = mobile_ui._backQuitTick
    mobile_ui._backQuitTick = 0.0
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

        # 3. 遮罩对话框(手机端是主窗口里的子控件覆盖层，_VisibleTopWindow 找不到)
        dialog = _VisibleMaskDialog(mainView)
        if dialog is not None:
            try:
                dialog.close()
            except Exception as es:
                Log.Error(es)
            return _BackDone("close-dialog:{}".format(_DescribeWidget(dialog)))

        # 4. 抽屉
        if mobile_ui.IsDrawerOpen(mainView):
            mobile_ui.CloseDrawer(mainView)
            return _BackDone("close-drawer")

        # 5. 看图 -> 退出看图回到漫画详情页
        if getattr(mainView, "totalStackWidget", None) is not None \
                and mainView.totalStackWidget.currentIndex() == 1 and readView is not None:
            _ExitReader(mainView, readView)
            return _BackDone("close-reader")

        # 6. 页面栈回退一层(与左上角返回按钮一致)
        stack = getattr(mainView, "subStackWidget", None)
        subList = getattr(mainView, "subStackList", None) or []
        index = stack.currentIndex() if stack is not None else -1
        if index in subList and subList.index(index) > 0:
            before = CurrentPageName(mainView)
            mainView.SwitchWidgetLast()
            Log.Warn("back: 页面回退 {} -> {}".format(before, CurrentPageName(mainView)))
            return _BackDone("switch-widget-last")

        # 7. 第一级页面 -> 回首页
        if GoHomePage(mainView):
            return _BackDone("goto-home")

        # 8. 首页 -> 再按一次退出；连按两次退出并清理
        if quitTick and now - quitTick <= BackQuitWindowMs:
            QuitAppAndCleanup(mainView)
            return _BackDone("quit")
        mobile_ui._backQuitTick = now
        try:
            from qt_owner import QtOwner
            QtOwner().ShowMsgOne("再按一次返回键退出")
        except Exception as es:
            Log.Error(es)
        return _BackDone("quit-hint")
    except Exception as es:
        Log.Error(es)
        return _BackDone("error")


def _ExitReader(mainView, readView):
    """ 退出看图，并且**确保**真的回到漫画详情页(本地漫画回本地列表)

    readView.Close() 是一条长链：
        AddHistory(存阅读历史/写库) -> ClearPixItem -> Clear(存设置、清任务、清下载)
        -> QtOwner().CloseReadView()  ← 真正切页( totalStackWidget.setCurrentIndex(0) )
    链上**任何一步**抛异常，切页那步就根本不会执行；而 HandleBackKey 外层的
    except 又会把这次按键记成"已处理"(返回 True)，于是用户看到的正是
    "在看图界面按返回键毫无反应"。所以这里不再依赖 Close() 自己切页：
    先记状态，Close() 出错也继续兜底把页面切回去。
    """
    # Close() 会把 bookId/isLocal 清掉，先记下来
    bookId = getattr(readView, "bookId", "") or ""
    isLocal = bool(getattr(readView, "isLocal", False))
    try:
        readView.Close()
    except Exception as es:
        Log.Error(es)
        Log.Warn("back: readView.Close() 抛异常，走兜底切页")
    # 兜底 1：页面栈还停在看图(索引 1)就自己切回详情页那一层
    try:
        stack = getattr(mainView, "totalStackWidget", None)
        if stack is not None and stack.currentIndex() == 1:
            stack.setCurrentIndex(0)
            Log.Warn("back: Close() 未切页，兜底 setCurrentIndex(0)")
    except Exception as es:
        Log.Error(es)
    # 兜底 2：在线漫画补切到这一本的详情页(自检直进/详情页被换掉的情况)；
    #         本地漫画没有在线详情页，停在本地列表即可。
    if bookId and not isLocal:
        try:
            stack = getattr(mainView, "subStackWidget", None)
            cur = stack.currentWidget() if stack is not None else None
            if cur is not None and cur not in (
                    getattr(mainView, "bookInfoView", None),
                    getattr(mainView, "bookInfoView2", None)):
                mainView.SwitchWidget(mainView.bookInfoView, bookId=bookId)
        except Exception as es:
            Log.Error(es)
    return


def InstallBackKeyShortcut(mainView):
    """ 窗口级返回键快捷键：不管焦点在哪个子控件，返回键都先到这里

    Qt 官方说明(Qt 6 Android platform notes "Back Key and Back Gesture")：
    返回键只送给**当前有焦点的项**，而触摸界面经常没有任何项持有焦点
    ("the back press never reaches it")，推荐的做法是绑一个**窗口级**快捷键；
    没人接住时 Qt 会把应用切到后台(旧版本直接走关闭)，应用侧看起来就是
    "按了没反应"。看图界面正好是纯触摸页(没有输入框/没有焦点控件)，是这条
    规则最容易踩中的地方，所以这里给主窗口补一个不受焦点影响的后备入口。

    与下面两条路径共存、互不重复：
        * main_view.keyPressEvent / keyReleaseEvent(有焦点时的按键路径)
        * 顶栏"返回"按钮(真机上连按键都到不了 Qt 时的可见入口)
    HandleBackKey 开头的 _backLastTick 去抖保证一次按键只处理一次。
    """
    try:
        if not IsEnabled() or getattr(mainView, "_jmBackShortcut", None) is not None:
            return False
        shortcut = QShortcut(QKeySequence(Qt.Key.Key_Back), mainView)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        # 与 main_view.keyPressEvent/顶栏返回按钮共用同一个入口(去抖在 HandleBackKey 里)
        shortcut.activated.connect(lambda: HandleBackKey(mobile_ui._mainView))
        mainView._jmBackShortcut = shortcut
        Log.Warn("mobile ui: 主窗口装了返回键快捷键(窗口级，不依赖焦点)")
        return True
    except Exception as es:
        Log.Error(es)
    return False


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
