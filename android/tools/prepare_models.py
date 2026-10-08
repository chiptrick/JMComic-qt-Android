# coding:utf-8
"""为高通 NPU(QNN/HTP) 准备 waifu2x ONNX 模型

QNN EP 不支持动态 shape，所以模型必须导出/改写成固定的 1x3xT x T 输入。
本脚本在电脑上运行(x86_64 Windows/Linux/macOS 均可)，产出文件直接放到
android/sr_qnn/models/ 或手机上的 JM_SR_MODELS 目录。

用法示例
--------
# 1) 把已有的 waifu2x onnx(动态 shape) 转成 NPU 可用的固定 shape
python prepare_models.py --src D:/waifu2x_onnx --tile 192

# 2) 同时生成 fp16 版本(体积更小，部分机型更快)
python prepare_models.py --src D:/waifu2x_onnx --tile 192 --fp16

# 3) 生成量化模型(QNN HTP 原生只支持量化模型，速度最快，需要 onnxruntime x64)
python prepare_models.py --src D:/waifu2x_onnx --tile 192 --quantize --calib-dir D:/anime_pics

# 4) 校验模型能不能跑(会打印输入输出信息与输出取值范围)
python prepare_models.py --src D:/waifu2x_onnx --tile 192 --verify

模型来源
--------
* waifu2x ONNX: HuggingFace 上的 waifu2x_onnx 等公开转换版本
* Real-CUGAN / Real-ESRGAN: 可用官方 pytorch 权重 torch.onnx.export 导出
* 只要满足：输入 NCHW float [0,1]，输出 NCHW float [0,1]，放大倍数为整数

产出文件名与 android/sr_qnn/models/models.txt 一一对应，例如
  waifu2x_anime_up2x_denoise3.onnx
脚本会按 "--map" 规则自动命名(见 NameMap)，也可以 --name 手动指定。
"""
import argparse
import os
import shutil
import sys

# 源文件名关键字 -> 目标文件名(与 models.txt 对应)
NameMap = [
    (("anime", "up2x", "noise3"), "waifu2x_anime_up2x_denoise3.onnx"),
    (("anime", "up2x", "noise2"), "waifu2x_anime_up2x_denoise2.onnx"),
    (("anime", "up2x", "noise1"), "waifu2x_anime_up2x_denoise1.onnx"),
    (("anime", "up2x", "noise0"), "waifu2x_anime_up2x_denoise0.onnx"),
    (("photo", "up2x", "noise3"), "waifu2x_photo_up2x_denoise3.onnx"),
    (("photo", "up2x", "noise2"), "waifu2x_photo_up2x_denoise2.onnx"),
    (("photo", "up2x", "noise1"), "waifu2x_photo_up2x_denoise1.onnx"),
    (("photo", "up2x", "noise0"), "waifu2x_photo_up2x_denoise0.onnx"),
    (("anime", "up1x", "noise3"), "waifu2x_anime_up1x_denoise3.onnx"),
    (("anime", "up1x", "noise2"), "waifu2x_anime_up1x_denoise2.onnx"),
    (("anime", "up1x", "noise1"), "waifu2x_anime_up1x_denoise1.onnx"),
    (("anime", "up1x", "noise0"), "waifu2x_anime_up1x_denoise0.onnx"),
]

DefaultInputs = {
    # 目标文件 -> (放大倍数, 是否需要降噪输入)
    "waifu2x_anime_up2x_denoise3.onnx": 2,
    "waifu2x_photo_up2x_denoise3.onnx": 2,
}


def GuessScale(name):
    lower = name.lower()
    for key, scale in (("up4x", 4), ("up3x", 3), ("up2x", 2), ("up1x", 1), ("x4", 4), ("x3", 3), ("x2", 2)):
        if key in lower:
            return scale
    return 2


def MapName(fileName):
    lower = os.path.basename(fileName).lower()
    for keys, target in NameMap:
        if all(k in lower for k in keys):
            return target
    return None


def ImportOnnx():
    try:
        import onnx
        return onnx
    except ImportError:
        print("需要 onnx: pip install onnx numpy")
        sys.exit(2)


