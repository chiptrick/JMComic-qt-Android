# coding:utf-8
"""GPU 合成层（Vulkan / QRhiWidget）：两张页面纹理 + 同步位移

为什么需要它
------------
Qt Widgets 是 raster(CPU) 绘制，换页动画每帧的代价 ≈ 脏区面积。实测（V2463A，
1440x3168 / DPR 3.75 / 120Hz）：

  * 整页脏区 30.4ms/帧（32fps）、120x120 脏区 9.2ms/帧
  * 即便把脏区压到"一条竖带"，仍有 ~9ms/帧的整窗合成地板
  * 120Hz 的预算是 8.33ms/帧 —— 所以纯 CPU 路线到不了 120fps

本模块把每一帧的绘制交给 GPU：两张页面快照各上传一次纹理，之后每帧只做
"全屏四边形 ×2 + 视口位移"，CPU 侧只剩一次 Qt 的合成提交。

为什么是 QRhiWidget 而不是 QOpenGLWidget
----------------------------------------
窗口合成后端是 Vulkan 时，Qt 明确拒绝 QOpenGLWidget：

    The top-level window is not using OpenGL for composition,
    'Vulkan' is not compatible with QOpenGLWidget

表现为 widget 构造成功、不抛异常，但 context()=None、isValid() 恒 False。
QRhiWidget 天生就是"用窗口当前 RHI 后端"渲染的，所以在 Vulkan 下可用。
着色器必须是预编译的 .qsb（见 shaders/animcover.*.qsb，用 pyside6-qsb 烘焙）。

绘制流程
--------
  1. 视口 x=-off 画 texPrev —— 旧页整体左移 off（前进方向）
  2. 视口 x=W-off 画 texNext —— 新页从右边缘滑入
两页共用同一个**整数设备像素** off，接缝严格对齐；视口可以超出渲染目标，
屏幕外部分被裁剪，所以每帧实际着色的像素仍约等于一屏（填充率不会翻倍）。
逐帧**不更新任何 uniform / buffer**，只改两个视口，没有顶点/UBO 上传。

后退方向（RightToLeft）把两个偏移取反：旧页右移、新页从左滑入。

为什么不用 scissor：scissor 是"揭示"语义（旧页不动、新页逐条露出），
而位移需要两页同时移动。视口偏移可以在不改着色器、不加 UBO 的前提下做到，
且 QRhi 的 scissor 状态是 sticky 的，混用容易把下一页裁成一条。

失败降级
--------
initialize() 抛异常 / 资源创建失败 → _broken=True 并回调 BrokenHook，
AnimationStackWidget 会立刻用同一对快照切回 raster 覆盖层，动画不中断。
"""
import os

from PySide6.QtCore import QFile, QIODevice, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QImage, QShader, QRhi, QRhiBuffer, QRhiDepthStencilClearValue,
                           QRhiGraphicsPipeline, QRhiSampler,
                           QRhiShaderResourceBinding, QRhiShaderStage, QRhiTexture,
                           QRhiVertexInputAttribute, QRhiVertexInputBinding,
                           QRhiVertexInputLayout, QRhiViewport)
from PySide6.QtWidgets import QRhiWidget

_SHADER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shaders")

def _VertexData(yDown):
    """4 顶点三角带：(x, y, u, v)

    Y 轴约定随后端不同（实测 V2463A / Adreno）：
      * Vulkan：NDC 的 y 轴朝**下**，(-1,-1) 是屏幕左上 → 图像第 0 行(v=0)贴上去正好
      * OpenGL：NDC 的 y 轴朝**上**，(-1,-1) 是屏幕左下 → 必须把 v 翻过来
    搞错这一段的表现是整个动画画面上下颠倒（文字镜像、封面倒置）。
    """
    if yDown:
        return (-1.0, -1.0, 0.0, 0.0,
                 1.0, -1.0, 1.0, 0.0,
                -1.0,  1.0, 0.0, 1.0,
                 1.0,  1.0, 1.0, 1.0)
    return (-1.0, -1.0, 0.0, 1.0,
             1.0, -1.0, 1.0, 1.0,
            -1.0,  1.0, 0.0, 0.0,
             1.0,  1.0, 1.0, 0.0)


