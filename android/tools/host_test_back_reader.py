# coding:utf-8
""" 看图界面返回键回归测试(主机侧，offscreen，不联网)

背景
----
真机现象：看图界面按返回键**毫无反应**，退不回漫画详情页。
readView.Close() 是一条长链(AddHistory -> ClearPixItem -> Clear -> CloseReadView)，
链上任意一步抛异常，真正切页的那步就永远执行不到；HandleBackKey 外层又把这个
按键记成"已处理"，所以表现就是"按了没反应"。本用例锁住兜底行为：
Close() 抛异常也必须回到详情页(在线)= 详情页层(本地)= 列表。
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="jm_back_reader_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["JMCOMIC_ANDROID"] = "1"
os.environ["ANDROID_PRIVATE"] = TMP
os.environ["JM_ANDROID_SAVE_DIR"] = os.path.join(TMP, "save")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "android"))
try:
    import curl_cffi  # noqa: F401
except Exception:
    sys.path.append(os.path.join(ROOT, "android", "shims"))
os.chdir(TMP)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget  # noqa: E402

app = QApplication([])

from tools import platform_mobile  # noqa: E402

platform_mobile.InitAndroidEnv(app)
assert platform_mobile.IsAndroid(), "IsAndroid 应为 True"

from tools import mobile_ui  # noqa: E402

assert mobile_ui.IsEnabled(), "手机端 IsEnabled 应为 True"


class FakeReadView(object):
    """ 只保留返回键用到的三个属性 + Close() """

    def __init__(self, raiseOnClose=False):
        self.bookId = "123456"
        self.isLocal = False
        self.raiseOnClose = raiseOnClose
        self.closed = 0

    def Close(self):
        self.closed += 1
        if self.raiseOnClose:
            raise RuntimeError("模拟 AddHistory/Clear 链路抛异常")


class FakeMain(QWidget):
    """ 最小主窗口：页面栈(0 详情/1 看图) + 子页面栈 """

    def __init__(self):
        QWidget.__init__(self)
        self.totalStackWidget = QStackedWidget(self)
        self.totalStackWidget.addWidget(QWidget())   # 0 详情页层
        self.totalStackWidget.addWidget(QWidget())   # 1 看图
        self.subStackWidget = QStackedWidget(self)
        self.bookInfoView = QWidget()
        self.bookInfoView2 = QWidget()
        self.subStackWidget.addWidget(self.bookInfoView)
        self.subStackWidget.addWidget(self.bookInfoView2)
        self.switched = []
        self.SwitchWidget = self._SwitchWidget

    def _SwitchWidget(self, widget, **kwargs):
        self.switched.append((widget, kwargs))


def PressBack(main):
    # HandleBackKey 有 200ms 去抖，模拟新的一次按键
    mobile_ui._backLastTick = 0.0
    return mobile_ui.HandleBackKey(main)


def MakeMain(read, subPage=None):
    main = FakeMain()
    if subPage is not None:
        main.subStackWidget.addWidget(subPage)
        main.subStackWidget.setCurrentWidget(subPage)
    main.readView = read
    main.totalStackWidget.setCurrentIndex(1)
    mobile_ui._mainView = main
    return main


# 1) Close() 正常：退看图，已经在详情页就不重复切
main = MakeMain(FakeReadView())
read = main.readView
assert PressBack(main) is True
assert read.closed == 1, read.closed
assert main.totalStackWidget.currentIndex() == 0, "应回到详情页层"
assert mobile_ui.BackStats["action"] == "close-reader", mobile_ui.BackStats
assert main.switched == [], "已在详情页, 不该重复切页: %s" % (main.switched,)
print("[ok] Close() 正常: 退看图 -> 详情页(已在详情页不重复切)")

# 2) Close() 抛异常(切页那步没执行)：兜底切层 + 补切这一本的详情页
searchView = QWidget()
main = MakeMain(FakeReadView(raiseOnClose=True), subPage=searchView)
read = main.readView
assert PressBack(main) is True, "异常也必须返回 True(按键不能漏给系统)"
assert read.closed == 1
assert main.totalStackWidget.currentIndex() == 0, "Close() 抛异常后必须兜底切回详情页层"
assert mobile_ui.BackStats["action"] == "close-reader", mobile_ui.BackStats
assert [w for w, _ in main.switched] == [main.bookInfoView], main.switched
assert main.switched[0][1].get("bookId") == "123456", main.switched
print("[ok] Close() 抛异常: 兜底切层 + 补切详情页")

# 3) 本地漫画：回本地列表，不切在线详情页
main = MakeMain(FakeReadView())
main.readView.isLocal = True
assert PressBack(main) is True
assert main.totalStackWidget.currentIndex() == 0
assert main.switched == [], "本地漫画不该切在线详情页: %s" % (main.switched,)
print("[ok] 本地漫画: 只回列表(不切在线详情页)")

# 4) 窗口级返回键快捷键：不依赖焦点，key=Back，WindowShortcut
main = FakeMain()
assert mobile_ui.InstallBackKeyShortcut(main) is True
shortcut = getattr(main, "_jmBackShortcut", None)
assert shortcut is not None, "应装上 _jmBackShortcut"
assert shortcut.key().toString() == "Back", shortcut.key().toString()
assert shortcut.context() == Qt.ShortcutContext.WindowShortcut, shortcut.context()
assert mobile_ui.InstallBackKeyShortcut(main) is False, "重复安装应返回 False"
print("[ok] 窗口级返回键快捷键: key=%s context=WindowShortcut"
      % shortcut.key().toString())

print("ALL PASS")
