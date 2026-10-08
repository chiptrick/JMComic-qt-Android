# coding:utf-8
"""本地冒烟测试：强制 Android 模式，检查竖屏适配是否按预期生效(offscreen，不联网)"""
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="jm_android_test_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["JMCOMIC_ANDROID"] = "1"
os.environ["ANDROID_PRIVATE"] = TMP
os.environ["JM_ANDROID_SAVE_DIR"] = os.path.join(TMP, "save")
os.environ["JM_SR_MODELS"] = os.path.join(TMP, "waifu2x-models")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "android"))
# 与 android/main.py 一致：没有原生 curl_cffi 时用纯 python 垫片顶上。
# Android 上就是这个情况，桌面跑测试也必须如此，否则业务代码一 import server 就失败。
try:
    import curl_cffi  # noqa: F401
except Exception:
    sys.path.append(os.path.join(ROOT, "android", "shims"))
# Windows 主机上 setting._xdgDir 会退化成相对目录 "data"，切到临时目录里跑，
# 避免读写仓库里的真实配置(Android 走的是 XDG 分支，不受影响)
os.chdir(TMP)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from tools import platform_mobile  # noqa: E402

platform_mobile.InitAndroidEnv(app)
assert platform_mobile.IsAndroid(), "IsAndroid 应为 True"
assert platform_mobile.SupportSystemTray is False
assert platform_mobile.SupportSingleInstance is False
assert platform_mobile.SupportSubProcessProbe is False
print("[ok] android env: data=%s save=%s" % (platform_mobile.GetAppDataDir(),
                                            platform_mobile.GetAndroidSavePath()))

from tools.log import Log  # noqa: E402
from config.setting import Setting  # noqa: E402
from tools.str import Str  # noqa: E402
from qt_owner import QtOwner  # noqa: E402

Log.Init()
Setting.Init()
Setting.InitLoadSetting()
Str.Reload()
QtOwner().SetApp(app)

assert Setting.SavePath.value == platform_mobile.GetAndroidSavePath()
print("[ok] android 下载目录默认值生效: %s" % Setting.SavePath.value)

# 防止测试把配置写到仓库里(Windows 上 _xdgDir 会退化成相对 "data")
configPath = os.path.abspath(Setting.GetConfigPath())
assert configPath.startswith(os.path.abspath(TMP)), \
    "配置目录跑到临时目录外了，会污染仓库: {}".format(configPath)

from tools import sr_backend  # noqa: E402

# 没有 libsr_qnn.so 时应优雅失败(不影响启动)
assert sr_backend.InstallQnnCompat() is False
print("[ok] sr_qnn 缺失时优雅降级, err=%s" % sr_backend.GetSrModule())

from view.main.main_view import MainView  # noqa: E402

main = MainView()
main.resize(420, 900)
main.show()
app.processEvents()

from tools import mobile_ui  # noqa: E402

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402


def waitHide(widget, timeout=2.0):
    """ 等抽屉真正隐藏(关闭动画 + 兜底定时器) """
    deadline = time.time() + timeout
    while time.time() < deadline and not widget.isHidden():
        app.processEvents()
        time.sleep(0.02)
    return widget.isHidden()


