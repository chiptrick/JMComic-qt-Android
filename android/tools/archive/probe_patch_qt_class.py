# coding:utf-8
""" 探测 PySide6 能否从 Python 侧替换 Qt 类的方法(决定"延后显示顶层窗口"怎么实现) """
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QWidget

app = QApplication(sys.argv)


def probe(label, obj, name, value):
    try:
        setattr(obj, name, value)
        print("{}: OK".format(label))
        return True
    except Exception as es:
        print("{}: FAIL {}: {}".format(label, type(es).__name__, es))
        return False


probe("QDialog.show = fn", QDialog, "show", lambda self: None)
probe("QWidget.show = fn", QWidget, "show", lambda self: None)


class MyDialog(QDialog):
    def show(self):
        super().show()


probe("MyDialog.show = fn", MyDialog, "show", lambda self: None)

try:
    from shiboken6 import isValid
    d = MyDialog()
    print("shiboken6.isValid: OK ->", isValid(d))
except Exception as es:
    print("shiboken6.isValid: FAIL", type(es).__name__, es)

try:
    import shiboken6
    print("shiboken6 version:", getattr(shiboken6, "__version__", "?"))
except Exception as es:
    print("shiboken6 import FAIL", es)
