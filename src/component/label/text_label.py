# coding:utf-8
""" 可选中文本控件的"触摸长按才选中"门卫(TextSelectGate)

要解决的问题(触摸屏桌面与 Android 真机一样中招)：
    评论文字、详情简介这些"只读但要能选中/能点链接"的文本控件开着
    TextBrowserInteraction(内含 TextSelectableByMouse)。鼠标拖拽选文本是桌面
    上要保留的功能，但手指**滑过**这些文字时，Qt 会把没人认领的触控**当场**合成
    成鼠标事件投给手指下的控件 —— press + move + release 一路下来就是一次
    "拖拽选中"。于是滑页面/滑列表时文字被莫名其妙选中(详情页简介最显眼：它自己
    还是个滚动区，一根手指滑过去既滚页面又选文字)。

目标交互：
    * 触摸：滑动 = 纯滚动，绝不选中；**长按(按住不动)** = 全选 + 弹"复制"菜单
    * 鼠标：点按 / 拖拽选择 / 双击选词 / 点链接，全部保持原样

怎么区分"触摸长按"与"鼠标操作"(两种输入互不干扰的关键)：
    1. 不引入新的输入通道，继续走 Qt 原生"未消费触控 -> 鼠标"合成：手指操作
       进来是 QTouchEvent，没人认领时 Qt 合成 QMouseEvent 投给手指下的控件；
       真实鼠标本来就是 QMouseEvent。两条路在控件眼里都是鼠标事件，靠
       QMouseEvent.source() 区分：
           source() == MouseEventNotSynthesized -> 真实鼠标，一律放行
           source() != 该值(System/Qt 合成)      -> 触控合成的，才走长按门卫
       老版本 PySide6 没有 source() 时按真实鼠标处理(桌面行为不变)。
    2. 合成鼠标的 **press / release 照常放行**：链接点按(QLabel 的
       LinksAccessibleByMouse)、编辑类控件的光标位置都靠这一对事件，吃掉就连
       不上链接、点不准位置了。单独一次 press 不会产生可见选区。
    3. 合成鼠标的 **move 一律拦掉**：鼠标拖拽选文本的唯一入口就是
       press(落锚点) + move(延展选区)，move 不进控件就永远选不中文字；长按成立
       后也不放行 move —— 触摸上的"选中"直接给全选 + 复制菜单，不做"长按后拖动
       框选"，免得和父级滚动的 QScroller 抢同一根手指(滚动与选择二选一，选滚动)。
    4. 长按判定 = 合成 press 之后 LongPressMs 内位移不超过 TouchSlopPx：
       超了就当滑动/滚动(停表、放弃本次长按)，抬手时什么都不做。
    5. 菜单在**手指抬起之后**才弹(长按成立先记着，release 时才弹)：手指还压在
       屏幕上时弹菜单，松手那一记 release 会落在菜单上，可能误触第一项。

和 mobile_ui 触控路由的配合(只在 Android 生效)：
    _TouchRouter 会把"已接管手指滚动的区域里的控件"的整条触控序列认领掉
    (接受 TouchBegin，Qt 就不再合成鼠标)，门卫就永远等不到合成鼠标。因此装上
    本门卫的控件会打上 `_jmTextSelect` 标记，_TouchRouter._Classify 见到它就
    返回 "native"(和 QLineEdit 同款待遇：不认领、放 Qt 原生合成)——
    滚动手感仍由 QScroller 在触控层提供，不受影响；滑动途中的合成 move 由
    门卫拦掉，所以不会选中文字。
"""
from PySide6.QtCore import Qt, QEvent, QObject, QPoint, QTimer
from PySide6.QtWidgets import QApplication, QMenu

from tools.log import Log
from tools.mobile_ui_base import TouchSlopPx, _EventLocalPos
from tools.str import Str

# 长按判定时长(ms)：和 Android 原生文本长按菜单的量级一致
TextLongPressMs = 500

# 真实鼠标的 source() 值；取不到该枚举(老版本 PySide6)时按"全是真实鼠标"处理
try:
    _MouseNotSynthesized = Qt.MouseEventSource.MouseEventNotSynthesized
except Exception:     # pragma: no cover - 老版本没有该枚举
    _MouseNotSynthesized = None


