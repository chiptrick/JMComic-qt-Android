# coding:utf-8
""" 主窗口生命周期挂钩（Apply / OnShown / OnResize / 应用前后台） """
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from tools.log import Log
from tools.mobile_ui_base import *  # noqa: F401,F403
from tools import mobile_ui


def Apply(mainView):
    """ 主窗口创建后调用一次 """
    if not IsEnabled():
        return
    mobile_ui._mainView = mainView
    try:
        mobile_ui.UpdateLimit(mainView)
        mobile_ui.SetupDrawer(mainView)
        mobile_ui.RelaxMinSizes(mainView, mobile_ui._limit)
        mobile_ui.StackBookInfo(mainView.bookInfoView)
        mobile_ui.StackBookInfo(mainView.bookInfoView2)
        # 详情页操作按钮行(收藏/本地/评论/下载/上传/清理 + 购买 + 上次看到…)一行放不下，
        # 先折成多行，剩下的溢出交给 ReflowPortrait 的最后一道保险
        mobile_ui.WrapBookInfoButtons(mainView.bookInfoView)
        mobile_ui.WrapBookInfoButtons(mainView.bookInfoView2)
        mobile_ui.StackSideNavs(mainView)
        mobile_ui.StackSrTool(getattr(mainView, "waifu2xToolView", None), mainView)
        mobile_ui.CompactTabBar(mainView)
        mobile_ui.SetupReadTool(getattr(mainView, "readView", None))
        mobile_ui.ApplyGridCoverSize(mainView)
        mobile_ui.EnableTouchScroll(mainView)
        # 首页分区页是网络回来后逐个 AddTab 建的(EnableTouchScroll 那会儿还没有)：
        # 装上"后建滚动区域自动接管"，后面建出来的列表/面板照样能手指滚动
        mobile_ui.InstallScrollWatcher(mainView)
        mobile_ui.SetupBackButton(mainView)
        mobile_ui.InstallBackKeyShortcut(mainView)
        mobile_ui.InstallAppFilter(mainView)
        mobile_ui.InstallTouchGuard(mainView)
        mobile_ui.InstallWindowGuard(mainView)
        # 前后台切换：进后台刷最后一帧(多任务快照要有内容)、回前台重排重绘(防黑屏)
        mobile_ui.InstallAppStateHook(mainView)
        mobile_ui.ReflowPortrait(getattr(mainView, "subStackWidget", None))
        mobile_ui.InstallReflowHook(mainView)
        # 首页/其它页面里的 QTabWidget(分区标签)：换页后按真实视口重排封面
        # (标签条本身的横划滚动在 InstallTouchGuard 的滑动守卫里，见 mobile_ui_touch)
        mobile_ui.InstallTabReflowHook(mainView)
        Log.Warn("mobile ui adapted, limit:{}".format(mobile_ui._limit))
    except Exception as es:
        Log.Error(es)


def OnShown(mainView):
    """ 窗口首次显示 / 旋转 / 从后台回到前台时调用：重新计算尺寸并适配 """
    if not IsEnabled():
        return
    try:
        LogUiEvent("shown: {}x{} windowState={} page={}".format(
            mainView.width(), mainView.height(),
            mainView.windowState().name if hasattr(mainView.windowState(), "name") else "?",
            CurrentPageName(mainView)))
        mobile_ui.UpdateLimit(mainView)
        mobile_ui.RelaxMinSizes(mainView, mobile_ui._limit)
        mobile_ui.SetupDrawer(mainView)
        mobile_ui.StackSideNavs(mainView)
        mobile_ui.StackSettingNav(getattr(mainView, "settingView", None))
        mobile_ui.StackSrTool(getattr(mainView, "waifu2xToolView", None), mainView)
        mobile_ui.UpdateSrToolHeight(getattr(mainView, "waifu2xToolView", None), mainView)
        mobile_ui.SetupReadTool(getattr(mainView, "readView", None))
        mobile_ui.ApplyGridCoverSize(mainView)
        mobile_ui.ReflowPortrait(getattr(mainView, "subStackWidget", None))
        mobile_ui.EnableTouchScroll(mainView)
        mobile_ui.InstallScrollWatcher(mainView)
        mobile_ui.InstallTabReflowHook(mainView)
        mobile_ui.MaybeSelfTest(mainView)
        mobile_ui.MaybeTouchSelfTest(mainView)
        mobile_ui.MaybeDeviceVerify(mainView)
        mobile_ui.MaybeReaderSelfTest(mainView)
        mobile_ui.MaybeKeyDiag(mainView)
    except Exception as es:
        Log.Error(es)
    return


