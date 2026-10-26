# coding:utf-8
""" Android 端应用内文件选择器(替代 QFileDialog)

为什么需要这个模块
------------------
真机反馈(vivo V2463A / Android 16 / arm64)：

    "导入本地漫画以及图片超分导入本地图片的操作会导致应用卡死"

原因是这些调用点直接用了 `QFileDialog.getExistingDirectory` /
`getOpenFileName` / `getSaveFileName`。Qt 的 QFileDialog 在 Android 上会

    1. 创建一个**新的顶层窗口**(native dialog 不存在，于是走 Qt 自己的
       QFileDialog 部件实现)；
    2. 在里面跑一个**嵌套的模态事件循环**(exec())；

而 Android 的 QPA 插件(android platform plugin)不保证这种"第二个顶层窗口 +
嵌套模态循环"能正常收尾 —— 实测就是界面卡死、再也不返回调用点，
导入本地漫画 / 图片超分导入图片这两个入口因此完全不可用。

本模块的做法
------------
`IsAndroid()` 为真时，**不再创建任何顶层窗口**，而是在当前主窗口内部放一个
**子覆盖控件(overlay)**：它 parent 到主窗口、覆盖整个窗口、`raise_()` 到最上层，
里面是竖屏友好的一个路径行 + 一个列表 + 几个按钮，然后用一个**嵌套 QEventLoop**
等待用户操作。原有调用点都是同步阻塞的写法(`url = QFileDialog.getExistingDirectory(...)`),
嵌套事件循环让这些调用点一行都不用改(只换成 `mobile_file_dialog.xxx`)。
Android 的返回键(Key_Back)与 Esc 都映射成"取消"。

桌面端**完全不受影响**：`IsAndroid()` 为假时，三个函数原样转发给对应的
`QFileDialog` 静态方法，连返回值形状都一模一样(`GetOpenFileName` /
`GetSaveFileName` 返回 `(文件名, 选中过滤器)` 元组，`GetExistingDirectory`
返回字符串，取消时为空串)。

Android 存储权限的现实约束
--------------------------
APK 只声明了 INTERNET / ACCESS_NETWORK_STATE / WAKE_LOCK / WRITE_EXTERNAL_STORAGE
(没有 READ_MEDIA_IMAGES / READ_EXTERNAL_STORAGE / MANAGE_EXTERNAL_STORAGE)，
targetSdk 34 + Android 16 下 /storage/emulated/0 的绝大多数目录(Download/Pictures/DCIM)
`os.scandir` 会抛 PermissionError。所以：
    * 列目录一律走 `os.scandir` + try/except，失败只显示一行红字提示并**停在原地**，
      绝不抛异常、绝不卡死；
    * 顶部固定一行提示，告诉用户手机存储需要授予"所有文件访问权限"；
    * 快捷入口(存储/下载/图片)如果读不了就**置灰**，而不是点进去报错。

相关：`tools/platform_mobile.py`(目录)、`tools/mobile_ui.py`(竖屏布局)。
"""
import os
import re
import stat

from PySide6.QtCore import QEvent, QEventLoop, Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout, QWidget)

from tools import platform_mobile

# 选择模式
ModeDir = "dir"
ModeOpen = "open"
ModeSave = "save"

# 取消时的返回值：必须与对应的 QFileDialog 静态方法完全一致 ——
# getOpenFileName / getSaveFileName 返回**空元组**，getExistingDirectory 返回**空串**
CancelResult = ()
CancelDir = ""

# 覆盖层背景(半透明，能看见底下的主界面)与内容卡片颜色
OverlayStyle = "FilePickerOverlay { background-color: rgba(0, 0, 0, 150); }"
CardStyle = """
#FilePickerCard { background-color: #ffffff; border-radius: 8px; }
#FilePickerCard QLabel { color: #333333; }
#FilePickerPath { color: #555555; font-size: 12px; }
#FilePickerHint { color: #b06a00; font-size: 11px; }
#FilePickerError { color: #cc0000; font-size: 12px; }
"""
ErrorColor = "#cc0000"

# 电话竖屏只有 ~384x845 逻辑像素：所有控件整宽、一行一个，最小宽度不超过这个值
MinWidthLimit = 340
# 快捷入口的高度(比默认按钮矮一点，省竖向空间)
ShortcutHeight = 30

