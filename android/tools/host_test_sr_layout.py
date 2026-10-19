# coding:utf-8
""" 宿主自检：批量超分页参数行(竖屏居中表单) + 下拉弹窗宽度

真机上这两个问题都只能靠肉眼发现(弹窗裁字 / 放大倍数框占半行且左对齐)，而它们的
判定全是可以量出来的几何关系，所以搬到宿主上用真 Qt 量：

  * 转换格式/线程数 的弹窗宽度 >= 最宽选项文字 + 余量(否则 webp/apng 被硬切)
  * 放大倍数 spin 回到自然宽度(不再是 .ui 里的 150px 最小宽)
  * "放大倍数/转换格式"两组按可见宽度居中(左右留白差 <= 2px)
  * 桌面宽屏(一行放得下)时不动布局
  * 重复调用幂等

需要本机有 PySide6；CI 里的 python3 没有就直接 SKIP(退出码 0)。
用法：python android/tools/host_test_sr_layout.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
except Exception as es:                      # pragma: no cover - CI 的宿主没有 PySide6
    print("SKIP: 本机没有 PySide6 ({})".format(es))
    sys.exit(0)

import images_rc  # noqa: E402,F401  主题图标资源

Failures = []


def Check(condition, message):
    if condition:
        print("  ok  {}".format(message))
    else:
        Failures.append(message)
        print("  FAIL {}".format(message))


def BuildPage():
    from interface.ui_batch_sr import Ui_BatchSrTool
    page = QWidget()
    ui = Ui_BatchSrTool()
    ui.setupUi(page)
    # 与 BatchSrToolView.__init__ 一致
    ui.fmtBox.addItem("")
    for fmt in ["png", "jpg", "webp", "apng", "bmp"]:
        ui.fmtBox.addItem(fmt)
    ui.coverModelName.setText("MODEL_REALEsRGAN_X4PLUSANIME_UP4X")
    ui.fmtBox.setCurrentText("png")
    ui.numLabel.setText("3/0/21")
    return page, ui


def MaxItemText(combo):
    metrics = combo.fontMetrics()
    return max([metrics.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())] or [0])


def PopupWidth(combo, app):
    view = combo.view()
    combo.showPopup()
    app.processEvents()
    width = view.window().width()
    combo.hidePopup()
    return width


def ApplyLayout(ui, page, available, app):
    """ 按 ReflowPortrait 的顺序跑一遍(桌面没有 IsEnabled，这里手动调) """
    from tools.mobile_ui_layout import (LayoutBatchSrTool, WrapWideRows, ShrinkToFit,
                                        ClampPageWidth, FitComboPopups)
    changed = LayoutBatchSrTool(ui, available)
    WrapWideRows(page, available)
    ShrinkToFit(page, available)
    ClampPageWidth(page, available)
    FitComboPopups(page)
    app.processEvents()
    return changed


def TestNarrow(app):
    print("\n[1] 竖屏 352px：表单居中 + 弹窗装得下最宽选项")
    page, ui = BuildPage()
    page.resize(352, 760)
    page.show()
    app.processEvents()
    changed = ApplyLayout(ui, page, 352, app)
    Check(changed is True, "参数行放不下 -> 改成居中表单")
    spin = ui.coverScale
    Check(spin.minimumWidth() == 0, "放大倍数的最小宽已收回(不再死守 150px)")
    Check(spin.width() <= spin.sizeHint().width() + 2,
          "放大倍数按自然宽度显示({}px, 自然 {}px)".format(spin.width(), spin.sizeHint().width()))
    center = (ui.label_26.x() + spin.x() + spin.width()) / 2.0
    Check(abs(center - 176) <= 2, "放大倍数整组居中(中心 %.1f, 期望 176)" % center)
    center = (ui.label_5.x() + ui.fmtBox.x() + ui.fmtBox.width()) / 2.0
    Check(abs(center - 176) <= 2, "转换格式整组居中(中心 %.1f, 期望 176)" % center)
    for name in ("fmtBox", "threadNum"):
        combo = getattr(ui, name)
        need = MaxItemText(combo)
        popup = PopupWidth(combo, app)
        Check(popup >= need + 72,
              "{} 弹窗 {}px >= 最宽文字 {}px + 72(popup 不再裁字)".format(name, popup, need))
    # 幂等：再跑一次不重复拆、位置不变
    before = (ui.label_26.x(), ui.coverScale.x(), ui.coverScale.width())
    Check(ApplyLayout(ui, page, 352, app) is False, "重复调用不再拆行")
    after = (ui.label_26.x(), ui.coverScale.x(), ui.coverScale.width())
    Check(before == after, "重复调用位置/尺寸不变 {}".format(after))
    page.close()


def TestWide(app):
    print("\n[2] 桌面 1100px：一行放得下 -> 布局原样保留")
    page, ui = BuildPage()
    page.resize(1100, 760)
    page.show()
    app.processEvents()
    changed = ApplyLayout(ui, page, 1100, app)
    Check(changed is False, "宽屏不拆行")
    Check(ui.coverScale.minimumWidth() == 150, "放大倍数保留 .ui 的 150px 最小宽(桌面不变)")
    Check(ui.horizontalLayout_5.indexOf(ui.coverScale) >= 0
          and ui.horizontalLayout_5.indexOf(ui.fmtBox) >= 0,
          "参数仍在原横排里(没被拆成上下两行)")
    page.close()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    qssPath = os.path.join(ROOT, "res", "theme", "dark_orange.qss")
    if os.path.exists(qssPath):
        with open(qssPath, encoding="utf-8") as f:
            # 宿主机通常没有 Roboto：去掉字体族，避免渲染成豆腐块(几何断言不受影响)
            app.setStyleSheet(f.read().replace("font-family: Roboto;", ""))
    TestNarrow(app)
    TestWide(app)
    print()
    if Failures:
        print("FAIL: {} 项不过: {}".format(len(Failures), Failures))
        return 1
    print("OK: 批量超分参数行/下拉弹窗布局全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
