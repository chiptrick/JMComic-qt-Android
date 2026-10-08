# coding:utf-8
""" 单独调试"首页一行 2 个封面"的自校正：打印每一轮的封面宽/item 宽/超宽量 """
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="jm_grid_probe_")
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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem

app = QApplication([])

from tools import platform_mobile

platform_mobile.InitAndroidEnv(app)

from tools.log import Log
from config.setting import Setting
from tools import mobile_ui
from component.widget.comic_item_widget import ComicItemWidget

Log.Init()
Setting.Init()
Setting.InitLoadSetting()

avail = 366
host = QListWidget()
host.resize(avail, 400)
host.setFlow(QListWidget.LeftToRight)
host.setWrapping(True)
host.setResizeMode(QListWidget.Adjust)
host.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
for i in range(2):
    widget = ComicItemWidget()
    widget.SetTitle("test title %d" % i, "")
    listItem = QListWidgetItem(host)
    listItem.setSizeHint(widget.sizeHint())
    host.setItemWidget(listItem, widget)
host.show()
app.processEvents()

print("viewport width =", host.viewport().width(), "avail =", avail)
mobile_ui.ResetGridCover()
print("initial GridCoverWidth =", mobile_ui.GridCoverWidth(False))
mobile_ui.ApplyGridCoverSize(host)
app.processEvents()
mobile_ui.ApplyGridCoverSize(host)
app.processEvents()
print("gridSize =", host.gridSize(), "viewport =", host.viewport().width(),
      "vbar visible =", host.verticalScrollBar().isVisible())
for row in range(host.count()):
    print("  item[%d] rect = %s sizeHint = %s" % (
        row, host.visualItemRect(host.item(row)), host.item(row).sizeHint()))

w = host.itemWidget(host.item(0))
print("after apply: cover =", w.picLabel.width(), "itemHint =", w.sizeHint().width(),
      "itemMin =", w.minimumSizeHint().width(), "gridSized =", getattr(w, "_jmGridSized", 0))
inner = w.layout()
if inner is not None:
    print("widget layout margins =", inner.contentsMargins().left(), inner.contentsMargins().right(),
          "count =", inner.count())
    for i in range(inner.count()):
        item = inner.itemAt(i)
        sub = item.widget()
        if sub is not None:
            print("   child[%d] %s '%s' min=%d hint=%d max=%d" % (
                i, type(sub).__name__, sub.objectName(), sub.minimumSizeHint().width(),
                sub.sizeHint().width(), sub.maximumWidth()))
        else:
            print("   child[%d] <layout/spacer> min=%d hint=%d" % (
                i, item.minimumSize().width(), item.sizeHint().width()))
print("overflow =", mobile_ui._GridOverflow(host))
print("stats =", mobile_ui.GridStatsLines(host))
print("final cover width =", mobile_ui.GridCoverWidth(False))
