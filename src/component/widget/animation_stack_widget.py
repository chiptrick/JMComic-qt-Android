from enum import Enum

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QPropertyAnimation,
                            QRect, QTimer, Property, Qt, Signal)
from PySide6.QtGui import QColor, QImage, QPaintEvent, QPainter, QPixmap
from PySide6.QtWidgets import QStackedWidget, QWidget

# GPU 合成层（QRhiWidget + Vulkan + 预编译 .qsb）。
# 历史坑：曾用 QOpenGLWidget，与 Vulkan 合成互斥（Qt 直接拒绝，context 恒 None），
# 已改为 QRhiWidget；.qsb 由 pyside6-qsb 烘焙，见 component/widget/shaders/。
UseGpuCover = True
# 8ms 精确定时器驱动。Qt 自带动画驱动固定 16ms，实测封顶 ~62fps。
UseTimerDriver = True


class AnimationEnum(Enum):
    LeftToRight = 1
    RightToLeft = 2
    Top = 3


class _TimerDriver(QObject):
    """精确定时器驱动的动画，接口对齐 QPropertyAnimation(start/stop/state/...)

    为什么不用 QPropertyAnimation：Qt 的动画驱动统一按 16ms 打点，实测封顶 62.8fps，
    再好的绘制也到不了 60fps 以上。这里自己按 IntervalMs 打点，间隔越短接缝越窄、
    每帧越便宜（正反馈），但打点太密会被主线程绘制排队反噬，实测 6ms 最优。
    """

    IntervalMs = 6

    def __init__(self, duration, on_value, on_finished, parent=None):
        super().__init__(parent)
        self._duration = max(1, int(duration))
        self._on_value = on_value
        self._on_finished = on_finished
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(max(1, int(self.IntervalMs)))
        self._timer.timeout.connect(self._Tick)
        self._start = 0
        self._end = 0
        self._elapsed = 0.0
        self._last = 0.0
        self._running = False
        self._easing = QEasingCurve(QEasingCurve.Type.OutCubic)

    def setDuration(self, ms):
        self._duration = max(1, int(ms))

    def setEasingCurve(self, curve):
        self._easing = QEasingCurve(curve)

    def setStartValue(self, value):
        self._start = value

    def setEndValue(self, value):
        self._end = value

    def state(self):
        return QPropertyAnimation.State.Running if self._running \
            else QPropertyAnimation.State.Stopped

    def start(self):
        import time
        self._running = True
        self._elapsed = 0.0
        self._last = time.perf_counter()
        self._on_value(self._start)
        self._timer.start()

    def stop(self):
        self._running = False
        self._timer.stop()

    def _Tick(self):
        import time
        now = time.perf_counter()
        self._elapsed += (now - self._last) * 1000.0
        self._last = now
        progress = min(1.0, self._elapsed / float(self._duration))
        value = self._start + (self._end - self._start) * self._easing.valueForProgress(progress)
        self._on_value(int(round(value)))
        if progress >= 1.0:
            self._running = False
            self._timer.stop()
            if self._on_finished:
                self._on_finished()