# 顶部固定提示：Android 16 + targetSdk 34 下，没有"所有文件访问权限"就读不了手机存储
StorageHint = ("提示：读取手机存储需要「所有文件访问权限」，"
               "如无法进入请在系统设置里为本应用开启。")

# `Image Files(*.jpg *.png)` / `*.zip` 这类过滤器里提取出来的扩展名
_FilterPatternRe = re.compile(r"\*\.([A-Za-z0-9_+\-]+)")


def _ParseFilterPatterns(pattern):
    """ 解析 QFileDialog 风格的过滤器，返回小写扩展名列表(带点，如 ['.zip'])

    解析不出来(空串 / "*.*" / 纯描述文字)时返回空列表，表示"显示所有文件"。
    多个过滤段(`Image Files(*.jpg);;Text(*.txt)`)会全部提取 —— 与桌面端
    QFileDialog 只显示第一个过滤器不同，这里宁可多显示也不漏。
    """
    if not pattern:
        return []
    exts = []
    for mo in _FilterPatternRe.finditer(pattern):
        ext = mo.group(1).lower()
        if ext in ("*", ""):
            continue
        ext = "." + ext
        if ext not in exts:
            exts.append(ext)
    return exts


def _IsReadableDir(path):
    """ 路径是否是存在的、可列目录的目录(不抛异常) """
    if not path:
        return False
    try:
        return os.path.isdir(path) and os.access(path, os.R_OK | os.X_OK)
    except OSError:
        return False


def _IsReadableFile(path):
    """ 文件是否可读(用于跳过列不出来的条目，不抛异常)

    **先 stat、只对普通文件 os.open**：命名管道(FIFO)在没有写端时 `os.open` 会一直
    阻塞到有人写进来为止 —— /tmp 里就藏着这种东西(GitHub runner 的 socket/管道)，
    主机上列一次 /tmp 整个进程直接挂死(CI 上正是这么卡的，栈停在
    `_GoUp -> _GoTo -> _FillList -> os.open`)。管道/套接字/设备节点直接按"能列出来"
    处理，绝不碰 os.open。
    """
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return False
    if not stat.S_ISREG(mode):
        return True
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    os.close(fd)
    return True


def _SplitRequestedDir(dir):
    """ 把调用点传进来的 dir 拆成 (起始目录, 默认文件名)

    调用点常常把"完整路径"当 dir 传(例如 `os.path.join(lastPath, "xx.jpg")`)，
    QFileDialog 会把它当成"默认文件名 + 所在目录"。这里做同样的事：
    指向已存在目录的 -> 起始目录；不存在的路径 -> 用它的父目录 + 文件名(保存模式用)。
    """
    text = str(dir or "").strip()
    if not text:
        return "", ""
    if _IsReadableDir(text):
        return text, ""
    if os.path.isabs(text):
        parent = os.path.dirname(text)
        name = os.path.basename(text)
        if parent:
            return parent, name
        return text, ""
    # 相对路径："." 是当前目录，其它当文件名
    if text in (".", ".."):
        return os.path.abspath(text), ""
    return os.path.abspath(os.curdir), text


def _StartDirs():
    """ 应用可以可靠访问的目录(Android 上的"应用目录/私有目录") """
    dirs = []
    for folder in (platform_mobile.GetExternalDir(), platform_mobile.GetAppDataDir()):
        if folder and folder not in dirs:
            dirs.append(folder)
    return dirs


def _StartDir(dir):
    """ 起始目录：请求的 dir -> 应用外部目录 -> 私有目录 -> 用户主目录 """
    wanted, _ = _SplitRequestedDir(dir)
    for folder in [wanted] + _StartDirs() + [os.path.expanduser("~")]:
        if _IsReadableDir(folder):
            return folder
    return wanted or os.path.expanduser("~")


def _ParentWindow(parent):
    """ 覆盖控件要 parent 到哪个窗口

    优先用调用点传进来的 parent 所在窗口；没有再退到 `QtOwner().owner`(主窗口)。
    **绝不**新建顶层窗口 —— 那正是要修掉的 bug。
    """
    window = None
    if isinstance(parent, QWidget):
        window = parent.window()
    if window is None or not isinstance(window, QWidget):
        try:
            from qt_owner import QtOwner
            window = QtOwner().owner
        except Exception:
            window = None
    if window is None or not isinstance(window, QWidget):
        window = QApplication.activeWindow()
    if not isinstance(window, QWidget):
        return None
    return window


