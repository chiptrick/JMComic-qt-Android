import weakref

from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QAbstractAnimation, Qt
from PySide6.QtWidgets import QScrollBar

from qt_owner import QtOwner
from tools.str import Str
from view.read.read_enum import ReadMode


class ReadScroll(QScrollBar):
    def __init__(self, parent):
        QScrollBar.__init__(self)
        self._owner = weakref.ref(parent)
        self.scrollTime = 200
        self.maxScrollTme = 500
        self.maxRate = 10

        self.ani = QPropertyAnimation()
        self.ani.setTargetObject(self)
        self.ani.setPropertyName(b"value")
        self.ani.setEasingCurve(QEasingCurve.Linear)
        self.ani.setDuration(self.scrollTime)
        self.__value = self.value()
        self.ani.finished.connect(self.Finished)
        self.setSingleStep(1)
        # self.oldupdateCurrentValue = self.ani.updateCurrentValue
        # self.ani.updateCurrentValue = self.UpdateCurrentValue
        # self.ani.valueChanged.connect(self.AniValueChange)
        self.priV = 0

        self.lastAniStartV = 0
        self.lastAniEndV = 0
        self.lastScrollTime = 0
        # self.valueChanged.connect(self.ValueChange)
        self.oldv = 0
        self.changeState = False

        self.lastSubV = 0
        self.lastIndex = 0

    @property
    def stripModel(self):
        return self._owner().qtTool.stripModel

    @property
    def isCurReadModel(self):
        if self.orientation() == Qt.Orientation.Vertical:
            return self.stripModel == ReadMode.UpDown
        else:
            return True

    #
    # def ValueChange(self,value):
    #     # self.oldv = value
    #     print("2, {}".format(value))
    #
    # def AniValueChange(self, value):
    #     print("1, {}".format(value))

    #
    # def UpdateCurrentValue(self, value):
    #     print("2, {}".format(value))
    #     self.oldupdateCurrentValue(value)

    def ResetAniValueByAdd(self, oldV, addV):
        QScrollBar.setValue(self, oldV + addV)
        changeV = self.lastAniEndV - self.lastAniStartV
        laveV = self.lastAniEndV - oldV
        scrollTime = 0
        if changeV != 0:
            scrollTime = min(self.maxScrollTme, int(laveV / changeV * self.lastScrollTime))
        if scrollTime > 0:
            self.ani.stop()
            # print("ani stop 5")
            self.StartAni(self.value(), self.lastAniEndV, scrollTime)
        else:
            self.ani.stop()
            # print("ani stop 6")
            self.StartAni(self.value(), self.value(), self.scrollTime)

    def AniValueByAdd(self, addV):
        changeV = self.lastAniEndV - self.lastAniStartV
        addV2 = self.lastAniEndV - self.value()
        self.lastAniStartV = self.value()
        if addV <= 0:
            v = max(self.maxRate * addV, addV + addV2)
        else:
            v = min(self.maxRate * addV, addV + addV2)
        self.lastAniEndV = self.lastAniStartV + v
        laveV = self.lastAniEndV - self.lastAniStartV

        scrollTime = self.scrollTime
        # if changeV != 0:
        #     scrollTime = min(self.maxScrollTme, int(laveV / changeV * self.lastScrollTime))
        # if scrollTime <= 0:
        #     scrollTime = self.scrollTime

        # print("add setV, {}, {}, {}".format(scrollTime,self.value(), self.lastAniEndV))
        self.ani.stop()
        # print("ani stop 1")
        self.StartAni(self.value(), self.lastAniEndV, scrollTime)

    # def AniValueChange(self, value):
    #     print("{}, {}".format(value, value - self.priV))
    #     self.priV = value

    @property
    def frame(self):
        return self._owner()

    @property
    def scrollArea(self):
        return self._owner().scrollArea

    @property
    def labelSize(self):
        return self.scrollArea.labelSize

    @property
    def readImg(self):
        return self.scrollArea.readImg

    def Finished(self):
        self.OnValueChange(self.value())

    def StopScroll(self):
        self.ani.stop()
        # print("ani stop 2")

    #
    # def Scroll(self, value, time=0):
    #     if self.ani.state() == QAbstractAnimation.State.Running:
    #         self.ani.stop()
    #     oldValue = self.value()
    #     self.ani.setStartValue(oldValue)
    #     if not time:
    #         self.ani.setDuration(self.scrollTime)
    #     else:
    #         self.ani.setDuration(time)
    #     self.ani.setEndValue(oldValue + value)
    #     self.ani.start()

    def ForceSetValue(self, value):
        self.ani.stop()
        # print("ani stop 3")
        QScrollBar.setValue(self, value)
        self.StartAni(value, value, self.scrollTime)

    def DragScroll(self, value: int, notify=True):
        """ 触摸拖动专用：**1:1 跟手**，不套补间动画

        为什么不能走 setValue 的 200ms 缓动(桌面滚轮/键盘半页/自动滚动用那条，
        那是"按一下滚一段"，缓动是刻意的)：
          * 拖动时每个 TouchUpdate 都调一次，动画永远追不上手指 —— 实测 600px/s
            的拖动，滚动条恒定落后十几像素；
          * `AniValueByAdd` 会把目标按 maxRate(10) 放大，抬手后还要再跑 200ms，
            并**冲过手指位置一百多像素**(一次 600px 的滑动过冲 ~18%)，真机现象
            就是"拖完图还在飘、滑过头"；
          * 安卓会把一帧里的多条触摸事件合并投递(dt≈0)，目标会被连续放大好几倍，
            过冲更夸张。

        notify=False 用于"放大后平移"：只改位置，不结算换页(放大状态下翻页是
        另一套逻辑，平移绝不该顺带换页)。
        """
        self.ani.stop()
        target = max(self.minimum(), min(self.maximum(), self.value() + int(value)))
        if target == self.value():
            return
        # 直接置值：QGraphicsView 跟着 valueChanged 立刻重绘，零延迟
        QScrollBar.setValue(self, target)
        if notify:
            # 动画路径靠 finished 触发 OnValueChange(滚动模式靠它结算跨到哪一页)
            self.OnValueChange(target)
        return

    # def ForceSetValue2(self, value, isAdd):
    #     if value == self.value():
    #         if isAdd and self.stripModel != ReadMode.RightLeftScroll:
    #             self.__value = self.__value + 1
    #         else:
    #             self.__value = self.__value - 1

    #     self.ani.stop()
    #     # print("ani stop 3")
    #     print("force setV2, {}".format(value))
    #     QScrollBar.setValue(self, value)
    #     self.StartAni(value, value, self.scrollTime)

    def StartAni(self, start, end, duration):
        self.lastAniEndV = end
        self.lastAniStartV = start
        self.lastScrollTime = duration
        self.ani.setStartValue(start)
        self.ani.setEndValue(end)
        self.ani.setDuration(duration)
        self.ani.start()

    def setValue(self, value: int):
        if value == self.value():
            return

        # 双指缩放预览期间直接定位，不要动画：
        # 预览每帧都会让 QGraphicsView 重新算滚动条范围/值，200ms 的补间动画
        # 会被下一帧反复打断，位置乱跳(手感就是"抖")
        if getattr(self.scrollArea, "_jmPinchPreview", False):
            self.ani.stop()
            QScrollBar.setValue(self, value)
            return

        # stop running animation
        if self.ani.state() == self.ani.State.Running:
            self.AniValueByAdd(value - self.value())
            # print("ani stop 1")
            # self.StartAni(self.value(), value, self.scrollTime)
        else:
            self.ani.stop()
            # print("ani stop 4")
            self.StartAni(self.value(), value, self.scrollTime)

    def scrollValue(self, value: int):
        """ scroll the specified distance """
        # self.__value += value
        # self.__value = max(self.minimum(), self.__value)
        # self.__value = min(self.maximum(), self.__value)
        self.setValue(self.value() + value)

    # def scrollTo(self, value: int):
    #     """ scroll to the specified position """
    #     self.__value = value
    #     self.__value = max(self.minimum(), self.__value)
    #     self.__value = min(self.maximum(), self.__value)
    #     self.setValue(self.__value)

    # def SetChangeState(self, state):
    #     self.changeState = state

    # value变化后，重新定位位置信息
    def SaveLastPosition(self):
        if not self.isCurReadModel:
            return

        if not ReadMode.isScroll(self.stripModel):
            return

        oldV = self.value()
        oldMinV = max(1, self.labelSize.get(self.readImg.curIndex, 0))
        if self.stripModel in [ReadMode.RightLeftScroll, ReadMode.RightLeftScroll2]:
            nextV = max(1, self.labelSize.get(self.readImg.curIndex - 1, 0))
            height = nextV - oldMinV
        else:
            nextV = max(1, self.labelSize.get(self.readImg.curIndex + 1, 0))
            height = nextV - oldMinV
        if height != 0:
            subV = (oldV - oldMinV) / height
        else:
            subV = 0

        self.lastSubV = subV
        self.changeState = True
        return

    def SaveLastPositionEnd(self):
        if not self.isCurReadModel:
            return

        if not ReadMode.isScroll(self.stripModel):
            return

        oldV = self.value()
        oldMinV = max(1, self.labelSize.get(self.readImg.curIndex, 0))
        if self.stripModel in [ReadMode.RightLeftScroll, ReadMode.RightLeftScroll2]:
            nextV = max(1, self.labelSize.get(self.readImg.curIndex - 1, 0))
            height = nextV - oldMinV
            newV = int(oldMinV + height * self.lastSubV)
        else:
            nextV = max(1, self.labelSize.get(self.readImg.curIndex + 1, 0))
            height = nextV - oldMinV
            newV = int(oldMinV + height * self.lastSubV)

        self.lastIndex = self.readImg.curIndex

        if oldV == newV:
            self.__value = newV
            self.lastSubV = 0
            self.changeState = False
            return
        self.ani.stop()
        QScrollBar.setValue(self, newV)
        self.__value = newV
        self.lastSubV = 0
        self.changeState = False
        return

    def OnValueChange(self, value):
        if self.changeState:
            return
        addValue = value - self.__value
        # self.UpdateScrollBar(value)
        self.__value = value

        # 双指缩放预览期间不做"滚动换页"：预览只是视图变换，滚动值的变化是
        # QGraphicsView 自己按场景矩形算出来的；这时候换页会触发 ReloadImg
        # (整页重排 + 重新解码)，手指还在屏幕上，滚动模式下手感直接崩掉。
        if getattr(self.scrollArea, "_jmPinchPreview", False):
            return

        if not self.isCurReadModel:
            return
        if not ReadMode.isScroll(self.scrollArea.initReadMode):
            return

        changeIndex = self.readImg.curIndex
        if self.scrollArea.initReadMode in [ReadMode.RightLeftScroll, ReadMode.RightLeftScroll2]:
            newValue = value + self.scrollArea.width()
            curPictureSize = self.labelSize.get(self.readImg.curIndex)
            nextPictureSize = self.labelSize.get(self.readImg.curIndex - 1, 0)
            while True:
                ## 切换上一图片
                if addValue > 0 and newValue >= nextPictureSize:
                    if changeIndex <= 0:
                        break
                    changeIndex -= 1
                    # print(self.readImg.curIndex)

                    # self.scrollArea.changeLastPage.emit(self.readImg.curIndex)

                ## 切换下一图片
                elif addValue < 0 and newValue < curPictureSize:
                    if changeIndex >= self.readImg.maxPic - 1:
                        break
                    changeIndex += 1
                    # print(self.readImg.curIndex)
                    # self.scrollArea.changeNextPage.emit(self.readImg.curIndex)
                else:
                    break
                curPictureSize = self.labelSize.get(changeIndex)
                nextPictureSize = self.labelSize.get(changeIndex - 1, 0)
        else:
            curPictureSize = self.labelSize.get(self.readImg.curIndex)
            nextPictureSize = self.labelSize.get(self.readImg.curIndex + 1, 0)
            while True:
                ## 切换上一图片
                if addValue < 0 and value < curPictureSize:
                    if changeIndex <= 0:
                        break
                    changeIndex -= 1
                    # print("last page, addv:{}, val:{}, cur:{}, next:{}".format(addValue, value, curPictureSize, nextPictureSize))
                    # self.scrollArea.changeLastPage.emit(self.readImg.curIndex)

                ## 切换下一图片
                elif addValue > 0 and value >= nextPictureSize:
                    if changeIndex >= self.readImg.maxPic - 1:
                        break
                    changeIndex += 1
                    # print("next page, addv:{}, val:{}, cur:{}, next:{}".format(addValue, value, curPictureSize, nextPictureSize))
                    # self.scrollArea.changeNextPage.emit(self.readImg.curIndex)
                else:
                    break
                curPictureSize = self.labelSize.get(changeIndex)
                nextPictureSize = self.labelSize.get(changeIndex + 1, 0)

        if self.readImg.curIndex == changeIndex:
            return
        elif self.readImg.curIndex > changeIndex:
            self.lastIndex = self.readImg.curIndex
            self.readImg.curIndex = changeIndex
            self.scrollArea.changeLastPage.emit(self.readImg.curIndex)
        elif self.readImg.curIndex < changeIndex:
            self.lastIndex = self.readImg.curIndex
            self.readImg.curIndex = changeIndex
            self.scrollArea.changeNextPage.emit(self.readImg.curIndex)
        return