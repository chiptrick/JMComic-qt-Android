# coding:utf-8
"""复现/验证"触摸自检的轮询 timer 到底有没有在跑"

真机上出现过：ui_touch_selftest 的分辨率/坐标行写出来了，但后面一条
`t=  1s presses=...` 轮询行都没有 —— 而 verify 脚本正是靠这些行做判定的。
这个脚本在宿主机上把同样的路径跑一遍(offscreen)，把诊断文件的内容打出来。

用法: python3 android/tools/probe_touch_selftest.py
"""
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="jm_touch_probe_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["JMCOMIC_ANDROID"] = "1"
os.environ["ANDROID_PRIVATE"] = TMP
os.environ["JM_ANDROID_SAVE_DIR"] = os.path.join(TMP, "save")
os.environ["JM_SR_MODELS"] = os.path.join(TMP, "waifu2x-models")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "android"))
try:
    import curl_cffi  # noqa: F401
except Exception:
    sys.path.append(os.path.join(ROOT, "android", "shims"))
os.chdir(TMP)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from tools import platform_mobile  # noqa: E402

platform_mobile.InitAndroidEnv(app)

from tools.log import Log  # noqa: E402
from config.setting import Setting  # noqa: E402
from tools.str import Str  # noqa: E402
from qt_owner import QtOwner  # noqa: E402

Log.Init()
Setting.Init()
Setting.InitLoadSetting()
Str.Reload()
QtOwner().SetApp(app)

from view.main.main_view import MainView  # noqa: E402
from tools import mobile_ui  # noqa: E402

main = MainView()
main.resize(384, 845)
main.show()
app.processEvents()

view = main.settingView
# 不走 SwitchWidget(宿主机 offscreen 下 subStackList 没建好)，直接切页并手动 Init
main.subStackWidget.setCurrentWidget(view)
view.SwitchCurrent(refresh=True)
app.processEvents()
print("view width:", view.width(), "scrollArea:", view.scrollArea.width(),
      "viewport:", view.scrollArea.viewport().width())

target = mobile_ui._PickVisibleCheckBox(view)
print("picked target:", target, getattr(target, "objectName", lambda: None)())

# 只跑报告这一段，然后等 3.5 秒看有没有轮询行落盘
mobile_ui._TouchSelfTestReport(view, target, ["", "===== probe ====="])

# 对照组：同样条件下自己起一个重复 timer，确认这个环境里 QTimer 到底会不会触发
from PySide6.QtCore import QTimer  # noqa: E402

control = {"n": 0}


def OnControl():
    control["n"] += 1
    print("  [control] timer tick", control["n"], flush=True)


ctl = QTimer(view)
ctl.setInterval(500)
ctl.timeout.connect(OnControl)
ctl.start()

deadline = time.time() + 3.5
while time.time() < deadline:
    app.processEvents()
    time.sleep(0.02)
print("对照组 timer 触发次数:", control["n"], " 活跃:", ctl.isActive())

path = os.path.join(platform_mobile.GetAppDataDir(), "android_startup.log")
print("--- 诊断文件 ---")
with open(path, encoding="utf-8", errors="replace") as f:
    for line in f:
        print(line.rstrip())
ticks = 0
with open(path, encoding="utf-8", errors="replace") as f:
    for line in f:
        if "presses=" in line:
            ticks += 1
print("轮询行数量:", ticks)
raise SystemExit(0 if ticks else 1)