class _PickerDialog(QWidget):
    """ 应用内文件选择覆盖控件(挂在主窗口内部，不是新的顶层窗口)

    属性(测试与上层都依赖)：
        entries     当前目录的条目列表 [{"name", "path", "isDir"}, ...](目录在前)
        currentDir  当前目录
        result      选择结果：取消时是 CancelResult，否则 (路径, 过滤器)
    """

    def __init__(self, parent=None, caption="", startDir="", mode=ModeOpen, filter=""):
        QWidget.__init__(self)
        self.mode = mode if mode in (ModeDir, ModeOpen, ModeSave) else ModeOpen
        self.entries = []
        self.currentDir = ""
        # 目录模式的取消值是空串，其它两个模式是空元组(与 QFileDialog 一致)
        self.cancelResult = CancelDir if self.mode == ModeDir else CancelResult
        self.result = self.cancelResult
        self._patterns = _ParseFilterPatterns(filter)
        self._nameFilter = filter or ""
        self._startDir = _StartDir(startDir)
        # 保存模式的 dir 常常带默认文件名(如 "20240101120000.jpg")
        _, self._initName = _SplitRequestedDir(startDir) if self.mode == ModeSave else ("", "")
        self._loop = None
        self._active = False

        window = _ParentWindow(parent)
        self._parentWindow = window
        if window is not None:
            # 挂成主窗口的子控件：不产生新的顶层窗口
            self.setParent(window)
            self.setGeometry(window.rect())
            window.installEventFilter(self)
        self.setObjectName("FilePickerOverlay")
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet(OverlayStyle)

        self.captionLabel = None
        self.hintLabel = None
        self.pathLabel = None
        self.listWidget = None
        self.nameEdit = None
        self.errorLabel = None
        self.upButton = None
        self.cancelButton = None
        self.okButton = None
        self.shortcutButtons = []
        self.card = None

        self._BuildUi(caption)
        self._GoTo(self._startDir, announce=False)
        self.show()
        self.raise_()

    # ------------------------------------------------------------------ 界面

    def _BuildUi(self, caption):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        self.card = QWidget(self)
        self.card.setObjectName("FilePickerCard")
        self.card.setStyleSheet(CardStyle)
        root.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 1. 当前目录(中间省略，绝不把窗口撑宽)
        self.captionLabel = QLabel(caption or "", self.card)
        self.captionLabel.setObjectName("FilePickerCaption")
        self.captionLabel.setWordWrap(True)
        layout.addWidget(self.captionLabel)

        self.pathLabel = QLabel("", self.card)
        self.pathLabel.setObjectName("FilePickerPath")
        self.pathLabel.setMinimumWidth(0)
        layout.addWidget(self.pathLabel)

        # 2. 固定的权限提示(Android 16 上手机存储很可能读不了)
        self.hintLabel = QLabel(StorageHint, self.card)
        self.hintLabel.setObjectName("FilePickerHint")
        self.hintLabel.setWordWrap(True)
        layout.addWidget(self.hintLabel)

        # 3. 快捷入口(读不了的置灰)
        layout.addWidget(self._BuildShortcuts())

        # 4. 条目列表
        self.listWidget = QListWidget(self.card)
        self.listWidget.setObjectName("FilePickerList")
        self.listWidget.setMinimumWidth(0)
        self.listWidget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.listWidget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.listWidget.itemSelectionChanged.connect(self._OnSelectionChanged)
        self.listWidget.itemDoubleClicked.connect(self._OnItemDoubleClicked)
        layout.addWidget(self.listWidget, 1)

        # 5. 错误/提示行
        self.errorLabel = QLabel("", self.card)
        self.errorLabel.setObjectName("FilePickerError")
        self.errorLabel.setWordWrap(True)
        self.errorLabel.setVisible(False)
        layout.addWidget(self.errorLabel)

        # 6. 保存模式的文件名输入框
        if self.mode == ModeSave:
            self.nameEdit = QLineEdit(self.card)
            self.nameEdit.setObjectName("FilePickerName")
            self.nameEdit.setMinimumWidth(0)
            self.nameEdit.setText(self._initName)
            self.nameEdit.returnPressed.connect(self._Accept)
            layout.addWidget(self.nameEdit)

        # 7. 按钮行：上级 / 取消 / 确定
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.upButton = QPushButton("上级", self.card)
        self.upButton.setObjectName("FilePickerUp")
        self.upButton.clicked.connect(self._GoUp)
        buttons.addWidget(self.upButton, 1)

        self.cancelButton = QPushButton("取消", self.card)
        self.cancelButton.setObjectName("FilePickerCancel")
        self.cancelButton.clicked.connect(self.Cancel)
        buttons.addWidget(self.cancelButton, 1)

        self.okButton = QPushButton("确定", self.card)
        self.okButton.setObjectName("FilePickerOk")
        self.okButton.setDefault(True)
        self.okButton.clicked.connect(self._Accept)
        buttons.addWidget(self.okButton, 1)
        layout.addLayout(buttons)

    def _BuildShortcuts(self):
        """ 快捷入口：应用目录 / 私有目录 / 存储 / 下载 / 图片(读不了的置灰) """
        box = QWidget(self.card)
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)

        items = [
            ("应用目录", platform_mobile.GetExternalDir()),
            ("私有目录", platform_mobile.GetAppDataDir()),
            ("存储", "/storage/emulated/0"),
            ("下载", "/storage/emulated/0/Download"),
            ("图片", "/storage/emulated/0/Pictures"),
        ]
        seen = set()
        targets = []
        for text, path in items:
            if not path or path in seen:
                continue
            seen.add(path)
            targets.append((text, path))

        columns = 3
        for index, (text, path) in enumerate(targets):
            button = QPushButton(text, box)
            button.setObjectName("FilePickerShortcut{}".format(index))
            button.setMinimumWidth(0)
            button.setFixedHeight(ShortcutHeight)
            button.setToolTip(path)
            readable = _IsReadableDir(path)
            button.setEnabled(readable)
            if not readable:
                # 读不了就置灰，而不是点进去再报错
                button.setToolTip("{}（无法访问，可能需要「所有文件访问权限」）".format(path))
            button.clicked.connect(lambda _=False, p=path: self._GoTo(p))
            grid.addWidget(button, index // columns, index % columns)
            self.shortcutButtons.append(button)
        return box

    # ------------------------------------------------------------- 目录操作

    def _GoTo(self, path, announce=True):
        """ 切换到 path 目录并刷新列表；失败则停在原地并显示红字 """
        path = os.path.abspath(str(path or ""))
        if not _IsReadableDir(path):
            if announce:
                self._ShowMessage("无法访问该目录: {}".format(path))
            self._Refresh()
            return False
        self.currentDir = path
        if announce:
            self._ShowMessage("")
        self._FillList()
        self._Refresh()
        return True

    def _GoUp(self):
        parent = os.path.dirname(self.currentDir)
        if not parent or parent == self.currentDir:
            self._ShowMessage("已经是最上层目录")
            return
        self._GoTo(parent)

    def _FillList(self, message=None):
        """ 用 os.scandir 列目录：目录在前、文件在后、都按名字不区分大小写排序

        任何 PermissionError/OSError 都只变成一行红字，绝不抛出、绝不卡死。
        列不出来的条目(权限/符号链接失效)直接跳过。
        """
        dirs = []
        files = []
        entries = []
        error = ""
        try:
            with os.scandir(self.currentDir) as it:
                for entry in it:
                    try:
                        isDir = entry.is_dir()
                    except OSError:
                        continue
                    try:
                        if not isDir and not _IsReadableFile(entry.path):
                            # 文件读不了就别列出来(列出来也打不开)
                            continue
                    except OSError:
                        continue
                    if isDir:
                        dirs.append({"name": entry.name, "path": entry.path, "isDir": True})
                    elif self._MatchFilter(entry.name):
                        files.append({"name": entry.name, "path": entry.path, "isDir": False})
        except (PermissionError, OSError) as es:
            error = "无法访问该目录: {}".format(es)

        dirs.sort(key=lambda v: v["name"].lower())
        files.sort(key=lambda v: v["name"].lower())
        self.entries = dirs + files

        if self.listWidget is not None:
            self.listWidget.clear()
            for info in self.entries:
                item = QListWidgetItem(("[目录] " if info["isDir"] else "") + info["name"])
                item.setData(Qt.ItemDataRole.UserRole, info)
                self.listWidget.addItem(item)

        if error:
            self._ShowMessage(error)
        elif message:
            self._ShowMessage(message)
        else:
            self._ShowMessage("")

    def _MatchFilter(self, name):
        """ 过滤器匹配；没有可用模式时显示所有文件 """
        if not self._patterns:
            return True
        return os.path.splitext(name)[1].lower() in self._patterns

    def _Refresh(self):
        """ 刷新路径行 / 上级按钮 / 确定按钮的状态 """
        if self.upButton is not None:
            parent = os.path.dirname(self.currentDir)
            self.upButton.setEnabled(bool(parent) and parent != self.currentDir)
        if self.okButton is not None:
            if self.mode == ModeDir:
                enabled = _IsReadableDir(self.currentDir)
            else:
                enabled = bool(self._SelectedPath())
            self.okButton.setEnabled(enabled)
        self._UpdatePathText()
        # 宽度要等布局跑完才准，先算一次、下一轮事件循环再算一次
        QTimer.singleShot(0, self._UpdatePathText)

    def _UpdatePathText(self):
        if self.pathLabel is None:
            return
        text = self.currentDir or ""
        width = self.pathLabel.width()
        if width <= 32:
            width = max(MinWidthLimit - 40, 60)
        try:
            metrics = QFontMetrics(self.pathLabel.font())
            text = metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, width)
        except Exception:
            pass
        self.pathLabel.setText(text)

    def _ShowMessage(self, message):
        if self.errorLabel is None:
            return
        if message:
            if self.errorLabel.text() == message and self.errorLabel.isVisible():
                # 同一条提示不要因为一次刷新就闪掉
                return
            self.errorLabel.setStyleSheet("color: {};".format(ErrorColor))
            self.errorLabel.setText(message)
            self.errorLabel.setVisible(True)
        else:
            self.errorLabel.setText("")
            self.errorLabel.setVisible(False)

    # --------------------------------------------------------------- 选择逻辑

    def _CurrentEntry(self):
        if self.listWidget is None:
            return None
        item = self.listWidget.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _SelectedPath(self):
        info = self._CurrentEntry()
        if not isinstance(info, dict) or info.get("isDir"):
            return ""
        return info.get("path") or ""

    def _OnSelectionChanged(self):
        self._Refresh()

    def _OnItemDoubleClicked(self, item):
        info = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(info, dict):
            return
        if info.get("isDir"):
            self._GoTo(info.get("path"))
        else:
            self._Accept()

    # 程序化调用(测试用)：设置当前目录 / 选择条目
    def setCurrentDir(self, path, announce=True):
        """ 把当前目录切到 path(测试/程序化用)，返回是否成功

        与从界面点进目录完全同一条路径，所以读不了时的红字提示也会照常显示。
        """
        return self._GoTo(path, announce=announce)

    def SelectName(self, name):
        """ 选中列表里指定名字的条目(测试用)，返回是否找到 """
        if self.listWidget is None:
            return False
        for row in range(self.listWidget.count()):
            item = self.listWidget.item(row)
            info = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(info, dict) and info.get("name") == name:
                self.listWidget.setCurrentItem(item)
                return True
        return False

    def _Accept(self):
        """ 确定：目录模式返回当前目录，打开模式返回选中文件，保存模式返回拼接路径 """
        message = ""
        if self.mode == ModeDir:
            if not _IsReadableDir(self.currentDir):
                message = "无法访问该目录: {}".format(self.currentDir)
            else:
                self._Finish((self.currentDir, ""))
                return
        else:
            path = self._SelectedPath()
            if self.mode == ModeSave and self.nameEdit is not None:
                text = self.nameEdit.text().strip()
                if text:
                    path = text if os.path.isabs(text) else os.path.join(self.currentDir, text)
            if not path:
                message = "请先选择一个文件"
            else:
                self._Finish((path, self._nameFilter))
                return
        self._ShowMessage(message)
        self._Refresh()

    def Cancel(self):
        self._Finish(self.cancelResult)

    def _Finish(self, result):
        """ 唯一的出口：记录结果 + 退出嵌套事件循环 (所有路径都必须经过这里) """
        self.result = result
        self._active = False
        loop = self._loop
        self._loop = None
        if loop is not None:
            try:
                loop.quit()
            except Exception:
                pass

    # ------------------------------------------------------------------ 事件

    def _Run(self):
        """ 跑嵌套事件循环(原有阻塞式调用点因此不需要改)

        退出后一定会把覆盖控件藏起来 —— 调用点拿到的必须只是一个返回值。
        """
        if self._active:
            return self.result
        self._active = True
        self._loop = QEventLoop()
        self.raise_()
        self.setFocus()
        try:
            self._loop.exec()
        finally:
            self._loop = None
            self._active = False
            try:
                self.hide()
            except Exception:
                pass
        return self.result

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Back):
            # Android 返回键
            self.Cancel()
            event.accept()
            return
        QWidget.keyPressEvent(self, event)

    def closeEvent(self, event):
        # 窗口被关掉也必须让嵌套循环退出，否则调用点永远等下去
        self._Finish(self.cancelResult)
        QWidget.closeEvent(self, event)

    def eventFilter(self, obj, event):
        try:
            if obj is self._parentWindow:
                if event.type() == QEvent.Type.Resize:
                    self.setGeometry(self._parentWindow.rect())
                elif event.type() == QEvent.Type.Close:
                    self._Finish(self.cancelResult)
        except Exception:
            pass
        return QWidget.eventFilter(self, obj, event)


