# coding:utf-8
"""扫描所有 .ui，找出在竖屏宽度下**放不下**的横向布局行。

竖屏宽度按 PortraitWidth(默认 360 逻辑像素) 计算。误触/显示不全的根因是：
某些布局把若干固定最小宽度的控件排在**同一行**，宽度之和超过屏幕宽度，
Qt 只能压缩/裁掉其中的部分控件。

判定规则(保守，宁可少报)：
    * 只统计 横向 QHBoxLayout / QGridLayout 的同一行
    * 控件可用最小宽度 = minimumSize.width(若>0) 否则估计文本宽度(中文 1em/字，ASCII 0.55em)
    * 行宽(含 spacing) > 阈值 即报告

用法: python3 android/tools/scan_ui_width.py [PortraitWidth]
"""
import os
import sys
import xml.etree.ElementTree as ET

CONTAINERS = ("widget", "layout", "spacer")
SPACING = 9
CHAR_EM = 11.0          # 12pt 正文中文单字宽度(逻辑像素)的粗略估计


def Prop(node, name):
    for p in node.findall("property"):
        if p.get("name") == name:
            return p
    return None


def TextWidth(s):
    if not s:
        return 0.0
    wide = sum(1 for ch in s if ord(ch) > 0x2000)
    narrow = len(s) - wide
    return (wide + narrow * 0.55) * CHAR_EM


def MinWidth(node):
    """控件的可用最小宽度"""
    if node.tag == "spacer":
        return 0
    p = Prop(node, "minimumSize")
    if p is not None:
        s = p.find("size")
        if s is not None:
            try:
                w = int(s.findtext("width") or 0)
            except ValueError:
                w = 0
            if w > 0:
                return w
    if node.tag == "layout":
        return LayoutWidth(node)
    texts = []
    for p in node.findall("property"):
        if p.get("name") == "text":
            texts.append(p.text or "")
    w = TextWidth(max(texts, key=len)) if texts else 0.0
    if node.get("class") in ("QLineEdit", "QComboBox", "WheelComboBox", "QDoubleSpinBox",
                             "WheelDoubleSpinBox", "QSpinBox", "WheelSpinBox", "QToolButton"):
        w = max(w, 60)
    return int(w)


def Children(node):
    """返回 [(item 或 None, 子 widget/layout)]

    注意：widget 的顶层 layout 是 <widget> 的**直接**子节点，没有 <item> 包装，
    只遍历 <item> 会让递归在第一层就断掉(第一版就是这么漏掉全部命中的)。
    """
    out = []
    for child in node:
        if child.tag in CONTAINERS:
            out.append((None, child))
    for item in node.findall("item"):
        subs = [s for s in item if s.tag in CONTAINERS]
        if subs:
            out.append((item, subs[0]))
    return out


def LayoutWidth(node):
    """布局本身的最小宽度(横向求和、纵向取最大)"""
    kids = Children(node)
    if not kids:
        return 0
    cls = node.get("class") or ""
    horiz = "HBox" in cls
    if node.get("class") is None:
        p = Prop(node, "orientation")
        horiz = (p is not None and "Horizontal" in (p.findtext("enum") or ""))
    if not horiz:
        return max(MinWidth(s) for _, s in kids)
    total = sum(MinWidth(s) for _, s in kids) + SPACING * max(0, len(kids) - 1)
    return total


def Walk(node, path, limit, out):
    cls = node.get("class") or ""
    name = node.get("name") or "?"
    here = path + "/" + name
    if node.tag == "layout":
        w = LayoutWidth(node)
        if w > limit:
            kids = Children(node)
            detail = ", ".join(
                "{}'{}'={}".format(s.get("class"), s.get("name"), MinWidth(s)) for _, s in kids)
            out.append((w, here, detail))
    elif "GridLayout" in cls:
        rows = {}
        for item, sub in Children(node):
            r = int(item.get("row") or 0)
            rows.setdefault(r, []).append(sub)
        for r, subs in rows.items():
            total = sum(MinWidth(s) for s in subs) + SPACING * max(0, len(subs) - 1)
            if total > limit and len(subs) > 1:
                detail = ", ".join("{}'{}'={}".format(s.get("class"), s.get("name"), MinWidth(s))
                                   for s in subs)
                out.append((total, here + " row={}".format(r), detail))
    for _, sub in Children(node):
        Walk(sub, here, limit, out)


def Scan(path, limit):
    root = ET.parse(path).getroot()
    top = root.find("widget")
    out = []
    Walk(top, "", limit, out)
    return out


def Main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 360
    uiDir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ui")
    uiDir = os.path.normpath(uiDir)
    hits = 0
    for dirpath, _dirnames, filenames in os.walk(uiDir):
        for fn in sorted(filenames):
            if not fn.endswith(".ui"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, os.path.dirname(uiDir)).replace("\\", "/")
            try:
                rows = Scan(full, limit)
            except Exception as es:
                print("{}: 解析失败 {}".format(rel, es))
                continue
            if not rows:
                continue
            hits += 1
            print("== {} (阈值 {})".format(rel, limit))
            for w, where, detail in sorted(rows, reverse=True):
                print("   宽≈{}  {}".format(w, where))
                print("        {}".format(detail))
    print("\n命中文件数: {} / 阈值 {}".format(hits, limit))


if __name__ == "__main__":
    Main()
