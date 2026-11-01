# coding:utf-8
"""换页方向回归（不需要手机，宿主 offscreen 跑）

守两条：
  1. 返回/回退路径必须显式传 RightToLeft —— 该路径会先把当前页从 subStackList
     里裁掉，靠 list.index 推方向会退化成 0<=0=LeftToRight（旧 bug）。
  2. 完整栈上的普通跳转方向仍按 oldIndex/newIndex 正确推导（前进/后退都对）。

跑法（WSL 构建树里，需要 PySide6）：
  QT_QPA_PLATFORM=offscreen <venv>/bin/python3 android/tools/host_test_switch_direction.py
"""
import os
import re
import sys
import time

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, _ROOT)

Failures = []


def Check(ok, name):
    print(("  ok  " if ok else "  FAIL ") + name)
    if not ok:
        Failures.append(name)


def MakePage(text):
    page = QWidget()
    page.setWindowTitle(text)
    layout = QVBoxLayout(page)
    layout.addWidget(QLabel(text))
    page.SwitchCurrent = lambda **kwargs: None
    return page


class Harness(object):
    def __init__(self, app):
        from component.widget import animation_stack_widget as _asw
        _asw.UseGpuCover = False          # 宿主没有 RHI，只测方向逻辑
        from component.widget.animation_stack_widget import AnimationStackWidget
        self.app = app
        self.win = QWidget()
        self.stack = AnimationStackWidget(self.win)
        for text in ("A", "B", "C"):
            self.stack.addWidget(MakePage(text))
        self.stack.setGeometry(0, 0, 384, 700)
        self.stack.subStackList = [0, 1, 2]
        self.stack.setCurrentIndex(0)
        self.win.show()
        self.Pump(80)

    def Pump(self, ms):
        end = time.time() + ms / 1000.0
        while time.time() < end:
            self.app.processEvents()
            time.sleep(0.005)

    def Switch(self, index, direction=None, timeout=900):
        """切页并等到动画结束（currentIndex 变化）"""
        before = self.stack.currentIndex()
        if before == index:
            return True
        if direction is None:
            self.stack.SwitchWidgetByIndex(index)
        else:
            self.stack.SwitchWidgetByIndex(index, direction)
        end = time.time() + timeout / 1000.0
        while time.time() < end:
            self.app.processEvents()
            if self.stack.currentIndex() == index:
                self.Pump(30)
                return True
            time.sleep(0.005)
        return False


def TestForwardAndBreadcrumb(app):
    from component.widget.animation_stack_widget import AnimationEnum
    print("\n[1] 完整栈上的方向推导：前进 / 面包屑后退")
    h = Harness(app)
    ok = h.Switch(1)
    Check(ok, "A -> B 切页成功")
    Check(h.stack.animationType == AnimationEnum.LeftToRight,
          "A -> B 是前进（实际 {}）".format(h.stack.animationType))
    ok = h.Switch(0)   # 面包屑/jump：此时栈仍完整 [0,1,2]，current=1
    Check(ok, "B -> A 切页成功")
    Check(h.stack.animationType == AnimationEnum.RightToLeft,
          "完整栈上 B -> A 仍能推出后退（实际 {}）".format(h.stack.animationType))
    h.win.close()


def TestBackPathAfterTrim(app):
    from component.widget.animation_stack_widget import AnimationEnum
    print("\n[2] 返回路径：先裁栈 + 显式方向（修复后的真实调用序列）")
    h = Harness(app)
    h.Switch(1)                            # 现在在 B，栈 [0,1,2]
    Check(h.stack.currentIndex() == 1, "已停在 B")
    # 复刻 SwitchWidgetLast：subIndex=1, keep=[0]，裁完再切
    h.stack.subStackList = h.stack.subStackList[:1]
    ok = h.Switch(0, AnimationEnum.RightToLeft)
    Check(ok, "裁栈后切回 A 成功")
    Check(h.stack.animationType == AnimationEnum.RightToLeft,
          "显式方向生效：返回播后退（实际 {}）".format(h.stack.animationType))
    Check("direction" not in h.stack.switchArg,
          "direction 没有被塞进 switchArg 传给 SwitchCurrent")
    h.win.close()


def TestTrimWithoutHint(app):
    from component.widget.animation_stack_widget import AnimationEnum
    print("\n[3] 反例守卫：裁栈后不传方向会退化成前进（旧 bug 的根因）")
    h = Harness(app)
    h.Switch(1)
    h.stack.subStackList = h.stack.subStackList[:1]
    ok = h.Switch(0)                       # 故意不传 direction
    Check(ok, "裁栈后切回 A 成功")
    Check(h.stack.animationType == AnimationEnum.LeftToRight,
          "不传方向时确实算成前进（说明 SwitchWidgetLast 必须显式传）")
    h.win.close()


def TestSourceGuard():
    print("\n[4] 源码守卫：SwitchWidgetLast 必须把 RightToLeft 传下去")
    path = os.path.join(_ROOT, "src", "view", "main", "main_view.py")
    src = open(path, encoding="utf-8").read()
    m = re.search(r"def SwitchWidgetLast\(self\):(.*?)(?=\n    def )", src, re.S)
    Check(m is not None, "找到 SwitchWidgetLast 定义")
    if m is not None:
        block = m.group(1)
        Check("AnimationEnum.RightToLeft" in block,
              "SwitchWidgetLast 里显式传了 AnimationEnum.RightToLeft")
        Check("SwitchWidgetByIndex(target, AnimationEnum.RightToLeft)" in block,
              "调用点在裁栈之后（顺序即代码顺序）")


def main():
    print("===== 换页方向回归 =====")
    app = QApplication.instance() or QApplication(sys.argv)
    TestForwardAndBreadcrumb(app)
    TestBackPathAfterTrim(app)
    TestTrimWithoutHint(app)
    TestSourceGuard()
    print()
    if Failures:
        print("FAILED {} 项:".format(len(Failures)))
        for name in Failures:
            print("  - " + name)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    code = main()
    # PySide6 在解释器 finalize 阶段回收 QRhiWidget/QWidget 时偶发
    # "bool_dealloc ... refcount error"（断言早已跑完）。测试进程直接退出，
    # 不让解释器去做 Qt 对象的析构。
    sys.stdout.flush()
    os._exit(code)