class TextSelectGate(QObject):
    """ 事件过滤器：挂在"可选中文本"控件上，触摸时长按才允许选中

    挂在控件本身(QLabel)或它的视口(QTextEdit/QPlainTextEdit 的鼠标事件走视口)上；
    对真实鼠标事件一律返回 False(放行)，桌面行为零改动。
    """

    def __init__(self, widget, target=None, parent=None):
        """ widget: 文本控件本身(选区/复制都操作它)
            target:  过滤器挂载的控件(可能只是 widget 的视口)，坐标换算用它 """
        super().__init__(parent if parent is not None else target)
        self._widget = widget
        self._target = target if target is not None else widget
        self._seq = False         # 是否正处于一个触控(合成鼠标)按下序列
        self._press = None        # 本次触控按下的点(target 本地坐标)
        self._armed = False       # 长按已成立(抬手时要全选 + 弹菜单)
        self._menu = None         # 长按菜单(开着的时候要能一键收掉)
        self._timer = None        # 长按计时器(第一次被手指按下时才建：列表里
                                  # 一条评论三个标签，懒建免得白养一堆定时器)

    def _EnsureTimer(self):
        if self._timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(TextLongPressMs)
            timer.timeout.connect(self._OnLongPress)
            self._timer = timer
        return self._timer

    # -- 判定 ----------------------------------------------------------------
    @staticmethod
    def FromTouch(event):
        """ 这个鼠标事件是不是触控合成的(真实鼠标一律 False，放行) """
        try:
            source = event.source()
        except Exception:
            return False
        if _MouseNotSynthesized is None:
            return False
        try:
            return source != _MouseNotSynthesized
        except Exception:
            return False

    def _Reset(self):
        if self._timer is not None:
            self._timer.stop()
        self._seq = False
        self._press = None
        self._armed = False

    def _CloseMenu(self, *args):
        menu, self._menu = self._menu, None
        if menu is not None:
            try:
                menu.close()
            except Exception:
                pass

    def _MovedFar(self, event):
        """ 本次触控的位移是否已经超过滑动阈值 """
        press = self._press
        pos = _EventLocalPos(event)
        if press is None or pos is None:
            return False
        try:
            return (QPoint(int(pos.x()), int(pos.y())) - press).manhattanLength() > TouchSlopPx
        except Exception:
            return False

    # -- 选区操作 -------------------------------------------------------------
    def _ClearSelection(self):
        widget = self._widget
        try:
            if hasattr(widget, "setSelection"):          # QLabel
                widget.setSelection(0, 0)
            elif hasattr(widget, "textCursor"):           # QTextEdit/QPlainTextEdit
                cursor = widget.textCursor()
                cursor.clearSelection()
                widget.setTextCursor(cursor)
            else:
                return
            widget.update()
        except Exception as es:
            Log.Error(es)

    def _SelectAll(self):
        """ 长按成立：把整段文字选中(给用户看得见的反馈，复制菜单也有东西可复制) """
        widget = self._widget
        try:
            selectAll = getattr(widget, "selectAll", None)
            if callable(selectAll):                       # QTextEdit/QPlainTextEdit
                selectAll()
            else:
                setSelection = getattr(widget, "setSelection", None)
                text = widget.text() if hasattr(widget, "text") else ""
                if callable(setSelection) and text:       # QLabel
                    setSelection(0, len(text))
                else:
                    return False
            widget.update()
            return True
        except Exception as es:
            Log.Error(es)
            return False

    def _SelectedText(self):
        widget = self._widget
        try:
            if hasattr(widget, "selectedText"):           # QLabel
                text = widget.selectedText()
                if text:
                    return text
            if hasattr(widget, "toPlainText"):            # QTextEdit/QPlainTextEdit
                return widget.toPlainText()
            if hasattr(widget, "text"):
                return widget.text()
        except Exception as es:
            Log.Error(es)
        return ""

    # -- 菜单 -----------------------------------------------------------------
    def _OnCopy(self, *args):
        # *args：QAction.triggered 会带一个 checked 参数，PySide6 虽允许少形参
        # 连接，写上更稳(测试里也会直接带参触发)
        text = self._SelectedText()
        if not text:
            return
        try:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(text)
        except Exception as es:
            Log.Error(es)

    def _ShowMenu(self, localPos):
        """ 在按下点弹出"复制/取消"菜单；菜单一收就把高亮收掉(和手机原生一致) """
        try:
            self._CloseMenu()
            menu = QMenu(self._widget)
            menu.addAction(Str.GetStr(Str.Copy)).triggered.connect(self._OnCopy)
            menu.addAction(Str.GetStr(Str.Cancel)).triggered.connect(self._CloseMenu)
            menu.aboutToHide.connect(self._ClearSelection)
            self._menu = menu
            menu.popup(self._target.mapToGlobal(localPos))
        except Exception as es:
            Log.Error(es)

    def _OnLongPress(self):
        # 手指还按着且没怎么动：长按成立(抬手时才全选 + 弹菜单)
        if self._seq:
            self._armed = True

    # -- 事件 -----------------------------------------------------------------
    def eventFilter(self, obj, event):
        try:
            eventType = event.type()
            if eventType == QEvent.Type.MouseButtonPress:
                return self._OnPress(event)
            if eventType == QEvent.Type.MouseButtonRelease:
                return self._OnRelease(event)
            if eventType == QEvent.Type.MouseMove:
                return self._OnMove(event)
        except Exception as es:
            Log.Error(es)
        return False

    def _OnPress(self, event):
        # 新一次按下：先收掉上次长按的菜单/状态(鼠标按下也收菜单，与原生一致)
        self._CloseMenu()
        self._Reset()
        if not self.FromTouch(event):
            return False                    # 真实鼠标：原样放行(点按/拖选/双击选词/点链接)
        if event.button() != Qt.LeftButton:
            return False                    # 触控合成出来的只可能是左键；别的按键照样放行
        self._ClearSelection()              # 上一次长按留下的高亮先收掉
        pos = _EventLocalPos(event)
        self._press = QPoint(int(pos.x()), int(pos.y())) if pos is not None else None
        self._seq = True
        self._armed = False
        self._EnsureTimer().start()
        # press 照常放行：链接点按 / 光标位置都靠它；单独一次 press 不会产生可见选区
        return False

    def _OnMove(self, event):
        if not self._seq:
            return False                    # 不在触控按下序列里(真实鼠标拖选)：放行
        if not self._MovedFar(event):
            return True                     # 手指小幅抖动(或取不到坐标)：仍然拦掉(不许起选)
        # 位移超过阈值：这是滑动/滚动，放弃本次长按；move 继续拦掉不产生选区
        if self._timer is not None:
            self._timer.stop()
        self._armed = False
        return True

    def _OnRelease(self, event):
        seq = self._seq
        armed = self._armed
        press = self._press
        self._Reset()
        if not seq:
            return False                    # 真实鼠标 / 没有触控序列：放行
        if not armed:
            # 普通点按：release 放行，链接点按恢复正常语义
            return False
        # 长按成立：全选 + 弹菜单；release 不再放行(否则长按链接会顺带把链接打开)
        self._SelectAll()
        self._ShowMenu(press)
        return True


