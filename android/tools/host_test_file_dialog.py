# coding:utf-8
""" `src/tools/mobile_file_dialog.py` 的回归测试(主机侧，不需要真机)

背景
----
真机(vivo V2463A / Android 16)上，导入本地漫画 / 图片超分导入图片会**卡死**，
根因是 QFileDialog 在 Android 上会创建第二个顶层窗口并跑嵌套模态循环，永不返回。
修法是 `tools/mobile_file_dialog.py`：Android 下改用**主窗口内部的子覆盖控件**
(不产生顶层窗口) + 嵌套 QEventLoop；桌面端原样转发给 QFileDialog。

本测试验证两条路径：
    A. 桌面路径(IsAndroid()->False)：必须**原样**委托给 QFileDialog，
       并且返回值形状不变 —— 这是"桌面端行为完全不变"的硬约束。
    B. Android 路径(monkeypatch IsAndroid()->True)：用临时目录树直接构造覆盖控件，
       验证目录在前/文件在后、过滤器生效、上级/进入子目录、确定返回当前目录，
       以及读不了的目录只显示红字提示、不抛异常不卡死。

用法:
    QT_QPA_PLATFORM=offscreen python3 android/tools/host_test_file_dialog.py
失败时退出码非 0，并打印 FAIL 行。
"""
import os
import shutil
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import logging

# Log.Error 在没 Init 的情况下会报 "No handlers could be found"，这里补一个空的
logging.getLogger().addHandler(logging.NullHandler())

from PySide6.QtCore import QEvent, QEventLoop, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

from tools import mobile_file_dialog as mfd
from tools import platform_mobile

FAILED = []
CHECKS = [0]


def Check(cond, what):
    CHECKS[0] += 1
    if cond:
        print("ok   " + what)
    else:
        print("FAIL " + what)
        FAILED.append(what)
    return bool(cond)


def BuildTree(root):
    """ 造一棵临时目录树：子目录 + .zip + .txt + 两个 .png """
    os.makedirs(os.path.join(root, "sub"), exist_ok=True)
    os.makedirs(os.path.join(root, "locked"), exist_ok=True)
    for name, data in (("b.zip", b"PK"), ("c.txt", b"txt"),
                       ("z.png", b"png"), ("a.png", b"png")):
        with open(os.path.join(root, name), "wb") as f:
            f.write(data)
    with open(os.path.join(root, "sub", "inner.txt"), "wb") as f:
        f.write(b"inner")


def Names(entries):
    return [v["name"] for v in entries]


def MakePicker(root, mode, filter="", startDir=None, parent=None):
    """ 构造覆盖控件：不跑嵌套循环(主机测试直接操作内部状态) """
    return mfd._PickerDialog(parent, "test", startDir or root, mode, filter)


# --------------------------------------------------------------------- 桌面路径