class _AnimCover(QWidget):
    """raster 覆盖层（GPU 不可用时的退路）：只画两张快照，按揭示进度刷窄带

    为什么不直接让 QStackedWidget 画：那样必须先 hide() 当前页，而 hide() 会触发
    一次整页重绘，等于动画一开始就付两遍整页的代价。
    """

    def __init__(self, stack):
        super().__init__(stack)
        self._stack = stack
        self._prev = None
        self._next = None
        self._reveal = 0
        self._type = AnimationEnum.LeftToRight
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()
        self.PaintCount = 0
        self.PaintArea = 0
        self.PaintMs = 0.0

    def Begin(self, prev, next_, type_):
        self._prev = prev
        self._next = next_
        self._type = type_
        self._reveal = 0
        self.setGeometry(self._stack.rect())
        self.show()
        self.raise_()
        self.repaint()

    def End(self):
        self.hide()
        self._prev = None
        self._next = None
        self._reveal = 0

    def SetReveal(self, value):
        old = self._reveal
        self._reveal = int(value)
        if self._prev is None:
            return
        band = self._BandRect(old, value)
        if band.isValid() and not band.isEmpty():
            self.update(band)

    def _Rect(self, value):
        w = self.width()
        h = self.height()
        v = max(0, min(int(value), max(0, w)))
        if v <= 0:
            return QRect(0, 0, 0, 0)
        if self._type == AnimationEnum.LeftToRight:
            return QRect(w - v, 0, v, h)
        return QRect(0, 0, v, h)

    def _BandRect(self, old, new):
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return QRect()
        o = max(0, min(int(old), w))
        n = max(0, min(int(new), w))
        if n == o:
            return QRect()
        lo, hi = (o, n) if o < n else (n, o)
        if self._type == AnimationEnum.LeftToRight:
            return QRect(w - hi, 0, hi - lo, h)
        return QRect(lo, 0, hi - lo, h)

    def paintEvent(self, event: QPaintEvent) -> None:
        if self._prev is None or self._next is None:
            # 没有快照（Begin 之前/End 之后，或快照渲染失败）。本类带
            # WA_OpaquePaintEvent，Qt 不会替我们填背景，直接 return 会留一块
            # "未绘制"区域（真机上就是黑块）。这里显式填窗口背景色兜底。
            try:
                paint = QPainter(self)
                paint.fillRect(event.rect(), self._stack._BackgroundColor())
            except Exception:
                pass
            return
        import time as _t
        t0 = _t.perf_counter()
        r = event.rect()
        self.PaintCount += 1
        self.PaintArea += max(0, r.width()) * max(0, r.height())
        reveal = self._Rect(self._reveal)
        paint = QPainter(self)
        # 脏区若整块落在"已揭示"区域内，新页会把它整块盖掉 —— 这时再画一遍旧页
        # 等于每帧多付一次同样面积的 blit。实测能省掉约一半 paintEvent 时间。
        if reveal.isEmpty() or not reveal.contains(r):
            paint.drawPixmap(0, 0, self._prev)
        if not reveal.isEmpty():
            paint.setClipRect(reveal)
            paint.drawPixmap(0, 0, self._next)
            paint.setClipping(False)
        self.PaintMs += (_t.perf_counter() - t0) * 1000.0
        return


class _FirstPaintWatcher(QObject):
    """等某个控件画出第一帧后回调（带超时兜底）

    为什么需要它：`Finished()` 里 `widget.show()` 之后，Qt 要等到下一轮事件循环
    才会真正 paint。这段时间如果已经把覆盖层撤掉，屏幕上就是**新页背景色**
    （实测每次切换有 100~150ms "只剩底色"）。覆盖层显示的是新页快照，形状内容
    都对，等它真正画出来再撤，用户完全看不出中间这一段。
    """

    def __init__(self, widget, on_first, timeoutMs=500):
        super().__init__(widget)
        self._widget = widget
        self._on_first = on_first
        self._done = False
        try:
            widget.installEventFilter(self)
        except Exception:
            pass
        QTimer.singleShot(timeoutMs, self._Fire)

    def eventFilter(self, obj, event):
        if not self._done:
            try:
                if event.type() == QEvent.Type.Paint:
                    self._Fire()
            except Exception:
                pass
        return False

    def _Fire(self):
        if self._done:
            return
        self._done = True
        try:
            self._widget.removeEventFilter(self)
        except Exception:
            pass
        try:
            if self._on_first is not None:
                self._on_first()
        except Exception:
            pass


