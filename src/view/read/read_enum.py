import math
from enum import Enum

from PySide6.QtCore import QSize, QPoint

from config import config
from config.setting import Setting
from tools.str import Str
from tools.tool import ToolUtil


class ReadMode(Enum):
    """ 阅读模式 """
    UpDown = 0  # 上下模式
    LeftRight = 1  # 默认
    LeftRightDouble = 2  # 左右双页
    RightLeftDouble = 3  # 右左双页
    LeftRightScroll = 4  # 左右滚动
    RightLeftScroll = 5  # 右左滚动
    RightLeftDouble2 = 6  # 右左双页(滚轮正序)
    Samewight = 7  # 等宽模式
    RightLeftScroll2 = 8  # 右左滚动(滚轮正序)

    @staticmethod
    def isDouble(model):
        return model in [ReadMode.LeftRightDouble, ReadMode.RightLeftDouble, ReadMode.RightLeftDouble2]

    @staticmethod
    def isRightLeft(model):
        return model in [ReadMode.RightLeftDouble, ReadMode.RightLeftDouble2, ReadMode.RightLeftScroll, ReadMode.RightLeftScroll2]

    @staticmethod
    def isUpDown(model):
        return model not in [ReadMode.LeftRightScroll, ReadMode.RightLeftDouble2, ReadMode.RightLeftScroll, ReadMode.RightLeftScroll2]

    @staticmethod
    def isScroll(model):
        return model in [ReadMode.UpDown, ReadMode.LeftRightScroll, ReadMode.RightLeftScroll, ReadMode.RightLeftScroll2]

    @staticmethod
    def isHorizontalPage(model):
        """ 横向翻页模式(单页/双页)：滑动翻页的手势轴是**横向**

        这几种模式的页面是左右排布的，用户自然是左右滑。注意不能用 isUpDown()
        判断：它把 LeftRight/LeftRightDouble/RightLeftDouble 也算成"纵向"
        (那是给滚轮留的旧语义，滚轮只有 angleDelta().y())，触摸手势照抄就会
        只认上下滑、左右滑被整条丢弃 —— 真机现象"左右/右左翻页怎么滑都不翻"。

        方向不用在这里区分左右：qtTool.NextPage()/LastPage() 内部已经为右左模式
        做了反转(RightLeftDouble: NextPage -> _LastPage)，横向位移统一按 -dx
        映射即可 —— LTR 左滑、RTL 右滑，都是"把下一张从它的方向拖进来"。
        """
        return model in [ReadMode.LeftRight, ReadMode.LeftRightDouble,
                         ReadMode.RightLeftDouble, ReadMode.RightLeftDouble2]

    @staticmethod
    def isHorizontalScroll(model):
        """ 横向滚动模式(左右滚动/右左滚动) """
        return model in [ReadMode.LeftRightScroll, ReadMode.RightLeftScroll, ReadMode.RightLeftScroll2]

    @staticmethod
    def isRightLeftScroll(model):
        """ 右左滚动(含滚轮正序)：页面从右往左排

        右左布局里**阅读前进 = 横向滚动条的值减小**(视口左移，新页从左边进来)，
        左右布局里则是值增大。所以凡是"下一屏/下一页"这种**语义量**都必须按这个
        方向换算(见 ForwardScrollDelta，被 ScrollValue/自动滚动使用)。

        手指拖动和滚轮**不用**在这里换算：它们是"内容跟手"的输入量，符号在
        ReadGraphicsView.wheelEvent / _ReaderTouch._Scroll 里按模式各自定
        (右左滚动基础版跟手即后退，只有"滚轮正序"版才把输入翻成页面正序)。
        """
        return model in [ReadMode.RightLeftScroll, ReadMode.RightLeftScroll2]

    @staticmethod
    def ForwardScrollDelta(model, value):
        """ 把"下一屏为正"的语义量换算成**横向**滚动条增量

        左右滚动：前进 = 值增大 -> 原样；
        右左滚动：前进 = 值减小 -> 取反。
        纵向模式(上下/等宽)没有这个问题，原样返回。
        """
        return -value if ReadMode.isRightLeftScroll(model) else value