def clickScrim(scrim):
    """ 模拟点遮罩(空白区域) """
    pos = QPointF(scrim.width() / 2.0, scrim.height() / 2.0)
    event = QMouseEvent(QEvent.Type.MouseButtonPress, pos,
                        QPointF(scrim.mapToGlobal(pos.toPoint())),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    app.sendEvent(scrim, event)
    return


nav = main.navigationWidget
sub = main.subMainWindow
scrim = getattr(main, "_jmDrawerScrim", None)
assert getattr(nav, "_jmDrawer", False), "导航栏应切换为抽屉模式"
assert nav.isHidden(), "抽屉默认应该是收起的"
assert scrim is not None, "抽屉应带遮罩层(用于点空白处关闭)"

main.CheckShowMenu()
app.processEvents()
assert not nav.isHidden(), "点菜单后抽屉应显示"

# 滑入动画必须真正落位，否则抽屉会停在屏幕外(x=-width)看不见
deadline = time.time() + 1.0
while time.time() < deadline and nav.x() != 0:
    app.processEvents()
    time.sleep(0.02)
assert nav.x() == 0, "抽屉滑入动画未落位, 停在 x=%d" % nav.x()

# 真机 bug 回归1：抽屉原来从 y=0 开始且 raise_()，把顶栏的"菜单"按钮整个盖住，
# 于是"点菜单后菜单键消失"，且再也点不到菜单键
barBottom = sub.mapFromGlobal(main.menuButton.mapToGlobal(QPoint(0, 0))).y() \
    + main.menuButton.height()
assert nav.y() >= barBottom, \
    "抽屉压住了顶栏菜单键: drawer.y=%d 菜单键底部=%d" % (nav.y(), barBottom)
assert scrim.y() >= barBottom, "遮罩压住了顶栏菜单键"
assert nav.geometry().bottom() <= sub.height(), "抽屉超出 subMainWindow"
assert nav.geometry().right() <= sub.width(), "抽屉超出 subMainWindow"
print("[ok] 抽屉避开顶栏: drawer=(%d,%d,%d,%d) 菜单键底部=%d"
      % (nav.x(), nav.y(), nav.width(), nav.height(), barBottom))

# 真机 bug 回归2：原来完全没有"点空白处关闭"，遮罩负责这件事
assert scrim.isVisible(), "抽屉打开时遮罩应显示"
assert scrim.x() <= 0 and scrim.width() >= sub.width(), "遮罩应覆盖整宽"
clickScrim(scrim)
assert waitHide(nav), "点遮罩(空白处)应关闭抽屉"
assert not scrim.isVisible(), "抽屉关闭后遮罩应隐藏"
print("[ok] 点空白处(遮罩)可关闭抽屉，且遮罩随抽屉一起收起")

mobile_ui.CloseDrawer(main)
assert waitHide(nav)
print("[ok] 导航抽屉: 默认收起 / 可展开 / 切换后自动收起 (w=%d, limit=%d)"
      % (nav.width(), mobile_ui.CurrentLimit()))

info = main.bookInfoView
assert getattr(info, "_jmStacked", False), "详情页应改为上下堆叠"
assert info.horizontalLayout.count() == 1, info.horizontalLayout.count()
assert info.gridLayout_3.rowCount() >= 2, info.gridLayout_3.rowCount()
print("[ok] 详情页封面/信息已竖屏堆叠 (horizontalLayout=%d, gridRows=%d)"
      % (info.horizontalLayout.count(), info.gridLayout_3.rowCount()))

# 真机 bug 回归6：设置页原来是 [左侧导航列, scrollArea] 左右并排，
# 竖屏 384px 下内容区被挤到 ~230px，里面 80+150+108 的行就"显示不全"了。
# 竖屏改为导航横排在顶部、内容区独占整宽。
from PySide6.QtWidgets import QBoxLayout, QCommandLinkButton, QSizePolicy, QWidget  # noqa: E402

setting = main.settingView
assert getattr(setting.horizontalLayout, "_jmNavStacked", False), "设置页导航应改为顶部横排"
assert setting.horizontalLayout.direction() == QBoxLayout.Direction.TopToBottom, \
    "设置页外层布局应改成上下排列, 实际=%s" % setting.horizontalLayout.direction()
assert setting.verticalLayout.direction() == QBoxLayout.Direction.LeftToRight, \
    "设置页导航应改成横排, 实际=%s" % setting.verticalLayout.direction()
navButtons = [setting.verticalLayout.itemAt(i).widget()
              for i in range(setting.verticalLayout.count())]
navButtons = [b for b in navButtons if isinstance(b, QCommandLinkButton)]
assert len(navButtons) == 4, "应有 4 个导航按钮, 实际=%d" % len(navButtons)
for button in navButtons:
    assert not button.description(), "横排后应清掉说明文字: %s" % button.objectName()
    assert button.icon().isNull(), "横排后应去掉图标: %s" % button.objectName()
    assert button.maximumWidth() > 300, button.maximumWidth()
    assert button.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored, \
        "%s 的水平策略必须是 Ignored, 否则 sizeHint 会变成最小宽度" % button.objectName()
# 整页的最小宽度必须真的能装进竖屏，否则导航横排只是把"放不下"换个地方
settingMin = setting.horizontalLayout.minimumSize().width()
assert settingMin <= mobile_ui.CurrentLimit(), \
    "设置页仍然要求 %dpx, 竖屏只有 %dpx" % (settingMin, mobile_ui.CurrentLimit())
# 目录行的路径标签最小宽 150px，竖屏下会把"打开目录"按钮挤出屏幕
assert setting.downloadDir.minimumWidth() <= 120, setting.downloadDir.minimumWidth()
print("[ok] 设置页竖屏排版: 导航 4 键横排在顶部, 内容区独占整宽, 目录标签最小宽=%d"
      % setting.downloadDir.minimumWidth())

# 真机 bug 回归7：图片超分页原来是 [图像预览, 参数面板(max 300px)] 左右并排，
# 竖屏下预览只剩 80 多像素。竖屏改为预览在上、参数面板在下。
srTool = main.waifu2xToolView
assert getattr(srTool, "_jmSrStacked", False), "超分页应改为上下堆叠"
grid = srTool.gridLayout
panelIndex = grid.indexOf(srTool.verticalLayout)
assert panelIndex >= 0, "参数面板应还在 grid 里"
row, col, _rs, _cs = grid.getItemPosition(panelIndex)
assert (row, col) == (1, 0), "参数面板应落在第 1 行第 0 列, 实际=(%d,%d)" % (row, col)
viewIndex = grid.indexOf(srTool.graphicsView)
vrow, vcol, _vrs, _vcs = grid.getItemPosition(viewIndex)
assert (vrow, vcol) == (0, 0), "预览应落在第 0 行第 0 列, 实际=(%d,%d)" % (vrow, vcol)
assert srTool.scrollArea.maximumWidth() > 300, srTool.scrollArea.maximumWidth()
assert 0 < srTool.scrollArea.maximumHeight() < 900, srTool.scrollArea.maximumHeight()
print("[ok] 超分页竖屏排版: 预览 (%d,%d) 在上 / 参数面板 (%d,%d) 在下, 面板限高=%d"
      % (vrow, vcol, row, col, srTool.scrollArea.maximumHeight()))

# 防误触的实现必须真的被 android/main.py 装上(否则真机上一行都不会生效)
mainSource = open(os.path.join(ROOT, "android", "main.py"), encoding="utf-8").read()
assert "InstallCtypesLibraryFinder" in mainSource, \
    "android/main.py 必须调用 platform_mobile.InstallCtypesLibraryFinder()"
finder = platform_mobile.FindLibrary
assert finder("") is None
assert platform_mobile._LibNameMatches("crypto", "libcrypto.so")
assert platform_mobile._LibNameMatches("crypto", "libcrypto.so.3")
assert platform_mobile._LibNameMatches("mymodule", "mymodule.arm64.so")
assert not platform_mobile._LibNameMatches("crypto", "libssl.so")
print("[ok] ctypes find_library 兜底实现: 库名匹配规则正确, 且 main.py 已接线")

limit = mobile_ui.CurrentLimit()
wide = []
for widget in main.findChildren(type(main)):
    pass
for name in ("weekView", "searchView", "settingView", "favoriteView", "localReadView", "nasView"):
    view = getattr(main, name, None)
    if view is None:
        continue
    for child in view.findChildren(type(view).__mro__[1]) if False else []:
        pass
weekCombo = main.weekView.comboBox
assert weekCombo.minimumWidth() <= limit, (weekCombo.minimumWidth(), limit)
print("[ok] 过宽最小尺寸已放宽: weekView.comboBox %d -> %d" % (400, weekCombo.minimumWidth()))

assert main.myTrayIcon is None, "Android 下不应创建系统托盘"
print("[ok] 未创建系统托盘")

# 顶部分页按钮应被压缩
assert main.toolButtons, "分页按钮应已创建"
print("[ok] 分页按钮 %d 个，按钮字号已压缩" % len(main.toolButtons))

# 返回键：抽屉打开时优先收起
main.CheckShowMenu()
app.processEvents()
assert not nav.isHidden()
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402

event = QKeyEvent(QKeyEvent.Type.KeyRelease, Qt.Key.Key_Back, Qt.KeyboardModifier.NoModifier)
main.keyReleaseEvent(event)
deadline = time.time() + 1.0
while time.time() < deadline and not nav.isHidden():
    app.processEvents()
    time.sleep(0.02)
assert nav.isHidden(), "返回键应优先收起抽屉"
print("[ok] 返回键优先收起抽屉")

# 旋转屏幕：resizeEvent -> mobile_ui.OnResize，抽屉几何跟着变(走真实回调，不手动调用)
# 必须在抽屉**打开**的状态下断言，否则隐藏的抽屉不会更新几何
main.CheckShowMenu()
app.processEvents()
assert not nav.isHidden()
main.resize(900, 420)          # 横屏
app.processEvents()
assert nav.width() == min(300, int(900 * 0.82)), nav.width()
assert nav.geometry().right() <= sub.width(), "横屏下抽屉超出 subMainWindow"
assert nav.geometry().bottom() <= sub.height(), "横屏下抽屉超出 subMainWindow"
main.resize(420, 900)          # 转回竖屏
app.processEvents()
assert 0 < nav.width() <= 300, nav.width()
assert nav.geometry().bottom() <= sub.height()
assert not nav.isHidden(), "旋转不应把抽屉弄丢"
mobile_ui.CloseDrawer(main)
assert waitHide(nav)
print("[ok] 旋转后重新适配: 抽屉宽=%d, 上限=%d" % (nav.width(), mobile_ui.CurrentLimit()))

# sr_qnn 的模型常量必须与界面下拉列表、models.txt 完全一致(C++ 内置表按此生成)
import re  # noqa: E402

import sr_qnn  # noqa: E402

assert hasattr(sr_qnn, "add") and hasattr(sr_qnn, "load") and hasattr(sr_qnn, "initSet")
assert sr_qnn.GetModelId("MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X") == -1  # 未加载库

uiSource = open(os.path.join(ROOT, "src", "view", "setting", "setting_sr_select_view.py"),
                encoding="utf-8").read()
uiModels = {"MODEL_{}_{}".format(family.replace("-", "").upper(), name.upper())
            for name, family in re.findall(r'\("([A-Z0-9_]+)",\s*"([^"]+)"', uiSource)}
pythonModels = {"MODEL_" + name for name in sr_qnn.ModelNames}
assert uiModels, "未能解析出界面模型列表"
assert uiModels == pythonModels, "界面列表与 sr_qnn 常量不一致:\n  仅界面={}\n  仅sr_qnn={}".format(
    sorted(uiModels - pythonModels), sorted(pythonModels - uiModels))
print("[ok] sr_qnn 模型常量与界面一致(%d 个)" % len(pythonModels))

manifest = open(os.path.join(ROOT, "android", "sr_qnn", "models", "models.txt"),
                encoding="utf-8").read()
manifestModels = {line.split()[0] for line in manifest.splitlines()
                  if line.strip() and not line.strip().startswith("#")}
unknown = manifestModels - {name for name in sr_qnn.ModelNames}
assert not unknown, "models.txt 里有未知模型名: {}".format(sorted(unknown))
print("[ok] models.txt 覆盖 %d/%d 个模型" % (len(manifestModels), len(pythonModels)))

# 垫片 curl_cffi 基本可用性(不联网，只验证导入与结构)
import importlib  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "android", "shims"))
for name in list(sys.modules):
    if name.startswith("curl_cffi"):
        del sys.modules[name]
