# coding:utf-8
"""GPU 合成层(Vulkan/QRhiWidget) 回归测试（不需要手机，宿主 offscreen 跑）

守四条不变量（都是 0.81→0.82 这轮踩过的坑）：
  1. 着色器 .qsb 存在、可被 QShader 解析、且含 Vulkan 需要的 SpirvShader
  2. GPU 覆盖层不再依赖 OpenGL（QOpenGLWidget 与 Vulkan 合成互斥，回归即失效）
  3. 顶点 UV 的 Y 轴方向随后端切换（Vulkan y 朝下 / OpenGL y 朝上），否则画面上下颠倒
  4. 双纹理位移：两页共用一个整数设备像素偏移、边缘严格相接、落地无残留

跑法（WSL 的构建树里，需要 PySide6）：
  cd <构建树>/src
  QT_QPA_PLATFORM=offscreen <venv>/bin/python3 android/tools/host_test_gpu_layer.py
"""
import os
import sys

from PySide6.QtCore import QFile, QIODevice

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, _ROOT)

Failures = []
ShaderDir = os.path.join(_ROOT, "src", "component", "widget", "shaders")


def Check(ok, name):
    print(("  ok  " if ok else "  FAIL ") + name)
    if not ok:
        Failures.append(name)


def TestShaders():
    print("\n[1] .qsb 着色器：存在 / 可解析 / 含 Vulkan 用的 SPIR-V")
    from PySide6.QtGui import QShader

    for name, stage in (("animcover.vert.qsb", QShader.Stage.VertexStage),
                        ("animcover.frag.qsb", QShader.Stage.FragmentStage)):
        path = os.path.join(ShaderDir, name)
        Check(os.path.isfile(path), "{} 存在".format(name))
        if not os.path.isfile(path):
            continue
        f = QFile(path)
        Check(f.open(QIODevice.OpenModeFlag.ReadOnly), "{} 可读".format(name))
        data = f.readAll()
        f.close()
        shader = QShader.fromSerialized(data)
        Check(shader.isValid(), "{} 能被 QShader 解析".format(name))
        Check(shader.stage() == stage, "{} 阶段正确".format(name))
        sources = set()
        for key in shader.availableShaders():
            try:
                sources.add(key.source().name)
            except Exception:
                pass
        Check("SpirvShader" in sources, "{} 含 SpirvShader（Vulkan 唯一需要的目标）".format(name))
        Check("GlslShader" in sources, "{} 含 GlslShader（OpenGL 回退用）".format(name))


def TestNoOpenGl():
    print("\n[2] GPU 覆盖层不再依赖 OpenGL")
    path = os.path.join(_ROOT, "src", "component", "widget", "gpu_anim_cover.py")
    src = open(path, encoding="utf-8").read()
    for bad in ("QtOpenGL", "QOpenGLWidget", "QOpenGLShader"):
        Check(bad not in src.split('"""')[2] if src.count('"""') > 2 else bad not in src,
              "源码里没有 {}".format(bad))
    from component.widget import gpu_anim_cover as g
    Check(hasattr(g, "GpuAnimCover"), "GpuAnimCover 存在")
    Check(g.GpuAvailable(), "GpuAvailable() 为真（模块 + 着色器齐全）")


def TestVertexOrientation():
    print("\n[3] 顶点 UV 的 Y 轴方向随后端切换")
    from component.widget.gpu_anim_cover import _VertexData
    vk = _VertexData(True)
    gl = _VertexData(False)
    Check(len(vk) == 16 and len(gl) == 16, "顶点数据是 4 顶点 × (x,y,u,v)")
    # Vulkan(y 朝下)：(-1,-1) 是屏幕左上 -> v 必须是 0
    Check(vk[3] == 0.0 and vk[1] == -1.0, "Vulkan：左上角 v=0（图像第 0 行贴顶部）")
    # OpenGL(y 朝上)：(-1,-1) 是屏幕左下 -> v 必须是 1
    Check(gl[3] == 1.0 and gl[1] == -1.0, "OpenGL：左下角 v=1（等价翻转）")
    Check([vk[i] for i in (0, 1, 4, 5, 8, 9, 12, 13)] ==
          [gl[i] for i in (0, 1, 4, 5, 8, 9, 12, 13)], "两种后端只差 UV，顶点位置一致")


def TestTranslationOffsets():
    print("\n[4] 双纹理位移：同一整数偏移、边缘严格相接、落地无残留")
    from component.widget.gpu_anim_cover import GpuAnimCover

    # 宽 400 逻辑、设备 1000 像素；50% 进度 -> 500 设备像素
    def Offsets(reveal, type_=1):
        return GpuAnimCover._OffsetsFor(400, reveal, type_, 1000)

    p0 = Offsets(0)
    Check(p0 == (0, 1000), "前进 0%：旧页铺满、新页在右边缘外 (实际 {})".format(p0))
    half = Offsets(200)
    Check(half == (-500, 500), "前进 50%：旧页左移半屏、新页从右滑入 (实际 {})".format(half))
    Check(half[1] - half[0] == 1000, "前进：两页边缘严格相接（无缝隙/重叠）")
    end = Offsets(400)
    Check(end == (-1000, 0), "前进 100%：旧页完全移出、左边缘无 1px 残留 (实际 {})".format(end))
    Check(end[0] + 1000 == 0, "前进落地：旧页右边缘恰好停在 0")
    back = Offsets(200, 2)
    Check(back == (500, -500), "后退 50%：旧页右移半屏、新页从左滑入 (实际 {})".format(back))
    Check(back[0] - back[1] == 1000, "后退：两页边缘严格相接")
    bend = Offsets(400, 2)
    Check(bend == (1000, 0), "后退 100%：旧页完全移出 (实际 {})".format(bend))

    mid = GpuAnimCover._OffsetFor(400, 137, 1000)
    Check(isinstance(mid, int) and 0 < mid < 1000, "中间进度是整数设备像素 ({})".format(mid))
    Check(GpuAnimCover._OffsetFor(400, -10, 1000) == 0, "进度越界(负)被夹到 0")
    Check(GpuAnimCover._OffsetFor(400, 9999, 1000) == 1000, "进度越界(超宽)被夹到 W")


def TestNoScissor():
    print("\n[5] 不再依赖 scissor（状态是 sticky 的，混用会把新页裁成一条）")
    path = os.path.join(_ROOT, "src", "component", "widget", "gpu_anim_cover.py")
    src = open(path, encoding="utf-8").read()
    Check("cb.setScissor" not in src, "绘制循环里没有 setScissor")
    Check("UsesScissor" not in src, "管线不再声明 UsesScissor")
    Check("QRhiScissor" not in src, "不再 import QRhiScissor")
    Check("setViewport" in src, "改用视口偏移实现位移")


def main():
    print("===== GPU 合成层(Vulkan) 回归 =====")
    TestShaders()
    TestNoOpenGl()
    TestVertexOrientation()
    TestTranslationOffsets()
    TestNoScissor()
    print()
    if Failures:
        print("FAILED {} 项:".format(len(Failures)))
        for name in Failures:
            print("  - " + name)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
