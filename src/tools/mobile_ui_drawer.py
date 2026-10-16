# coding:utf-8
""" 导航抽屉（竖屏把左侧固定导航栏改为浮动抽屉） """
from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QWidget
from tools.log import Log
from tools.mobile_ui_base import *  # noqa: F401,F403



class _DrawerScrim(QWidget):
    """ 抽屉遮罩层：点空白处关闭菜单

    真机上原来根本没有"点外部关闭"的处理，抽屉一打开就只能靠返回键或无路可走。
    """

    def __init__(self, mainView):
        super().__init__(mainView.subMainWindow)
        self._mainView = mainView
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 110);")
        self.hide()

    def mousePressEvent(self, event):
        CloseDrawer(self._mainView)
        return


def _TopOffset(mainView, subWindow):
    """ 抽屉顶部要避开顶栏，否则会盖住"菜单"按钮(真机上表现为菜单键消失) """
    for name in ("menuButton", "label"):
        widget = getattr(mainView, name, None)
        if widget is None:
            continue
        try:
            local = subWindow.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
            top = local.y() + widget.height()
            if top > 0:
                return top
        except Exception:
            continue
    return 0


def SetupDrawer(mainView):
    """ 导航栏改为浮动抽屉：手机竖屏下不再占用 240px 内容宽度 """
    nav = getattr(mainView, "navigationWidget", None)
    layout = getattr(mainView, "horizontalLayout_2", None)
    subWindow = getattr(mainView, "subMainWindow", None)
    if nav is None or layout is None or subWindow is None:
        return
    if getattr(nav, "_jmDrawer", False):
        UpdateDrawerGeometry(mainView)
        return

    layout.removeWidget(nav)
    nav.setParent(subWindow)
    nav.setMinimumWidth(0)
    nav.setMaximumWidth(DrawerMaxWidth)
    nav._jmDrawer = True
    nav.hide()
    # 点空白处关闭抽屉的遮罩层
    mainView._jmDrawerScrim = _DrawerScrim(mainView)
    # 尺寸变化时同步抽屉/遮罩几何
    mainView.WindowsSizeChange.connect(lambda: UpdateDrawerGeometry(mainView))
    UpdateDrawerGeometry(mainView)
    return


def UpdateDrawerGeometry(mainView):
    """ 重算抽屉与遮罩的位置

    注意：这里刻意不用 setFixedWidth —— 它会把宽度锁死，和导航栏基类
    aniShow/aniHide 的宽度动画互相打架(动画被夹到固定值，实际没有动画效果)。
    """
    nav = getattr(mainView, "navigationWidget", None)
    subWindow = getattr(mainView, "subMainWindow", None)
    if nav is None or subWindow is None or not getattr(nav, "_jmDrawer", False):
        return
    width = int(min(DrawerMaxWidth, max(220, mainView.width() * DrawerWidthRatio)))
    top = _TopOffset(mainView, subWindow)
    height = max(0, subWindow.height() - top)
    nav._jmDrawerWidth = width
    nav._jmDrawerTop = top
    scrim = getattr(mainView, "_jmDrawerScrim", None)
    if scrim is not None:
        scrim.setGeometry(0, top, subWindow.width(), height)
    if not nav.isHidden():
        nav.setGeometry(0, top, width, height)
        nav.raise_()
        if scrim is not None:
            scrim.raise_()
            nav.raise_()
    return


def IsDrawerOpen(mainView):
    nav = getattr(mainView, "navigationWidget", None)
    if nav is None or not getattr(nav, "_jmDrawer", False):
        return False
    return not nav.isHidden()


def OpenDrawer(mainView):
    nav = getattr(mainView, "navigationWidget", None)
    if nav is None or not getattr(nav, "_jmDrawer", False):
        return False
    UpdateDrawerGeometry(mainView)
    top = getattr(nav, "_jmDrawerTop", 0)
    width = getattr(nav, "_jmDrawerWidth", DrawerMaxWidth)
    height = max(0, mainView.subMainWindow.height() - top)
    scrim = getattr(mainView, "_jmDrawerScrim", None)
    if scrim is not None:
        scrim.show()
        scrim.raise_()
    nav.show()
    nav.setGeometry(0, top, width, height)
    nav.raise_()
    ani = _DrawerAni(nav)
    ani.stop()
    ani.setDuration(DrawerAniMs)
    ani.setEasingCurve(QEasingCurve.Type.OutCubic)
    ani.setStartValue(QPoint(-width, top))
    ani.setEndValue(QPoint(0, top))
    ani.start()
    return True


def _DrawerAni(nav):
    """ 复用挂在导航栏上的位移动画(只动 x，不动宽度，避免与基类冲突) """
    ani = getattr(nav, "_jmDrawerAni", None)
    if ani is None:
        ani = QPropertyAnimation(nav, b"pos", nav)
        nav._jmDrawerAni = ani
    return ani


def CloseDrawer(mainView):
    """ 切换界面/按返回键/点空白处后收起抽屉 """
    nav = getattr(mainView, "navigationWidget", None)
    if nav is None or not getattr(nav, "_jmDrawer", False):
        return
    scrim = getattr(mainView, "_jmDrawerScrim", None)
    if scrim is not None:
        scrim.hide()
    if nav.isHidden():
        return
    width = getattr(nav, "_jmDrawerWidth", DrawerMaxWidth)
    top = getattr(nav, "_jmDrawerTop", 0)
    ani = _DrawerAni(nav)
    ani.stop()
    ani.setDuration(DrawerAniMs)
    ani.setEasingCurve(QEasingCurve.Type.InCubic)
    ani.setStartValue(nav.pos())
    ani.setEndValue(QPoint(-width, top))
    ani.start()
    # 兜底：动画被打断(快速连点等)时也要真正隐藏，否则抽屉会一直留在屏幕上
    QTimer.singleShot(DrawerAniFallbackMs, lambda: _HideDrawer(nav))
    return


def ToggleDrawer(mainView):
    """ 点"菜单"按钮：返回 True 表示移动端已接管(桌面端返回 False，走原逻辑) """
    if not IsEnabled():
        return False
    if IsDrawerOpen(mainView):
        CloseDrawer(mainView)
    else:
        OpenDrawer(mainView)
    return True


def _HideDrawer(nav):
    try:
        ani = getattr(nav, "_jmDrawerAni", None)
        if ani is not None:
            ani.stop()
        if not nav.isHidden():
            nav.hide()
    except Exception as es:
        Log.Error(es)
    return