def TestDesktopDelegate():
    print("\n===== A. 桌面路径：原样委托给 QFileDialog =====")
    sentinel = "/a/sentinel/dir"
    sentinelOpen = ("/a/sentinel/file.jpg", "Image Files(*.jpg)")
    sentinelSave = ("/a/sentinel/out.jpg", "Image Files(*.jpg)")
    calls = []

    realGetDir = QFileDialog.getExistingDirectory
    realGetOpen = QFileDialog.getOpenFileName
    realGetSave = QFileDialog.getSaveFileName

    def FakeGetDir(parent=None, caption="", dir="", options=None):
        calls.append(("dir", parent, caption, dir))
        return sentinel

    def FakeGetOpen(parent=None, caption="", dir="", filter="", selectedFilter="", options=None):
        calls.append(("open", parent, caption, dir, filter))
        return sentinelOpen

    def FakeGetSave(parent=None, caption="", dir="", filter="", selectedFilter="", options=None):
        calls.append(("save", parent, caption, dir, filter))
        return sentinelSave

    QFileDialog.getExistingDirectory = staticmethod(FakeGetDir)
    QFileDialog.getOpenFileName = staticmethod(FakeGetOpen)
    QFileDialog.getSaveFileName = staticmethod(FakeGetSave)
    try:
        Check(platform_mobile.IsAndroid() is False, "主机上 IsAndroid() 为 False")
        got = mfd.GetExistingDirectory(None, "cap", "/tmp")
        Check(got == sentinel, "GetExistingDirectory 委托结果原样返回: {!r}".format(got))
        Check(calls[-1] == ("dir", None, "cap", "/tmp"),
              "GetExistingDirectory 参数原样转发: {}".format(calls[-1]))

        got = mfd.GetOpenFileName(None, "cap", "/tmp", "Image Files(*.jpg)")
        Check(got == sentinelOpen, "GetOpenFileName 委托结果原样返回: {!r}".format(got))
        Check(calls[-1] == ("open", None, "cap", "/tmp", "Image Files(*.jpg)"),
              "GetOpenFileName 参数原样转发: {}".format(calls[-1]))

        got = mfd.GetSaveFileName(None, "cap", "/tmp/x.jpg", "Image Files(*.jpg)")
        Check(got == sentinelSave, "GetSaveFileName 委托结果原样返回: {!r}".format(got))
        Check(calls[-1] == ("save", None, "cap", "/tmp/x.jpg", "Image Files(*.jpg)"),
              "GetSaveFileName 参数原样转发: {}".format(calls[-1]))

        # 真实签名确认：QFileDialog 的 open/save 返回二元组、existing 返回字符串，
        # 我们的委托就是原样转发，所以形状天然一致(看 __doc__ 即可，不去真弹窗)
        Check("Tuple[str, str]" in (realGetOpen.__doc__ or ""),
              "QFileDialog.getOpenFileName 返回二元组(与本模块一致)")
        Check("Tuple[str, str]" in (realGetSave.__doc__ or ""),
              "QFileDialog.getSaveFileName 返回二元组(与本模块一致)")
        Check("-> str" in (realGetDir.__doc__ or ""),
              "QFileDialog.getExistingDirectory 返回字符串(与本模块一致)")
        Check(mfd.CancelResult == (), "取消值就是空元组(与 QFileDialog 一致)")
    finally:
        QFileDialog.getExistingDirectory = realGetDir
        QFileDialog.getOpenFileName = realGetOpen
        QFileDialog.getSaveFileName = realGetSave


# -------------------------------------------------------------------- Android 路径

def TestFilterParse():
    print("\n===== 过滤器解析 =====")
    Check(mfd._ParseFilterPatterns("Image Files(*.zip)") == [".zip"],
          "Image Files(*.zip) -> ['.zip']")
    Check(mfd._ParseFilterPatterns("Image Files(*.jpg *.png)") == [".jpg", ".png"],
          "多个模式 -> ['.jpg', '.png']")
    Check(mfd._ParseFilterPatterns("") == [], "空过滤器 -> 显示所有文件")
    Check(mfd._ParseFilterPatterns("*.*") == [], "*.* -> 显示所有文件")
    Check(mfd._ParseFilterPatterns("所有文件") == [], "无法解析的过滤器 -> 显示所有文件")


def TestListing(tempRoot):
    print("\n===== B. Android 路径：列表顺序与过滤 =====")
    entries = MakePicker(tempRoot, mfd.ModeDir).entries
    names = Names(entries)
    print("     条目: {}".format(names))
    Check(names[0] == "locked" and names[1] == "sub",
          "目录按名字排序且排在文件前面: {}".format(names[:2]))
    Check(all(not v["isDir"] for v in entries[2:]), "目录之后才是文件")
    Check(names == ["locked", "sub", "a.png", "b.zip", "c.txt", "z.png"],
          "同级按名字不区分大小写排序: {}".format(names))

    filtered = Names(MakePicker(tempRoot, mfd.ModeOpen, "Image Files(*.zip)").entries)
    print("     *.zip 过滤: {}".format(filtered))
    Check("b.zip" in filtered, "过滤器保留 .zip")
    Check("c.txt" not in filtered, "过滤器隐藏 .txt")
    Check("a.png" not in filtered, "过滤器隐藏 .png")

    onlyPng = Names(MakePicker(tempRoot, mfd.ModeOpen, "Image Files(*.jpg *.png)").entries)
    Check("a.png" in onlyPng and "z.png" in onlyPng and "b.zip" not in onlyPng,
          "多模式过滤器: {}".format(onlyPng))

    allFiles = Names(MakePicker(tempRoot, mfd.ModeOpen, "").entries)
    Check("c.txt" in allFiles and "b.zip" in allFiles, "无过滤器时显示所有文件")