def _Launch(parent, caption, dir, mode, filter):
    """ Android 路径：建覆盖控件 -> 嵌套事件循环 -> 删除覆盖控件 -> 返回结果

    任何一步出意外都只记日志并返回"取消值"，绝不把异常丢给调用点，
    也绝不留下一个还在跑的嵌套事件循环。
    """
    cancelled = CancelDir if mode == ModeDir else CancelResult
    try:
        picker = _PickerDialog(parent, caption, dir, mode, filter)
    except Exception as es:
        _LogError(es)
        return cancelled

    result = cancelled
    try:
        result = picker._Run()
    except Exception as es:
        _LogError(es)
        result = getattr(picker, "cancelResult", cancelled)
    finally:
        # 不在 finally 里同步 deleteLater：嵌套循环退出后调用点还要用 result，
        # 交回事件循环再删，避免任何"控件已析构"的时序问题
        try:
            QTimer.singleShot(0, picker.deleteLater)
        except Exception:
            pass
    if result is None:
        result = cancelled
    return result


def _LogError(es):
    """ 记日志(Log 没初始化时也不能再抛异常) """
    try:
        from tools.log import Log
        Log.Error(es)
    except Exception:
        pass


def GetExistingDirectory(parent=None, caption="", dir=""):
    """ 选择目录；取消返回 ""(与 QFileDialog.getExistingDirectory 一致)

    Android 上走 SAF(ACTION_OPEN_DOCUMENT_TREE)：选完把整棵树**拷进应用目录**，
    返回拷贝后的本地路径 —— 因为业务层全是按路径干活的(解码/超分/上传)，
    而 SAF 给的 content:// URI 只有 Java 侧能读。
    没有桥可用(桥没打进 APK / am 被拦)时回落到应用内选择器。
    """
    if not platform_mobile.IsAndroid():
        from PySide6.QtWidgets import QFileDialog
        return QFileDialog.getExistingDirectory(parent, caption, dir)
    path = SafImportFolder(caption, parent)
    if path is not None:
        return path
    return _Launch(parent, caption, dir, ModeDir, "")