def InstallTextSelect(widget):
    """ 给"可选中文本"控件装上触摸长按门卫(幂等；纯鼠标的桌面环境等于零改动)

    覆盖 QLabel(评论/标题/搜索提示)与 QTextEdit/QPlainTextEdit(详情简介/日志)：
    鼠标点按、拖拽选择、双击选词、点链接完全不变；触摸从"滑动即选中"改成
    "长按才选中(全选 + 复制菜单)"。装上后控件带 `_jmTextSelect` 标记，
    mobile_ui 的触控路由器据此不认领它的触控(见 TextSelectGate 文档)。
    """
    if widget is None:
        return False
    if getattr(widget, "_jmTextSelect", False):
        return False
    try:
        # 顺带确保"可被鼠标选中"：没有这个标志 QLabel 连文本控件都不会建，
        # setSelection/selectedText 全是空转(长按也就选不中)。这只是兜底 ——
        # 各调用点都已显式设了 TextBrowserInteraction，正常情况下是空操作。
        try:
            flags = widget.textInteractionFlags() if hasattr(widget, "textInteractionFlags") else None
            if flags is not None and not (int(flags) & int(Qt.TextSelectableByMouse)):
                widget.setTextInteractionFlags(flags | Qt.TextSelectableByMouse)
        except Exception:
            pass
        widget._jmTextSelect = True
        # QTextEdit/QPlainTextEdit 的鼠标事件投在视口上，过滤器要挂视口才拦得到
        target = widget
        viewport = widget.viewport() if hasattr(widget, "viewport") else None
        if viewport is not None:
            target = viewport
        gate = TextSelectGate(widget, target)
        target.installEventFilter(gate)
        # 双保险持住引用(QObject 也已挂到 target 上，正常不会被 GC)
        widget._jmTextGate = gate
    except Exception as es:
        Log.Error(es)
        return False
    return True