def OnResize(mainView):
    """ 尺寸变化(旋转屏幕、软键盘弹出)后调用；只有上限变化时才全量放宽 """
    if not IsEnabled():
        return
    try:
        old = mobile_ui._limit
        mobile_ui.UpdateLimit(mainView)
        mobile_ui.UpdateDrawerGeometry(mainView)
        mobile_ui.UpdateSrToolHeight(getattr(mainView, "waifu2xToolView", None), mainView)
        if old != mobile_ui._limit:
            mobile_ui.RelaxMinSizes(mainView, mobile_ui._limit)
            # 软键盘弹出/旋转后封面宽度会变，重算一次"一行 2 个"
            mobile_ui.ResetGridCover()
            mobile_ui.ApplyGridCoverSize(mainView)
        else:
            # _limit 在宽屏下会饱和到 MinWidthLimit(320)，所以"设计尺寸 800px -> 手机
            # 384px"这种缩放走不到上面那支；但列表视口其实变了，封面宽得跟着重算，
            # 否则首屏那批 item 会一直停在按 800px 算出来的 GridCoverMax(240px) ——
            # 真机现象就是"打开首页一行 1 个"。这里去抖地补一次重排。
            mobile_ui.ScheduleGridCoverSize(mainView)
    except Exception as es:
        Log.Error(es)
    return


def InstallAppStateHook(mainView):
    """ 监听前后台切换：把最后一帧刷出去 + 打一行可验证的日志

    1) **多任务卡片里看不到本应用的画面**：系统是在 Activity 停下来前后抓的任务快照。
       如果这一帧还没刷出去(或者渲染表面已经被释放)，抓到的就是黑图/空图。
       在 `ApplicationInactive`(≈ onPause，画面还在) 主动 `repaint()` 一次，
       保证系统抓到的至少是"当前这一屏"。
       (真正的根因是渲染容器用了 SurfaceView —— 它不在 View 树里，
       快照抓不到它的内容；见 android/main.py 里把容器切成 TextureView 的说明。)
    2) **从多任务切回来黑屏/白屏**(本项目历史问题)：`ApplicationActive` 时按新尺寸重排
       并强制重绘一次。
    3) 每次状态变化打一行 `appState:` 日志 —— 真机上一眼能分清
       "只是进了后台" / "被系统销毁重来"(日志会出现冷启动记录)。
    """
    if not IsEnabled() or mainView is None:
        return False
    if getattr(mainView, "_jmAppStateHook", False):
        return False
    app = QApplication.instance()
    if app is None:
        return False

    def OnAppState(state):
        try:
            name = state.name if hasattr(state, "name") else str(state)
        except Exception:
            name = str(state)
        try:
            Log.Warn("appState: {} visible={} active={} page={}".format(
                name, mainView.isVisible(), mainView.isActiveWindow(),
                CurrentPageName(mainView)))
        except Exception:
            pass
        try:
            if state == Qt.ApplicationState.ApplicationActive:
                # 回到前台：先按新尺寸重排(抽屉/封面/表格列宽)，再整窗强制重绘
                mobile_ui.OnShown(mainView)
                mainView.update()
                mainView.repaint()
            elif state == Qt.ApplicationState.ApplicationInactive:
                # 即将进后台(≈ onPause)：把当前这一帧刷出去，系统抓快照才不是黑图
                mainView.repaint()
        except Exception as es:
            Log.Error(es)
        return

    app.applicationStateChanged.connect(OnAppState)
    mainView._jmAppStateHook = True
    Log.Warn("mobile ui: 已监听前后台切换(进后台刷帧 / 回前台重排重绘)")
    return True