def FixShapes(modelPath, outPath, tile, scale):
    """ 把动态 shape 固化为 1x3xT x T / 1x3x(T*scale)x(T*scale) """
    onnx = ImportOnnx()
    model = onnx.load(modelPath)
    inputNames = {vi.name for vi in model.graph.input}
    outputNames = {vi.name for vi in model.graph.output}
    fixed = 0
    targets = list(model.graph.input) + list(model.graph.output) + list(model.graph.value_info)
    for valueInfo in targets:
        tensorType = valueInfo.type.tensor_type
        dims = tensorType.shape.dim
        if len(dims) != 4:
            continue
        if valueInfo.name in inputNames:
            want = [1, 3, tile, tile]
        elif valueInfo.name in outputNames:
            want = [1, 3, tile * scale, tile * scale]
        else:
            continue
        for index, dim in enumerate(dims):
            if dim.HasField("dim_value") and dim.dim_value == want[index]:
                continue
            dim.ClearField("dim_param")
            dim.dim_value = want[index]
            fixed += 1
    onnx.save(model, outPath)
    print("  固定 shape: {} 个维度 -> {}".format(fixed, os.path.basename(outPath)))
    return outPath


def ConvertFp16(srcPath, outPath):
    try:
        from onnxconverter_common import float16
    except ImportError:
        print("  跳过 fp16(需要 pip install onnxconverter-common)")
        return None
    onnx = ImportOnnx()
    model = onnx.load(srcPath)
    model16 = float16.convert_float_to_float16(model, keep_io_types=True, disable_shape_infer=True)
    onnx.save(model16, outPath)
    print("  生成 fp16: {}".format(os.path.basename(outPath)))
    return outPath


def Quantize(srcPath, outPath, calibDir, tile):
    """ 生成 QNN 友好的 QDQ 量化模型(uint16 激活 + uint8 权重) """
    try:
        import numpy as np
        import onnxruntime
        from onnxruntime.quantization import CalibrationDataReader, QuantType, quantize
        from onnxruntime.quantization.execution_providers.qnn import (get_qnn_qdq_config,
                                                                      qnn_preprocess_model)
    except ImportError as es:
        print("  跳过量化(需要 x64 上的 onnxruntime + numpy): {}".format(es))
        return None

    maxCalib = 16

    class Reader(CalibrationDataReader):
        def __init__(self, images):
            self.images = images
            self.index = 0
            self.session = onnxruntime.InferenceSession(srcPath, providers=["CPUExecutionProvider"])

        def _tensor(self):
            if self.images:
                from PIL import Image
                image = Image.open(self.images[self.index % len(self.images)]).convert("RGB")
                image = image.resize((tile, tile))
                array = np.asarray(image, dtype=np.float32) / 255.0
            else:
                array = np.random.rand(3, tile, tile).astype(np.float32)
            return np.expand_dims(array, 0)

        def get_next(self):
            if self.index >= maxCalib:
                return None
            self.index += 1
            return {self.session.get_inputs()[0].name: self._tensor()}

        def rewind(self):
            self.index = 0

    images = []
    if calibDir and os.path.isdir(calibDir):
        for name in sorted(os.listdir(calibDir))[:maxCalib]:
            if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
                images.append(os.path.join(calibDir, name))
    if not images:
        print("  警告：没有标定图片(--calib-dir)，用随机数据量化，精度可能下降")

    preproc = outPath + ".preproc.onnx"
    changed = qnn_preprocess_model(srcPath, preproc)
    target = preproc if changed else srcPath
    config = get_qnn_qdq_config(target, Reader(images),
                                activation_type=QuantType.QUInt16,
                                weight_type=QuantType.QUInt8)
    quantize(target, outPath, config)
    if os.path.exists(preproc):
        os.remove(preproc)
    print("  生成量化模型: {}".format(os.path.basename(outPath)))
    return outPath