def TestNavigation(tempRoot):
    print("\n===== B. Android 路径：进入子目录 / 上级 =====")
    picker = MakePicker(tempRoot, mfd.ModeDir)
    picker.SelectName("sub")
    Check(picker._SelectedPath() == "", "目录条目不会被当成选中文件")
    picker._OnItemDoubleClicked(picker.listWidget.currentItem())
    Check(os.path.abspath(picker.currentDir) == os.path.abspath(os.path.join(tempRoot, "sub")),
          "双击目录进入子目录: {}".format(picker.currentDir))
    Check(Names(picker.entries) == ["inner.txt"], "子目录列表正确: {}".format(Names(picker.entries)))

    picker._GoUp()
    Check(os.path.abspath(picker.currentDir) == os.path.abspath(tempRoot),
          "上级返回父目录: {}".format(picker.currentDir))
    Check("sub" in Names(picker.entries), "返回后列表恢复")

    # 到根目录后"上级"必须禁用，否则会跳出可访问范围
    picker.setCurrentDir(tempRoot)
    picker._GoUp()
    Check(picker.upButton.isEnabled() is True, "有父目录时'上级'可用")
    picker.setCurrentDir("/")
    Check(picker.upButton.isEnabled() is False, "'/' 上'上级'禁用")


def TestDirAccept(tempRoot):
    print("\n===== B. Android 路径：目录模式确定 / 取消 =====")
    picker = MakePicker(tempRoot, mfd.ModeDir)
    Check(picker.result == "", "初始 result 是取消值(空串)")
    picker._Accept()
    Check(isinstance(picker.result, tuple) and len(picker.result) == 2,
          "确定后 result 是二元组: {!r}".format(picker.result))
    Check(os.path.abspath(picker.result[0]) == os.path.abspath(tempRoot),
          "目录模式确定返回当前目录: {}".format(picker.result[0]))

    picker2 = MakePicker(tempRoot, mfd.ModeDir)
    picker2.Cancel()
    Check(picker2.result == "", "取消返回空串")

    # 返回键(Android 的 Key_Back)与 Esc 都必须是取消
    for key, label in ((Qt.Key.Key_Back, "Key_Back"), (Qt.Key.Key_Escape, "Key_Escape")):
        picker3 = MakePicker(tempRoot, mfd.ModeDir)
        event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
        picker3.keyPressEvent(event)
        Check(picker3.result == "", "{} 取消: {!r}".format(label, picker3.result))


def TestOpenAccept(tempRoot):
    print("\n===== B. Android 路径：打开模式确定 =====")
    picker = MakePicker(tempRoot, mfd.ModeOpen, "Image Files(*.zip)")
    Check(picker.SelectName("b.zip"), "能选中 b.zip")
    Check(picker.okButton.isEnabled() is True, "选中文件后'确定'可用")
    Check(picker._SelectedPath() == os.path.join(tempRoot, "b.zip"),
          "选中文件路径正确: {}".format(picker._SelectedPath()))
    picker._Accept()
    Check(picker.result == (os.path.join(tempRoot, "b.zip"), "Image Files(*.zip)"),
          "打开模式返回 (文件, 过滤器): {!r}".format(picker.result))

    empty = MakePicker(tempRoot, mfd.ModeOpen, "Image Files(*.zip)")
    empty._Accept()
    Check(empty.result == (), "没选文件就确定 -> 不返回，仍留在界面")

    # 双击文件 = 确定
    picker2 = MakePicker(tempRoot, mfd.ModeOpen, "Image Files(*.zip)")
    picker2.SelectName("b.zip")
    picker2._OnItemDoubleClicked(picker2.listWidget.currentItem())
    Check(picker2.result[0] == os.path.join(tempRoot, "b.zip"), "双击文件等于确定")