def PickLocalDir(parent=None, caption="", dir=""):
    """ 选一个**真实文件系统目录**，不导入、不拷贝任何内容

    与 GetExistingDirectory 的区别：后者在 Android 上是"导入"语义 —— 走 SAF
    把整棵树拷进应用目录，然后返回拷贝后的本地路径。缓存目录不能那么干：
    缓存必须由 Python 直接 open，SAF 的 content:// 打不开；而且把缓存目录
    再拷一份纯属浪费。

    所以这里只用应用内选择器(它列出来的都是真实路径)；用户没权限进的目录
    本来就列不出来。取消返回 ""。
    """
    if not platform_mobile.IsAndroid():
        from PySide6.QtWidgets import QFileDialog
        return QFileDialog.getExistingDirectory(parent, caption, dir)
    result = _Launch(parent, caption, dir or platform_mobile.GetExternalDir(), ModeDir, "")
    # ModeDir 的确定结果是 (目录, "") 元组，取消是 ""(与 _Launch 一致)
    if isinstance(result, (tuple, list)):
        return str(result[0]) if result else ""
    return str(result or "")


def SafImportFolder(caption="", parent=None):
    """ SAF 选目录 -> 拷进应用目录 -> 返回本地路径

    返回 "" 表示用户取消(不要再弹应用内选择器)，None 表示桥不可用(调用方回落)。
    """
    try:
        from tools import saf_bridge
        if not saf_bridge.IsSupported():
            return None
    except Exception:
        return None
    picked = saf_bridge.PickTree(caption or "")
    if picked is None:
        return None
    if not picked:
        return ""
    # 选完只拿到 URI：拷进 import 根目录下的同名子目录
    name = _SafeName(picked.get("name") or "folder")
    target = _UniqueDir(os.path.join(_ImportRoot(), name))
    # 整棵树拷贝可能要几秒到几十秒：先把提示打出来(嵌套事件循环里仍会绘制)
    try:
        from qt_owner import QtOwner
        QtOwner().ShowMsg("正在导入，请稍候…")
    except Exception:
        pass
    copied = saf_bridge.CopyTreeIn(picked.get("uri") or "", target)
    if not copied:
        _ShowMsg("导入失败：无法读取所选目录")
        return ""
    count = int(copied.get("count") or 0)
    if count <= 0:
        # 一个文件都没读到：别再返回一个空目录让上层"以为成功了"
        _ShowMsg("导入失败：所选目录里没有可读取的文件")
        return ""
    return copied.get("path") or target