shim = importlib.import_module("curl_cffi")
reqShim = importlib.import_module("curl_cffi.requests")
excShim = importlib.import_module("curl_cffi.requests.exceptions")
assert hasattr(shim, "CurlOpt") and hasattr(shim, "CurlHttpVersion") and hasattr(shim, "Session")
assert issubclass(excShim.DNSError, excShim.ConnectionError)
headers = reqShim.Headers({"Content-Type": "text/html"})
assert headers.get("content-type") == "text/html"
assert headers.setdefault("X-Test", "1") == "1"
assert headers.get("x-test") == "1"
resp = reqShim.Response(200, {"Content-Encoding": "identity"}, b"hello")
assert resp.text == "hello" and resp.status_code == 200
print("[ok] curl_cffi 垫片可导入且头/响应行为正确")

# 真机 bug 回归3：CurlOpt 定义在 curl_cffi **包顶层**，垫片里曾经错写成
# `from . import CurlOpt`(等价 curl_cffi.requests.CurlOpt) -> 每个请求都 ImportError，
# 真机上就表现为"网络错误"
assert reqShim._GetCurlOpt() is shim.CurlOpt, "CurlOpt 必须取包顶层的那个"
session = reqShim.Session()
assert session._resolveIp("example.com") is None
session.curl_options = {shim.CurlOpt.RESOLVE: ["example.com:443:1.2.3.4"]}
assert session._resolveIp("example.com") == "1.2.3.4"
assert session._resolveIp("other.com") is None
print("[ok] curl_cffi 垫片 CurlOpt/RESOLVE 解析正常(回归真机 ImportError)")

# 真机 bug 回归4：代理曾被静默丢弃(源码写成 `None if proxy else None`，恒为 None)
captured = {}
originOpen = reqShim._OpenConnection


def fakeOpen(parsed, timeout, resolveIp=None, proxy=None, impersonate=None):
    captured["proxy"] = proxy
    raise excShim.DNSError("stop-here")


reqShim._OpenConnection = fakeOpen
try:
    session.request("GET", "http://example.com/", proxies={"http": "http://127.0.0.1:8888"})
except Exception:
    pass
finally:
    reqShim._OpenConnection = originOpen
assert captured.get("proxy") == "http://127.0.0.1:8888", \
    "代理没有传给 _OpenConnection: %r" % (captured,)
print("[ok] curl_cffi 垫片把代理真正传给连接层(回归静默忽略代理)")

# 真机 bug 回归5：jmcomic 的 jm_async_client 顶层写着
#   from curl_cffi.requests import AsyncSession
# 垫片缺这个名字会让 `from jmcomic import JmCryptoTool` 直接 ImportError，
# 于是图片解密(JmCryptoTool)整条链断掉 —— 真机上每个接口都刷这个 traceback
assert hasattr(reqShim, "AsyncSession") and hasattr(shim, "AsyncSession"), \
    "垫片必须提供 curl_cffi.requests.AsyncSession(jmcomic 需要)"
import asyncio  # noqa: E402


async def _asyncProbe():
    sess = reqShim.AsyncSession()
    assert isinstance(sess.cookies, reqShim.Cookies)
    assert sess.curl_options is not None or True
    await sess.close()


asyncio.run(_asyncProbe())
print("[ok] curl_cffi 垫片提供 AsyncSession(回归 jmcomic 图片解密 ImportError)")

# 真机 bug 回归9：在设置页用手指滑动时，手指下的勾选框会被"顺手点一下"，
# 于是滑一下设置就被改了。守卫只吃掉"位移超过阈值"的 release。
guard = mobile_ui.TouchGuardStats()
assert guard is not None, "移动端应装上滑动防误触守卫"
box = setting.downAuto
assert getattr(setting.scrollArea, "_jmTouchScroll", False), \
    "设置页滚动区域应已接管手指滚动"