class AnimationStackWidget(QStackedWidget):
    """换页动画：两页快照 + GPU 纹理位移（不可用时退回 raster 窄带）

    真机（1440x3168 / DPR 3.75 / 120Hz）三步演进：
      * 原实现：每帧两页各「新建 QPixmap + render 整棵树 + 平滑缩放 blit」，
        6.7~14fps；高 DPR 下还因漏设 devicePixelRatio 被放大 3.75 倍裁切
      * 快照 + 窄带：每帧只刷一条竖带，39~44fps（Qt 动画驱动 16ms 封顶 ~62fps）
      * 本版：QRhiWidget(Vulkan) 承载两张纹理 + 6ms 定时器驱动，
        每帧只剩两次全屏四边形 + 视口位移，CPU 侧 ~0.1ms；实测 115~123fps
        （QOpenGLWidget 与 Vulkan 合成本质互斥，已弃用，见 gpu_anim_cover.py）
    """

    AnimationMs = 250
    # 缓动曲线：换页每帧的代价 ≈ 接缝宽度 × 高度（脏区面积）。
    # 实测（V2463A，6ms 驱动，同一对页面反复跑）：
    #   OutCubic  74~80fps（起步是均速 3 倍，头几帧接缝 150+ 逻辑px，单帧 15~18ms）
    #   OutQuad   75~98fps（峰值 2 倍均速，仍有 40ms 级尖峰）
    #   Linear   111.5fps（接缝全程 12~19 逻辑px，paint 1.5ms，p50 7.8ms）
    # 250ms 的滑动里两者观感差异很小，优先要帧率 → 用 Linear。
    # 想要"减速收尾"的观感，把它改成 QEasingCurve.Type.OutQuad 即可（掉到 75~98fps）。
    Easing = QEasingCurve.Type.Linear
    # 每页快照缓存：页面没变更时复用，省掉一次整页 render
    CacheEnabled = True
    # 每帧进度(诊断用：换页动画的 tick 节奏)
    FrameTick = Signal(int)

    def __init__(self, parent=None):
        QStackedWidget.__init__(self, parent)
        self._value = 0
        self.animation = QPropertyAnimation(self, b"value")
        self.animation.valueChanged.connect(self.ValueChanged)
        self.animation.finished.connect(self.Finished)
        self.currentValue = 0
        self.nextIndex = 0
        self.subStackList = [0]
        self.animationType = AnimationEnum.LeftToRight
        self.switchArg = {}
        self._driver = None
        self._cache = {}
        self._rasterCover = _AnimCover(self)
        self._gpuCover = None
        self._gpuOk = False
        self._lastSnapshots = None
        self._gpuSoftFails = 0
        self._leavingPage = None
        if UseGpuCover:
            try:
                from component.widget.gpu_anim_cover import CreateGpuCover
                self._gpuCover = CreateGpuCover(self)
                self._gpuOk = self._gpuCover is not None
                if self._gpuCover is not None:
                    # GPU 初始化/渲染中途失败时回调：同一对快照切回 raster，动画不断
                    self._gpuCover.BrokenHook = self._OnGpuBroken
                    # 首帧画出来之前不能藏旧页（藏了就是黑屏），见 _OnCoverFirstFrame
                    self._gpuCover.FirstFrame.connect(self._OnCoverFirstFrame)
            except Exception as es:
                self._gpuCover = None
                self._gpuOk = False
                try:
                    from tools.log import Log
                    Log.Error("gpu cover init failed: {!r}".format(es))
                except Exception:
                    pass

    def _OnGpuBroken(self, hard=True):
        """GPU 覆盖层出问题：下一轮事件循环切回 raster，动画不中断

        hard=True  —— 资源/管线建不起来（或渲染抛异常），之后永久退回 raster
        hard=False —— 本次 120ms 内没画出来（启动早期窗口还没合成，属正常抖动），
                      只放弃这一次；连续 3 次才彻底放弃，避免反复白试

        不能在 render()/paintEvent 的调用栈里直接操作另一个控件（会重入绘制），
        所以这里只打标记 + singleShot(0)。
        """
        if hard:
            self._gpuOk = False
            self._gpuSoftFails = 0
        else:
            self._gpuSoftFails = getattr(self, "_gpuSoftFails", 0) + 1
            if self._gpuSoftFails >= 3:
                self._gpuOk = False
        QTimer.singleShot(0, self._FallbackToRaster)

    def _FallbackToRaster(self):
        try:
            cover = self._gpuCover
            if cover is not None:
                cover.End()
        except Exception:
            pass
        snapshots = getattr(self, "_lastSnapshots", None)
        if not snapshots:
            return
        prev, next_ = snapshots
        try:
            self._rasterCover.Begin(prev, next_, self.animationType)
            self._rasterCover.SetReveal(self.currentValue)
            # raster 已经有内容了，这时才把旧页藏起来
            self._HideLeavingPage()
        except Exception as es:
            try:
                from tools.log import Log
                Log.Error("fallback to raster failed: {!r}".format(es))
            except Exception:
                pass

    def _OnCoverFirstFrame(self):
        """GPU 覆盖层画出第一帧了：现在藏旧页是安全的（旧页已被覆盖层盖住）

        为什么必须等这一下：GPU 首帧要建管线 + 上传两张整页纹理（实测 +37ms），
        在这之前藏旧页，屏幕上就是一块黑（实测 4 帧 ≈ 23ms 全黑，用户看到"闪一下"）。
        """
        page = self._leavingPage
        if page is None:
            return
        # emit 发生在 render() 的调用栈里，这里只排队，不在绘制栈里动别的控件。
        # 必须把"要藏的那一页"绑进闭包：排队期间可能又切了一次页，读 _leavingPage
        # 会拿到新页面，把用户正看的那页藏掉（页面栈对不上，返回键也会错乱）。
        # repaint=False：覆盖层是独立的 GPU layer，不需要（也不应该）用同步重绘去
        # "补"stack 的 backing store —— 那反而会让合成器把一帧不含覆盖层的画面推上屏。
        QTimer.singleShot(0, lambda p=page: self._HideLeavingPage(page=p, repaint=False))

    def _HideLeavingPage(self, page=None, repaint=True):
        """隐藏离开的页面（覆盖层已经画好内容之后才调）"""
        if page is None:
            page = self._leavingPage
        elif page is not self._leavingPage:
            # 已经换过一轮了，这一页不再是被覆盖层盖住的那页，别动它
            return
        self._leavingPage = None
        if page is None:
            return
        try:
            page.hide()
        except Exception:
            pass
        if repaint:
            # hide() 会把"页面消失后的整窗重绘"排进事件循环。这里同步补一次，
            # 动画从干净状态起跑（此时覆盖层有内容，补的是覆盖层自己那块）。
            try:
                self.repaint()
            except Exception:
                pass

    def _LandOnTarget(self):
        """立刻落位到目标页（供 resize 等"必须马上结束动画"的场景用）

        顺序必须是"先把目标页**画出来**、再撤覆盖层"：只 show() 不 repaint 的话，
        Qt 要等下一轮事件循环才绘制，而覆盖层已经撤了 —— 那一两帧就是整块黑。
        """
        if getattr(self, "_landing", False):
            return
        self._landing = True
        try:
            page = self.widget(self.nextIndex)
            try:
                self.setCurrentIndex(self.nextIndex)
            except Exception:
                pass
            if page is not None:
                try:
                    page.show()
                except Exception:
                    pass
                try:
                    page.repaint()          # 同步画出新页，别等下一轮
                except Exception:
                    pass
            self._StopAnimation()
            self._leavingPage = None
        finally:
            self._landing = False

    def _ActiveCover(self):
        if self._gpuOk and self._gpuCover is not None:
            return self._gpuCover
        return self._rasterCover

    @property
    def cover(self):
        """当前生效的覆盖层（GPU 或 raster），供诊断/测试读取"""
        return self._ActiveCover()

    # -- 快照缓存 ---------------------------------------------------------
    def InvalidatePage(self, widget=None):
        """页面内容变了就调这里（切页后/刷新后），下次重新拍快照"""
        try:
            if widget is None:
                self._cache.clear()
            else:
                self._cache.pop(id(widget), None)
        except Exception:
            pass

    def _CachedSnapshot(self, widget):
        if not self.CacheEnabled or widget is None:
            return None
        entry = self._cache.get(id(widget))
        if not entry:
            return None
        pixmap, size = entry
        try:
            if pixmap is None or pixmap.isNull() or size != widget.size():
                return None
        except Exception:
            return None
        return pixmap

    def _RenderPage(self, widget, useCache=False):
        """把一页渲染成 DPR 正确的快照（可选缓存）"""
        if widget is None:
            return None
        if useCache:
            cached = self._CachedSnapshot(widget)
            if cached is not None:
                return cached
        try:
            # 隐藏页没有被 QStackedLayout 调整过几何：它可能还停在 880x805 之类的
            # 设计尺寸上（实测 SettingView 就是），而 stack 只有 372x716。按它自己的
            # 尺寸拍快照，再裁到 stack 区域 → 裁出来是"另一个布局的左上角"，
            # 动画里就是一张错位/空白的图（用户看到"动画不见了、只闪一下"）。
            # 拍之前先把目标页对到 stack 的尺寸上。
            try:
                if widget.width() != self.width() or widget.height() != self.height():
                    widget.resize(self.width(), self.height())
            except Exception:
                pass
            if widget.width() < 2 or widget.height() < 2:
                return None
            dpr = self.devicePixelRatio()
            pixmap = QPixmap(widget.size() * dpr)
            pixmap.setDevicePixelRatio(dpr)
            # 关键：页面容器是 WA_TranslucentBackground（见 component/widget/main_widget.py），
            # 页面本身不一定铺满不透明背景（登录弹层这类就是半透明的）。直接 render 到
            # 未初始化的 QPixmap 上，透明区域保留的是"未初始化内存"，实测呈**纯黑** ——
            # 于是换页动画整段都在放一张黑图，用户看到的就是"切页黑屏"。
            # 先填成窗口背景色，透明部分就还原成"页面在屏幕上本该显示的样子"。
            try:
                pixmap.fill(self._BackgroundColor())
            except Exception:
                pixmap.fill(Qt.GlobalColor.black)
            # 目标页**第一次**被拍快照时往往还没显示过：QStackedLayout 给了它
            # geometry，但内部布局没激活（QLayout::activate() 只在 show/resize 时跑），
            # 子控件位置还是默认值 —— 这时 render() 画出来是一张**纯底色**，
            # 动画就成了"旧页 → 一张空图 → 新页"，也就是用户说的"动画不见了"。
            # 先把样式和布局落到当前尺寸，再渲染。
            self._PrepareForRender(widget)
            try:
                widget.render(pixmap)
            finally:
                self._FinishRender(widget)
            if self.CacheEnabled and useCache:
                self._cache[id(widget)] = (pixmap, widget.size())
            return pixmap
        except Exception:
            return None

    @staticmethod
    def _PrepareForRender(widget):
        """让隐藏页尽量渲染出完整内容（样式 + 布局落到实际尺寸）

        注意：**不要**用 `WA_DontShowOnScreen` + show() 那套让它"逻辑显示"。
        栈上同时出现两个可见页会让 QStackedLayout 的状态打架，实测切页瞬间整块空白。
        这里只做安全的两步：polish + 把各层布局按当前尺寸算完。
        """
        try:
            widget.ensurePolished()
        except Exception:
            pass
        try:
            lay = widget.layout()
            if lay is not None:
                lay.activate()
        except Exception:
            pass
        try:
            from PySide6.QtWidgets import QGroupBox, QScrollArea, QTabWidget
            for child in widget.findChildren(QGroupBox):
                lay = child.layout()
                if lay is not None:
                    lay.activate()
            for area in widget.findChildren(QScrollArea):
                inner = area.widget()
                if inner is not None:
                    lay = inner.layout()
                    if lay is not None:
                        lay.activate()
            for tabs in widget.findChildren(QTabWidget):
                cur = tabs.currentWidget()
                lay = cur.layout() if cur is not None else None
                if lay is not None:
                    lay.activate()
        except Exception:
            pass

    @staticmethod
    def _FinishRender(widget):
        """成对占位（_PrepareForRender 不再改可见性，这里无需恢复）"""
        return

    def _BackgroundColor(self):
        """页面背后应有的底色（主容器是半透明的，快照必须自己铺底）"""
        try:
            color = self.palette().window().color()
            if color.isValid():
                return color
        except Exception:
            pass
        try:
            from PySide6.QtWidgets import QApplication
            return QApplication.palette().window().color()
        except Exception:
            pass
        return QColor(0, 0, 0)

    # -- 动画值 -----------------------------------------------------------
    @Property(int)
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        self._value = value

    def ValueChanged(self, value):
        self.currentValue = value
        try:
            self.FrameTick.emit(int(value))
        except Exception:
            pass
        try:
            self._ActiveCover().SetReveal(value)
        except Exception:
            pass
        return

    def _Driver(self):
        if UseTimerDriver:
            if self._driver is None:
                self._driver = _TimerDriver(self.AnimationMs, self.ValueChanged,
                                            self.Finished, self)
            return self._driver
        return self.animation

    # -- 流程 -------------------------------------------------------------
    def _StopAnimation(self):
        # 取消上一轮"等首帧撤覆盖层"的观察器：它挂着的是旧页，回调时会把
        # 新一轮动画的覆盖层误撤（画面直接跳一下）。
        try:
            watcher = getattr(self, "_paintWatcher", None)
            if watcher is not None:
                watcher._done = True
                watcher._on_first = None
                self._paintWatcher = None
        except Exception:
            pass
        try:
            driver = self._Driver()
            if driver.state() == QPropertyAnimation.State.Running:
                driver.stop()
        except Exception:
            pass
        for cover in (self._gpuCover, self._rasterCover):
            try:
                if cover is not None:
                    cover.End()
            except Exception:
                pass
        self._leavingPage = None

    def Finished(self):
        widget = self.widget(self.nextIndex)
        # 顺序很关键：**先**把新页切上来，**最后**才撤覆盖层。
        self.setCurrentIndex(self.nextIndex)
        self._leavingPage = None
        args = self.switchArg
        self.switchArg = {}
        if widget is None:
            for cover in (self._gpuCover, self._rasterCover):
                try:
                    if cover is not None:
                        cover.End()
                except Exception:
                    pass
            return
        widget.show()
        self.InvalidatePage(widget)

        def Withdraw():
            for cover in (self._gpuCover, self._rasterCover):
                try:
                    if cover is not None:
                        cover.End()
                except Exception:
                    pass
            try:
                self.update()
            except Exception:
                pass

        def RepaintAndWithdraw():
            # 先同步画一遍新页（确保 backing store 里是"有内容的新页"），再撤覆盖层。
            # 少了这一步，撤掉覆盖层的瞬间屏幕上只有新页的背景色（实测 120~140ms）。
            try:
                widget.repaint()
            except Exception:
                pass
            Withdraw()

        def RunAndWithdraw():
            # 1) 先跑 SwitchCurrent：页面**首次**进入时会建表/排版/填数据（实测
            #    200ms+）。在这之前新页是"空壳"，此时撤覆盖层就是一片空白。
            try:
                widget.SwitchCurrent(**args)
            except Exception:
                pass
            try:
                widget.update()
            except Exception:
                pass
            # 2) 再等两帧：SwitchCurrent 里改过的控件要下一次布局才落到最终几何，
            #    立刻 repaint 会画到"中间状态"。覆盖层上是新页快照，多留一拍无感。
            QTimer.singleShot(48, RepaintAndWithdraw)
            # 3) 双保险：若新页 400ms 内一帧都没画出来（某些页首帧很慢），
            #    也不能一直挡着 —— 直接撤，至少页面已 show。
            self._paintWatcher = _FirstPaintWatcher(widget, Withdraw, 400)

        # 让动画最后一帧先画出去（update + 16ms），再把 SwitchCurrent 这种
        # 200ms 级的重活接上去，避免它把尾帧拖住。
        self.update()
        QTimer.singleShot(16, RunAndWithdraw)
        return

    @staticmethod
    def _RunSwitchCurrent(widget, args):
        try:
            widget.SwitchCurrent(**args)
        except Exception:
            pass

    def SwitchWidgetByIndex(self, index, direction=None, **kwargs):
        self._StopAnimation()
        self.nextIndex = index
        if direction is not None:
            # 调用方显式指定方向（返回/回退走这条）：此类路径会先把当前页从
            # subStackList 里裁掉，再靠 list.index 推方向会退化成 0<=0=前进。
            self.animationType = direction
        else:
            oldIndex = 0
            if self.currentIndex() in self.subStackList:
                oldIndex = self.subStackList.index(self.currentIndex())

            newIndex = 0
            if index in self.subStackList:
                newIndex = self.subStackList.index(index)
            self.animationType = AnimationEnum.LeftToRight if oldIndex <= newIndex \
                else AnimationEnum.RightToLeft
        self.switchArg = kwargs

        current = self.widget(self.currentIndex())
        target = self.widget(index)
        # 离开的这页内容还"新鲜"，拍一张存起来；目标页若没变过直接复用缓存
        prev = self._RenderPage(current, useCache=False)
        next_ = self._RenderPage(target, useCache=True)
        if prev is None or next_ is None:
            self.Finished()
            return
        if self.CacheEnabled and current is not None:
            self._cache[id(current)] = (prev, current.size())

        self.currentValue = 0
        self._lastSnapshots = (prev, next_)
        cover = self._ActiveCover()
        # 旧页先留着！覆盖层还没画出第一帧之前就把旧页藏掉，屏幕上就是一块黑
        # （实测 4 帧 ≈ 23ms，用户感知为"切页闪一下"）。等真正有内容盖上来再藏。
        self._leavingPage = current
        cover.Begin(prev, next_, self.animationType)
        # GL context 没起来（模拟器/驱动异常）：立刻退回 raster，动画不中断
        if cover is self._gpuCover:
            try:
                bad = self._gpuCover.IsBroken() or not self._gpuCover.isValid()
            except Exception:
                bad = True
            if bad:
                self._gpuOk = False
                try:
                    self._gpuCover.End()
                except Exception:
                    pass
                cover = self._rasterCover
                cover.Begin(prev, next_, self.animationType)
        if cover is self._rasterCover:
            # raster 覆盖层的 Begin() 里是同步 repaint，返回时已经有内容了，
            # 可以立刻藏旧页（否则动画期间整窗重绘会把旧页也画一遍）。
            self._HideLeavingPage()
        else:
            # GPU 首帧是异步的：等 FirstFrame 信号再藏。万一它迟迟不来，
            # 看门狗会降级到 raster，_FallbackToRaster 里也会藏。
            pass
        self._animSize = (self.width(), self.height())
        driver = self._Driver()
        driver.setDuration(self.AnimationMs)
        driver.setEasingCurve(self.Easing)
        driver.setStartValue(0)
        driver.setEndValue(self.width())
        driver.start()

    def resizeEvent(self, event):
        QStackedWidget.resizeEvent(self, event)
        # 动画期间尺寸变了（软键盘弹出/收起、旋转、分屏）：覆盖层还带着旧几何，
        # QRhiWidget 还会重建资源（重建期间 render() 不画 = 黑屏）。直接落位到
        # 目标页比"半途换几何继续播"稳。
        #
        # 但**必须区分"真尺寸变化"和"布局抖一下"**：切页时面包屑要重建（
        # ClearTabBar + UpdateTabBar 增删 QToolButton），menuLayout 会重排一次，
        # 顺手把 stack 的 resizeEvent 也带起来。如果对这种 1~2px 的抖动也落位，
        # 动画会在第一帧就被掐掉 —— 用户看到的就是"动画没了、页面直接跳"。
        try:
            if (self._driver is not None
                    and self._driver.state() == QPropertyAnimation.State.Running):
                last = getattr(self, "_animSize", None)
                now = (self.width(), self.height())
                if last is None or abs(now[0] - last[0]) > 8 or abs(now[1] - last[1]) > 8:
                    self._LandOnTarget()
        except Exception:
            pass
        try:
            self.InvalidatePage()
            if self._rasterCover.isVisible():
                self._rasterCover.setGeometry(self.rect())
            if self._gpuCover is not None and self._gpuCover.isVisible():
                self._gpuCover.setGeometry(self.rect())
        except Exception:
            pass

    def paintEvent(self, event: QPaintEvent) -> None:
        # 自己铺一层不透明底色。原因：主容器（totalStackWidget/widget）是
        # WA_TranslucentBackground（见 component/widget/main_widget.py），页面本身也
        # 可能半透明（登录弹层就是这样）。底下没有任何东西铺底时，透明区域在真机上
        # 就是**纯黑** —— 表现为"切到登录页 / 从登录页切走时整块内容区黑一下"。
        try:
            paint = QPainter(self)
            paint.fillRect(event.rect(), self._BackgroundColor())
            paint.end()
        except Exception:
            pass
        QStackedWidget.paintEvent(self, event)