def _ShowMsg(text):
    """ 提示(没有 QtOwner 时静默) """
    try:
        from qt_owner import QtOwner
        QtOwner().ShowMsg(text)
    except Exception:
        pass
    return


def _ImportRoot():
    """ 导入内容的落地目录(SF 授权拿到的东西必须先拷进来) """
    try:
        from tools import platform_mobile
        root = os.path.join(platform_mobile.GetAppDataDir(), "import")
    except Exception:
        root = os.path.join(os.path.expanduser("~"), "jmcomic-import")
    try:
        os.makedirs(root, exist_ok=True)
    except Exception:
        pass
    return root


def _SafeName(name):
    text = "".join(("_" if (ch in "/\\:" or ord(ch) < 32) else ch) for ch in str(name or ""))
    text = text.strip().strip(".")
    return text or "import"


def _UniqueDir(path):
    """ 同名的导入目录不覆盖，加后缀 """
    if not os.path.exists(path):
        return path
    for index in range(1, 10000):
        candidate = "{} ({})".format(path, index)
        if not os.path.exists(candidate):
            return candidate
    return "{}-{}".format(path, int(__import__("time").time()))


def PickExportTree(caption=""):
    """ 选下载目录：返回 {"uri","name"} / "" 取消 / None 不可用

    为什么不返回本地路径：SAF 授权的是 URI，Python 的 open() 打不开。而这个目录是
    要**持续写入**的(每本漫画每一页)，所以真正的写入走 `saf_bridge` 的 socket
    数据面(见 tools/vfs.py)：选中的目录就是下载目录本身，文件直接落在里面，
    没有"先写私有目录再导出"。
    """
    try:
        from tools import saf_bridge
        if not saf_bridge.IsSupported():
            return None
    except Exception:
        return None
    picked = saf_bridge.PickTree(caption or "")
    if picked is None:
        return None
    if not picked:
        return ""
    uri = picked.get("uri") or ""
    name = picked.get("name") or ""
    if not name:
        # Java 侧在 tree URI 上可能取不到显示名：用 URI 最后一段兜底，
        # 不然设置页那一行会退回显示本地路径，用户以为"没生效"
        name = saf_bridge.UriDisplayName(uri)
    return {"uri": uri, "name": name}