def TestSaveAccept(tempRoot):
    print("\n===== B. Android 路径：保存模式 =====")
    picker = MakePicker(tempRoot, mfd.ModeSave, "Image Files(*.jpg)", startDir=tempRoot)
    Check(picker.nameEdit is not None, "保存模式有文件名输入框")
    picker.nameEdit.setText("out.jpg")
    picker._Accept()
    Check(picker.result == (os.path.join(tempRoot, "out.jpg"), "Image Files(*.jpg)"),
          "保存模式返回 os.path.join(当前目录, 文件名): {!r}".format(picker.result))

    # 调用点会传带默认文件名的路径(如 read_view 的 "{bookId}_{page}.jpg")
    withName = MakePicker(tempRoot, mfd.ModeSave, "", startDir=os.path.join(tempRoot, "def.jpg"))
    Check(withName.currentDir.rstrip("/") == tempRoot.rstrip("/"),
          "dir 是完整文件路径时，起始目录取它的父目录: {}".format(withName.currentDir))
    Check(withName.nameEdit.text() == "def.jpg",
          "默认文件名填进输入框: {!r}".format(withName.nameEdit.text()))

    relative = MakePicker(tempRoot, mfd.ModeSave, "", startDir="20240101.jpg")
    Check(relative.nameEdit.text() == "20240101.jpg",
          "相对默认文件名也能填进输入框: {!r}".format(relative.nameEdit.text()))


def TestUnreadable(tempRoot):
    print("\n===== B. Android 路径：读不了的目录只报错、不卡死 =====")
    locked = os.path.join(tempRoot, "no_such_dir")
    if os.geteuid() != 0:
        # 普通用户可以用真的权限位模拟
        locked = os.path.join(tempRoot, "locked")
        os.chmod(locked, 0)

    picker = MakePicker(tempRoot, mfd.ModeDir)
    before = os.path.abspath(picker.currentDir)
    result = picker.setCurrentDir(locked)
    Check(result is False, "进入读不了的目录返回 False")
    Check(os.path.abspath(picker.currentDir) == before, "读不了时停在原目录")
    Check("无法访问该目录" in picker.errorLabel.text(),
          "显示红字提示: {!r}".format(picker.errorLabel.text()))
    Check(picker.okButton.isEnabled() is True, "目录模式确定按钮仍然可用(当前目录可读)")

    if os.geteuid() != 0:
        os.chmod(locked, stat.S_IRWXU)

    # 真机上最典型的场景：目录本身在(挂载点存在)，但 os.scandir 抛 PermissionError
    # (Android 16 + targetSdk 34 + 没有"所有文件访问权限"时 /storage/emulated/0 就是这样)。
    # root 身份无视权限位，所以这里直接把 os.scandir 换成会抛异常的版本 —— 等价于那道权限墙。
    realScandir = mfd.os.scandir

    def DeniedScandir(path, *args, **kwargs):
        raise PermissionError(13, "Permission denied", str(path))

    mfd.os.scandir = DeniedScandir
    try:
        picker2 = MakePicker(tempRoot, mfd.ModeDir)
        Check(picker2.entries == [], "列不出来时条目为空")
        Check("无法访问该目录" in picker2.errorLabel.text(),
              "os.scandir 抛 PermissionError -> 红字提示: {!r}".format(picker2.errorLabel.text()))
        Check(os.path.abspath(picker2.currentDir) == os.path.abspath(tempRoot),
              "列不出来时仍停在当前目录: {}".format(picker2.currentDir))
        mfd.os.scandir = realScandir
        Check(picker2.setCurrentDir(os.path.join(tempRoot, "sub")) is True,
              "报错后换个目录仍能正常工作(没有卡死)")
        Check("无法访问该目录" not in picker2.errorLabel.text(), "成功进入后红字提示消失")
    finally:
        mfd.os.scandir = realScandir

    broken = mfd._PickerDialog(None, "t", "/no/such/dir/at/all", mfd.ModeDir, "")
    Check(broken.currentDir != "", "起始目录不存在时回退到一个可用目录: {}".format(broken.currentDir))
    Check(mfd._IsReadableDir(broken.currentDir), "回退目录确实可读")


