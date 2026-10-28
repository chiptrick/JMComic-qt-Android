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
        self.lastCount = 0
        self.SwitchWidget = self._SwitchWidget

    def _SwitchWidget(self, widget, **kwargs):
        self.switched.append((widget, kwargs))

    def SwitchWidgetLast(self):
        self.lastCount += 1


def PressBack(main):
    # HandleBackKey 有 400ms 去抖，模拟新的一次按键(按下)
    mobile_ui._backLastTick = 0.0
    mobile_ui._backLastSource = ""
    mobile_ui._backPressTick = 0.0
    return mobile_ui.HandleBackKey(main, "press")


def ShiftBackTicks(ms):
    """ 把返回键的时间戳往前挪 ms(模拟"两个事件之间过了这么久") """
    mobile_ui._backLastTick -= ms
    mobile_ui._backPressTick -= ms


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


class FakeReaderWithTool(object):
    """ 带工具菜单的假看图页：菜单是子控件，父控件(看图页)可以被"不在前台" """

    def __init__(self):
        self.bookId = ""
        self.isLocal = False
        self.page = QWidget()               # 看图页(隐藏 = 不在前台)
        self.frame = QWidget(self.page)
        self.frame.qtTool = QWidget(self.frame)
        self.closed = 0

    def Close(self):
        self.closed += 1


def MakeNav(main, index=1):
    """ 给假主窗口装上"多级页面"用的子页面栈(0 首页 / 1 二级页) """
    main.subStackList = [0, 1]
    main.subStackWidget.addWidget(QWidget())
    main.subStackWidget.addWidget(QWidget())
    main.subStackWidget.setCurrentIndex(index)
    return main


# 5) 看图页不在前台时，"菜单自己没被 hide"不能吃掉返回键
#    (真机现象：退出看图后在任何页面按返回都要按两次 —— 第一次去隐藏一个看不见的菜单)
read = FakeReaderWithTool()
main = MakeNav(FakeMain())
main.totalStackWidget.setCurrentIndex(0)       # 当前不在看图
main.readView = read
mobile_ui._mainView = main
assert read.frame.qtTool.isHidden() is False, "前提：菜单自己没被 hide，但父控件隐藏"
assert read.frame.qtTool.isVisible() is False, "前提：用户其实看不见它"
assert PressBack(main) is True
assert mobile_ui.BackStats["action"] == "switch-widget-last", \
    "看图页不在前台时，返回键必须直接走页面回退，不能被 close-read-tool 吃掉: %s" \
    % (mobile_ui.BackStats,)
print("[ok] 看图页不在前台: 一次返回键就回退(不再被看不见的菜单吃掉)")

# 6) 看图页在前台且菜单真的显示：一次返回键收起菜单，再一次退看图
main = MakeNav(FakeMain())
main.totalStackWidget.setCurrentIndex(1)
main.readView = read
mobile_ui._mainView = main
read.page.show()
read.frame.show()
read.frame.qtTool.show()
app.processEvents()
assert read.frame.qtTool.isVisible() is True
assert PressBack(main) is True
assert mobile_ui.BackStats["action"] == "close-read-tool", mobile_ui.BackStats
assert read.frame.qtTool.isHidden() is True, "菜单必须真的收起来"
assert read.closed == 0, "收菜单不能顺手退出看图"
assert PressBack(main) is True
assert mobile_ui.BackStats["action"] == "close-reader", mobile_ui.BackStats
assert read.closed == 1
print("[ok] 看图菜单: 一次收菜单，再一次退看图(每按一次只走一档)")

# 7) 输入框焦点/软键盘：切页/进出看图/按返回时主动收掉
#    (Qt 认为软键盘弹着时会把返回键拿去收键盘并吞掉，用户看到的就是"要按两次")
from PySide6.QtWidgets import QLineEdit  # noqa: E402

win = QWidget()
win.show()
edit = QLineEdit(win)
edit.show()
edit.setFocus()
app.processEvents()
assert edit.hasFocus(), "前提：输入框拿到焦点"
assert mobile_ui.DismissTextInput("host-test") is True, "应报告已收起东西"
assert not edit.hasFocus(), "输入框焦点必须被清掉(否则 Qt 一直认为软键盘弹着)"
assert mobile_ui.DismissTextInput("host-test") is False, "已经没有可收的东西了"
print("[ok] 输入框焦点: 主动清掉(返回键不会再被 Qt 当成收软键盘吞掉)")

# 8) 一次物理按键只能走一档：按下做了动作，同一次按键的抬起(哪怕晚 430ms 才来)
#    不能再做一次。真机实测：抬起能晚 400ms 以上，只靠时间去抖会"按一次退两级"，
#    在首页就是"按一次直接退出"。
mobile_ui._backLastTick = 0.0
mobile_ui._backLastSource = ""
mobile_ui._backPressTick = 0.0
main = MakeNav(FakeMain())
main.subStackList = [0, 1, 2]
main.subStackWidget.addWidget(QWidget())
main.subStackWidget.setCurrentIndex(2)
main.totalStackWidget.setCurrentIndex(0)
main.readView = FakeReaderWithTool()
mobile_ui._mainView = main
assert mobile_ui.HandleBackKey(main, "press") is True
assert main.lastCount == 1, "按下应回退一档: %s" % (main.lastCount,)
ShiftBackTicks(430)                      # 抬起晚 430ms 才到
assert mobile_ui.HandleBackKey(main, "release") is True, "抬起也要吃掉事件"
assert main.lastCount == 1, "同一次按键的抬起不能再回退一档: %s" % (main.lastCount,)
print("[ok] 按下 + 抬起(晚 430ms): 只走一档")

# 9) 按下被系统吞掉(只来抬起)的机型：抬起照样要能返回，连按两次也要算两次
mobile_ui._backLastTick = 0.0
mobile_ui._backLastSource = ""
mobile_ui._backPressTick = 0.0
main = MakeNav(FakeMain())
main.subStackList = [0, 1, 2]
main.subStackWidget.addWidget(QWidget())
main.subStackWidget.setCurrentIndex(2)
main.totalStackWidget.setCurrentIndex(0)
main.readView = FakeReaderWithTool()
mobile_ui._mainView = main
assert mobile_ui.HandleBackKey(main, "release") is True
assert main.lastCount == 1, "只剩抬起时也必须返回: %s" % (main.lastCount,)
ShiftBackTicks(300)
assert mobile_ui.HandleBackKey(main, "release") is True
assert main.lastCount == 2, "两次按键(两次抬起)要算两次: %s" % (main.lastCount,)
print("[ok] 只有抬起事件时: 每次按键都算一次(不会丢掉连按)")

print("ALL PASS")