def _LoadShader(name):
    """读预编译 .qsb；缺失/损坏返回 None（调用方降级）"""
    path = os.path.join(_SHADER_DIR, name)
    try:
        f = QFile(path)
        if not f.open(QIODevice.OpenModeFlag.ReadOnly):
            return None
        data = f.readAll()
        f.close()
        shader = QShader.fromSerialized(data)
        if not shader.isValid():
            return None
        return shader
    except Exception:
        return None


def GpuAvailable():
    """轻量探测：模块与着色器都在就认为"可能可用"（真正验证在 initialize()）"""
    try:
        import PySide6.QtWidgets as _w
        if not hasattr(_w, "QRhiWidget"):
            return False
    except Exception:
        return False
    if not os.path.exists(os.path.join(_SHADER_DIR, "animcover.vert.qsb")):
        return False
    if not os.path.exists(os.path.join(_SHADER_DIR, "animcover.frag.qsb")):
        return False
    return True


class GpuAnimCover(QRhiWidget):
    """两张页面纹理 + 同步位移的 GPU 覆盖层"""

    # 第一帧真正画出来（= 覆盖层已经有内容可看）。栈靠它决定"什么时候藏旧页"：
    # GPU 首帧要建资源 + 上传两张整页纹理（实测 +37ms），在那之前藏旧页就是黑屏。
    FirstFrame = Signal()

    def __init__(self, stack):
        super().__init__(stack)
        self._stack = stack
        self._type = 1                  # 1=LeftToRight(前进) 2=RightToLeft(后退)
        self._reveal = 0
        self._imgPrev = None
        self._imgNext = None
        self._pending = False           # 有新快照待上传
        self._ready = False
        self._broken = False
        self.BrokenHook = None          # 初始化失败时回调(由栈注入)

        self._vbuf = None
        self._texPrev = None
        self._texNext = None
        self._sampler = None
        self._srbPrev = None
        self._srbNext = None
        self._pipeline = None
        self._texSize = QSize()
        self._yDown = True
        self._framesAtBegin = 0
        self._firstFrameDone = False

        # 诊断计数（性能探针读，语义与 raster 覆盖层一致）
        self.PaintCount = 0
        self.PaintArea = 0
        self.PaintMs = 0.0

        # 默认跟随窗口的合成后端（Android 端由 android/main.py 钉成 Vulkan，
        # 桌面端可能是 OpenGL 或 raster）。不硬写 Api.Vulkan 的原因：桌面没有
        # Vulkan 时硬指定会让这个 widget 直接建不起来，动画只剩黑屏。
        self.ForceVulkan = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        try:
            self.setAutoFillBackground(False)
        except Exception:
            pass
        self.hide()

    # -- 生命周期 ---------------------------------------------------------
    def _ApplyApi(self):
        if not self.ForceVulkan:
            return
        try:
            self.setApi(QRhiWidget.Api.Vulkan)
        except Exception:
            pass

    def Begin(self, prev, next_, type_):
        self._type = type_.value if hasattr(type_, "value") else int(type_)
        self._reveal = 0
        self._imgPrev = self._ToImage(prev)
        self._imgNext = self._ToImage(next_)
        self._pending = True
        self._firstFrameDone = False
        self.setGeometry(self._stack.rect())
        self._framesAtBegin = self.PaintCount
        self._ApplyApi()
        self.show()
        self.raise_()
        self.update()
        # QRhiWidget 拿不到 RHI 时既不抛异常也不报错，只是永远不调用 render()；
        # 那样动画期间页面被藏着，屏幕会一直空着（250ms 黑屏）。这里用"有没有画过
        # 一帧"做看门狗，超时就回调降级。
        QTimer.singleShot(120, self._Watchdog)

    def End(self):
        self.hide()
        self._imgPrev = None
        self._imgNext = None
        self._pending = False
        self._reveal = 0

    def _Watchdog(self):
        """软降级：本次动画退回 raster，但**不**把 GPU 路径判死

        启动早期（登录页自动切首页那一刻）窗口可能还没完成第一次 RHI 合成，
        QRhiWidget 这时候确实一帧都画不出来。如果这里直接把 _broken 置真，
        一次启动期抖动就会让整个进程再也用不上 GPU 覆盖层（实测 0.82 装包首启
        就是这样退化的）。所以只通知"这次别用了"，下次动画照常重试。
        """
        if self._broken or not self.isVisible():
            return
        if self.PaintCount > getattr(self, "_framesAtBegin", 0):
            return
        try:
            from tools.log import Log
            Log.Warn("GpuAnimCover watchdog: 120ms 内没有渲染过一帧，本次退回 raster")
        except Exception:
            pass
        self._NotifyBroken(hard=False)

    def SetReveal(self, value):
        """value: 0..逻辑宽度，表示两页已滑过的距离（沿用旧接口名，语义=位移进度）

        整数化只在 _OffsetPx() 里做一次，并把同一个值同时用于两页，
        避免两页各自取整产生 1px 竖缝。
        """
        self._reveal = int(value)
        # 每帧只改两个视口再提交一次绘制，CPU 侧没有额外上传
        self.update()

    def IsBroken(self):
        return self._broken

    def isValid(self):
        """与 QOpenGLWidget 的语义对齐：没坏就当作可用（乐观）"""
        return not self._broken

    @staticmethod
    def _ToImage(pixmap):
        if pixmap is None:
            return None
        try:
            if isinstance(pixmap, QImage):
                img = pixmap
            else:
                img = pixmap.toImage()
            if img.isNull():
                return None
            if img.format() != QImage.Format.Format_RGBA8888:
                img = img.convertToFormat(QImage.Format.Format_RGBA8888)
            return img
        except Exception:
            return None

    # -- QRhi 回调 --------------------------------------------------------
    def initialize(self, cb):
        """创建/重建全部 GPU 资源（widget 尺寸变化时 Qt 会再进来一次）"""
        self._ready = False
        try:
            rhi = self.rhi()
            if rhi is None:
                raise RuntimeError("no QRhi")
            self._Release()
            self._ReleaseOwned()

            vert = _LoadShader("animcover.vert.qsb")
            frag = _LoadShader("animcover.frag.qsb")
            if vert is None or frag is None:
                raise RuntimeError("qsb shader missing/invalid")

            # 顶点缓冲（64 字节，静态）；Y 轴约定按后端选
            try:
                yDown = rhi.backend() == QRhi.Implementation.Vulkan
            except Exception:
                yDown = False
            vertexData = _VertexData(yDown)
            self._yDown = yDown
            self._vbuf = rhi.newBuffer(QRhiBuffer.Type.Immutable,
                                       QRhiBuffer.UsageFlag.VertexBuffer,
                                       len(vertexData) * 4)
            self._vbuf.setName(b"animcover-vbuf")
            if not self._vbuf.create():
                raise RuntimeError("vbuf create failed")
            rub = rhi.nextResourceUpdateBatch()
            rub.uploadStaticBuffer(self._vbuf, _PackFloats(vertexData))
            cb.resourceUpdate(rub)

            self._sampler = rhi.newSampler(QRhiSampler.Filter.Linear, QRhiSampler.Filter.Linear,
                                           QRhiSampler.Filter.Linear,
                                           QRhiSampler.AddressMode.ClampToEdge,
                                           QRhiSampler.AddressMode.ClampToEdge)
            self._sampler.setName(b"animcover-sampler")
            if not self._sampler.create():
                raise RuntimeError("sampler create failed")

            # 纹理尺寸必须等于渲染目标（= 覆盖层的设备像素尺寸）。
            # 页面快照可能是别的大小（页面没被重新布局时快照尺寸会和栈不一致），
            # 直接上传会被 Qt 拒绝并 clamp：
            #   "Invalid texture upload issued; size WxH ... will be clamped"
            # 结果就是画错内容 / 黑块。这里统一按渲染目标建纹理，图像上传前适配。
            size = self.renderTarget().pixelSize()
            size = QSize(max(2, size.width()), max(2, size.height()))
            self._texSize = size
            self._texPrev = self._NewTexture(rhi, size)
            self._texNext = self._NewTexture(rhi, size)

            self._srbPrev = self._NewSrb(rhi, self._texPrev)
            self._srbNext = self._NewSrb(rhi, self._texNext)

            self._pipeline = rhi.newGraphicsPipeline()
            self._pipeline.setName(b"animcover-pipe")
            self._pipeline.setShaderStages([
                QRhiShaderStage(QRhiShaderStage.Type.Vertex, vert),
                QRhiShaderStage(QRhiShaderStage.Type.Fragment, frag),
            ])
            layout = QRhiVertexInputLayout()
            layout.setBindings([QRhiVertexInputBinding(4 * 4)])
            layout.setAttributes([
                QRhiVertexInputAttribute(0, 0, QRhiVertexInputAttribute.Format.Float2, 0),
                QRhiVertexInputAttribute(0, 1, QRhiVertexInputAttribute.Format.Float2, 2 * 4),
            ])
            self._pipeline.setVertexInputLayout(layout)
            self._pipeline.setTopology(QRhiGraphicsPipeline.Topology.TriangleStrip)
            self._pipeline.setShaderResourceBindings(self._srbPrev)
            self._pipeline.setDepthTest(False)
            self._pipeline.setDepthWrite(False)
            self._pipeline.setRenderPassDescriptor(self.renderTarget().renderPassDescriptor())
            try:
                self._pipeline.setSampleCount(self.renderTarget().sampleCount())
            except Exception:
                pass
            if not self._pipeline.create():
                raise RuntimeError("pipeline create failed")

            self._ready = True
            self._broken = False
            self._pending = True        # 资源刚建好，快照要重新上传
        except Exception as es:
            self._ready = False
            self._broken = True
            # 资源建不起来：立刻隐藏，避免一块黑色渲染目标盖在页面上一整段动画
            self._HideIfVisible()
            try:
                from tools.log import Log
                Log.Error("GpuAnimCover.initialize failed: {!r}".format(es))
            except Exception:
                pass
            self._NotifyBroken()

    def render(self, cb):
        """每帧：上传(仅在有新快照时) + 两页按同一偏移同步位移"""
        if not self._ready or self._broken:
            # 资源没建好：这块渲染目标是未定义内容（Vulkan 上通常就是黑）。
            # 自己藏起来，让下面的页面露出来，绝不留一块黑在屏幕上。
            QTimer.singleShot(0, self._HideIfVisible)
            return
        import time as _t
        t0 = _t.perf_counter()
        area = 0
        try:
            rhi = self.rhi()
            rub = rhi.nextResourceUpdateBatch()
            if self._pending:
                if self._texPrev is not None and self._imgPrev is not None:
                    rub.uploadTexture(self._texPrev, self._FitImage(self._imgPrev))
                if self._texNext is not None and self._imgNext is not None:
                    rub.uploadTexture(self._texNext, self._FitImage(self._imgNext))
                self._pending = False
            rt = self.renderTarget()
            px = rt.pixelSize()
            area = px.width() * px.height()
            # 清屏色用页面底色（不是黑）：纹理万一还没上传完，至少露出的是
            # "页面该有的背景"而不是一块纯黑。
            cb.beginPass(rt, self._ClearColor(), QRhiDepthStencilClearValue(1.0, 0), rub)
            cb.setGraphicsPipeline(self._pipeline)
            cb.setVertexInput(0, [(self._vbuf, 0)])

            # 1)~2) 两页按同一个整数设备像素偏移同步位移。
            # 视口允许负 x/超出渲染目标，屏幕外部分由光栅化裁剪；两页在
            # x=W-off 处严格拼接，既不会漏底色，也不会重叠。
            prevX, nextX = self._Offsets(px.width())
            cb.setViewport(QRhiViewport(prevX, 0, px.width(), px.height()))
            cb.setShaderResources(self._srbPrev)
            cb.draw(4)

            cb.setViewport(QRhiViewport(nextX, 0, px.width(), px.height()))
            cb.setShaderResources(self._srbNext)
            cb.draw(4)
            cb.endPass()
        except Exception as es:
            self._broken = True
            try:
                from tools.log import Log
                Log.Error("GpuAnimCover.render failed: {!r}".format(es))
            except Exception:
                pass
            self._NotifyBroken()
        self.PaintCount += 1
        self.PaintArea += area
        self.PaintMs += (_t.perf_counter() - t0) * 1000.0
        if not self._firstFrameDone and self._ready and not self._broken:
            self._firstFrameDone = True
            try:
                self.FirstFrame.emit()
            except Exception:
                pass

    def _ClearColor(self):
        try:
            color = self._stack._BackgroundColor()
            return QColor(color.red(), color.green(), color.blue(), 255)
        except Exception:
            return QColor(0, 0, 0, 255)

    def _HideIfVisible(self):
        try:
            if self.isVisible():
                self.hide()
        except Exception:
            pass

    def releaseResources(self):
        self._ready = False
        self._Release()

    # -- 内部 -------------------------------------------------------------
    def _FitImage(self, img):
        """把快照适配到纹理尺寸（设备像素）

        大图裁左上、小图平滑放大：大图裁切与 raster 版的 drawPixmap(0, 0, pix) 行为一致，
        小图放大只在页面尺寸异常时发生（正常流程两者相等，直接返回原图，零拷贝）。
        """
        try:
            if img is None or img.isNull():
                return img
            tw = max(2, self._texSize.width())
            th = max(2, self._texSize.height())
            if img.width() == tw and img.height() == th:
                return img
            if img.width() >= tw and img.height() >= th:
                return img.copy(0, 0, tw, th)
            return img.scaled(tw, th, Qt.AspectRatioMode.IgnoreAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        except Exception:
            return img

    def _NewTexture(self, rhi, size):
        tex = rhi.newTexture(QRhiTexture.Format.RGBA8, size)
        tex.setName(b"animcover-tex")
        if not tex.create():
            raise RuntimeError("texture create failed")
        return tex

    def _NewSrb(self, rhi, tex):
        srb = rhi.newShaderResourceBindings()
        srb.setBindings([
            QRhiShaderResourceBinding.sampledTexture(
                0, QRhiShaderResourceBinding.StageFlag.FragmentStage, tex, self._sampler)
        ])
        if not srb.create():
            raise RuntimeError("srb create failed")
        return srb

    def _Release(self):
        for obj in (self._pipeline, self._srbPrev, self._srbNext,
                    self._texPrev, self._texNext, self._sampler, self._vbuf):
            try:
                if obj is not None:
                    obj.destroy()
            except Exception:
                pass
        self._pipeline = None
        self._srbPrev = None
        self._srbNext = None
        self._texPrev = None
        self._texNext = None
        self._sampler = None
        self._vbuf = None

    def _ReleaseOwned(self):
        """占位：以后若加了只属于本类的 Python 侧资源在这里释放"""
        return

    def _NotifyBroken(self, hard=True):
        """hard=True: 资源/管线真的建不起来，之后别再试
        hard=False: 只是本次没渲染出来（启动早期常见），下次还可以再试
        """
        hook = self.BrokenHook
        if hook is None:
            return
        try:
            hook(hard)
        except TypeError:
            try:
                hook()
            except Exception:
                pass
        except Exception:
            pass

    @staticmethod
    def _OffsetFor(logicalW, reveal, w):
        """纯函数：逻辑进度 -> 设备像素位移（两页共用）

        只做一次 v/logicalW -> 设备像素的换算。不要写成 round(v*DPR)：
        DPR 常是 3.75 这类非整数，两页各自换算会差 1px，表现为一条竖缝。
        进度两端直接返回 0 / w，保证落地时旧页完全移出、不残留一列像素。
        """
        logicalW = max(1, int(logicalW))
        v = max(0, min(int(reveal), logicalW))
        if v <= 0:
            return 0
        if v >= logicalW:
            return w
        return max(0, min(w, int(round(v * w / float(logicalW)))))

    @staticmethod
    def _OffsetsFor(logicalW, reveal, type_, w):
        """纯函数：两页的视口 x（设备像素）

        前进(1)：旧页 x=-off（左移），新页 x=W-off（从右滑入）；
        后退(2)：旧页 x=+off（右移），新页 x=off-W（从左滑入）。
        两种方向都满足"两页边缘严格相接"，不会漏底色或重叠。
        """
        off = GpuAnimCover._OffsetFor(logicalW, reveal, w)
        if int(type_) == 1:
            return (-off, w - off)
        return (off, off - w)

    def _OffsetPx(self, w):
        return self._OffsetFor(self.width() or self._stack.width(), self._reveal, w)

    def _Offsets(self, w):
        return self._OffsetsFor(self.width() or self._stack.width(),
                                self._reveal, self._type, w)


def _PackFloats(values):
    """tuple[float] -> bytes（小端 f32）"""
    import struct
    return struct.pack("<{}f".format(len(values)), *values)












def CreateGpuCover(stack):
    """创建 GPU 覆盖层；不可用时返回 None（调用方退回 raster）"""
    if not GpuAvailable():
        return None
    try:
        return GpuAnimCover(stack)
    except Exception as es:
        try:
            from tools.log import Log
            Log.Error("CreateGpuCover failed: {!r}".format(es))
        except Exception:
            pass
        return None