def TestShortcutsAndShape():
    print("\n===== B. Android 路径：快捷入口与窗口形状 =====")
    tree = tempfile.mkdtemp(prefix="jmfd_short_")
    try:
        os.makedirs(os.path.join(tree, "s"), exist_ok=True)
        picker = MakePicker(tree, mfd.ModeDir)
        Check(len(picker.shortcutButtons) >= 2,
              "至少有应用目录/私有目录两个快捷入口: {}".format(
                  [b.text() for b in picker.shortcutButtons]))
        labels = [b.text() for b in picker.shortcutButtons]
        Check("存储" in labels or "下载" in labels or "图片" in labels,
              "手机存储快捷入口也在列表里(读不了则置灰): {}".format(labels))
        # 应用目录/私有目录必须可用；手机存储那几个在 APK 里读不了时必须是置灰的
        for button in picker.shortcutButtons:
            path = button.toolTip().split("（")[0]
            readable = mfd._IsReadableDir(path)
            Check(bool(button.isEnabled()) == readable,
                  "快捷入口'{}'可用性与实际可读性一致(读不了就置灰): {}".format(
                      button.text(), path))
        appDirButtons = [b for b in picker.shortcutButtons if b.text() in ("应用目录", "私有目录")]
        Check(appDirButtons and all(b.isEnabled() for b in appDirButtons),
              "应用目录/私有目录快捷入口可用")
        # 覆盖控件必须是**子控件**，不能是新的顶层窗口
        parent = QWidget()
        parent.resize(384, 845)
        child = MakePicker(tree, mfd.ModeDir, parent=parent)
        Check(child.parent() is parent, "覆盖控件 parent 到调用点所在窗口(不是顶层窗口)")
        Check(child.isWindow() is False, "覆盖控件 isWindow() = False(没有第二个顶层窗口)")
        Check(child.geometry() == parent.rect(), "覆盖控件铺满父窗口: {}".format(child.geometry()))
        Check(child.hintLabel.isVisible() or child.hintLabel.text(),
              "顶部有手机存储权限提示")
        Check("所有文件访问权限" in child.hintLabel.text(),
              "提示内容说明需要'所有文件访问权限'")
        Check(len(child.pathLabel.text()) <= 400, "路径行受控(中间省略)")
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def TestNestedLoop():
    """ 真正跑一次嵌套 QEventLoop：确认阻塞式调用能拿到结果并返回(不卡死) """
    print("\n===== B. Android 路径：嵌套事件循环(原有阻塞式调用点) =====")
    tree = tempfile.mkdtemp(prefix="jmfd_loop_")
    try:
        os.makedirs(os.path.join(tree, "sub"), exist_ok=True)
        holder = {"picker": None, "result": "未返回"}

        def OnLoop():
            picker = mfd._PickerDialog(None, "t", tree, mfd.ModeDir, "")
            holder["picker"] = picker
            QTimer.singleShot(0, picker._Accept)
            holder["result"] = picker._Run()

        loop = QEventLoop()
        QTimer.singleShot(0, OnLoop)
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(5000)
        loop.exec()

        Check(holder["result"] != "未返回", "嵌套循环返回了(没有卡死)")
        if holder["result"] != "未返回":
            Check(isinstance(holder["result"], tuple) and
                  os.path.abspath(holder["result"][0]) == os.path.abspath(tree),
                  "嵌套循环里确定返回当前目录: {!r}".format(holder["result"]))
        Check(holder["picker"] is not None and holder["picker"].isVisible() is False,
              "返回后覆盖控件已隐藏")
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def TestStaticApiOnAndroid(tempRoot):
    """ IsAndroid() 为真时，三个静态函数必须走覆盖控件而不是 QFileDialog """
    print("\n===== B. Android 路径：静态函数走应用内选择器 =====")
    called = {"qfd": 0}

    def Boom(*args, **kwargs):
        called["qfd"] += 1
        raise AssertionError("Android 上不允许调用 QFileDialog")

    realGetDir = QFileDialog.getExistingDirectory
    QFileDialog.getExistingDirectory = staticmethod(Boom)
    realRun = mfd._PickerDialog._Run
    try:
        def FakeRun(self):
            self._Accept()
            return self.result

        mfd._PickerDialog._Run = FakeRun
        got = mfd.GetExistingDirectory(None, "cap", tempRoot)
        Check(got == (tempRoot, ""), "Android: GetExistingDirectory 返回 (目录, 过滤器): {!r}".format(got))
        Check(called["qfd"] == 0, "Android 上没有碰 QFileDialog")

        got = mfd.GetOpenFileName(None, "cap", tempRoot, "Image Files(*.zip)")
        Check(got == (), "Android: 没选文件时 GetOpenFileName 返回 () : {!r}".format(got))

        got = mfd.GetSaveFileName(None, "cap", tempRoot, "Image Files(*.jpg)")
        Check(got == (), "Android: 没输入文件名时 GetSaveFileName 返回 () : {!r}".format(got))
    finally:
        QFileDialog.getExistingDirectory = realGetDir
        mfd._PickerDialog._Run = realRun


