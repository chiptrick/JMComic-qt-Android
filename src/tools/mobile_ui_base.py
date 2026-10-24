# coding:utf-8
""" 竖屏/触摸适配的公共常量与无状态工具 """
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtWidgets import QAbstractButton, QAbstractScrollArea, QAbstractSpinBox, QComboBox, QScrollBar, QSlider, QTabBar, QWidget
from tools.log import Log
from tools import platform_mobile


# 竖屏下允许的最小控件宽度(比这更宽的都会被放宽)
MinWidthLimit = 320
# 抽屉宽度占屏幕比例
DrawerWidthRatio = 0.82
DrawerMaxWidth = 300
# 抽屉滑入/滑出动画时长，以及兜底隐藏时间
DrawerAniMs = 120
DrawerAniFallbackMs = 260
# 手指滑动的判定阈值(逻辑像素)。小于它的位移仍然按"点按"处理(走控件公开入口
# 激活)，大于它的位移一律视为滚动，不触发任何控件。
TouchSlopPx = 16
# 翻页模式(单页/双页/等宽，非滚动)下"滑动翻页"的触发阈值(逻辑像素)：单指在
# **翻页轴向上**、以按下位置为基准的累计位移要超过它才翻一页。比拖动判定
# (TouchSlopPx)大一号是故意的：刚过拖动阈值的小动作更像误触，不翻页；
# 一定要是"果断的一划"才翻。翻页模式下**一次手势最多翻一页**：翻过之后本手势
# 直接作废(继续滑/反方向滑都不再翻)，想继续翻必须重新按下 —— 与"点按一下翻
# 一页/滚轮一格翻一页"一一对应，杜绝"一滑跳过好几页"。滚动模式是连续滚动、
# 没有"一页一翻"的语义，不走这个阈值(见 mobile_ui_reader._Scroll)。
TurnPageSlopPx = 32
# 同一次 TouchBegin 会在父级链上重复投递(毫秒级)，这个窗口内同 id 的按下算"同一次"。
# 超过这个窗口还挂着同 id 的旧序列，说明抬手事件丢了(触点被销毁/被系统抢走)：
# 必须当成新的一次手势重来，否则这个触点永远进不了判定，输入框再也拿不到合成鼠标。
TouchSeqRestartSec = 0.35
# 残留序列的兜底寿命(秒)：超过就直接丢掉(手指不可能按这么久还等着收尾)
TouchSeqStaleSec = 8.0
# 触摸自检的观察窗口(秒)
TouchSelfTestSeconds = 120
# QWidget 的"无上限"宽度
WidgetSizeMax = 16777215
# 返回键去抖(毫秒)：Android 会同时给按下和抬起两个事件，连点也要吞掉
BackDebounceMs = 400
# 首页/列表每行放几个封面(竖屏)
GridColumns = 2
# 封面最小/最大宽度(逻辑像素)
GridCoverMin = 96
GridCoverMax = 240
# item widget 自己的边距/标签所占的额外宽度 + 安全余量。
# 实测：宿主 18px、真机 12px(字体/布局不同)，取 36 是为了保证**首次**算出来的封面
# 一定能放下 2 个(后面还有 self-correct 会继续收紧)。只算封面宽是不够的：
# QListWidget 是按整个 item 的 sizeHint 装箱的。
GridItemOverhead = 36
# "刚加完一批漫画"的去抖重排(见 ScheduleGridCoverSize)。
# 首页的漫画是网络回来后一条条 AddBookItem 的，建控件时用的是那一刻的封面宽；
# 之前只有 shown/切页才会重排，于是首屏那批 item 建完后就没人再纠正了。
GridScheduleMs = 80
# QTabWidget 换页(首页的"分区"标签)之后，等 Qt 把新页的几何摆好再重排一次网格(毫秒)
TabReflowMs = 60
# 标签条横划的致动自检位移(px)：喂一个像素滚轮事件，看偏移动不动
TabSelfCheckPx = 8
# 标签条横划松手后的惯性(见 mobile_ui_touch._TabSwipe.StartFling)：
# 帧间隔、速度每秒衰减到的比例、低于这个速度就停下、甩出去的速度上限(防合成事件
# 的时间抖动灌出荒谬速度)、以及"松手前手指已经停了这么久(毫秒)就当成就地放手指，不甩"
# ——衰减比取得比 QScroller 的默认值更狠：**整体必须能在 1s 出头停住**，否则真机上
# 会觉得标签条"甩出去收不住"，宿主回归里也有"惯性要在 1.5s 内自己停下来"这一条。
TabFlingIntervalMs = 16
TabFlingDecay = 0.05
TabFlingMinVelocity = 120.0
TabFlingMaxVelocity = 2500.0
TabFlingStopGapMs = 150
# 速度估计窗口(毫秒)：安卓会把一帧里的多条触摸事件合并到同一次投递里(dt≈0)，
# 攒够这个窗口再算速度，免得 dx/dt 算出天量速度、一松手就冲到尽头
TabVelocityWindowMs = 8
# 估速度时回头看多久以前的那次位移(毫秒)
TabVelocitySampleMs = 120
# "后来才建的滚动区域自动接管"(见 mobile_ui_touch._ScrollWatcher)：
# 攒住待扫控件的上限，防止一次性建几千个控件时把内存/耗时堆起来
ScrollWatchMaxPending = 512


