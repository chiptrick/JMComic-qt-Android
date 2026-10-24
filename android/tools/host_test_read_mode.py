# coding:utf-8
""" 宿主自检：阅读模式的方向判定(左右 / 右左 的前进方向换算)

read_enum.py 只用到 PySide6.QtCore 的 QSize/QPoint 和 config/Str/ToolUtil 的少量
名字，这里用桩顶掉依赖，直接 import **真模块**，确保：
  * 横向翻页模式(左右/右左单页双页)判定正确；
  * "下一屏"语义量 -> 横向滚动条增量的换算在右左滚动下必须取反
    (ScrollValue / 自动滚动都走 ForwardScrollDelta，改回"两种排版共用一个
    符号"会立刻在这里红)。

用法：python android/tools/host_test_read_mode.py
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))


class _Any:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _Any()

    def __call__(self, *args, **kwargs):
        return _Any()


def _Module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


# read_enum 的模块级依赖(只需要名字存在，不参与计算)
_Module("PySide6")
_Module("PySide6.QtCore", QSize=_Any, QPoint=_Any)
_Module("PySide6.QtGui")
sys.modules["PySide6"].QtCore = sys.modules["PySide6.QtCore"]
_Module("config", config=_Any())
_Module("config.setting", Setting=_Any())
_Module("tools")
_Module("tools.str", Str=_Any())
_Module("tools.tool", ToolUtil=_Any)

from view.read.read_enum import ReadMode  # noqa: E402

Failures = []


def Check(ok, name):
    print("  {} {}".format("OK  " if ok else "FAIL", name))
    if not ok:
        Failures.append(name)


def TestHorizontalPage():
    print("\n[1] 横向翻页模式：左右/右左的单页与双页")
    for mode in (ReadMode.LeftRight, ReadMode.LeftRightDouble,
                 ReadMode.RightLeftDouble, ReadMode.RightLeftDouble2):
        Check(ReadMode.isHorizontalPage(mode), "{} -> 横向翻页".format(mode.name))
    for mode in (ReadMode.UpDown, ReadMode.Samewight, ReadMode.LeftRightScroll,
                 ReadMode.RightLeftScroll, ReadMode.RightLeftScroll2):
        Check(not ReadMode.isHorizontalPage(mode), "{} -> 非横向翻页".format(mode.name))


def TestHorizontalScroll():
    print("\n[2] 横向滚动模式：左右滚动 / 右左滚动(含滚轮正序)")
    for mode in (ReadMode.LeftRightScroll, ReadMode.RightLeftScroll, ReadMode.RightLeftScroll2):
        Check(ReadMode.isHorizontalScroll(mode), "{} -> 横向滚动".format(mode.name))
    Check(not ReadMode.isHorizontalScroll(ReadMode.UpDown), "UpDown -> 非横向滚动")
    Check(not ReadMode.isHorizontalScroll(ReadMode.LeftRight), "LeftRight -> 非横向滚动")
    for mode in (ReadMode.RightLeftScroll, ReadMode.RightLeftScroll2):
        Check(ReadMode.isRightLeftScroll(mode), "{} -> 右左滚动".format(mode.name))
    Check(not ReadMode.isRightLeftScroll(ReadMode.LeftRightScroll), "LeftRightScroll -> 非右左")
    # 右左滚动是 isRightLeft 的子集，别把双页也算进来
    Check(not ReadMode.isRightLeftScroll(ReadMode.RightLeftDouble), "RightLeftDouble -> 非右左滚动")


def TestForwardDelta():
    print("\n[3] 前进方向换算：右左滚动必须取反")
    Check(ReadMode.ForwardScrollDelta(ReadMode.LeftRightScroll, 100) == 100,
          "左右滚动: +100 -> +100(前进=值增大)")
    Check(ReadMode.ForwardScrollDelta(ReadMode.RightLeftScroll, 100) == -100,
          "右左滚动: +100 -> -100(前进=值减小)")
    Check(ReadMode.ForwardScrollDelta(ReadMode.RightLeftScroll2, 100) == -100,
          "右左滚动(正序): +100 -> -100")
    Check(ReadMode.ForwardScrollDelta(ReadMode.RightLeftScroll, -60) == 60,
          "右左滚动: -60 -> +60(反向同样取反)")
    Check(ReadMode.ForwardScrollDelta(ReadMode.UpDown, 100) == 100,
          "上下模式: 原样返回")
    Check(ReadMode.ForwardScrollDelta(ReadMode.LeftRight, 30) == 30,
          "左右翻页: 原样返回")


def main():
    TestHorizontalPage()
    TestHorizontalScroll()
    TestForwardDelta()
    print()
    if Failures:
        print("FAIL: {} 项不过: {}".format(len(Failures), Failures))
        return 1
    print("OK: 阅读模式方向判定全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
