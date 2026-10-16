# coding:utf-8
""" 主窗口生命周期挂钩（Apply / OnShown / OnResize） """
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
        mobile_ui.InstallAppFilter(mainView)
        mobile_ui.InstallTouchGuard(mainView)
        mobile_ui.InstallWindowGuard(mainView)
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
