# coding:utf-8
""" 探测 PySide6 暴露了哪些"平台相关"API

真机(Android)上要做的两件事都需要平台 API：
    1. 返回键回桌面 -> 需要把 Activity 退到后台(moveTaskToBack / 最小化)
    2. 导入本地文件 -> 需要存储权限
Qt6 有 QJniObject / QPermission 这类接口，但 PySide6 不一定绑定。
这里把它们打出来，避免"以为有、结果 ImportError"。
"""
import sys

import PySide6
import PySide6.QtCore as QtCore
import PySide6.QtWidgets as QtWidgets


def main():
    print("PySide6", PySide6.__version__)
    print("QtCore 版本", QtCore.__version__ if hasattr(QtCore, "__version__") else "?")
    print("permission 相关:", [n for n in dir(QtCore) if "ermission" in n])
    print("jni 相关:", [n for n in dir(QtCore) if "Jni" in n or "JNI" in n])
    print("android 相关:", [n for n in dir(QtCore) if "ndroid" in n])
    print("QCoreApplication permission 方法:",
          [n for n in dir(QtCore.QCoreApplication) if "ermission" in n.lower()])
    print("QWidget.showMinimized:", hasattr(QtWidgets.QWidget, "showMinimized"))
    print("QWidget.setWindowState:", hasattr(QtWidgets.QWidget, "setWindowState"))
    print("QGuiApplication.requestPermission:",
          hasattr(QtCore.QGuiApplication, "requestPermission"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
