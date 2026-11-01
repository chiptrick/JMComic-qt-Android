from PySide6.QtCore import (QBuffer, QIODevice, QObject, QRunnable, QSize, Qt,
                            QThreadPool, QTimer, Signal)
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QImage, QImageReader, QPixmap
from PySide6.QtWidgets import QListWidget, QWidget

from config import config
from config.setting import Setting
from interface.ui_comic_item import Ui_ComicItem
from tools.str import Str


def DecodeCoverImage(data, targetW, targetH):
    """按**像素**目标尺寸解码成一幅 QImage（可在工作线程里跑）

    原来是 loadFromData 整图解码(常见 700x1000) + SmoothTransformation 缩到封面尺寸，
    一张 ~3ms 全压在主线程；一屏 60 个封面就是 180ms 的卡顿。
    QImageReader 直接按目标尺寸解码(JPEG 走 DCT 缩放)，省掉整图 + 缩放两步；
    QImage 不碰 GUI 资源，可以放心放到线程池里。
    """
    targetW = max(1, int(targetW))
    targetH = max(1, int(targetH))
    if not data:
        return QImage()
    try:
        buf = QBuffer()
        buf.setData(data)
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buf)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and size.width() > targetW and size.height() > targetH:
            scaled = size.scaled(QSize(targetW, targetH), Qt.AspectRatioMode.KeepAspectRatio)
            if scaled.width() > 0 and scaled.height() > 0:
                reader.setScaledSize(scaled)
        img = reader.read()
        if img.isNull():
            img = QImage()
            img.loadFromData(data)
        if img.isNull():
            return QImage()
        # 关键：无论原图比目标大还是小，最后都缩放到目标框（老版本就是这么做的）。
        # 只在"原图更大"时缩放的话，缓存里 400x533 这类小图会原样塞进 QLabel 被居中绘制，
        # 表现为封面比标题窄一圈、左右各留一条边（真机 0.80 的图就是这样）。
        if img.width() != targetW or img.height() != targetH:
            img = img.scaled(targetW, targetH, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        return img
    except Exception:
        return QImage()


def DecodeCoverPixmap(data, targetW, targetH, radio):
    """同步版（宿主测试/降级用）：返回 DPR 已设置好的 QPixmap"""
    if not data:
        return QPixmap()
    img = DecodeCoverImage(data, targetW * radio, targetH * radio)
    if img.isNull():
        return QPixmap()
    pixmap = QPixmap.fromImage(img)
    pixmap.setDevicePixelRatio(radio)
    return pixmap


_CoverPool = None


def _Pool():
    global _CoverPool
    if _CoverPool is None:
        pool = QThreadPool()
        pool.setMaxThreadCount(2)
        _CoverPool = pool
    return _CoverPool


_ApplyQueue = []
_ApplyTimer = None


def _QueueCoverApply(widget, pixmap):
    """把"设置封面"排进全局队列（每 16ms 最多铺 2 张）"""
    global _ApplyTimer
    try:
        _ApplyQueue.append((widget, pixmap))
    except Exception:
        return
    if _ApplyTimer is None:
        timer = QTimer()
        timer.setInterval(16)
        timer.timeout.connect(_DrainCoverApply)
        _ApplyTimer = timer
    if not _ApplyTimer.isActive():
        _ApplyTimer.start()
    return


def _DrainCoverApply():
    global _ApplyTimer
    done = 0
    while _ApplyQueue and done < 2:
        widget, pixmap = _ApplyQueue.pop(0)
        done += 1
        try:
            from shiboken6 import isValid
            if not isValid(widget):
                continue
        except Exception:
            pass
        try:
            widget.picLabel.setPixmap(pixmap)
        except Exception:
            pass
    if not _ApplyQueue and _ApplyTimer is not None:
        try:
            _ApplyTimer.stop()
        except Exception:
            pass
    return


class _CoverTask(QRunnable):
    """工作线程：只解 QImage，不碰任何 QWidget/QPixmap"""

    def __init__(self, gen, data, targetW, targetH, emit):
        super().__init__()
        self.setAutoDelete(True)
        self.gen = gen
        self.data = data
        self.targetW = targetW
        self.targetH = targetH
        self.emit = emit

    def run(self):
        img = QImage()
        try:
            img = DecodeCoverImage(self.data, self.targetW, self.targetH)
        except Exception:
            img = QImage()
        try:
            self.emit(self.gen, img)
        except Exception:
            pass


class ComicItemWidget(QWidget, Ui_ComicItem):
    PicLoad = Signal(int)
    # 工作线程解完后的回投信号(gen, image)；跨线程自动排队到 GUI 线程
    CoverDecoded = Signal(int, QImage)
    # 桌面端封面基准尺寸(宽 x 高)，竖屏按比例换算
    BaseCoverWidth = 250
    BaseCoverHeight = 340
    # 图标缓存：SVG/PNG 图标每次 addFile 都会重新栅格化，列表里每项都要建一次
    _NewIcon = None
    _StarIcon = None

    def __init__(self, isCategory=False, isShiled=False):
        QWidget.__init__(self)
        Ui_ComicItem.__init__(self)
        self.setupUi(self)
        self.isShiled = isShiled
        self.picData = None
        self.id = ""
        self.title = ""
        self.picNum = 0
        self.category = ""
        self.tags = ""
        self.rawBook = None

        self.index = 0
        self.url = ""
        self.path = ""
        # TODO 如何自适应
        self.isCategory = isCategory
        if not isCategory:
            rate = Setting.CoverSize.value
            baseW = ComicItemWidget.BaseCoverWidth
            baseH = ComicItemWidget.BaseCoverHeight
        else:
            rate = Setting.CategorySize.value
            baseW = 300
            baseH = 300

        width, height = self._CoverSize(baseW, baseH, rate)

        if ComicItemWidget._NewIcon is None:
            ComicItemWidget._NewIcon = QIcon()
            ComicItemWidget._NewIcon.addFile(u":/png/icon/new.svg", QSize(), QIcon.Normal, QIcon.Off)
        icon2 = ComicItemWidget._NewIcon

        self.toolButton.setMinimumSize(QSize(0, 40))
        self.toolButton.setFocusPolicy(Qt.NoFocus)
        self.toolButton.setIcon(icon2)
        self.toolButton.setIconSize(QSize(32, 32))

        self.picLabel.setFixedSize(width, height)
        if self.isShiled:
            pic = QImage(":/png/icon/shiled.svg")
            radio = self.devicePixelRatio()
            pic.setDevicePixelRatio(radio)
            newPic = pic.scaled(self.picLabel.width() * radio, self.picLabel.height() * radio, Qt.KeepAspectRatio,
                                Qt.SmoothTransformation)
            newPic2 = QPixmap(newPic)
            self.picLabel.setPixmap(newPic2)

        # self.picLabel.setMinimumSize(300, 400)
        # self.picLabel.setMaximumSize(220, 308)

        # self.categoryLabel.setMinimumSize(210, 25)
        # self.categoryLabel.setMaximumSize(210, 150)

        if ComicItemWidget._StarIcon is None:
            ComicItemWidget._StarIcon = QIcon(":/png/icon/icon_bookmark_on.png")
        self.starButton.setIcon(ComicItemWidget._StarIcon)
        self.starButton.setIconSize(QSize(20, 20))
        self.starButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.starButton.setMinimumHeight(24)
        self.timeLabel.setMinimumHeight(24)

        self.categoryLabel.setMaximumWidth(width-20)
        self.starButton.setMaximumWidth(width-20)
        self.timeLabel.setMaximumWidth(width-20)

        # self.nameLable.setMinimumSize(210, 25)
        # self.nameLable.setMaximumSize(210, 150)
        self.nameLable.setMaximumWidth(width-20)
        self.nameLable.adjustSize()
        self.nameLable.setWordWrap(True)
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.nameLable.setFont(font)
        self.adjustSize()
        self.isWaifu2x = False
        self.isWaifu2xLoading = False
        self.isLoadPicture = False
        self._coverGen = 0
        self._coverRetry = False
        self._syncGuard = False
        self.CoverDecoded.connect(self._OnCoverDecoded)

    @staticmethod
    def _CoverSize(baseW, baseH, rate):
        """ 封面尺寸(逻辑像素)

        桌面端 = 基准尺寸 x 用户设置的百分比；Android 竖屏下改为按屏幕宽度反算成
        "一行放得下 2 本"，否则 250x340 的桌面封面在 384px 的竖屏上每行只能放 1 本。
        宽高比保持桌面原样。
        """
        try:
            rate = float(rate or 100)
        except Exception:
            rate = 100.0
        width = float(baseW) * rate / 100.0
        height = float(baseH) * rate / 100.0
        try:
            from tools import platform_mobile
            if platform_mobile.IsAndroid():
                from tools import mobile_ui
                cover = float(mobile_ui.GridCoverWidth(False))
                if cover > 0:
                    width = cover
                    height = cover * float(baseH) / float(baseW)
        except Exception:
            pass
        return max(24, int(width)), max(24, int(height))

    def ResizeCover(self, coverWidth):
        """ 按新的封面宽度重算尺寸(运行时改设置/旋转屏幕用)，保持宽高比 """
        try:
            coverWidth = int(coverWidth)
            if coverWidth <= 0:
                return
            if self.isCategory:
                baseW, baseH = 300, 300
            else:
                baseW, baseH = ComicItemWidget.BaseCoverWidth, ComicItemWidget.BaseCoverHeight
            height = int(coverWidth * float(baseH) / float(baseW))
            if self.picLabel.width() == coverWidth and self.picLabel.height() == height:
                return
            # RefreshItemSizeHints 为了让 QListView 的装箱确定，会把 item widget 的宽度
            # setFixedWidth 钉住。要变**小**就必须先松绑：否则下面的 adjustSize() 缩不回去，
            # 控件会停在旧宽度(封面小了、控件没小 -> 真机上还是一行 1 个)。
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self.picLabel.setFixedSize(coverWidth, height)
            # 文字块与封面同宽（原来是 coverWidth-20，和图片左右边界对不齐）
            for lb in (self.categoryLabel, self.starButton, self.timeLabel, self.nameLable):
                lb.setMaximumWidth(coverWidth)
            self.adjustSize()
            # 列表随后会把 item 钉到 cellW；这里再按真实内容宽度对齐一次
            self.SyncContentWidth()
            if self.picData:
                self.SetPicture(self.picData, self.picLabel.width(), self.picLabel.height())
        except Exception as es:
            from tools.log import Log
            Log.Error(es)
        return

    def SetTitle(self, title, fontColor):
        self.title = title
        if Setting.NotCategoryShow.value:
           self.categoryLabel.setVisible(False)

        if Setting.TitleLine.value == 0:
            self.nameLable.setVisible(False)
        elif Setting.TitleLine.value == 1:
            self.nameLable.setWordWrap(False)
            self.nameLable.setText(title + fontColor)
        elif Setting.TitleLine.value > 3:
            self.nameLable.setText(title+fontColor)
        else:
            title2 = self.ElidedLineText(fontColor)
            self.nameLable.setText(title2)

    def ElidedLineText(self, fontColor):
        line = Setting.TitleLine.value
        if line <= 0 :
            line = 2
        f = QFontMetrics(self.nameLable.font())
        if (line == 1):
            return f.elidedText(self.title + fontColor, Qt.ElideRight, self.nameLable.maximumWidth())

        strList = []
        start = 0
        isEnd = False
        for i in range(1, len(self.title)):
            if f.boundingRect(self.title[start:i]).width() >= self.nameLable.maximumWidth()-10:
                strList.append(self.title[start:i])
                if len(strList) >= line:
                    isEnd = True
                    break
                start = i

        if not isEnd:
            strList.append(self.title[start:])

        if not strList:
            strList.append(self.title)

        # strList[-1] = strList[-1] + fontColor

        hasElided = True
        endIndex = len(strList) - 1
        endString = strList[endIndex]
        if f.boundingRect(endString).width() < self.nameLable.maximumWidth() -10:
            strList[endIndex] += fontColor
            hasElided = False

        if (hasElided):
            if len(endString) > 8 :
                endString = endString[0:len(endString) - 8] + "..." + fontColor
                strList[endIndex] = endString
            else:
                strList[endIndex] += fontColor
        return "".join(strList)

    def GetTitle(self):
        return self.title

    def SetPicture(self, data, targetW=None, targetH=None):
        """设置封面：解码+缩放放到线程池，主线程只负责 setPixmap

        targetW/targetH 是**逻辑像素**的目标尺寸，默认取 picLabel 当前大小。
        图形层改过 label 尺寸之后必须显式传进来：setFixedSize 要等下一轮布局才反映到
        width()，此刻按 width() 解码，解出来的图会比 label 小 —— QLabel 默认是
        **居中绘制**不缩放，于是封面看起来左右各缩进一截，和标题对不齐（真机就是这样）。
        """
        self.picData = data
        self.isWaifu2x = False
        self.isWaifu2xLoading = False
        self._coverGen += 1
        gen = self._coverGen
        self._coverRetry = False
        self._coverTarget = (0, 0)
        if not data:
            self.picLabel.setPixmap(QPixmap())
            return
        radio = self.devicePixelRatio()
        w = self.picLabel.width() if targetW is None else targetW
        h = self.picLabel.height() if targetH is None else targetH
        self._coverTarget = (int(w), int(h))
        tw = max(1, int(w * radio))
        th = max(1, int(h * radio))
        try:
            _Pool().start(_CoverTask(gen, data, tw, th, self._EmitCoverDecoded))
        except Exception:
            # 线程池不可用：退回同步路径，功能不受影响
            self._OnCoverDecoded(gen, DecodeCoverImage(data, tw, th))

    def _EmitCoverDecoded(self, gen, img):
        """在工作线程里被调用：只发信号，不碰界面"""
        try:
            self.CoverDecoded.emit(gen, img)
        except Exception:
            pass

    def _OnCoverDecoded(self, gen, img):
        if gen != self._coverGen:
            return          # 期间又换了图，这帧作废
        if img is None or img.isNull():
            return
        try:
            pixmap = QPixmap.fromImage(img)
            radio = self.devicePixelRatio()
            pixmap.setDevicePixelRatio(radio)
            # 解码期间 label 可能被重排大了（栅格定宽/换页重排）：QLabel 是居中绘制不缩放，
            # 小图放进去就变成"封面比标题窄一圈"。这里**只比 label 与解码时用的目标尺寸**，
            # 不能比 pixmap 实际大小 —— 封面宽高比(≈0.67)本来就窄于 label(147x200≈0.735)，
            # 按实际大小判会永远"小一圈"，进而无限重解（真机 gen 涨到 274、pixmap 反而为空）。
            try:
                tw0, th0 = getattr(self, "_coverTarget", (0, 0))
                lw, lh = self.picLabel.width(), self.picLabel.height()
                if (self.picData and not self._coverRetry and tw0 >= 60
                        and (lw > tw0 * 1.12 or lh > th0 * 1.12)):
                    self._coverRetry = True
                    self.SetPicture(self.picData, lw, lh)
                    return
            except Exception:
                pass
            self._coverRetry = False
            # 不直接 setPixmap：一批封面同时到达时，逐个 setPixmap 会让列表在同一个
            # 事件循环里连续重绘一大片（实测空闲态 1.5s 内 15 次 >16.7ms 停顿，最大 35ms）。
            # 交给全局队列按 ~16ms 一批、每批 2 张铺上去，把大脏区摊成小脏区。
            _QueueCoverApply(self, pixmap)
        except Exception:
            pass

    # -- 图文对齐 ---------------------------------------------------------
    def _ContentWidth(self):
        """item 内部真正可用的宽度(去掉布局左右边距)"""
        try:
            m = self.verticalLayout_2.contentsMargins()
            base = self.width()
            # setFixedWidth 之后要到下一次布局才会反映到 width()，这中间用旧宽度算
            # 会把封面算宽 4px，sizeHint 反过来又超出栅格（真机表现为越排越窄）
            if self.minimumWidth() == self.maximumWidth() and self.maximumWidth() > 0:
                base = self.maximumWidth()
            return max(40, base - m.left() - m.right())
        except Exception:
            return max(40, self.width() - 12)

    def SyncContentWidth(self, notify=True):
        """让封面左右边界与下方文字块严格对齐

        真机上 item 的宽度由栅格固定(cellW)，常常比"封面+边距"更宽；而 picLabel
        是固定尺寸的，会被布局**居中**，文字却占满整行 —— 于是图片左右各缩进一截，
        就是"图片和下方文字对不齐"。这里统一按 item 的内容宽度重排：
        图片宽度 = 文字可用宽度 = 内容宽度。

        notify=False 由栅格排版(RefreshItemSizeHints)内部调用：那一趟已经在重排，
        再回头排一次会互相打架（曾经把 cell 越排越小、文字还压到下一项上）。
        """
        if self._syncGuard:
            return
        # 宽度还没被排版定下来(<60)时不要动：这时算出来的是临时值，
        # 一旦按它改小封面，栅格就会跟着缩小（真机表现为封面只有 96px 宽）
        if self.width() < 60:
            return
        width = self._ContentWidth()
        if self.isCategory:
            baseW, baseH = 300, 300
        else:
            baseW, baseH = ComicItemWidget.BaseCoverWidth, ComicItemWidget.BaseCoverHeight
        height = max(24, int(round(width * float(baseH) / float(baseW))))
        try:
            if (self.picLabel.width() == width and self.picLabel.height() == height
                    and self.nameLable.width() == width):
                return
        except Exception:
            return
        self._syncGuard = True
        try:
            self.picLabel.setFixedSize(width, height)
            # 文字块必须"钉成同一宽度"，只设 maximumWidth 不够：标签的 sizeHint 比它
            # 小时布局只给 sizeHint 那么宽（真机实测右边界差 4~20px）。name/category
            # 用固定宽度，其余小控件保持 maximumWidth 即可。
            self.nameLable.setFixedWidth(width)
            # 分类标签自身有缩进(在设计器里靠右)，钉死宽度会顶出控件，只给上限
            for lb in (self.categoryLabel, self.starButton, self.timeLabel):
                lb.setMaximumWidth(width)
            self.updateGeometry()
        except Exception:
            pass
        finally:
            self._syncGuard = False
        if self.picData:
            # 用刚算出来的 width/height，别读 picLabel.width()（还没生效）
            self.SetPicture(self.picData, width, height)
        if notify:
            self._RequestGridRefresh()

    def _RequestGridRefresh(self):
        """图片高度跟着宽度变了，让所在列表重新排一次(去抖)"""
        try:
            parent = self.parentWidget()
            view = None
            while parent is not None:
                if isinstance(parent, QListWidget):
                    view = parent
                    break
                parent = parent.parentWidget()
            if view is None:
                return
            from tools import mobile_ui
            mobile_ui.ScheduleGridCoverSize(view)
        except Exception:
            pass

    def resizeEvent(self, event):
        QWidget.resizeEvent(self, event)

    def SetWaifu2xData(self, data):
        pic = QPixmap()
        if not data:
            return
        self.isWaifu2x = True
        self.isWaifu2xLoading = False
        pic.loadFromData(data)
        radio = self.devicePixelRatio()
        pic.setDevicePixelRatio(radio)
        newPic = pic.scaled(self.picLabel.width()*radio, self.picLabel.height()*radio, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.picLabel.setPixmap(newPic)

    def SetPictureErr(self, status):
        self.picLabel.setText(Str.GetStr(status))

    @property
    def isSelect(self):
        return self.picLabel.isSelect

    def SetSelect(self, select):
        self.picLabel.SetSelect(select)

    def SwitchSelect(self):
        self.picLabel.SetSelect(not self.picLabel.isSelect)

    def paintEvent(self, event) -> None:
        if self.isShiled:
            return QWidget.paintEvent(self, event)
        if self.url and not self.isLoadPicture and config.IsLoadingPicture:
            self.isLoadPicture = True
            self.PicLoad.emit(self.index)
        return QWidget.paintEvent(self, event)