def Verify(modelPath, tile, scale):
    """ 用 CPU 跑一遍，确认模型可用 """
    try:
        import numpy as np
        import onnxruntime
    except ImportError:
        print("  跳过校验(需要 onnxruntime numpy)")
        return True
    session = onnxruntime.InferenceSession(modelPath, providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    print("  输入: {} {}".format(inputs[0].name, inputs[0].shape))
    print("  输出: {} {}".format(outputs[0].name, outputs[0].shape))
    data = np.random.rand(1, 3, tile, tile).astype(np.float32)
    result = session.run(None, {inputs[0].name: data})[0]
    print("  推理成功: shape={}, range=[{:.3f}, {:.3f}]".format(
        result.shape, float(result.min()), float(result.max())))
    expect = tile * scale
    if result.shape[-1] != expect:
        print("  警告：输出边长 {} != 期望 {}，请检查 models.txt 里的倍数".format(result.shape[-1], expect))
        return False
    return True


def ProcessOne(srcPath, outDir, tile, scale, name, doFp16, doQuant, calibDir, verify):
    target = name or MapName(srcPath)
    if not target:
        base = os.path.splitext(os.path.basename(srcPath))[0]
        target = base + ".onnx"
        print("  [未匹配命名规则] 输出为 {}".format(target))
    outPath = os.path.join(outDir, target)
    print("处理 {} (倍数 {})".format(os.path.basename(srcPath), scale))
    FixShapes(srcPath, outPath, tile, scale)
    ok = True
    if verify:
        ok = Verify(outPath, tile, scale)
    if doFp16:
        ConvertFp16(outPath, os.path.join(outDir, target.replace(".onnx", ".fp16.onnx")))
    if doQuant:
        Quantize(srcPath, os.path.join(outDir, target.replace(".onnx", ".qdq.onnx")), calibDir, tile)
    return ok


def Main():
    parser = argparse.ArgumentParser(description="为高通 NPU 准备 waifu2x ONNX 模型")
    parser.add_argument("--src", required=True, help="源 onnx 文件或目录")
    parser.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                      "..", "sr_qnn", "models"),
                        help="输出目录，默认 android/sr_qnn/models")
    parser.add_argument("--tile", type=int, default=192, help="固定输入边长，默认 192")
    parser.add_argument("--scale", type=int, default=0, help="放大倍数，0=按文件名推断")
    parser.add_argument("--name", default="", help="输出文件名(仅单个源文件时有效)")
    parser.add_argument("--fp16", action="store_true", help="额外生成 fp16 模型")
    parser.add_argument("--quantize", action="store_true", help="额外生成 QDQ 量化模型(HTP 最快)")
    parser.add_argument("--calib-dir", default="", help="量化标定图片目录")
    parser.add_argument("--verify", action="store_true", help="用 CPU 推理校验")
    args = parser.parse_args()

    outDir = os.path.abspath(args.out)
    os.makedirs(outDir, exist_ok=True)
    if not os.path.exists(os.path.join(outDir, "models.txt")):
        srcTxt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sr_qnn", "models", "models.txt")
        if os.path.exists(srcTxt) and os.path.abspath(srcTxt) != os.path.join(outDir, "models.txt"):
            shutil.copy(srcTxt, outDir)

    sources = []
    if os.path.isdir(args.src):
        for root, _, files in os.walk(args.src):
            for name in files:
                if name.lower().endswith(".onnx"):
                    sources.append(os.path.join(root, name))
    else:
        sources.append(args.src)
    if not sources:
        print("没有找到 onnx 文件")
        return 1

    okAll = True
    for srcPath in sources:
        scale = args.scale or GuessScale(os.path.basename(srcPath))
        okAll = ProcessOne(srcPath, outDir, args.tile, scale, args.name, args.fp16,
                           args.quantize, args.calib_dir, args.verify) and okAll
    print("\n输出目录: {}".format(outDir))
    print("把该目录整体拷贝到手机的 JM_SR_MODELS 目录(默认 /data/data/<包名>/files/waifu2x-models)，")
    print("或重新打包 APK(见 android/README.md)。")
    return 0 if okAll else 3


if __name__ == "__main__":
    sys.exit(Main())