def DeferCall(fn, ms=0):
    """ 把一次调用推迟到当前事件处理结束之后执行

    真机实测(Android/Qt6)：在**输入事件处理过程中**同步 show()/hide() 一个顶层窗口
    (MsgLabel 提示条、加载框、各种对话框)，Qt 会在 QWindowPrivate::setVisible 里
    同步 flush 窗口系统事件 -> 立刻派发 Expose -> 立刻走一遍 paint -> 最终
    QAndroidPlatformOpenGLWindow::eglSurface() 重入，直接:

        Abort message: 'Failed to acquire deadlock protector for
                        QAndroidPlatformOpenGLWindow::eglSurface().'

    (真机 SIGABRT 栈: QTabBar::mousePressEvent -> python 槽 -> QDialog::setVisible
     -> QPlatformWindow::setVisible -> flushWindowSystemEvents -> paintAndFlush ->
     rhiFlush -> makeCurrent -> eglSurface -> abort)

    设置页里"改任何选项都会弹一次保存成功提示条"，正好命中这条路径，于是每次改设置
    都崩。延后 0ms 执行，语义完全一样，但不再重入。
    """
    if fn is None:
        return
    QTimer.singleShot(max(0, int(ms)), fn)
    return


def ShouldDeferWindowShow():
    """ 移动端需要把顶层窗口的显示/隐藏延后(桌面端保持同步，行为不变) """
    return IsEnabled()


def IsEnabled():
    return platform_mobile.IsAndroid()


def _SelfAndChildren(root, cls):
    """ root 自己(如果就是 cls)+ 所有子孙里的 cls

    Qt 的 findChildren 不含自己，而调用方经常直接传"那个列表/那个控件"，
    漏掉自己就会静默什么都不做(真机/主机都踩过)。
    """
    found = []
    try:
        if isinstance(root, cls):
            found.append(root)
        found.extend(root.findChildren(cls))
    except Exception as es:
        Log.Error(es)
    return found


# 拆行后行与行之间的间距
WrapRowSpacing = 6
# 预留余量：每层布局还有自己的边距，按页面宽度直接装箱会略微溢出
WrapSafetyMargin = 12


def _InTouchArea(widget):
    """ 手指下这个控件是不是在"已接管手指滚动"的滚动区域里 """
    node = widget
    while node is not None:
        if getattr(node, "_jmTouchScroll", False):
            return True
        node = node.parentWidget()
    return False


def _DescribeWidget(widget):
    if widget is None:
        return "None"
    # 用 Class:objectName 而不是 repr —— 这行会被 verify_on_device.ps1 用正则解析
    return "{}:{}".format(type(widget).__name__, widget.objectName() or "?")


def _IsDescendant(widget, ancestor):
    """ widget 是不是 ancestor 的子孙(含自己) """
    if widget is None or ancestor is None:
        return False
    node = widget
    while node is not None:
        if node is ancestor:
            return True
        node = node.parentWidget()
    return False


def _EventLocalPos(event):
    """ 事件的本地坐标(Qt6 是 position()，老签名是 pos())。

    滑动相关的地方都用这两个函数取坐标(见 mobile_ui_touch 的"滑动只有一处")，
    免得每种滑动各自 try/except 一遍。
    """
    try:
        return QPointF(event.position())
    except Exception:
        try:
            return QPointF(event.pos())
        except Exception:
            return None


def _EventGlobalPos(event):
    """ 事件的全局坐标(判断"手指动了多少"必须用全局坐标) """
    try:
        return QPointF(event.globalPosition())
    except Exception:
        try:
            return QPointF(event.globalPos())
        except Exception:
            return None


def _WindowType(widget):
    """ 顶层窗口的"类型"部分(去掉 Window 位)

    注意不能直接写 `flags & Qt.WindowType.Popup`：Qt 的 Popup = 0x8 | Window，
    Window 位是共有的，那样写连普通主窗口都会被判成 Popup(踩过这个坑)。
    """
    try:
        flags = widget.windowFlags() & Qt.WindowType.WindowType_Mask
        return Qt.WindowType(int(flags))
    except Exception:
        return Qt.WindowType.Widget


def _InPopup(widget):
    """ 手指下的控件是不是在弹出窗口里

    下拉框弹出的列表、右键菜单、输入框补全列表都是独立弹窗(Qt::Popup)，
    有自己的点击/滚动语义，误触防护不能插手。
    """
    try:
        if not isinstance(widget, QWidget):
            return True
        window = widget.window()
        if window is None:
            return True
        return _WindowType(window) == Qt.WindowType.Popup
    except Exception:
        return True


def _TabBarAncestor(widget):
    """ 手指底下这个控件属于哪个标签条(不在标签条上则 None) """
    node = widget
    while node is not None:
        if isinstance(node, QTabBar):
            return node
        node = node.parentWidget()
    return None


def _WidgetAlive(widget):
    try:
        from shiboken6 import isValid
        return bool(isValid(widget))
    except Exception:
        return widget is not None
# 根页面连按两次返回键的间隔(毫秒)：第二次才真的退出应用
BackQuitWindowMs = 2500


def PageName(widget):
    try:
        if widget is None:
            return "?"
        title = widget.windowTitle()
        return "{}[{}]".format(type(widget).__name__, title or widget.objectName() or "?")
    except Exception:
        return "?"


def CurrentPageName(mainView):
    try:
        stack = getattr(mainView, "subStackWidget", None)
        if stack is None:
            return "?"
        return PageName(stack.currentWidget())
    except Exception:
        return "?"


def LogUiEvent(text):
    """ 把关键 UI 事件写进日志

    真机上没法看屏幕(没有 OCR)，只能靠这些行判断"用户到底停在哪个页面、
    窗口有没有真的显示出来"。行数有限，不会刷屏。
    """
    try:
        Log.Warn("ui: {}".format(text))
    except Exception:
        pass
    return