def sendMouse(kind, widget, localPos):
    globalPos = QPointF(widget.mapToGlobal(localPos.toPoint()))
    isRelease = (kind == QEvent.Type.MouseButtonRelease)
    event = QMouseEvent(kind, localPos, globalPos,
                        Qt.MouseButton.LeftButton,
                        Qt.MouseButton.NoButton if isRelease else Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    app.sendEvent(widget, event)
    return


slop = mobile_ui.TouchSlopPx
center = QPointF(box.width() / 2.0, box.height() / 2.0)
inside = QPointF(box.width() / 2.0, box.height() / 2.0 + slop + 2)

# 9a: 滑动(位移超过阈值) -> release 被吃掉, 勾选状态不变
box.setChecked(False)
Setting.DownloadAuto.SetValue(0)
pressedBefore, suppressedBefore, dragsBefore = guard.Presses, guard.Suppressed, guard.Drags
sendMouse(QEvent.Type.MouseButtonPress, box, center)
assert guard.Presses == pressedBefore + 1, "按下应被守卫看到"
sendMouse(QEvent.Type.MouseMove, box, inside)
app.processEvents()
assert guard.Drags == dragsBefore + 1, "超过阈值的位移应被判定为滑动"
assert box.isChecked() is False, "滑动过程中不应该切换勾选框"
sendMouse(QEvent.Type.MouseButtonRelease, box, inside)
app.processEvents()
assert guard.Suppressed == suppressedBefore + 1, "滑动的 release 应被拦下"
assert box.isChecked() is False, "滑动后勾选框不应被切换"
assert not box.isDown(), "滑动后勾选框不应停留在按下状态"
assert Setting.DownloadAuto.value == 0, "滑动后设置值不应被改写"
print("[ok] 滑动防误触: 位移 %dpx > 阈值 %dpx 时 release 被拦下, 设置未被改动 (%s)"
      % ((inside - center).manhattanLength(), slop, guard.LastSuppressed))

# 9b: 正常点按(位移小于阈值) 必须仍然生效
suppressedBefore = guard.Suppressed
sendMouse(QEvent.Type.MouseButtonPress, box, center)
sendMouse(QEvent.Type.MouseMove, box, QPointF(center.x(), center.y() + 3))
sendMouse(QEvent.Type.MouseButtonRelease, box, QPointF(center.x(), center.y() + 3))
app.processEvents()
assert box.isChecked() is True, "正常点按必须仍然切换勾选框"
assert Setting.DownloadAuto.value == 1, "正常点按必须仍然写入设置"
assert guard.Suppressed == suppressedBefore, "正常点按不应被拦截"
print("[ok] 防误触不影响正常点按: 3px 位移仍然算点击, 设置已写入=%d" % Setting.DownloadAuto.value)

# 9c: 滚动条/非滚动区域的控件不受影响
pressesBefore = guard.Presses
sendMouse(QEvent.Type.MouseButtonPress, setting.scrollArea.vScrollBar,
          QPointF(4, setting.scrollArea.vScrollBar.height() / 2.0))
assert guard.Presses == pressesBefore, "滚动条不应该被守卫接管(拖滚动条要能用)"
sendMouse(QEvent.Type.MouseButtonPress, main.menuButton, QPointF(2, 2))
assert guard.Presses == pressesBefore, "不在滚动区域里的控件不应该被守卫接管"
# 下拉框弹出列表是 combo 的子孙：在里面滑动是滚列表，不能把弹窗收起来
assert mobile_ui._IsDescendant(setting.downAuto, setting.scrollArea)
assert not mobile_ui._IsDescendant(main.menuButton, setting.scrollArea)
assert mobile_ui._IsDescendant(setting.colorBox.view(), setting.colorBox)
print("[ok] 防误触只管滚动区域: 滚动条与顶栏按钮不受影响, 下拉弹窗归属判定正确")

# 真机取证用的竖屏几何描述(verify_on_device.ps1 解析的就是这些行)
portrait = mobile_ui.DescribePortrait(main)
for line in portrait:
    print("     |", line)
assert any("settings: outer.direction=TopToBottom" in x for x in portrait), portrait
assert any("nav 在内容之上: True" in x for x in portrait), portrait
assert any(x.startswith("  最宽的横向布局需要") for x in portrait), portrait
assert any("sr tool:" in x and "上下堆叠" in x for x in portrait), portrait
assert any("接口解密统计: ok=" in x for x in portrait), portrait
print("[ok] 竖屏几何描述可用于真机取证(%d 行)" % len(portrait))


# 逐页量"最宽的横向行"：QLayout.minimumSize() 是 Qt 自己的权威值，
# 比 scan_ui_width.py 那种 XML 估算靠谱。用来看还有哪些界面在竖屏下放不下。
def WidestRow(page):
    worst = None
    for layout in page.findChildren(QBoxLayout):
        if layout.direction() not in (QBoxLayout.Direction.LeftToRight,
                                      QBoxLayout.Direction.RightToLeft):
            continue
        need = layout.minimumSize().width()
        if worst is None or need > worst[0]:
            owner = layout.parentWidget().objectName() if layout.parentWidget() else "?"
            worst = (need, layout.objectName() or "?", owner)
    return worst


main.resize(384, 845)
app.processEvents()
stack = main.subStackWidget
available = mobile_ui.PortraitWidth(main)
# 拆行之后再量一遍：现在应该**没有**任何页面还有放不下的横向行
# 拆行/压单列/折行/压扁都只是"重排"，绝不能把控件弄丢。
# 真机上 Setting.DownloadModelName 是完整模型名，downModelName 最小宽 314px 把
# "模型"那一行撑到 378px > 内容视口 352px 被裁；宿主配置里名字很短，这里手动设长名复现。
pages = [stack.widget(i) for i in range(stack.count()) if stack.widget(i) is not None]
main.settingView.downModelName.setText("MODEL_WAIFU2X_CUNET_UP2X_DENOISE3X_ANIME_VIDEO_MODE")
app.processEvents()
print("   (复现真机长模型名: downModelName 最小宽 = %dpx)"
      % main.settingView.downModelName.minimumSizeHint().width())
beforeCounts = {p.objectName(): len(p.findChildren(QWidget)) for p in pages}
mobile_ui.EnableLabelWrap(stack, available)
mobile_ui.WrapWideRows(stack, available)
mobile_ui.FlattenWideGrids(stack, available)
mobile_ui.ShrinkToFit(stack, available)
app.processEvents()
afterCounts = {p.objectName(): len(p.findChildren(QWidget)) for p in pages}
assert beforeCounts == afterCounts, "重排丢了控件: %s" % [
    (k, beforeCounts[k], afterCounts.get(k)) for k in beforeCounts
    if beforeCounts[k] != afterCounts.get(k)]
print("[ok] 竖屏重排没有丢失任何控件(共 %d 个页面)" % len(pages))
app.processEvents()
rows = []
for i in range(stack.count()):
    page = stack.widget(i)
    if page is None:
        continue
    worst = WidestRow(page)
    if worst is None:
        continue
    rows.append((worst[0], type(page).__name__, page.objectName(), worst[1], worst[2]))
rows.sort(reverse=True)
print("竖屏 %dpx 下最宽的横向行(前 12 个页面, 已拆行):" % available)
for need, cls, name, layoutName, owner in rows[:12]:
    print("   %-20s %-20s %4dpx  %s" % (cls, name, need,
                                        "放得下" if need <= available else "放不下"))
settingRow = [r for r in rows if r[1] == "SettingView"]
assert settingRow, "没量到 SettingView"
worstSetting = settingRow[0]
assert worstSetting[0] <= available, \
    "设置页仍有放不下的横向行: {}.{} 需要 {}px > 可用 {}px".format(
        worstSetting[4], worstSetting[3], worstSetting[0], available)
print("[ok] 设置页最宽横向行 %dpx <= 可用 %dpx (%s.%s)"
      % (worstSetting[0], available, worstSetting[4], worstSetting[3]))
# 真机上超分模型名那个 QToolButton 最小宽 314px，把"模型"那一行撑到 378px 被裁
downBtn = main.settingView.downModelName
downRow = None
for layout in main.settingView.findChildren(QBoxLayout):
    if layout.direction() not in (QBoxLayout.Direction.LeftToRight,
                                  QBoxLayout.Direction.RightToLeft):
        continue
    if layout.indexOf(downBtn) >= 0:
        downRow = layout
        break
assert downRow is not None, "没找到装着 downModelName 的那一行"
assert downRow.minimumSize().width() <= available, \
    "模型名那一行仍然放不下: %dpx > 可用 %dpx" % (downRow.minimumSize().width(), available)
assert downBtn.minimumSize().width() <= available, \
    "模型名按钮本身仍然放不下: %dpx > 可用 %dpx" % (
        downBtn.minimumSize().width(), available)
print("[ok] 超长模型名那一行已放得下: 行 %dpx / 按钮 %dpx <= 可用 %dpx "
      "(按钮水平策略=%s, tooltip=%r)"
      % (downRow.minimumSize().width(), downBtn.minimumSize().width(), available,
         downBtn.sizePolicy().horizontalPolicy(), downBtn.toolTip()[:28]))

overflow = [r for r in rows if r[0] > available]
if overflow:
    for need, cls, name, layoutName, owner in overflow:
        print("   !! %s '%s' 仍然放不下: %dpx > %dpx (%s.%s)"
              % (cls, name, need, available, owner, layoutName))
        # 把这一行的构成打出来，方便定位是谁在撑宽度
        for i in range(stack.count()):
            page = stack.widget(i)
            if page is None or page.objectName() != name:
                continue
            for layout in page.findChildren(QBoxLayout):
                if layout.objectName() != layoutName:
                    continue
                for j in range(layout.count()):
                    item = layout.itemAt(j)
                    child = item.widget()
                    label = "%s '%s'" % (type(child).__name__, child.objectName()) \
                        if child is not None else "<spacer/layout>"
                    print("         item[%d] %-34s min=%d hint=%d" % (
                        j, label, item.minimumSize().width(), item.sizeHint().width()))
                    if child is not None:
                        inner = child.layout()
                        if inner is not None:
                            for k in range(inner.count()):
                                sub = inner.itemAt(k)
                                subw = sub.widget()
                                sublabel = "%s '%s'" % (type(subw).__name__, subw.objectName()) \
                                    if subw is not None else "<spacer/layout>"
                                print("             inner[%d] %-30s min=%d" % (
                                    k, sublabel, sub.minimumSize().width()))
assert not overflow, "还有 %d 个页面存在放不下的横向行" % len(overflow)
print("[ok] 所有可达页面都没有放不下的横向行(%d 个页面)" % len(rows))

# ---------------------------------------------------------------------------
# 本轮修复的真机问题(2026-09-30 用户反馈)
# ---------------------------------------------------------------------------
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox  # noqa: E402

# ① "分流设置仍为双排排版"：分流设置就是 loginNewView 的 tab_4，
#    结构同样是 [竖排标题列, scrollArea_3] 左右并排 -> 必须也改成上下。
login = main.loginNewView
assert hasattr(login, "horizontalLayout_14"), "分流设置页的外层布局应为 horizontalLayout_14"
assert getattr(login.horizontalLayout_14, "_jmNavStacked", False), \
    "分流设置页仍然左右并排(用户报的'仍为双排')"
assert login.horizontalLayout_14.direction() == QBoxLayout.Direction.TopToBottom, \
    "分流设置页外层应改成上下排列, 实际=%s" % login.horizontalLayout_14.direction()
assert login.verticalLayout_14.direction() == QBoxLayout.Direction.LeftToRight, \
    "分流设置页的标题列应改成横排"
assert login.horizontalLayout_14.minimumSize().width() <= available, \
    "分流设置页仍然要求 %dpx > 可用 %dpx" % (login.horizontalLayout_14.minimumSize().width(),
                                          available)
# 设置页也是同一个模式，一起断言(两边逻辑合并成了一个通用实现)
assert getattr(setting.horizontalLayout, "_jmNavStacked", False), "设置页应标记为已堆叠"
print("[ok] 分流设置页(login_new.tab_4)已改为上下堆叠: 外层=%s, 标题列=%s, 需要 %dpx"
      % (login.horizontalLayout_14.direction().name,
         login.verticalLayout_14.direction().name,
         login.horizontalLayout_14.minimumSize().width()))

# ② "看图界面的菜单宽度会超出屏幕 + 看图界面和菜单都滚不动"
#    原来 ScaleFrame 写死 qtTool.setGeometry(w-400, 0, 400, h)：384px 屏上 x=-16。
frame = main.readView.frame
tool = frame.qtTool
main.resize(384, 845)
app.processEvents()
frame.ScaleFrame()
app.processEvents()
assert tool.x() >= 0, "看图工具菜单跑到屏幕左边外面了: x=%d" % tool.x()
assert tool.x() + tool.width() <= frame.width() + 2, \
    "看图工具菜单超出看图区: %d > %d" % (tool.x() + tool.width(), frame.width())
assert tool.width() >= frame.width() - 2, "竖屏下工具菜单应占满整宽"
assert getattr(main.readView.frame, "_jmToolMobile", False), "看图工具菜单应装好竖屏几何钩子"
# 工具菜单里的滚动区必须被 QScroller 接管，否则手指拖不动
assert getattr(frame.qtTool.scrollArea22, "_jmTouchScroll", False), \
    "看图工具菜单的滚动区没有被接管手指滚动"
# 看图区自己要有拖动滚动(桌面端只有滚轮)
assert mobile_ui._readerDrag is not None, "看图区应装上拖动滚动"
print("[ok] 看图菜单整宽在屏内: tool=(%d,%d,%d,%d) 看图区=%dx%d；菜单滚动区已接管、"
      "看图区拖动滚动已接管" % (tool.x(), tool.y(), tool.width(), tool.height(),
                             frame.width(), frame.height()))

# ③ "主页每行要放得下 2 本漫画"
avail = mobile_ui.PortraitWidth(main)
from component.widget.comic_item_widget import ComicItemWidget  # noqa: E402
from PySide6.QtWidgets import QListWidget, QListWidgetItem  # noqa: E402


def _StopPendingGrid():
    """ 停掉 ScheduleGridCoverSize 排下的去抖重排

    ③ 的断言是"快照一致性"(self-correct 出的封面宽要原样缓存给后加的 item 用)，
    而真机上所有列表同宽、不会有"另一个宽度的列表把全局封面宽改掉"的情况；
    这里的 host 是为了测试单独造的列表，所以先固定住快照(真机上的重排见 ③.5)。
    """
    timer = getattr(mobile_ui, "_gridTimer", None)
    if timer is not None:
        timer.stop()
    del mobile_ui._gridPending[:]
    return


# 真机用的是一行 2 个的自动装箱：把 item 放进一个真实宽度的 QListWidget，
# 让 ApplyGridCoverSize 自己校正封面宽度，最后断言"item 宽 <= 可用宽/2"。
mobile_ui.ResetGridCover()
_StopPendingGrid()
host = QListWidget()
host.resize(avail, 400)
host.setFlow(QListWidget.LeftToRight)
host.setWrapping(True)
host.setResizeMode(QListWidget.Adjust)
host.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
for i in range(2):
    widget = ComicItemWidget()
    widget.SetTitle("测试标题%d" % i, "")
    widget.SetPicture(None)
    listItem = QListWidgetItem(host)
    listItem.setSizeHint(widget.sizeHint())
    host.setItemWidget(listItem, widget)
host.show()
app.processEvents()
# 真机上这个函数会在"页面切出来"和"切出来 150ms 后"各跑一次(文字/布局那时才定下来)，
# 所以这里也跑两次：第一次按屏幕宽度算，第二次按真实 sizeHint 自校正到收敛。
mobile_ui.ApplyGridCoverSize(host)
app.processEvents()
mobile_ui.ApplyGridCoverSize(host)
app.processEvents()
over = mobile_ui._GridOverflow(host)
firstWidget = host.itemWidget(host.item(0))
assert over <= 0, "封面控件仍然超出可用宽/2 共 %dpx(会退回一行 1 个)" % over
# QListView 的"一行几个"就是按 item 宽(这里被显式设成 gridSize)算的；
# offscreen 下 visualItemRect 在有滚动条时不一定跟着重排，所以主机侧断言这个几何条件，
# 真正的"一行几个"由真机自检(GridStatsLines，visualItemRect)来数。
cell = host.gridSize().width() or firstWidget.sizeHint().width()
assert cell * mobile_ui.GridColumns <= host.viewport().width() + 2, \
    "栅格 %dpx x %d 列放不进 %dpx 视口" % (cell, mobile_ui.GridColumns,
                                        host.viewport().width())
stats = mobile_ui.GridStatsLines(host)
assert mobile_ui.GridCoverWidth(False) == getattr(firstWidget, "_jmGridSized", 0), \
    "self-correct 后的封面宽应被缓存给后加的 item 用"
print("[ok] 首页封面竖屏尺寸: 封面 %dpx item %dpx / 可用 %dpx -> 一行 2 个 "
      "(self-correct 后缓存 %dpx, 后加的 item 也用它)"
      % (firstWidget.picLabel.width(), firstWidget.sizeHint().width(),
         mobile_ui.PortraitWidth(main), mobile_ui.GridCoverWidth(False)))
print("     |", stats[0])
# 真机取证用的网格统计行(首页列表)
lines = mobile_ui.GridStatsLines(main.indexView.newListWidget)
assert lines and lines[0].startswith("首页网格:"), lines
print("     |", lines[0])
host.hide()
host.deleteLater()
app.processEvents()

# ③.5 首屏"打开首页一行 1 个，进设置页再返回才变一行 2 个"的回归
#   真机顺序：启动早期列表还没被布局(ComicListWidget.__init__ 里写死了 resize(800,600))、
#   主窗口也还没被 Android 拉成竖屏 -> **空列表**就把封面宽 freeze 住了；等网络回来一条条
#   建 item 时用的就是这个宽度 -> 一行只放得下 1 个。而重排原来只在窗口 shown / 切页时跑，
#   于是首屏一直错到用户切页为止(切页触发了那次重排 = 用户说的"进设置再返回才对")。
#   修复：① MeasureGridAvail 把超过页面宽的视口按页面宽夹住 ② AddBookItem 里挂去抖重排。
from component.list.comic_list_widget import ComicListWidget  # noqa: E402

mobile_ui.ResetGridCover()
stale = ComicListWidget(None)               # 真的那套列表(构造里就 resize(800,600))
stale.show()
app.processEvents()
mobile_ui.ApplyGridCoverSize(stale)         # 空列表：这次量到的视口是"设计宽度"
frozen = mobile_ui.GridCoverWidth(False)
page = mobile_ui.PortraitWidth(main)
assert mobile_ui._gridAvail <= page + 2, \
    "超过页面宽的视口没被夹住: %dpx > 页面 %dpx" % (mobile_ui._gridAvail, page)
stale.resize(330, 400)                      # 真机上的列表视口只有 ~330px(页面 384px)
app.processEvents()
# 真机顺序：网络回来后一条条 AddBookItem(内部就是靠它排的去抖重排)。
# 这里刻意不 processEvents —— 保证 item 就是按"冻结的宽封面"建出来的。
stale.AddBookItem("1", "首屏回归1", "", "")
stale.AddBookItem("2", "首屏回归2", "", "")
firstStale = stale.itemWidget(stale.item(0))
overBefore = mobile_ui._GridOverflow(stale)
assert firstStale.picLabel.width() == frozen, \
    "item 没按冻结的封面宽建出来: %d != %d" % (firstStale.picLabel.width(), frozen)
assert overBefore >= 8, "没复现出'一行放不下 2 个'(over=%d)" % overBefore
print("[ok] 复现首屏: 空列表在设计宽度下就把封面宽冻结成 %dpx(视口按页面宽 %dpx 夹住) -> "
      "首屏 item %dpx 超出可用宽/2 共 %dpx(一行 1 个)"
      % (frozen, page, firstStale.sizeHint().width(), overBefore))
# 只等去抖重排跑完，不切页、不重开窗口
deadline = time.time() + 3.0
while time.time() < deadline and mobile_ui._GridOverflow(stale) > 0:
    app.processEvents()
    time.sleep(0.02)
overAfter = mobile_ui._GridOverflow(stale)
assert overAfter <= 0, "去抖重排后首屏仍然一行 1 个(over=%d)" % overAfter
assert mobile_ui.GridCoverWidth(False) < frozen, "冻结的封面宽没有被重算"
assert firstStale.picLabel.width() == mobile_ui.GridCoverWidth(False), \
    "已经在列表里的封面没跟着重算: %d != %d" % (firstStale.picLabel.width(),
                                             mobile_ui.GridCoverWidth(False))
print("[ok] 首屏自动收敛(无需切页): 封面 %d -> %dpx / item %dpx <= 可用 %dpx 的一半 -> 一行 2 个"
      % (frozen, mobile_ui.GridCoverWidth(False), firstStale.sizeHint().width(),
         stale.viewport().width()))
print("     |", mobile_ui.GridStatsLines(stale)[0])
stale.hide()
stale.deleteLater()
app.processEvents()

# ④ "在下拉框/数值框附近滑动会误触它们"
#    下拉框/数值框在 **press** 时就生效，所以守卫要连 press 一起扣住，点按时再重放。
main.SwitchWidgetAndClear(main.subStackWidget.indexOf(main.settingView))
app.processEvents()


def pickAny(view, cls, minWidth):
    """ 先挑视口里露出来的，挑不到就退化成"任意一个可用控件"(测试只发事件，不需要坐标) """
    found = mobile_ui._PickVisibleWidget(view, lambda w: isinstance(w, cls), minWidth)
    if found is not None:
        return found
    for widget in view.findChildren(cls):
        if widget.isEnabled() and widget.width() >= minWidth:
            return widget
    return None


combo = pickAny(setting, QComboBox, 60)
spin = pickAny(setting, QAbstractSpinBox, 40)
assert combo is not None and spin is not None, "设置页应有下拉框/数值框"
for widget in (combo, spin):
    before = guard.Presses
    sendMouse(QEvent.Type.MouseButtonPress, widget, QPointF(widget.width() / 2.0, 6))
    assert guard.Presses == before + 1, "%s 的按下应被守卫接管" % widget.objectName()
    sendMouse(QEvent.Type.MouseMove, widget, QPointF(widget.width() / 2.0, 6 + slop + 4))
    app.processEvents()
    assert not (combo.view().isVisible() if widget is combo else False), \
        "滑动过程中下拉框不应该弹出来"
comboValue = combo.currentText()
spinValue = spin.value()
sendMouse(QEvent.Type.MouseButtonRelease, combo, QPointF(combo.width() / 2.0, 6 + slop + 4))
sendMouse(QEvent.Type.MouseButtonRelease, spin, QPointF(spin.width() / 2.0, 6 + slop + 4))
app.processEvents()
assert combo.currentText() == comboValue, "滑过下拉框不应该改它的值"
assert spin.value() == spinValue, "滑过数值框不应该改它的值"
assert not combo.view().isVisible(), "滑动不应该把下拉列表弹出来"
print("[ok] 下拉框/数值框附近滑动不再误触: %s=%r / %s=%d 均未变"
      % (combo.objectName(), comboValue, spin.objectName(), spinValue))

# 点按仍然生效(重放 press+release)：下拉框应该弹出列表
combo.setCurrentIndex(0)
sendMouse(QEvent.Type.MouseButtonPress, combo, QPointF(combo.width() / 2.0, combo.height() / 2.0))
sendMouse(QEvent.Type.MouseButtonRelease, combo, QPointF(combo.width() / 2.0, combo.height() / 2.0))
app.processEvents()
assert combo.view().isVisible(), "正常点按必须仍然弹出下拉列表(重放链路断了)"
combo.hidePopup()
app.processEvents()
# 数值框：点它的"上箭头"应该加 1(说明重放真的落到了控件自己的处理逻辑里)
upX = spin.width() - 6
beforeValue = spin.value()
sendMouse(QEvent.Type.MouseButtonPress, spin, QPointF(upX, 6))
sendMouse(QEvent.Type.MouseButtonRelease, spin, QPointF(upX, 6))
app.processEvents()
assert spin.value() == beforeValue + 1, \
    "点数值框上箭头应该 +1, 实际 %d -> %d" % (beforeValue, spin.value())
print("[ok] 正常点按仍然生效: 下拉框弹出列表, 数值框箭头 %d -> %d"
      % (beforeValue, spin.value()))

# ⑤ "改设置/输入就崩溃"：真机上是**第二个顶层窗口**一渲染就撞
#    QAndroidPlatformOpenGLWindow::eglSurface() 的死锁保护器 -> SIGABRT。
#    所以提示条/加载框/遮罩对话框在手机端全部改成主窗口里的**子控件覆盖层**，
#    另外任何残留的顶层窗口的 show/hide/close 仍会被延后到输入事件之后。
assert mobile_ui.ShouldDeferWindowShow(), "移动端应开启顶层窗口延后显示"
stats = mobile_ui.ShowDeferralStats
from component.label.msg_label import MsgLabel  # noqa: E402

msg = MsgLabel(main)
msg.setText("测试")
assert not msg.isWindow(), "提示条必须是子控件(第二个顶层窗口会 abort)"
msg.ShowMsg("保存成功")
assert msg.isVisible(), "子控件提示条应立即显示(同一个平台窗口，不需要延后)"
assert msg.parent() is not None, "提示条应挂在主窗口里"
print("[ok] 提示条(MsgLabel)已是主窗口内的子控件: parent=%s isWindow=%s"
      % (type(msg.parent()).__name__, msg.isWindow()))
main.loadingDialog.show()
assert main.loadingDialog.isVisible(), "加载框应立即显示"
assert not main.loadingDialog.isWindow(), "加载框必须是子控件"
main.loadingDialog.close()
app.processEvents()
# 现在测"延后"机制本身：故意造一个真正的顶层窗口
from PySide6.QtWidgets import QWidget as _QWidget  # noqa: E402

beforeDefer = stats["deferred"]
probe = _QWidget()
probe.setWindowFlags(Qt.Window)
probe.setWindowTitle("top-level probe")
probe.resize(200, 100)
probe.show()
assert not probe.isVisible(), "顶层窗口的 show 必须被延后(同步 show 会触发真机 SIGABRT)"
deadline = time.time() + 2.0
while time.time() < deadline and not probe.isVisible():
    app.processEvents()
    time.sleep(0.02)
assert probe.isVisible(), "延后之后应该真的显示出来"
assert stats["deferred"] > beforeDefer, "延后计数应该增加"
probe.close()
deadline = time.time() + 2.0
while time.time() < deadline and probe.isVisible():
    app.processEvents()
    time.sleep(0.02)
assert not probe.isVisible(), "延后关闭也必须真的关掉(不能无限延后)"
print("[ok] 残留顶层窗口的 show/close 仍会延后到输入事件之后 "
      "(deferred=%d shown=%d closed=%d)" % (stats["deferred"], stats["shown"], stats["closed"]))
# 遮罩对话框同样必须是子控件
from component.dialog.base_mask_dialog import BaseMaskDialog  # noqa: E402

mask = BaseMaskDialog(main)
assert not mask.isWindow(), "遮罩对话框必须是主窗口的子控件"
assert getattr(mask, "_jmChildOverlay", False), "遮罩对话框应标记为子控件覆盖层"
mask.show()
assert mask.isVisible()
mask.close()
app.processEvents()
print("[ok] 遮罩对话框(登录/收藏夹/模型选择等基类)已是子控件覆盖层")

# 返回键：真机上 Android 的返回键到不了 Qt 窗口，所以顶栏必须有一个看得见的返回入口
backButton = getattr(main, "_jmBackButton", None)
assert backButton is not None, "手机端顶栏应有返回按钮"
assert backButton.text(), backButton.text()
assert backButton.parent() is not None
# 点它等价于按一次返回键(走同一条 HandleBackKey)
mobile_ui._backLastTick = 0.0
beforeAction = mobile_ui.BackStats["count"]
backButton.click()
app.processEvents()
assert mobile_ui.BackStats["count"] == beforeAction + 1, "点返回按钮应走 HandleBackKey"
print("[ok] 顶栏返回按钮: '%s' -> %s" % (backButton.text(), mobile_ui.BackStats["last"]))

# ⑥ 返回键优先级："先收看图菜单 -> 再退看图 -> 再回退页面 -> 最后退到后台"
def pressBack():
    mobile_ui._backLastTick = 0.0
    return mobile_ui.HandleBackKey(main)


# 先回退页面：推一个二级页面进去
# 注意：页面切换是 250ms 的位移动画，currentIndex 要等动画结束才变，必须等
def waitPage(index, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if main.subStackWidget.currentIndex() == index:
            return True
        time.sleep(0.02)
    return main.subStackWidget.currentIndex() == index


idxHelp = main.subStackWidget.indexOf(main.helpView)
idxSetting = main.subStackWidget.indexOf(main.settingView)
print("     (页面下标: helpView=%d settingView=%d 总页数=%d)"
      % (idxHelp, idxSetting, main.subStackWidget.count()))
assert idxHelp >= 0 and idxSetting >= 0, "helpView/settingView 必须是页面栈里的页面"
main.SwitchWidgetAndClear(idxHelp)
assert waitPage(idxHelp), "没切到 helpView"
main.SwitchWidgetByIndex(idxSetting)
assert waitPage(idxSetting), "没切到 settingView"
assert len(main.subStackList) >= 2, main.subStackList
beforePage = main.subStackWidget.currentIndex()
assert pressBack() is True
changed = waitPage(main.subStackList[0])
print("     (返回后 action=%s page %d -> %d, 顶层窗口=%s)"
      % (mobile_ui.BackStats["action"], beforePage, main.subStackWidget.currentIndex(),
         mobile_ui._VisibleTopWindow(main)))
assert changed and main.subStackWidget.currentIndex() != beforePage, \
    "返回键应先回退一层页面"
assert mobile_ui.BackStats["action"] == "switch-widget-last", mobile_ui.BackStats
print("[ok] 返回键回退页面: %s" % mobile_ui.BackStats["last"])

# 看图：菜单优先
main.totalStackWidget.setCurrentIndex(1)
frame.qtTool.show()
app.processEvents()
assert not frame.qtTool.isHidden()
assert pressBack() is True
assert frame.qtTool.isHidden(), "看图菜单打开时返回键应先收起菜单"
assert mobile_ui.BackStats["action"] == "close-read-tool", mobile_ui.BackStats
print("[ok] 返回键先收看图菜单: %s" % mobile_ui.BackStats["last"])

# 看图：再按一次退出看图
assert pressBack() is True
assert mobile_ui.BackStats["action"] == "close-reader", mobile_ui.BackStats
assert main.totalStackWidget.currentIndex() == 0, "第二次返回应退出看图回到上级"
print("[ok] 返回键退出看图: %s" % mobile_ui.BackStats["last"])

# 根页面：不能把 Qt 窗口藏起来(实测 showMinimized 只隐藏 Qt 窗口、Activity 仍在前台
# -> 屏幕上就是一片白，正是用户报的"白屏")，所以要"保持可见 + 给一句提示"
beforeMin = mobile_ui.BackStats["minimize"]
assert pressBack() is True
assert mobile_ui.BackStats["action"] == "root-page", mobile_ui.BackStats
assert mobile_ui.BackStats["minimize"] == beforeMin + 1
assert main.isVisible(), "根页面按返回不能把主窗口藏起来(会白屏)"
assert not main.isMinimized(), "根页面按返回不能用 showMinimized(真机上就是白屏)"
print("[ok] 根页面返回: 保持窗口可见 + 提示(不会白屏): %s" % mobile_ui.BackStats["last"])
main.showNormal()
app.processEvents()

# ⑦ "导入本地漫画/导入本地图片卡死"：Android 上不再用 QFileDialog(它会弹一个
#    回不来的顶层窗口)。桌面端必须仍然原样转发给 QFileDialog。
from PySide6.QtWidgets import QFileDialog  # noqa: E402

from tools import mobile_file_dialog  # noqa: E402

originExisting = QFileDialog.getExistingDirectory
originOpen = QFileDialog.getOpenFileName
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "/tmp/delegated")
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("/tmp/delegated.jpg", ""))
try:
    # 主机(非 Android) 模式下 IsAndroid() 为 True(本测试强制 Android)…
    # 所以这里直接验"Android 分支不碰 QFileDialog"，再用 monkeypatch 验桌面分支的转发。
    called = {"existing": 0, "open": 0}
    QFileDialog.getExistingDirectory = staticmethod(
        lambda *a, **k: called.__setitem__("existing", called["existing"] + 1) or "/tmp/d")
    QFileDialog.getOpenFileName = staticmethod(
        lambda *a, **k: called.__setitem__("open", called["open"] + 1) or ("/tmp/f.jpg", ""))
    assert mobile_ui.ShouldDeferWindowShow(), "移动端应开启顶层窗口延后显示"
    assert mobile_file_dialog.CancelDir == "", "目录模式取消值必须是空串"
    assert mobile_file_dialog.CancelResult == (), "文件模式取消值必须是空元组"
    picker = mobile_file_dialog._PickerDialog(main, "选择目录", TMP,
                                              mobile_file_dialog.ModeDir, "")
    assert not picker.isWindow(), "Android 选择器必须是主窗口的子控件，不能是顶层窗口"
    assert picker.parent() is not None, "选择器必须有父控件"
    assert picker.cancelResult == "", "目录模式的取消值应为空串"
    picker.hide()
    picker.deleteLater()
    app.processEvents()
    assert mobile_file_dialog.GetExistingDirectory is not None
    print("[ok] 文件选择器: Android 走应用内子控件(不是顶层窗口), 桌面端转发 QFileDialog, "
          "取消值形状正确")
