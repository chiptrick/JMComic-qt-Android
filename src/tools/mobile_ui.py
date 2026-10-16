# coding:utf-8
""" 手机竖屏/触摸界面适配层（模块状态 + 门面）

只在 Android(platform_mobile.IsAndroid()) 下生效，桌面端不会调用这里，
因此桌面端的布局与交互保持原样(不影响主要功能)。

适配内容：
    1. 左侧固定 240px 导航栏 -> 抽屉式浮动面板(竖屏下不挤压内容宽度)
    2. 对话框/页面里写死的过宽最小尺寸 -> 按屏幕宽度自动放宽
    3. 漫画详情页/设置页/分流设置页 等"左导航 + 右内容"左右并排 -> 上下堆叠
    4. 滚动区域全部支持手指拖动(动量滚动)
    5. 顶部分页按钮在窄屏下压缩字号，避免溢出
    6. 触摸防误触：滑动永远不会触发手指下的控件(下拉框/数值框/勾选框)
    7. 返回键:先收菜单/抽屉 -> 再退出看图 -> 再回退页面 -> 最后退到后台
    8. 看图界面的工具菜单改为整宽(原来固定 400px，在 384px 屏上跑到屏幕外)
    9. 首页/列表每行放 2 个封面(原来按桌面 250px 封面尺寸只放得下 1 个)
   10. 顶层窗口的 show/hide 延后到当前输入事件处理结束(见 DeferCall 注释)
   11. 首页顶部的"分区"标签条支持手指横划滚动 + 惯性(与所有滑动共用一套判定，用合成的像素滚轮事件驱动，见 mobile_ui_touch)；切分区后按新页的真实视口宽重排封面
       (隐藏页的列表视口是"没布局过"的假值，见 mobile_ui_grid.ReflowGridCoverForPage)
   12. 后建出来的滚动区域(首页分区页、详情页/设置页里的滚动区、看图工具菜单等)自动接管手指滚动：
       这些页面是网络回来后/进详情页时才建的，Apply/OnShown 那一次全量扫描够不着它们，
       真机现象就是"首页只有最新上传能滑"(见 mobile_ui_touch._ScrollWatcher)

实现按关注点拆到同目录的 `mobile_ui_*.py`(base/hooks/window/drawer/layout/
reader/grid/touch/diag)；本模块只持有会话级可变状态，并对外保持
`mobile_ui.X` 门面(`__getattr__` 惰性转发)。所有会话级可变状态都定义在本模块，
子模块通过 `mobile_ui.<name>` 读写它，因此外部(含 android/tools 下的宿主回归)
对 `mobile_ui.<name>` 的读取/写入语义不变，`from tools import mobile_ui` /
`mobile_ui.X` 的调用方式也不变。 """
from tools.mobile_ui_base import *  # noqa: F401,F403
from tools.mobile_ui_base import (_DescribeWidget, _GuardMode, _InPopup, _InTouchArea, _IsDescendant, _SelfAndChildren, _WidgetAlive, _WindowType)

# self-correct 之后定下来的封面宽：后加的 item(翻页)直接用它，避免又变回一行 1 个
_gridCoverFinal = 0
# 上面那个封面宽是按多大的视口算出来的：视口变了(旋转/改窗口大小)必须重算，
# 否则横屏量出来的宽会被拿到竖屏用 -> 又变回一行 1 个
_gridCoverAvail = 0
# 列表视口的真实宽度(空列表也能量出来)。用它比用"页面宽度"准得多：
# 真机上页面 384px，而列表视口只有 330~338px(边距+滚动条+父级边框)。
_gridAvail = 0
_gridPending = []
_gridTimer = None


_filter = None
_limit = MinWidthLimit
_mainView = None
# 按键/窗口事件诊断开关(<AppDataDir>/device_keys 标记)：真机上"返回键到底有没有
# 到 Qt 窗口"、"白屏之前窗口发生了什么"只能靠把事件打出来判断。
_keyDiagEnabled = False
KeyDiagStats = {"key": 0, "window": 0, "back": 0}


def CurrentLimit():
    return _limit


def UpdateLimit(mainView):
    """ 根据当前窗口宽度计算可用的最小宽度上限 """
    global _limit
    width = mainView.width()
    if width <= 0:
        width = mainView.sizeHint().width()
    if width <= 0:
        width = MinWidthLimit
    _limit = max(240, min(MinWidthLimit, width - 24))
    return _limit


# ---------------------------------------------------------------------------
# 看图区拖动滚动
# ---------------------------------------------------------------------------
#
# 真机现象："看图界面无法滚动"。看图区是 QGraphicsView，桌面端只支持滚轮
# (wheelEvent)，触摸设备既没有滚轮也没有拖动实现：
#   * QGraphicsView 设的是 NoDrag(不做 ScrollHandDrag)
#   * 场景的鼠标事件只用来识别"点按三分区"(而且要求 |dx| <= 20 才算点按)
# 所以手指在图片上拖动毫无反应(菜单面板是另一个滚动区，那是另一回事)。
#
# 这里直接把拖动位移喂给和滚轮**同一条**路径(ReadScroll.scrollValue)，
# 顺带复用滚轮那套"到页尾自动翻页"的逻辑；点按(|dx|、|dy| 都小于阈值)完全不碰，
# 原来的三分区点按逻辑一点不变。

_readerDrag = None


