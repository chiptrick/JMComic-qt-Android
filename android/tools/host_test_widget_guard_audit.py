# coding:utf-8
""" 宿主自检：全项目"文本框 / 选项框"防误触覆盖审计

背景：滑动误触修了两轮 —— 先是选项框(勾选框/单选/下拉框)，再是文本框(输入框)。
两轮都靠"合成鼠标点按门卫"(_TapGate) + 触控路由的通道分流。这个脚本把**覆盖面**
变成可执行的清单，避免以后再冒出一个新的输入控件却没人给它挂门卫：

  [1] 静态清单：扫 ui/*.ui 与 ui/component/*.ui，把"文本框 / 选项框 / 数值框"逐个
      列出来，按处理方式归类；出现**没登记过**的控件类直接失败(逼着做决定)。
  [2] 运行期核验：实例化真实页面(分流设置页 Ui_LoginNew、设置页 Ui_SettingNew)，
      调用**真实的** `InstallTouchGuard`(把 IsEnabled 打桩成 True)，再逐个断言：
        * 勾选框/单选/下拉框 -> 有门卫 && 分类 activate
        * 可编辑文本框(含 QTextEdit 的 viewport) -> 有门卫 && 分类 input
        * 只读文本框 -> 分类 native(不弹输入法，选中交给长按门卫)
        * 数值框 -> **不**挂门卫 && 分类 spin(自动重复只认 mouseRelease)
  [3] 汇总：把"处理方式"打印成一张表，方便人工复核。

用法：python android/tools/host_test_widget_guard_audit.py
"""
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QAbstractSpinBox,
                                   QApplication, QComboBox, QLineEdit, QPlainTextEdit,
                                   QScrollArea, QTextEdit, QWidget)
except Exception as es:                      # pragma: no cover
    print("SKIP: 本机没有 PySide6 ({})".format(es))
    sys.exit(0)

import tools.mobile_ui_touch as touch  # noqa: E402

Failures = []


def Check(condition, message):
    if condition:
        print("  ok  {}".format(message))
    else:
        Failures.append(message)
        print("  FAIL {}".format(message))


# ---------------------------------------------------------------------------
# 静态清单：.ui 里出现过的控件类 -> (归类, 防误触方式)
# ---------------------------------------------------------------------------
# 新增控件类时**必须**在这里登记：脚本会因为"没登记"而失败，从而不会漏掉挂门卫。
WidgetPolicy = {
    # 选项框(点击切换状态)
    "QCheckBox": ("选项框", "门卫 _TapGate(滑动不切状态)"),
    "QRadioButton": ("选项框", "门卫 _TapGate(滑动不切状态)"),
    "QComboBox": ("选项框(下拉)", "门卫 _TapGate + 弹出列表也挂"),
    "WheelComboBox": ("选项框(下拉)", "门卫 _TapGate + 弹出列表也挂"),
    # 文本框
    "QLineEdit": ("文本框", "门卫 _TapGate(扣住按下, 点按才补回)"),
    "TipLineEdit": ("文本框", "门卫 _TapGate(扣住按下, 点按才补回)"),
    "SearchLineEdit": ("文本框", "门卫 _TapGate(扣住按下, 点按才补回)"),
    "QTextEdit": ("文本框(多行)", "viewport 挂门卫 / 只读走长按门卫"),
    "QPlainTextEdit": ("文本框(多行)", "viewport 挂门卫 / 只读走长按门卫"),
    # 数值框：按住自动重复只认 mouseRelease，不能挂门卫
    "QSpinBox": ("数值框", "spin 通道(不挂门卫)"),
    "QDoubleSpinBox": ("数值框", "spin 通道(不挂门卫)"),
    "WheelSpinBox": ("数值框", "spin 通道(不挂门卫)"),
    "WheelDoubleSpinBox": ("数值框", "spin 通道(不挂门卫)"),
    # 其余"点按类"按钮(不切设置，但同一套门卫)
    "QPushButton": ("按钮", "门卫 _TapGate"),
    "QToolButton": ("按钮", "门卫 _TapGate"),
    "IconToolButton": ("按钮", "门卫 _TapGate"),
    "QCommandLinkButton": ("按钮", "门卫 _TapGate"),
    "QDialogButtonBox": ("按钮", "门卫 _TapGate"),
    "QTabBar": ("标签条", "自己的横划通道(不挂门卫)"),
    # 需要真鼠标按下语义的
    "QSlider": ("滑块", "native(不碰触控)"),
    "QScrollBar": ("滚动条", "native(不碰触控)"),
    "QTextBrowser": ("只读文本", "native + 长按门卫"),
    "SmoothScrollArea": ("滚动区", "QScroller 接管"),
}

