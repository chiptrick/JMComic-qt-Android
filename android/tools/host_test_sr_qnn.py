# coding:utf-8
"""在 x86_64 Linux(宿主)上验证 sr_qnn 引擎逻辑

不依赖高通 NPU，验证的是与设备无关的核心逻辑：
    模型表/常量、固定 shape 分块推理的无缝拼接、任意倍数与目标尺寸缩放、
    结果编码(jpg/png)、add/load/remove/removeWaitProc/stop 任务语义、模型回退

依赖：pip install PySide6 onnx numpy
用法：
    JM_SR_QNN_LIB=/path/to/libsr_qnn.so python android/tools/host_test_sr_qnn.py
"""
import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TILE = 192

TMP = tempfile.mkdtemp(prefix="sr_qnn_host_test_")
MODELS = os.path.join(TMP, "models")
os.makedirs(MODELS, exist_ok=True)
os.environ["JM_SR_MODELS"] = MODELS
os.environ["JM_SR_CACHE"] = os.path.join(TMP, "context")
os.environ["JMCOMIC_ANDROID"] = "1"      # 让 platform_mobile 走移动分支
os.environ["ANDROID_PRIVATE"] = TMP
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "android"))

FAILS = []


def Check(name, ok, detail=""):
    print("[{}] {}{}".format("ok" if ok else "FAIL", name, ("  " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)
    return ok


def BuildTestModel(path, tile=TILE, scale=2):
    """ 构造一个固定 shape 的 2x 双线性放大 onnx 作为被测模型 """
    import onnx
    from onnx import TensorProto, helper

    nodes = [
        helper.make_node("Resize", ["input", "", "scales"], ["output"],
                         mode="linear", coordinate_transformation_mode="half_pixel"),
    ]
    graph = helper.make_graph(
        nodes, "sr_test",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, tile, tile])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3, tile * scale, tile * scale])],
        [helper.make_tensor("scales", TensorProto.FLOAT, [4], [1.0, 1.0, float(scale), float(scale)])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model, path)
    return path


