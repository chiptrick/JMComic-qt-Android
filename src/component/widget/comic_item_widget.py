from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap, QIcon, QFont, QFontMetrics, QImage
from PySide6.QtWidgets import QWidget

from config import config
from config.setting import Setting
from interface.ui_comic_item import Ui_ComicItem
from tools.str import Str


class ComicItemWidget(QWidget, Ui_ComicItem):
    PicLoad = Signal(int)
    # 桌面端封面基准尺寸(宽 x 高)，竖屏按比例换算
    BaseCoverWidth = 250
    BaseCoverHeight = 340

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

        icon2 = QIcon()
        icon2.addFile(u":/png/icon/new.svg", QSize(), QIcon.Normal, QIcon.Off)

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

        self.starButton.setIcon(QIcon(":/png/icon/icon_bookmark_on.png"))
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
            self.categoryLabel.setMaximumWidth(coverWidth - 20)
            self.starButton.setMaximumWidth(coverWidth - 20)
            self.timeLabel.setMaximumWidth(coverWidth - 20)
            self.nameLable.setMaximumWidth(coverWidth - 20)
            self.adjustSize()
            if self.picData:
                self.SetPicture(self.picData)
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

    def SetPicture(self, data):
        self.picData = data
        pic = QPixmap()
        if data:
            pic.loadFromData(data)
        self.isWaifu2x = False
        self.isWaifu2xLoading = False
        radio = self.devicePixelRatio()
        pic.setDevicePixelRatio(radio)
        newPic = pic.scaled(self.picLabel.width() * radio, self.picLabel.height() * radio, Qt.KeepAspectRatio,
                            Qt.SmoothTransformation)
        self.picLabel.setPixmap(newPic)

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