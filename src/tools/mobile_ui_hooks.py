# coding:utf-8
""" 主窗口生命周期挂钩（Apply / OnShown / OnResize / 应用前后台） """
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from tools.log import Log
from tools.mobile_ui_base import *  # noqa: F401,F403
from tools import mobile_ui, platform_mobile


# ---------------------------------------------------------------------------
# 尺寸变化的空闲去抖：一串 resize 只适配一次
# ---------------------------------------------------------------------------
#
# Android 上窗口尺寸是**成串**变化的：软键盘弹出/收起一次 resize，分屏拖动时每帧
# 一次 resize，旋转两三次 resize。原来每个 resize 都同步做全量适配(放宽最小尺寸 +
# 重算封面宽 + 整页重排)，再叠加 MainView.PauseRepaint 的 setUpdatesEnabled(False)
# 冻结整窗，用户看到的就是"页面闪一下 + 跳一下"。真机日志里就是软键盘一弹出就跟着
# 一行 "portrait: 520 个封面改为一行 2 个(封面宽 189px)"。
#
# 现在在 resize 停下 ResizeSettleMs 之后只做**一次**适配(见 OnSizeSettled)，
# 而且只有"宽度相关"的变化才重排：软键盘只改高度 -> 完全不碰布局树。
# 120ms 约 7 帧：足够把一串 resize 合并成一次，又不会让用户觉得"停下来才变"。
ResizeSettleMs = 120


# ---------------------------------------------------------------------------
# 窗口底色：Android 上"resize 一闪"里那一下白色，是 Qt 在 resize 时拿调色板的
# Window 画刷擦除窗口背景造成的。桌面端擦完马上重绘看不出来，Android 上 surface
# 重分配/首帧延迟会被放大成肉眼可见的白闪。这里把主窗口调色板的 Window 底色对齐
# 当前主题 QSS 的窗口底色(深色 #31363b / 浅色 #f3f3f3)，擦除帧也是深色，白闪消失。
# 只改 Window 一个角色：QSS 里的控件底色/输入框底色不受影响。
# ---------------------------------------------------------------------------
def _ThemeBackgroundColor():
    """ 从当前主题 QSS 里取 QWidget 的窗口底色(取不到时退回 Android 深色主题色) """
    try:
        from qt_owner import QtOwner
        sheet = QtOwner().app.styleSheet() or ""
        match = re.search(r"QWidget\s*\{[^}]*?background-color:\s*(#[0-9a-fA-F]{3,6})",
                          sheet, re.S)
        if match:
            return match.group(1)
    except Exception:
        pass
    return "#31363b"


def _ApplyAndroidBackground(mainView):
    """ Android：窗口调色板的 Window 底色对齐主题底色，避免 resize 擦除出白帧 """
    if not platform_mobile.IsAndroid() or mainView is None:
        return
    try:
        color = _ThemeBackgroundColor()
        palette = mainView.palette()
        old = palette.color(QPalette.ColorRole.Window).name()
        if old.lower() == color.lower():
            return
        palette.setColor(QPalette.ColorRole.Window, QColor(color))
        mainView.setPalette(palette)
        Log.Warn("mobile ui: 窗口底色 {} -> {} (防 resize 擦除白闪)".format(old, color))
    except Exception as es:
        Log.Error(es)
    return


def _FinishRelayout(mainView):
    """ 重排收尾：先把布局参数算完，再整窗刷新一次(合成到下一帧，不多画) """
    try:
        layout = mainView.layout()
        if layout is not None:
            layout.activate()
    except Exception as es:
        Log.Error(es)
    mainView.update()
    return


def _WindowStateName(mainView):
    """ 窗口状态名(最大化/全屏/分屏切换时状态位会变，日志里直接打名字) """
    try:
        state = mainView.windowState()
        return state.name if hasattr(state, "name") else str(state)
    except Exception:
        return "?"


def _RememberAdapted(mainView):
    """ 记下"布局已经按当前 尺寸/页面/窗口状态 适配过"

    OnShown(从后台回来、软键盘收起、Activity 恢复)靠它判断要不要重排：
    签名一样就只重绘，避免"每次回前台都重排一遍 -> 页面闪一下"。
    """
    try:
        if mainView is None:
            return
        mobile_ui._shownWidth = mainView.width()
        mobile_ui._shownHeight = mainView.height()
        mobile_ui._shownLimit = mobile_ui._limit
        mobile_ui._shownPage = CurrentPageName(mainView)
        mobile_ui._shownState = _WindowStateName(mainView)
    except Exception as es:
        Log.Error(es)
    return


