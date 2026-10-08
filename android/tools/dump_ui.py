# coding:utf-8
"""把 .ui 文件的结构骨架打印出来(类名/对象名/几何/布局行列)，用于规划竖屏排版。

用法:
    python3 android/tools/dump_ui.py ui/ui_setting_new.ui [maxDepth] [nameFilter]

Qt Designer 的 .ui 是嵌套很深的 XML，直接读文件很难看出"哪一块是左右并排"。
这个脚本只打印结构 + 关键几何/尺寸属性，方便定位需要改的布局。
nameFilter 命中时只展开包含该子串的子树。
"""
import sys
import xml.etree.ElementTree as ET

INTERESTING = ("minimumSize", "maximumSize", "orientation", "currentIndex", "stretch",
               "sizeType", "rowStretch", "columnStretch")
CONTAINERS = ("widget", "layout", "spacer")


def Prop(node, name):
    for p in node.findall("property"):
        if p.get("name") == name:
            return p
    return None


def Geo(node):
    p = Prop(node, "geometry")
    if p is None:
        return ""
    r = p.find("rect")
    if r is None:
        return ""
    return "{},{} {}x{}".format(r.findtext("x"), r.findtext("y"),
                                r.findtext("width"), r.findtext("height"))


def Extra(node):
    out = []
    for name in INTERESTING:
        p = Prop(node, name)
        if p is None:
            continue
        if name == "orientation":
            out.append("orient=" + (p.findtext("enum") or "?").replace("Qt::", ""))
        elif name in ("minimumSize", "maximumSize"):
            s = p.find("size")
            if s is not None:
                out.append("{}={}x{}".format(name, s.findtext("width"), s.findtext("height")))
        else:
            out.append("{}={}".format(name, (p.text or "").strip()[:20]))
    if node.get("class") and node.get("class").startswith("QCommandLinkButton"):
        pass
    return (" [" + " ".join(out) + "]") if out else ""


def Walk(node, depth, maxDepth, needle, out, ann=""):
    if depth > maxDepth:
        return
    tag = node.tag
    if tag not in CONTAINERS:
        return
    if tag == "widget":
        head = "{}{} '{}' {}".format("  " * depth, node.get("class"), node.get("name"), Geo(node))
    elif tag == "layout":
        head = "{}{} '{}'".format("  " * depth, node.get("class"), node.get("name"))
    else:
        head = "{}<spacer> '{}'".format("  " * depth, node.get("name"))
    line = head + Extra(node) + ann
    if tag == "widget" and node.findall("item"):
        line += "  (有布局)"
    out.append(line)
    for child in node:
        if child.tag in CONTAINERS:
            Walk(child, depth + 1, maxDepth, needle, out)
        elif child.tag == "item":
            subs = [s for s in child if s.tag in CONTAINERS]
            if not subs:
                continue
            attrs = ["{}={}".format(k, v) for k, v in child.attrib.items()]
            subAnn = ("  <item {}>".format(" ".join(attrs))) if attrs else ""
            if needle and needle not in ET.tostring(child, encoding="unicode"):
                continue
            Walk(subs[0], depth + 1, maxDepth, needle, out, subAnn)


def Dump(path, maxDepth=6, needle=""):
    root = ET.parse(path).getroot()
    top = root.find("widget")
    out = ["# {}  (root: {})".format(path, top.get("class") if top is not None else "?")]
    Walk(top, 0, maxDepth, needle, out)
    print("\n".join(out))


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        raise SystemExit(1)
    Dump(argv[0], int(argv[1]) if len(argv) > 1 else 6, argv[2] if len(argv) > 2 else "")