class QtFileData(object):
    Downloading = Str.Downloading
    Converting = Str.Converting
    DownloadSuc = Str.DownloadSuc
    DownloadError = Str.DownloadError
    DownloadReset = Str.DownloadReset

    WaifuWait = Str.WaifuWait
    WaifuStateStart = Str.WaifuStateStart
    WaifuStateCancle = Str.WaifuStateCancle
    WaifuStateEnd = Str.WaifuStateEnd
    WaifuStateFail = Str.WaifuStateFail
    OverResolution = Str.OverResolution
    AnimationNotAuto = Str.AnimationNotAuto

    def __init__(self):
        self.size = 0
        self.w = 0
        self.h = 0
        self.mat = "jpg"
        self.scaleW = 0
        self.scaleH = 0
        self.state = self.Downloading
        self.data = None
        self._isWaifu2x = -1
        self.waifuState = self.WaifuStateCancle
        self.waifuDataSize = 0
        self.waifuData = None
        self.waifuTick = 0
        self.waifu2xTaskId = 0
        self.model = {}

        self.cacheImage = None
        self.cacheImageScale = ""
        self.cacheImageTaskId = 0
        self.cacheWaifu2xImage = None
        self.cacheWaifu2xImageScale = ""
        self.cacheWaifu2xImageTaskId = 0

        self.downloadSize = 0
        self.isGif = False
        self.saveParams = None

    @property
    def isWaifu2x(self):
        if self._isWaifu2x == -1:
            return Setting.IsOpenWaifu.value
        return self._isWaifu2x

    @isWaifu2x.setter
    def isWaifu2x(self, value):
        self._isWaifu2x = value

    @property
    def qSize(self):
        return QSize(self.w, self.h)

    @property
    def waifuQSize(self):
        return QSize(self.scaleW, self.scaleH)

    def SetData(self, data, category):
        if not data:
            self.state = self.DownloadError
            return

        self.w, self.h, self.mat, isAni = ToolUtil.GetPictureSize(data)

        if self.cacheImage:
            if Setting.IsOpenWaifu.value:
                self.waifuState = self.WaifuWait
            else:
                self.waifuState = self.WaifuStateCancle

            if max(self.w, self.h) <= Setting.LookMaxNum.value:
                pass
            else:
                if self._isWaifu2x == -1:
                    self.waifuState = self.OverResolution

            if self._isWaifu2x == -1 and isAni:
                self.waifuState = self.AnimationNotAuto

        self.isGif = isAni
        self.data = data
        self.model = ToolUtil.GetLookScaleModel(category, self.w, self.h, self.mat)
        self.state = self.DownloadSuc
        self.size = len(data)

    def SetWaifuData(self, data, tick):
        if not data:
            self.waifuState = self.WaifuStateFail
            return
        self.waifuData = data
        self.waifuState = self.WaifuStateEnd
        self.waifuDataSize = len(self.waifuData)
        self.scaleW, self.scaleH, _, _ = ToolUtil.GetPictureSize(data)
        self.waifuTick = tick
        return

    @staticmethod
    def GetReadScale(stripModel, scaleCnt, maxWidth, maxHeight, isToQImage):
        # 不进行缩放了，因为导致模糊
        if stripModel == ReadMode.LeftRight:
            scale = (1 + scaleCnt * 0.1)
            wight = int(maxWidth * scale)
            height = maxHeight * scale
            toScaleW = wight
            toScaleH = height
        elif stripModel in [ReadMode.RightLeftDouble, ReadMode.RightLeftDouble2]:
            scale = (1 + scaleCnt * 0.1)
            toScaleW =int(maxWidth // 2 * scale)
            toScaleH = maxHeight * scale

        elif stripModel in [ReadMode.LeftRightDouble]:
            scale = (1 + scaleCnt * 0.1)

            toScaleW = int(maxWidth // 2 * scale)
            toScaleH = maxHeight * scale
        elif stripModel in [ReadMode.LeftRightScroll]:
            scale = (1 + scaleCnt * 0.1)
            toScaleW = maxWidth * scale * 10
            toScaleH = min(maxHeight, maxHeight * scale)

        elif stripModel in [ReadMode.RightLeftScroll, ReadMode.RightLeftScroll2]:
            scale = (1 + scaleCnt * 0.1)
            toScaleW = maxWidth * scale * 10
            toScaleH = min(maxHeight, maxHeight * scale)

        elif stripModel in [ReadMode.UpDown]:
            scale = (1 + scaleCnt * 0.1)
            toScaleW = min(maxWidth, maxWidth * scale)
            toScaleH = maxHeight * scale * 10
        elif stripModel in [ReadMode.Samewight]:
            scale = (1 + scaleCnt * 0.1)
            toScaleW = maxWidth * scale
            toScaleH = maxHeight * scale * 10
        else:
            return maxWidth, maxHeight

        # if not ReadMode.isScroll(stripModel):
        if isToQImage:
            toScaleH = 0
            toScaleW = 0
        return toScaleW, toScaleH

    @staticmethod
    def GetReadToPos(stripModel, maxWidth, maxHeight, toWidth, toHeight, index, curIndex, oldPos):
        if stripModel in [ReadMode.LeftRight, ReadMode.Samewight]:
            return QPoint(maxWidth // 2 - toWidth // 2, max(0, maxHeight // 2 - toHeight // 2))
        elif stripModel in [ReadMode.RightLeftDouble, ReadMode.RightLeftDouble2]:
            if index == curIndex:
                return QPoint(math.trunc((maxWidth-2) / 2), max(0, maxHeight / 2 - toHeight / 2))
            else:
                return QPoint(math.ceil(maxWidth / 2 - toWidth), max(0, maxHeight // 2 - toHeight // 2))
        elif stripModel in [ReadMode.LeftRightDouble]:
            if index != curIndex:
                return QPoint(math.trunc((maxWidth-2) / 2), max(0, maxHeight // 2 - toHeight // 2))
            else:
                return QPoint(math.ceil(maxWidth / 2 - toWidth), max(0, maxHeight // 2 - toHeight // 2))
        elif stripModel in [ReadMode.LeftRightScroll]:
            return QPoint(oldPos.x(), max(0, maxHeight // 2 - toHeight // 2))

        elif stripModel in [ReadMode.RightLeftScroll, ReadMode.RightLeftScroll2]:
            return QPoint(oldPos.x(), max(0, maxHeight // 2 - toHeight // 2))

        elif stripModel in [ReadMode.UpDown]:
            return QPoint(maxWidth // 2 - toWidth // 2, oldPos.y())
        else:
            return QPoint(0, 0)