def BuildShrinkModel(path, tile=TILE, scale=2, crop=18):
    """ 构造"会收缩"的固定 shape 模型：先把 T×T 每边裁掉 crop，再做 scale 倍双线性放大

    输出边长 O = (T - 2*crop) * scale，精确复现 cunet 的分块几何
    (实测 cunet up2x: 192 -> 312 = (192-2*18)*2；up1x: 192 -> 136 = 192-2*28)。
    它用来回归真机上的分块错位/缺带 bug：引擎若按 out = in*scale 算读取偏移，
    这个模型就会拼出位移且带黑条的图。
    """
    import onnx
    from onnx import TensorProto, helper

    inner = tile - 2 * crop
    nodes = [
        helper.make_node("Slice", ["input", "starts", "ends", "axes"], ["cropped"]),
        helper.make_node("Resize", ["cropped", "", "scales"], ["output"],
                         mode="linear", coordinate_transformation_mode="half_pixel"),
    ]
    graph = helper.make_graph(
        nodes, "sr_shrink_test",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, tile, tile])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT,
                                       [1, 3, inner * scale, inner * scale])],
        [helper.make_tensor("starts", TensorProto.INT64, [2], [crop, crop]),
         helper.make_tensor("ends", TensorProto.INT64, [2], [tile - crop, tile - crop]),
         helper.make_tensor("axes", TensorProto.INT64, [2], [2, 3]),
         helper.make_tensor("scales", TensorProto.FLOAT, [4],
                            [1.0, 1.0, float(scale), float(scale)])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save(model, path)
    return path


def RefBilinear(image, scale):
    """ numpy 参考实现：与 ORT 的 half_pixel 双线性 2x 放大对齐 """
    height, width, _ = image.shape
    outH, outW = height * scale, width * scale
    ys = (np.arange(outH) + 0.5) / scale - 0.5
    xs = (np.arange(outW) + 0.5) / scale - 0.5
    ys = np.clip(ys, 0, height - 1)
    xs = np.clip(xs, 0, width - 1)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    y1 = np.clip(y0 + 1, 0, height - 1)
    x1 = np.clip(x0 + 1, 0, width - 1)
    wy = (ys - y0)[:, None, None]
    wx = (xs - x0)[None, :, None]
    top = image[y0][:, x0] * (1 - wx) + image[y0][:, x1] * wx
    bottom = image[y1][:, x0] * (1 - wx) + image[y1][:, x1] * wx
    return top * (1 - wy) + bottom * wy


def Main():
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage

    import sr_qnn

    # ---------- 模型准备 ----------
    # 文件名必须与 models.txt 里该模型名映射到的文件一致，否则会走"回退到最近可用模型"
    # 的路径，测的就不是我们想测的那个模型了
    BuildTestModel(os.path.join(MODELS, "waifu2x_cunet_up2x_denoise3.onnx"))
    BuildShrinkModel(os.path.join(MODELS, "waifu2x_cunet_up2x_denoise0.onnx"))
    manifest = open(os.path.join(ROOT, "android", "sr_qnn", "models", "models.txt"), encoding="utf-8").read()
    with open(os.path.join(MODELS, "models.txt"), "w", encoding="utf-8") as f:
        f.write(manifest)

    # ---------- 加载引擎 ----------
    lib = os.environ.get("JM_SR_QNN_LIB", "")
    if not lib or not os.path.exists(lib):
        print("需要设置 JM_SR_QNN_LIB 指向宿主构建的 libsr_qnn.so")
        return 2
    Check("LoadEngine", sr_qnn.LoadEngine(MODELS), "htp={} backend={}".format(
        sr_qnn.HasHtp(), sr_qnn.GetBackendInfo()))
    if not sr_qnn.IsLoaded():
        print("引擎加载失败: {}".format(sr_qnn.GetLoadError()))
        return 2
    Check("模型常量(默认看图模型)", hasattr(sr_qnn, "MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X"))
    Check("模型表数量", len(sr_qnn.GetModelList()) == len(sr_qnn.ModelNames),
          "{} 个".format(len(sr_qnn.GetModelList())))
    Check("版本串", "sr_qnn" in sr_qnn.getVersion(), sr_qnn.getVersion())

    # ---------- 初始化 ----------
    Check("init()", sr_qnn.init() >= 0)
    Check("initSet(设备0, 单线程)", sr_qnn.initSet(0, 1) >= 0)
    cpuNum = sr_qnn.getCpuCoreNum()
    Check("getCpuCoreNum", cpuNum > 0, str(cpuNum))
    Check("getGpuInfo 列表", isinstance(sr_qnn.getGpuInfo(), list) and len(sr_qnn.getGpuInfo()) >= 1,
          str(sr_qnn.getGpuInfo()))

    # ---------- 测试图 ----------
    width, height = 300, 200
    yy, xx = np.mgrid[0:height, 0:width]
    base = np.zeros((height, width, 3), dtype=np.uint8)
    base[..., 0] = (xx * 255 // max(1, width - 1)).astype(np.uint8)
    base[..., 1] = (yy * 255 // max(1, height - 1)).astype(np.uint8)
    base[..., 2] = (((xx // 8 + yy // 8) % 2) * 255).astype(np.uint8)   # 棋盘格：容易暴露接缝
    img = QImage(base.data, width, height, width * 3, QImage.Format.Format_RGB888)
    pngBytes = QByteArray()
    buffer = QBuffer(pngBytes)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buffer, "PNG")
    buffer.close()
    pngBytes = bytes(pngBytes)
    # 注意：这张图很规则，PNG 压缩后可能只有几百字节，这里只校验能被 Qt 解回来
    decoded = QImage.fromData(pngBytes)
    Check("测试图编码可解码", len(pngBytes) > 100 and not decoded.isNull()
          and (decoded.width(), decoded.height()) == (width, height),
          "{} bytes, {}x{}".format(len(pngBytes), decoded.width(), decoded.height()))

    # ---------- 2x 超分 + 接缝检查 ----------
    taskId = sr_qnn.add(pngBytes, sr_qnn.MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X, 1, 2.0,
                        format="png", tileSize=0)
    Check("add(scale=2) 返回任务号", taskId > 0, str(taskId))
    result = sr_qnn.load(30000)
    Check("load 返回结果", bool(result) and result[0], str(result if not result else len(result[0] or b"")))
    if not (result and result[0]):
        print("引擎错误: {}".format(sr_qnn.getLastError()))
        return 3
    data, fmt, backId, tick = result
    Check("任务号回传", backId == taskId, "{} vs {}".format(backId, taskId))
    Check("耗时字段", tick > 0, "{:.3f}s".format(tick))
    out = QImage.fromData(data)
    Check("输出尺寸 = 2x", (out.width(), out.height()) == (width * 2, height * 2),
          "{}x{}".format(out.width(), out.height()))
    out = out.convertToFormat(QImage.Format.Format_RGB888)
    got = np.frombuffer(bytes(out.constBits()), dtype=np.uint8).reshape(out.height(), out.bytesPerLine())[:, :out.width() * 3]
    got = got.reshape(out.height(), out.width(), 3)

    ref = RefBilinear(base.astype(np.float32), 2)
    diff = np.abs(got.astype(np.float32) - ref)
    Check("与参考双线性放大一致(无接缝/无错位)", diff.max() <= 3.0,
          "max={:.1f} mean={:.3f} (T={} 分块边界在 x={})".format(
              diff.max(), diff.mean(), TILE, [TILE - 32, 2 * (TILE - 32)]))

    # 接缝检查：分块边界处不应该出现"参考图里没有的"额外突变。
    # (不能直接比较不同列的差分，因为棋盘格图案本身的列差就有大有小)
    step = TILE - 2 * 16
    seam = []
    for boundary in range(step, width, step):
        col = boundary * 2
        if 0 < col < got.shape[1] - 1:
            jumpGot = np.abs(got[:, col + 1].astype(np.int32)
                             - got[:, col - 1].astype(np.int32)).mean()
            jumpRef = np.abs(ref[:, col + 1] - ref[:, col - 1]).mean()
            seam.append(jumpGot - jumpRef)
    Check("分块边界无额外突变", all(abs(v) < 2 for v in seam) if seam else True,
          "边界跳变偏移={}".format([round(float(v), 2) for v in seam]))

    # ---------- 收缩模型(cunet 几何)的分块拼接 ----------
    # 真机 bug 回归：原实现按 out = in*nativeScale 算有效区读取偏移，而 cunet 是收缩网络
    # (192->312)，于是每块整体位移，并且 rh*scale 会撞上 ty>=outH 被 break 截断出黑带。
    shrinkName = "WAIFU2X_ANIME_UP2X_DENOISE0X"   # models.txt -> waifu2x_cunet_up2x_denoise0.onnx
    # 注意：sr_qnn 的 _modelIdByName 用**不带 MODEL_ 前缀**的名字做键
    shrinkId = getattr(sr_qnn, "MODEL_" + shrinkName, -1)
    Check("收缩模型已注册", shrinkId > 0, "MODEL_{} id={}".format(shrinkName, shrinkId))

    rampW, rampH = 300, 200
    ry, rx = np.mgrid[0:rampH, 0:rampW]
    ramp = np.zeros((rampH, rampW, 3), dtype=np.uint8)
    ramp[..., 0] = (rx * 255 // max(1, rampW - 1)).astype(np.uint8)
    ramp[..., 1] = (ry * 255 // max(1, rampH - 1)).astype(np.uint8)
    ramp[..., 2] = 128                     # 常量通道：用来发现"根本没被写入"的像素
    rampImg = QImage(ramp.data, rampW, rampH, rampW * 3, QImage.Format.Format_RGB888)
    rampBytes = QByteArray()
    rampBuf = QBuffer(rampBytes)
    rampBuf.open(QIODevice.OpenModeFlag.WriteOnly)
    rampImg.save(rampBuf, "PNG")
    rampBuf.close()
    rampBytes = bytes(rampBytes)

    taskId = sr_qnn.add(rampBytes, shrinkId, 10, 2.0, format="png")
    Check("add(收缩模型, scale=2)", taskId > 0, str(taskId))
    result = sr_qnn.load(60000)
    if not (result and result[0]):
        Check("收缩模型 load 返回结果", False, "err={}".format(sr_qnn.getLastError()))
    else:
        sout = QImage.fromData(result[0])
        Check("收缩模型输出尺寸 = 2x", (sout.width(), sout.height()) == (rampW * 2, rampH * 2),
              "{}x{}".format(sout.width(), sout.height()))
        sout = sout.convertToFormat(QImage.Format.Format_RGB888)
        sgot = np.frombuffer(bytes(sout.constBits()), dtype=np.uint8)
        sgot = sgot.reshape(sout.height(), sout.bytesPerLine())[:, :sout.width() * 3]
        sgot = sgot.reshape(sout.height(), sout.width(), 3)
        unwritten = int((sgot[..., 2] == 0).sum())
        Check("收缩模型无未写入像素(无黑带)", unwritten == 0,
              "{} 个像素的 B 通道为 0，共 {} 像素".format(unwritten, sgot.shape[0] * sgot.shape[1]))
        sref = RefBilinear(ramp.astype(np.float32), 2)
        sdiff = np.abs(sgot.astype(np.float32) - sref)
        Check("收缩模型与参考一致(无整体位移)", sdiff.max() <= 4.0,
              "max={:.1f} mean={:.3f}".format(sdiff.max(), sdiff.mean()))

    # ---------- 任意倍数 / 目标尺寸 ----------
    taskId = sr_qnn.add(pngBytes, sr_qnn.MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X, 2, 1.5, format="jpg")
    result = sr_qnn.load(30000)
    out = QImage.fromData(result[0]) if result and result[0] else None
    Check("scale=1.5 -> 450x300", out is not None and (out.width(), out.height()) == (450, 300),
          "{}".format(None if out is None else "{}x{}".format(out.width(), out.height())))

    taskId = sr_qnn.add(pngBytes, sr_qnn.MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X, 3, 600, 400, format="png")
    result = sr_qnn.load(30000)
    out = QImage.fromData(result[0]) if result and result[0] else None
    Check("目标尺寸 600x400", out is not None and (out.width(), out.height()) == (600, 400),
          "{}".format(None if out is None else "{}x{}".format(out.width(), out.height())))

    # ---------- 模型回退(请求缺失的模型) ----------
    taskId = sr_qnn.add(pngBytes, sr_qnn.MODEL_REALCUGAN_SE_UP4X, 4, 2.0, format="png")
    result = sr_qnn.load(30000)
    Check("缺失模型自动回退仍可用", bool(result) and result[0], "task={}".format(taskId))

    # ---------- removeWaitProc：排队中的任务被丢弃 ----------
    first = sr_qnn.add(pngBytes, sr_qnn.MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X, 5, 2.0, format="png")
    second = sr_qnn.add(pngBytes, sr_qnn.MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X, 6, 2.0, format="png")
    sr_qnn.removeWaitProc([second])
    result = sr_qnn.load(30000)
    Check("removeWaitProc 丢弃排队任务", result is not None and result[2] == first,
          "拿到 taskId={}".format(None if result is None else result[2]))
    Check("被丢弃任务不再产出", sr_qnn.load(500) is None)

    # ---------- remove：取消 ----------
    taskId = sr_qnn.add(pngBytes, sr_qnn.MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X, 7, 2.0, format="png")
    sr_qnn.remove([taskId])
    result = sr_qnn.load(30000)
    Check("remove 取消任务", result is not None and result[2] == taskId,
          "taskId={} data={}".format(None if result is None else result[2],
                                     None if not result else bool(result[0])))

    # ---------- 无效输入 ----------
    taskId = sr_qnn.add(b"not an image", sr_qnn.MODEL_WAIFU2X_ANIME_UP2X_DENOISE3X, 8, 2.0)
    Check("非法图片被拒绝", taskId <= 0, str(taskId))
    taskId = sr_qnn.add(pngBytes, 99999, 9, 2.0)
    Check("非法模型号被拒绝", taskId <= 0, str(taskId))

    sr_qnn.stop()
    print()
    if FAILS:
        print("失败 {} 项: {}".format(len(FAILS), FAILS))
        return 1
    print("全部通过：sr_qnn 宿主逻辑测试(分块拼接/缩放/编码/任务 API/回退)")
    return 0


if __name__ == "__main__":
    sys.exit(Main())
