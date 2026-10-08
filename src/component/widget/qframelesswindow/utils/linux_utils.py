# coding: utf-8
from enum import Enum

# 注意：xcffib / QtX11Extras 只存在于 Linux 桌面环境。Android 打包时
# (pyside6-android-deploy) 会静态扫描源码里的 PySide6 模块字样来决定要打包哪些
# Qt 模块，而 Android 的 PySide6 wheel 里并没有这个 X11 模块，会让打包直接失败。
# 所以这里用 importlib + 拼字符串的方式动态导入，源码里不出现该模块名的字面量。
import importlib

xcb = None
QX11Info = None
ButtonIndex = ButtonMask = ButtonReleaseEvent = None
ClientMessageData = ClientMessageEvent = EventMask = xprotoExtension = None
try:  # pragma: no cover - 仅 Linux/X11 桌面会成功
    xcb = importlib.import_module("xcffib")
    _xproto = importlib.import_module("xcffib.xproto")
    _x11mod = importlib.import_module("PySide6.Qt" + "X11Extras")
    QX11Info = _x11mod.QX11Info
    ButtonIndex = _xproto.ButtonIndex
    ButtonMask = _xproto.ButtonMask
    ButtonReleaseEvent = _xproto.ButtonReleaseEvent
    ClientMessageData = _xproto.ClientMessageData
    ClientMessageEvent = _xproto.ClientMessageEvent
    EventMask = _xproto.EventMask
    xprotoExtension = _xproto.xprotoExtension
except Exception:
    pass

from PySide6 import sip
from PySide6.QtCore import QPointF, Qt, QEvent, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QWidget, QApplication


class WindowMessage(Enum):
    """ Window message enum class """
    # refer to: https://specifications.freedesktop.org/wm-spec/1.1/x170.html
    _NET_WM_MOVERESIZE_SIZE_TOPLEFT = 0
    _NET_WM_MOVERESIZE_SIZE_TOP = 1
    _NET_WM_MOVERESIZE_SIZE_TOPRIGHT = 2
    _NET_WM_MOVERESIZE_SIZE_RIGHT = 3
    _NET_WM_MOVERESIZE_SIZE_BOTTOMRIGHT = 4
    _NET_WM_MOVERESIZE_SIZE_BOTTOM = 5
    _NET_WM_MOVERESIZE_SIZE_BOTTOMLEFT = 6
    _NET_WM_MOVERESIZE_SIZE_LEFT = 7
    _NET_WM_MOVERESIZE_MOVE = 8
    _NET_WM_MOVERESIZE_SIZE_KEYBOARD = 9
    _NET_WM_MOVERESIZE_MOVE_KEYBOARD = 10
    _NET_WM_MOVERESIZE_CANCEL = 11


class LinuxMoveResize:
    """ Tool class for moving and resizing window """

    moveResizeAtom = None

    @classmethod
    def sendButtonReleaseEvent(cls, window, globalPos):
        """ send button release event

        Parameters
        ----------
        window: QWidget
            window to be moved or resized

        globalPos: QPoint
            the global point of mouse release event
        """
        globalPos = QPointF(QPointF(globalPos) *
                            window.devicePixelRatio()).toPoint()
        pos = window.mapFromGlobal(globalPos)

        # open the connection to X server
        conn = xcb.wrap(sip.unwrapinstance(QX11Info.connection()))
        windowId = int(window.winId())
        xproto = xprotoExtension(conn)

        # refer to: https://www.x.org/releases/X11R7.5/doc/libxcb/tutorial/
        event = ButtonReleaseEvent.synthetic(
            detail=ButtonIndex._1,
            time=xcb.CurrentTime,
            root=QX11Info.appRootWindow(QX11Info.appScreen()),
            event=windowId,
            child=xcb.NONE,
            root_x=globalPos.x(),
            root_y=globalPos.y(),
            event_x=pos.x(),
            event_y=pos.y(),
            state=ButtonMask._1,
            same_screen=True,
        )
        xproto.SendEvent(True, windowId, EventMask.ButtonRelease, event.pack())
        conn.flush()

    @classmethod
    def startSystemMoveResize(cls, window, globalPos, message):
        """ resize window

        Parameters
        ----------
        window: QWidget
            window to be moved or resized

        globalPos: QPoint
            the global point of mouse release event

        message: int
            window message
        """
        cls.sendButtonReleaseEvent(window, globalPos)

        globalPos = QPointF(QPointF(globalPos) *
                            window.devicePixelRatio()).toPoint()

        # open the connection to X server
        conn = xcb.wrap(sip.unwrapinstance(QX11Info.connection()))
        xproto = xprotoExtension(conn)

        if not cls.moveResizeAtom:
            cls.moveResizeAtom = xproto.InternAtom(
                False, len("_NET_WM_MOVERESIZE"), "_NET_WM_MOVERESIZE").reply().atom

        union = ClientMessageData.synthetic([
            globalPos.x(),
            globalPos.y(),
            message,
            ButtonIndex._1,
            0
        ], "I"*5)
        event = ClientMessageEvent.synthetic(
            format=32,
            window=int(window.winId()),
            type=cls.moveResizeAtom,
            data=union
        )
        xproto.UngrabPointer(xcb.CurrentTime)
        xproto.SendEvent(
            False,
            QX11Info.appRootWindow(QX11Info.appScreen()),
            EventMask.SubstructureRedirect | EventMask.SubstructureNotify,
            event.pack()
        )
        conn.flush()

    @classmethod
    def startSystemMove(cls, window, globalPos):
        """ move window """
        if QX11Info.isPlatformX11():
            cls.startSystemMoveResize(
                window, globalPos, WindowMessage._NET_WM_MOVERESIZE_MOVE.value)
        else:
            window.windowHandle().startSystemMove()
            event = QMouseEvent(QEvent.MouseButtonRelease, QPoint(-1, -1),
                                Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
            QApplication.instance().postEvent(window.windowHandle(), event)

    @classmethod
    def starSystemResize(cls, window, globalPos, edges):
        """ resize window

        Parameters
        ----------
        window: QWidget
            window

        globalPos: QPoint
            the global point of mouse release event

        edges: `Qt.Edges`
            window edges
        """
        if not edges:
            return

        if QX11Info.isPlatformX11():
            messageMap = {
                Qt.TopEdge: WindowMessage._NET_WM_MOVERESIZE_SIZE_TOP,
                Qt.TopEdge | Qt.LeftEdge: WindowMessage._NET_WM_MOVERESIZE_SIZE_TOPLEFT,
                Qt.TopEdge | Qt.RightEdge: WindowMessage._NET_WM_MOVERESIZE_SIZE_TOPRIGHT,
                Qt.BottomEdge: WindowMessage._NET_WM_MOVERESIZE_SIZE_BOTTOM,
                Qt.BottomEdge | Qt.LeftEdge: WindowMessage._NET_WM_MOVERESIZE_SIZE_BOTTOMLEFT,
                Qt.BottomEdge | Qt.RightEdge: WindowMessage._NET_WM_MOVERESIZE_SIZE_BOTTOMRIGHT,
                Qt.LeftEdge: WindowMessage._NET_WM_MOVERESIZE_SIZE_LEFT,
                Qt.RightEdge: WindowMessage._NET_WM_MOVERESIZE_SIZE_RIGHT,
            }
            cls.startSystemMoveResize(window, globalPos, messageMap[edges].value)
        else:
            window.windowHandle().startSystemResize(edges)
