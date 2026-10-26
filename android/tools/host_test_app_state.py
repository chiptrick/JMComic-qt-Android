# coding:utf-8
""" 宿主自检：前后台切换钩子（进后台刷帧 / 回前台重排重绘）

真机现象(0.53)：按 HOME 进后台后，多任务界面里看不到本应用的画面。

根因有两层，本自检只锁第 2 层(第 1 层在 android/main.py：把渲染容器从
SurfaceView 换成 TextureView——SurfaceView 的内容不在 View 树里，系统抓任务
快照抓不到，整屏都是黑的)：

    第 2 层：系统是在 Activity 停下来前后抓快照的。如果这一帧还没刷出去，
    抓到的同样是黑图。所以在 ApplicationInactive(≈onPause、画面还在)主动
    repaint 一次，把当前这一屏推给系统；回前台(ApplicationActive)再按新尺寸
    重排+重绘一次，顺带修"从多任务切回来黑屏/白屏"的老问题。

用法：python android/tools/host_test_app_state.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
except Exception as es:                      # pragma: no cover - 宿主没有 PySide6
    print("SKIP: 本机没有 PySide6 ({})".format(es))
    sys.exit(0)

import tools.mobile_ui as mobile_ui  # noqa: E402
import tools.mobile_ui_hooks as hooks  # noqa: E402

Failures = []


def Check(condition, message):
    if condition:
        print("  ok  {}".format(message))
    else:
        print("  FAIL {}".format(message))
        Failures.append(message)


def Main():
    app = QApplication.instance() or QApplication(sys.argv)
    # 宿主不是 Android：把平台判定钉成 True，才能装这条移动端钩子
    hooks.IsEnabled = lambda: True

    counts = {"onshown": 0, "repaint": 0}
    originalOnShown = mobile_ui.OnShown
    mobile_ui.OnShown = lambda view: counts.__setitem__("onshown", counts["onshown"] + 1)

    page = QWidget()
    page.resize(480, 800)
    page.show()
    app.processEvents()

    print("\n[A] 安装与幂等")
    Check(hooks.InstallAppStateHook(page) is True, "首次安装返回 True")
    Check(hooks.InstallAppStateHook(page) is False, "重复安装返回 False(不重复连接)")
    Check(getattr(page, "_jmAppStateHook", False) is True, "主窗口打了已安装标记")

    print("\n[B] 状态切换的动作")
    # repaint 没法直接断言，用计数代理：临时把 repaint 换成计数器
    originalRepaint = page.repaint
    page.repaint = lambda *a, **k: counts.__setitem__("repaint", counts["repaint"] + 1)

    counts["onshown"] = 0
    counts["repaint"] = 0
    app.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
    app.processEvents()
    Check(counts["repaint"] == 1, "进后台(Inactive) -> 刷一帧(多任务快照才有内容) -> {}".format(
        counts["repaint"]))
    Check(counts["onshown"] == 0, "进后台不做重排(别在后台白跑一遍布局)")

    counts["onshown"] = 0
    counts["repaint"] = 0
    app.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    app.processEvents()
    Check(counts["onshown"] == 1, "回前台 -> 按新尺寸重排一次 -> {}".format(counts["onshown"]))
    Check(counts["repaint"] >= 1, "回前台 -> 强制重绘(防黑屏) -> {}".format(counts["repaint"]))

    page.repaint = originalRepaint
    mobile_ui.OnShown = originalOnShown
    page.hide()
    page.deleteLater()
    app.processEvents()

    if Failures:
        print("\nFAIL: {} 项未通过".format(len(Failures)))
        for item in Failures:
            print("  - {}".format(item))
        return 1
    print("\nOK: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(Main())