def Apply(mainView):
    """ 主窗口创建后调用一次 """
    if not IsEnabled():
        return
    mobile_ui._mainView = mainView
    try:
        # 主题 QSS 已在 main_view 构造里 LoadSetting 时应用：这里把窗口擦除底色对齐主题，
        # 否则 resize 时 Qt 用默认(白)调色板擦背景 -> 用户看到一下白闪
        _ApplyAndroidBackground(mainView)
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
        # 前后台切换：进后台刷最后一帧(多任务快照要有内容)、回前台重绘(防黑屏)
        mobile_ui.InstallAppStateHook(mainView)
        mobile_ui.ReflowPortrait(getattr(mainView, "subStackWidget", None))
        mobile_ui.InstallReflowHook(mainView)
        # 首页/其它页面里的 QTabWidget(分区标签)：换页后按真实视口重排封面
        # (标签条本身的横划滚动在 InstallTouchGuard 的滑动守卫里，见 mobile_ui_touch)
        mobile_ui.InstallTabReflowHook(mainView)
        # 记下这次全量适配的尺寸：紧跟着的 showEvent/回后台再回来，只要签名没变
        # 就只重绘(启动时把整套重排再跑一遍，页面会明显闪一下)
        mobile_ui._adaptWidth = mainView.width()
        mobile_ui._adaptLimit = mobile_ui._limit
        _RememberAdapted(mainView)
        Log.Warn("mobile ui adapted, limit:{} size:{}x{} bg={}".format(
            mobile_ui._limit, mainView.width(), mainView.height(),
            mainView.palette().color(QPalette.ColorRole.Window).name()))
    except Exception as es:
        Log.Error(es)


def OnShown(mainView):
    """ 窗口首次显示 / 从后台回到前台时调用：重新计算尺寸并适配

    **必须便宜且幂等**：Android 上从后台回来、软键盘收起、Activity 恢复都会走到这里。
    原来每次都跑整套重排(放宽最小尺寸 + 重算封面宽 + 全栈 ReflowPortrait + 自检)，
    所以"从多任务切回来"、"软键盘收起"时页面会闪一下。现在只有
    窗口宽 / 最小宽度上限 / 页面 / 窗口状态 真的变了才重排，否则只更新便宜几何 +
    重绘一帧。
    """
    if not IsEnabled() or mainView is None:
        return
    try:
        _ApplyAndroidBackground(mainView)
        width, height = mainView.width(), mainView.height()
        state = _WindowStateName(mainView)
        page = CurrentPageName(mainView)
        limit = mobile_ui.UpdateLimit(mainView)
        # 只有"宽度相关"的变化才需要重排：高度变化(软键盘弹出/分屏上下拖动)不会让
        # 任何一行从放得下变成放不下，重排只会让页面跳一下(见 OnSizeSettled 同样的判断)
        needRelayout = (width != mobile_ui._shownWidth or limit != mobile_ui._shownLimit
                        or page != mobile_ui._shownPage or state != mobile_ui._shownState)
        LogUiEvent("shown: {}x{} windowState={} page={} limit={} bg={} {}".format(
            width, height, state, page, limit,
            mainView.palette().color(QPalette.ColorRole.Window).name(),
            "relayout" if needRelayout else "skip(unchanged)"))
        # 装配 + 便宜几何：都带 _jm 标记或只是几何计算，重复调用是空操作。
        # 旋转/首次显示后"抽屉压住顶栏"之类的历史问题靠它们兜底，所以两条路径都跑。
        mobile_ui.SetupDrawer(mainView)
        mobile_ui.UpdateDrawerGeometry(mainView)
        mobile_ui.StackSrTool(getattr(mainView, "waifu2xToolView", None), mainView)
        mobile_ui.UpdateSrToolHeight(getattr(mainView, "waifu2xToolView", None), mainView)
        mobile_ui.SetupReadTool(getattr(mainView, "readView", None))
        if needRelayout:
            # 尺寸/页面/窗口状态真的变了：这时候重排不会"闪"，因为页面本来就要换样
            mobile_ui._adaptWidth = width
            mobile_ui._adaptLimit = limit
            mobile_ui.RelaxMinSizes(mainView, limit)
            mobile_ui.StackSideNavs(mainView)
            mobile_ui.StackSettingNav(getattr(mainView, "settingView", None))
            mobile_ui.ApplyGridCoverSize(mainView)
            mobile_ui.ReflowPortrait(getattr(mainView, "subStackWidget", None))
            mobile_ui.EnableTouchScroll(mainView)
            mobile_ui.InstallScrollWatcher(mainView)
            mobile_ui.InstallTabReflowHook(mainView)
            # 重排后先激活布局再整窗刷新一次(合成到下一帧)；不再冻结/强刷
            _FinishRelayout(mainView)
        else:
            # 尺寸没变：只把当前这一帧重绘出去(多任务快照/回前台防黑屏由调用方负责)
            mainView.update()
        _RememberAdapted(mainView)
    except Exception as es:
        Log.Error(es)
    # 真机自检/诊断钩子：标记文件触发，没有标记时只是一次 os.path.exists；
    # 放在重排分支之外，保证任何一次 OnShown 都能等到标记(不改原有触发语义)。
    for hook in (mobile_ui.MaybeSelfTest, mobile_ui.MaybeTouchSelfTest,
                 mobile_ui.MaybeDeviceVerify, mobile_ui.MaybeReaderSelfTest,
                 mobile_ui.MaybeKeyDiag):
        try:
            hook(mainView)
        except Exception as es:
            Log.Error(es)
    return