WatchPolicy = ("选项框", "选项框(下拉)", "文本框", "文本框(多行)", "数值框")


def ScanUi():
    """ 扫所有 .ui，返回 [(类名, 控件名, 文件)] 里"和防误触有关"的那些 """
    found = []
    for base, _dirs, files in os.walk(os.path.join(ROOT, "ui")):
        for name in files:
            if not name.endswith(".ui"):
                continue
            path = os.path.join(base, name)
            try:
                tree = ET.parse(path)
            except Exception as es:
                print("  !! 解析失败 {}: {}".format(name, es))
                continue
            for node in tree.iter("widget"):
                cls = node.get("class") or ""
                objName = node.get("name") or "?"
                policy = WidgetPolicy.get(cls)
                if policy is None or policy[0] not in WatchPolicy:
                    continue
                found.append((cls, objName, os.path.relpath(path, ROOT), policy[0]))
    return found


def TestStatic():
    print("\n[1] 静态清单：.ui 里的文本框/选项框/数值框")
    found = ScanUi()
    byClass = {}
    for cls, _obj, _path, kind in found:
        byClass.setdefault((cls, kind), []).append(_obj)
    for (cls, kind), objs in sorted(byClass.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        print("  {:<22} {:<10} x{:<3} {}".format(
            cls, kind, len(objs), WidgetPolicy[cls][1]))
    Check(len(found) > 0, "扫到 {} 个受管控件".format(len(found)))

    # 没登记过的控件类 -> 失败(新增控件必须在这里表态)
    known = set()
    for base, _dirs, files in os.walk(os.path.join(ROOT, "ui")):
        for name in files:
            if not name.endswith(".ui"):
                continue
            try:
                tree = ET.parse(os.path.join(base, name))
            except Exception:
                continue
            for node in tree.iter("widget"):
                known.add(node.get("class") or "")
    import component.line_edit.search_line_edit  # noqa: F401  确认自定义类可导入
    custom = sorted(c for c in known if not c.startswith("Q") and c not in WidgetPolicy)
    unhandled = [c for c in custom if c.endswith(("LineEdit", "Edit", "ComboBox",
                                                  "CheckBox", "RadioButton", "SpinBox"))]
    Check(not unhandled, "没有'没登记处理方式'的输入类控件 {}".format(unhandled or ""))
    return True


def Prepare(page):
    """ 用**真实的** InstallTouchGuard 给这一页装防误触(把'是不是移动端'打桩成 True) """
    touch.IsEnabled = lambda: True
    touch.mobile_ui._touchGuard = None
    touch.mobile_ui._scrollWatcher = None
    touch.InstallTouchGuard(page)
    QApplication.processEvents()
    return page


def AuditPage(page, title):
    print("\n   --- {} ---".format(title))
    buttons = page.findChildren(QAbstractButton)
    combos = page.findChildren(QComboBox)
    edits = page.findChildren(QLineEdit)
    texts = page.findChildren(QTextEdit) + page.findChildren(QPlainTextEdit)
    spins = page.findChildren(QAbstractSpinBox)
    sliders = page.findChildren(QAbstractSlider)

    bad = []
    for widget in buttons + combos:
        gate = getattr(widget, "_jmTapGate", None)
        mode = touch._TouchRouter._Classify(widget)
        ok = (gate is not None) and (mode == "activate"
                                     or (mode == "tabbar"
                                         and touch._TabBarAncestor(widget) is not None))
        if not ok:
            bad.append("{}:{} gate={} mode={}".format(type(widget).__name__,
                                                      widget.objectName() or "?", gate is not None, mode))
    Check(not bad, "{:<10} {} 个勾选框/单选/按钮 + {} 个下拉框都有门卫且分类 activate {}".format(
        title, len(buttons), len(combos), bad or ""))

    bad = []
    skipped = 0
    for widget in edits:
        if isinstance(widget.parentWidget(), (QComboBox, QAbstractSpinBox)):
            skipped += 1                    # 下拉框/数值框内部的输入行
            continue
        if widget.isReadOnly():
            continue
        gate = getattr(widget, "_jmTapGate", None)
        mode = touch._TouchRouter._Classify(widget)
        if gate is None or mode != "input":
            bad.append("{}:{} gate={} mode={}".format(type(widget).__name__,
                                                      widget.objectName() or "?", gate is not None, mode))
    Check(not bad, "{:<10} {} 个单行文本框(跳过 {} 个组合控件内部输入行)都有门卫且分类 input {}".format(
        title, len(edits) - skipped, skipped, bad or ""))

    bad = []
    for widget in texts:
        target = touch._GateInstallTarget(widget)
        gate = getattr(target, "_jmTapGate", None)
        mode = touch._TouchRouter._Classify(widget)
        visible = widget.objectName() or "?"
        if widget.isReadOnly():
            if mode != "native":
                bad.append("只读 {} mode={}(应为 native)".format(visible, mode))
        elif gate is None or mode != "input":
            bad.append("{} gate={} mode={}".format(visible, gate is not None, mode))
    Check(not bad, "{:<10} {} 个多行文本框：可编辑有门卫/只读走 native {}".format(
        title, len(texts), bad or ""))

    bad = []
    for widget in spins:
        if getattr(widget, "_jmTapGate", None) is not None:
            bad.append("{} 不该挂门卫(会把 release 吞掉导致数值一直加)".format(widget.objectName()))
        if touch._TouchRouter._Classify(widget) != "spin":
            bad.append("{} 分类应为 spin".format(widget.objectName()))
    Check(not bad, "{:<10} {} 个数值框：不挂门卫、走 spin 通道 {}".format(
        title, len(spins), bad or ""))

    for widget in sliders:
        mode = touch._TouchRouter._Classify(widget)
        if mode != "native":
            Check(False, "{} 滑块/滚动条应为 native，实际 {}".format(widget.objectName(), mode))
    return True


def TestRuntime():
    print("\n[2] 运行期核验：真实页面逐个控件检查")
    from interface.ui_login_new import Ui_LoginNew
    from interface.ui_setting_new import Ui_SettingNew

    class LoginPage(QWidget, Ui_LoginNew):
        def __init__(self):
            super().__init__()
            self.setupUi(self)
            self.resize(384, 720)
            self.tabWidget.setCurrentIndex(3)       # 分流页

    class SettingPage(QWidget, Ui_SettingNew):
        def __init__(self):
            super().__init__()
            self.setupUi(self)
            self.resize(384, 720)

    app = QApplication.instance()
    login = LoginPage()
    login.show()
    app.processEvents()
    Prepare(login)
    AuditPage(login, "分流设置页")
    login.hide()

    setting = SettingPage()
    setting.show()
    app.processEvents()
    Prepare(setting)
    AuditPage(setting, "设置页")
    setting.hide()
    return True


def main():
    QApplication(sys.argv)          # 必须先有 QApplication，再谈控件
    print("=" * 78)
    print("文本框 / 选项框 防误触覆盖审计")
    print("=" * 78)
    TestStatic()
    TestRuntime()
    print("")
    if Failures:
        print("FAIL: {} 项没通过".format(len(Failures)))
        for item in Failures:
            print("  - {}".format(item))
        return 1
    print("OK: 覆盖审计全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