# ---------------------------------------------------------------------------
# 滑动只有一处：`_TouchGuard` 这个 App 级过滤器把每一次手指滑动只判定一次
# (点按 / 滚动 / 标签条横划)，点按再原样重放给控件；滚动区域的手势交给 Qt 自己的
# QScroller(见 mobile_ui_touch.EnableTouchScroll)，只有 QTabBar 没有公开的偏移
# API，才用合成的"逐像素滚轮事件"驱动(见 mobile_ui_touch._TabBarScroll)。
#
# 触摸防误触(tap guard)
# ---------------------------------------------------------------------------
#
# 真机现象：
#   * 在设置页手指上滑，滑的过程中设置被改掉(勾选框被切换)
#   * 在"下拉菜单的选项框"和"数值选项框"**附近**滑动也会误触它们
#
# 原因是 Qt 把触摸合成为鼠标事件后**直接投给手指下的那个子控件**，而这些控件
#   * QComboBox 在 **press** 时就弹出下拉列表，
#   * QAbstractSpinBox 在 **press** 时就开始加减数值，并且按住不放会**自动重复**，
#     它的自动重复只认 mouseReleaseEvent —— 把 release 吃掉反而会让数值一直加下去，
#   * QAbstractButton(勾选框/单选/按钮)在 release 时切换，
# 于是"滚动的起手动作"被当成了点击。
#
# 做法(只在移动端、只作用于"已接管手指滚动"的滚动区域里的控件)：
#   1. 按下时先**扣住 press**，不发给控件，只记下位置
#   2. 位移超过 TouchSlopPx 判定为滚动：丢弃这次 press，什么都不做(控件完全不知情)
#   3. 位移没超阈值判定为点按：把记下的 press+release 原样**重放**给控件
#      (控件看到的和自己收到一次真实点击完全一样，语义零变化)
# 这样滑动永远不会触发控件，点按和以前一模一样。
#
# 例外(走旧的"扣住 release"策略，不能扣 press)：
#   * QSlider / QScrollBar 需要真正的 press-drag(拖把手/滑块)
#   * QAbstractScrollArea 的视口 / QAbstractItemView 自己要处理按下拖动
#     (列表项的按下拖动、QScroller 的鼠标手势都在 press 上)
#   * Qt::Popup 弹窗(下拉列表、右键菜单)里的点击/滚动不拦，否则列表没法点

_touchGuard = None

# "后来才建的滚动区域自动接管"(见 mobile_ui_touch._ScrollWatcher)
_scrollWatcher = None


# ---------------------------------------------------------------------------
# 顶层窗口显示/隐藏守卫 + 返回键
# ---------------------------------------------------------------------------
#
# 两个真机问题都出在"顶层窗口/Activity"这一层：
#
# 1) 崩溃：改设置时弹"保存成功"提示条(MsgLabel 是一个独立顶层窗口)、切页签时弹
#    加载框(LoadingDialog)、点"选择模型"弹遮罩对话框，这些都是在**输入事件处理
#    过程中**同步 show()，Qt 会在 QWindowPrivate::setVisible -> show_sys 里同步
#    flush 窗口系统事件 -> 立刻派发 Expose -> 立刻 paint ->
#    QAndroidPlatformOpenGLWindow::eglSurface() 重入 ->
#    'Failed to acquire deadlock protector for ... eglSurface()' -> SIGABRT。
#    (真机栈: QTabBar::mousePressEvent -> python 槽 -> QDialog::setVisible ->
#     QPlatformWindow::setVisible -> flushWindowSystemEvents -> paintAndFlush ->
#     rhiFlush -> makeCurrent -> eglSurface -> abort)
#
#    注意：QEvent.Show 是在 show_sys() **之后**才发的，所以在事件过滤器里拦
#    Show 事件根本来不及(平台窗口已经建好、flush 已经发生)。必须拦在
#    "调用 show()" 这一层 —— PySide6 允许从 Python 侧替换 Qt 类的方法，
#    所以这里直接给 QWidget.show/hide 套一层"延后到当前输入事件处理结束"。
#
# 2) 返回键：Android 的返回键 = Qt.Key_Back(按下)+release。原来只在
#    keyReleaseEvent 里处理，优先级只有"退出看图/收抽屉/回退页面"三档：
#      * 看图界面的工具菜单(是个子控件，不是窗口)收不起来
#      * 根页面上什么都不做，事件继续往下走，最后 Activity 被 finish，
#        Python 侧 app.exec() 返回、主线程退出，但 Activity 还留在前台 ->
#        **白屏**(用户看到的)
#    现在统一在 mobile_ui.HandleBackKey 里按优先级处理并吃掉事件。

_showDeferralInstalled = False
_showDeferralOrigin = {}
ShowDeferralStats = {"deferred": 0, "shown": 0, "hidden": 0, "closed": 0}


# -- 返回键 -----------------------------------------------------------------

BackStats = {"count": 0, "action": "", "last": "", "minimize": 0, "quit": 0}
_backLastTick = 0.0


# ---------------------------------------------------------------------------
# 门面：子模块里的函数按需惰性转发
# ---------------------------------------------------------------------------
_SUBMODULES = (
    "mobile_ui_hooks",
    "mobile_ui_window",
    "mobile_ui_drawer",
    "mobile_ui_layout",
    "mobile_ui_reader",
    "mobile_ui_grid",
    "mobile_ui_touch",
    "mobile_ui_diag",
)

_MISSING = object()


def __getattr__(name):
    """ 惰性把未在本模块定义的符号转发到对应子模块(见模块文档) """
    if name.startswith("__") and name.endswith("__"):
        raise AttributeError(name)
    import importlib
    for modName in _SUBMODULES:
        try:
            module = importlib.import_module("tools." + modName)
        except Exception:
            continue
        value = getattr(module, name, _MISSING)
        if value is not _MISSING:
            globals()[name] = value
            return value
    raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