def OnResize(mainView):
    """ 尺寸变化(旋转屏幕、软键盘弹出/收起、分屏、自由窗口拖动)后调用

    这里只做"必须立刻生效、又不动布局树"的便宜几何更新(抽屉位置/宽度、超分面板
    限高)；最小尺寸放宽、封面宽重算、整页重排这些重活交给空闲去抖的 OnSizeSettled：
    一串 resize 只做一次，而不是每帧一次。
    """
    if not IsEnabled() or mainView is None:
        return
    try:
        mobile_ui._resizeEvents += 1
        mobile_ui.UpdateLimit(mainView)
        mobile_ui.UpdateDrawerGeometry(mainView)
        mobile_ui.UpdateSrToolHeight(getattr(mainView, "waifu2xToolView", None), mainView)
        ScheduleSizeSettled(mainView)
    except Exception as es:
        Log.Error(es)
    return


def ScheduleSizeSettled(mainView):
    """ 排一次"尺寸停下来之后"的适配(连续 resize 会不断推迟到停下为止) """
    if mainView is None:
        return
    try:
        timer = mobile_ui._resizeTimer
        if timer is None:
            timer = QTimer()
            timer.setSingleShot(True)
            timer.setInterval(ResizeSettleMs)
            timer.timeout.connect(_FlushSizeSettled)
            mobile_ui._resizeTimer = timer
        mobile_ui._resizeTarget = mainView
        # 对已在计时的单次定时器，start() 就是重新计时：resize 不停就一直往后推，
        # 直到最后一次 resize 之后 ResizeSettleMs 没有新事件才真正跑一次适配
        timer.start()
    except Exception as es:
        Log.Error(es)
    return


def _FlushSizeSettled():
    mainView = mobile_ui._resizeTarget
    mobile_ui._resizeTarget = None
    OnSizeSettled(mainView)
    return


def OnSizeSettled(mainView):
    """ 尺寸稳定后的**唯一一次**适配：按"变的是宽还是高"决定做多少

    真机现象(本次修复的主目标)：
      * 点输入框弹出软键盘 -> 窗口只变矮 -> 原来每个 resize 事件都全量重排，
        列表还重新算了一遍封面(日志: "520 个封面改为一行 2 个")，页面闪一下；
      * 分屏/小窗拖动 -> 每帧一次全量重排，整页持续闪。
    现在：宽度没变(软键盘、分屏上下拖动)就完全不碰布局树；宽度变了才放宽最小尺寸、
    重算封面宽、重排整页 —— 而且一整串 resize 只做一次。
    """
    if not IsEnabled() or mainView is None:
        return
    if not mainView.isVisible():
        # 已经不可见了(比如 resize 之后马上被切走)：回前台时 OnShown 会按签名补一次
        return
    try:
        _ApplyAndroidBackground(mainView)
        width, height = mainView.width(), mainView.height()
        page = CurrentPageName(mainView)
        limit = mobile_ui.UpdateLimit(mainView)
        landscape = width > height
        events = mobile_ui._resizeEvents
        mobile_ui._resizeEvents = 0
        widthChanged = width != mobile_ui._adaptWidth
        limitChanged = limit != mobile_ui._adaptLimit
        mobile_ui._adaptWidth = width
        mobile_ui._adaptLimit = limit
        # 布局已经按这个尺寸适配过了(OnShown 也认这个签名)，回前台时别再重排一次
        _RememberAdapted(mainView)
        if not widthChanged and not limitChanged:
            # 只变了高度(软键盘弹出/收起、分屏上下拖动)：宽度相关的排版全部还成立，
            # 不重算封面宽、不放宽最小尺寸、不重排整页，也就不会闪。
            Log.Warn("resize: {}x{} limit={} landscape={} page={} events={} bg={} updates={} -> height-only, skip relayout".format(
                width, height, limit, landscape, page, events,
                mainView.palette().color(QPalette.ColorRole.Window).name(),
                mainView.updatesEnabled()))
            return
        mobile_ui.UpdateDrawerGeometry(mainView)
        if limitChanged:
            # limit 是"最小宽度上限"：只有它变小了，才可能有新的控件需要放宽
            mobile_ui.RelaxMinSizes(mainView, limit)
        mobile_ui.ResetGridCover()
        mobile_ui.ApplyGridCoverSize(mainView)
        mobile_ui.ReflowPortrait(getattr(mainView, "subStackWidget", None))
        # 重排后先激活布局再整窗刷新一次(不冻结、不强刷，合成到下一帧)
        _FinishRelayout(mainView)
        Log.Warn("resize: {}x{} limit={} landscape={} page={} events={} bg={} updates={} -> relayout".format(
            width, height, limit, landscape, page, events,
            mainView.palette().color(QPalette.ColorRole.Window).name(),
            mainView.updatesEnabled()))
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
       并强制重绘一次。重排本身是**幂等**的(尺寸/页面/窗口状态没变时 OnShown 只重绘)，
       否则每次回前台都把整页重排一遍，用户看到的就是"切回来闪一下"。
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
                # 回到前台：OnShown 只会在尺寸/页面/窗口状态真的变了时重排(否则只重绘)，
                # 再整窗强制重绘一次(防黑屏)
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