def OpenUri(uri):
    """ 请系统文件管理器打开一个 SAF 目录/文件 URI；返回 (ok, reason) """
    if not platform_mobile.IsAndroid():
        return False, "unsupported"
    try:
        from tools import saf_bridge
        return saf_bridge.OpenUri(uri)
    except Exception as es:
        _LogError(es)
        return False, "error"


def OpenDir(path):
    """ 请系统文件管理器打开目录；返回 True 表示已经交给系统

    手机上 `QDesktopServices.openUrl(file://…)` 既没有处理者、file:// 也被系统禁了 ——
    这就是"点了打开目录没反应"的原因。这里改走 SAF/Intent。
    """
    if not platform_mobile.IsAndroid():
        return False
    try:
        from tools import saf_bridge
        ok, reason = saf_bridge.OpenPath(path)
        if ok:
            return True
        if reason == "sandbox":
            try:
                from qt_owner import QtOwner
                QtOwner().ShowMsg("该目录在应用专属存储里，系统文件管理器无法浏览；"
                                  "请先在设置里选择一个导出目录（SAF）")
            except Exception:
                pass
        elif reason == "no_handler":
            try:
                from qt_owner import QtOwner
                QtOwner().ShowMsg("没有可打开该目录的文件管理器")
            except Exception:
                pass
        return True
    except Exception as es:
        _LogError(es)
        return False