def TestParentWindowFallback(tempRoot):
    """ parent 为 None / 不是 QWidget 时也必须找到真实的主窗口，不能抛异常 """
    print("\n===== 兜底：parent 缺失也必须有可用父窗口 =====")
    # 模仿真机：先有主窗口(顶层的)，再弹选择器
    host = QWidget()
    host.setObjectName("FakeMainWindow")
    host.resize(384, 845)
    host.show()
    try:
        QApplication.processEvents()
        window = mfd._ParentWindow(None)
        Check(isinstance(window, QWidget), "_ParentWindow(None) 返回一个窗口: {!r}".format(window))
        Check(window is not None and window.isWindow() is True, "兜底拿到的是顶层窗口(主窗口)")
        Check(mfd._ParentWindow("not a widget") is window, "_ParentWindow(非 QWidget) 走同一个兜底")
        picker = mfd._PickerDialog(None, "t", tempRoot, mfd.ModeDir, "")
        Check(isinstance(picker, mfd._PickerDialog), "parent=None 也能构造覆盖控件")
        Check(picker.parent() is window, "parent=None 时覆盖控件仍挂在主窗口内部(不是顶层窗口)")
        Check(picker.isWindow() is False, "parent=None 也不会新建顶层窗口")
    finally:
        host.close()
        host.deleteLater()
        QApplication.processEvents()


def Main():
    print("python: {}".format(sys.version.replace("\n", " ")))
    print("repo  : {}".format(REPO))

    app = QApplication.instance() or QApplication(sys.argv[:1])

    TestDesktopDelegate()

    # ---- 从这里开始伪装成 Android ----
    realIsAndroid = platform_mobile.IsAndroid
    platform_mobile.IsAndroid = lambda: True
    tempRoot = tempfile.mkdtemp(prefix="jmfd_tree_")
    try:
        BuildTree(tempRoot)
        print("临时目录树: {}".format(tempRoot))
        TestFilterParse()
        TestListing(tempRoot)
        TestNavigation(tempRoot)
        TestDirAccept(tempRoot)
        TestOpenAccept(tempRoot)
        TestSaveAccept(tempRoot)
        TestUnreadable(tempRoot)
        TestShortcutsAndShape()
        TestNestedLoop()
        TestStaticApiOnAndroid(tempRoot)
        TestParentWindowFallback(tempRoot)
    finally:
        platform_mobile.IsAndroid = realIsAndroid
        shutil.rmtree(tempRoot, ignore_errors=True)

    print("\n检查项 {} 个，失败 {}".format(CHECKS[0], len(FAILED)))
    if FAILED:
        for item in FAILED:
            print("  FAIL " + item)
        print("结果: 有 {} 项失败".format(len(FAILED)))
        return 1
    print("结果: 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(Main())