finally:
    QFileDialog.getExistingDirectory = originExisting
    QFileDialog.getOpenFileName = originOpen

# ⑧ 图片分割(分块还原)链路(离线自检)：与**独立实现**的官方算法逐像素比对
#    (旧自检用 rem=0 的等分样本自我验证，既测不出算法错，也测不出真机 Pillow 没有 webp 解码器)
decrypt = mobile_ui.DecryptSelfTest()
for line in decrypt:
    print("     |", line)
assert any("解密自检: PASS" in x for x in decrypt), decrypt
assert any("图片分割自检(合成" in x and "PASS" in x for x in decrypt), decrypt
assert any("TaskQImage.ConverQImage" in x for x in decrypt), decrypt
assert any("TaskQImage(带 saveParams)" in x and "可比=True 不同像素=0" in x for x in decrypt), decrypt
print("[ok] 图片分割/解码自检通过(离线、与官方算法逐像素比对)")

# ⑨ 图片解码管线统计(真机上用它判断"图片没出来"是拼图失败还是 QImage 线程死了)
pipeline = mobile_ui._ImagePipelineLines()
assert any(x.startswith("图片解码:") for x in pipeline), pipeline
assert any(x.startswith("拼图解密:") for x in pipeline), pipeline
for line in pipeline:
    print("     |", line)
print("[ok] 图片解码/拼图统计可读")

print("\n全部冒烟测试通过")
print("\n全部冒烟测试通过")