def SaveBytes(parent, caption, defaultPath, filter, data):
    """ 另存为：手机上走 SAF(先选保存位置，再把 data 写进去)

    桌面端保持原来的 QFileDialog 行为(selected path 直接写)。
    返回落地后的路径(桌面端是用户选的路径，手机上是 SAF URI)；失败返回 ""。
    """
    if not data:
        return ""
    if not platform_mobile.IsAndroid():
        filepath = GetSaveFileName(parent, caption, defaultPath, filter)
        if not filepath or not filepath[0]:
            return ""
        with open(filepath[0], "wb") as f:
            f.write(data)
        return filepath[0]
    try:
        from tools import saf_bridge
        if not saf_bridge.IsSupported():
            return ""
        name = os.path.basename(str(defaultPath or "")) or "image.jpg"
        uri = saf_bridge.PickSave(caption or "", name, filter)
        if not uri:
            return ""
        staging = os.path.join(_ImportRoot(), "saf-save")
        try:
            os.makedirs(staging, exist_ok=True)
        except Exception:
            staging = _ImportRoot()
        tmp = os.path.join(staging, _SafeName(name))
        with open(tmp, "wb") as f:
            f.write(data)
        return uri if saf_bridge.WriteFile(uri, tmp) else ""
    except Exception as es:
        _LogError(es)
        return ""


def GetOpenFileName(parent=None, caption="", dir="", filter=""):
    """ 选择文件；返回 (文件名, 选中过滤器)，取消返回 () —— 与 QFileDialog 一致

    Android 上走 SAF(ACTION_OPEN_DOCUMENT)：选完把内容拷进应用缓存目录，返回
    **本地路径**(与桌面语义一致，调用方一行都不用改)。
    """
    if not platform_mobile.IsAndroid():
        from PySide6.QtWidgets import QFileDialog
        return QFileDialog.getOpenFileName(parent, caption, dir, filter)
    try:
        from tools import saf_bridge
        if saf_bridge.IsSupported():
            picked = saf_bridge.PickFile(caption or "", filter)
            if picked is None:
                return _Launch(parent, caption, dir, ModeOpen, filter)
            if not picked:
                return CancelResult
            return picked
    except Exception as es:
        _LogError(es)
    return _Launch(parent, caption, dir, ModeOpen, filter)


def GetSaveFileName(parent=None, caption="", dir="", filter=""):
    """ 另存为；返回 (文件路径, 选中过滤器)，取消返回 () —— 与 QFileDialog 一致 """
    if not platform_mobile.IsAndroid():
        from PySide6.QtWidgets import QFileDialog
        return QFileDialog.getSaveFileName(parent, caption, dir, filter)
    return _Launch(parent, caption, dir, ModeSave, filter)
