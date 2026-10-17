# coding:utf-8
"""把 waifu2x cunet 的 ONNX 改写成 QNN HTP 能吃下的"静态图"

为什么要做
----------
仓库里原来的 cunet 模型是动态 shape 导出的，图里有 100+ 个
`Shape` / `Gather` / `Concat` / `Reshape` / `ConstantOfShape` / `Where` / `Expand`
节点。QNN EP 的算子白名单里**没有 `Shape` / `Reshape` / `ConstantOfShape`**，于是：

* 严格 HTP 会话(`session.disable_cpu_ep_fallback=1`)必然失败；
* 只能退到"HTP + 允许 CPU 回退"，图被切成 NPU/CPU 两段，**每块 tile 都要在
  NPU 与 CPU 之间来回搬张量** —— 这是 QNN 超分比预期慢一大截的主要原因。

输入形状本来就是固定的 `1x3x192x192`，这些 shape 运算可以全部常量折叠掉。
折叠后：257 节点 -> 79 节点，只剩 Conv/LeakyRelu/Relu/Sigmoid/GlobalAveragePool/
Mul/Add/Pad/Expand/ConvTranspose/Clip，全部落在 QNN 白名单内；输出与折叠前
**逐位相同**(max|Δ| = 0)。

用法
----
    # 先 dry-run 看报告(不写回)，确认"非QNN算子"一列为空、max|Δ| 为 0
    python android/tools/simplify_models.py android/sr_qnn/models

    # 确认无误后写回(覆盖原文件；建议先把原文件备份到仓库外)
    python android/tools/simplify_models.py android/sr_qnn/models --write

依赖：pip install onnx onnxsim onnxruntime numpy
"""
import argparse
import collections
import os
import shutil
import sys

TILE = 192
# cunet 的真实输出边长(实测；模型 metadata 里被 prepare_models.py 写成了 tile*scale)
REAL_OUT = {1: 136, 2: 312}

# ONNX Runtime QNN EP 支持的算子(官方文档 "Supported ONNX operators" 的 ai.onnx 部分)
QNN_OPS = set("""Abs Add And ArgMax ArgMin Asin Atan AveragePool BatchNormalization Cast
Clip Concat Conv ConvTranspose Cos DepthToSpace DequantizeLinear Div Elu Equal Exp Expand
Flatten Floor Gather Gelu Gemm GlobalAveragePool Greater GreaterOrEqual GridSample HardSwish
InstanceNormalization LRN LayerNormalization LeakyRelu Less LessOrEqual Log LogSoftmax
LpNormalization MatMul Max MaxPool Min Mul Neg Not Or Prelu Pad Pow QuantizeLinear ReduceMax
ReduceMean ReduceMin ReduceProd ReduceSum Relu Resize Round Sigmoid Sign Sin Slice Softmax
SpaceToDepth Split Sqrt Squeeze Sub Tanh Tile TopK Transpose Unsqueeze Where""".split())


def _imports():
    try:
        import numpy  # noqa
        import onnx  # noqa
        import onnxsim  # noqa
        import onnxruntime  # noqa
    except ImportError as es:
        print("缺少依赖({})：pip install onnx onnxsim onnxruntime numpy".format(es))
        sys.exit(2)
    import numpy as np
    import onnx
    import onnxsim
    import onnxruntime as ort
    return np, onnx, onnxsim, ort


def FixShapes(model, onnx, scale):
    """输入固定成 1x3xTILExTILE，输出改成真实边长(不再是 tile*scale)"""
    out = REAL_OUT.get(scale, TILE * scale)
    for vi in model.graph.input:
        dims = vi.type.tensor_type.shape.dim
        if len(dims) == 4:
            dims[2].dim_value = TILE
            dims[3].dim_value = TILE
    for vi in model.graph.output:
        dims = vi.type.tensor_type.shape.dim
        if len(dims) == 4:
            dims[2].dim_value = out
            dims[3].dim_value = out
    return model


def ConstantsToInitializers(model, onnx):
    """Constant 节点 -> initializer(QNN 白名单里没有 Constant)"""
    graph = model.graph
    if not any(node.op_type == "Constant" for node in graph.node):
        return model, 0
    keep = []
    added = 0
    for node in graph.node:
        if node.op_type != "Constant":
            keep.append(node)
            continue
        tensor = None
        for attr in node.attribute:
            if attr.name == "value":
                tensor = onnx.helper.get_attribute_value(attr)
        if tensor is None:
            keep.append(node)
            continue
        tensor.name = node.output[0]
        graph.initializer.append(tensor)
        added += 1
    del graph.node[:]
    graph.node.extend(keep)
    return model, added


def _run(ort, path, feed):
    options = ort.SessionOptions()
    options.log_severity_level = 3
    session = ort.InferenceSession(path, options, providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name
    return session.run(None, {name: feed})[0]


def TestInput(np):
    """漫画页风格的校验输入：白底 + 黑线 + 渐变 + 轻微噪声"""
    gridY, gridX = np.mgrid[0:TILE, 0:TILE]
    x = np.zeros((1, 3, TILE, TILE), dtype=np.float32)
    x[0, 0] = 0.9 + 0.1 * np.sin(gridX / 7.0)
    x[0, 1] = 0.9 + 0.1 * np.cos(gridY / 9.0)
    x[0, 2] = 0.95
    x[0, :, ::13, :] = 0.05
    x[0, :, :, ::17] = 0.05
    rng = np.random.default_rng(11)
    return np.clip(x + rng.normal(0, 0.01, x.shape), 0, 1).astype(np.float32)


def QnnFriendlyPass(model, onnx):
    """ 把 QNN EP 容易拒收的写法改成等价但更朴素的写法

    实测(sr_qnn 0.6 真机, SM8750)：静态化之后严格 HTP 仍然失败，会话退成
    "HTP(CPU 回退)"，每块 473ms —— 说明有个别节点没被 QNN 接下。逐条排掉这些
    "虽然 ONNX 合法、但容易被 EP 判掉" 的写法：

    1. `Expand(x, shape)` 后接 `Mul(a, y)`：Expand 只是把 [N,C,1,1] 的缩放系数
       广播成 [N,C,H,W]，而 `Mul` 本身就会广播 —— 直接把 Expand 折叠掉，少 4 个节点。
    2. `Pad(data, pads, '')`：第三个输入是空字符串(表示可选输入缺省)。ONNX 允许，
       但有些 EP 的 builder 会把它当成真实输入名处理而拒绝整块。直接去掉尾随空串。
    3. 其余(Pad/Clip/ConvTranspose/GlobalAveragePool)保持原样。

    改写后数学上与原图完全等价(见调用方的 max|Δ| 校验)。
    """
    graph = model.graph

    def inputCount(node):
        return len([x for x in node.input if x != ""])

    expandOutputs = {}
    for node in graph.node:
        if node.op_type == "Expand" and len(node.input) >= 2:
            expandOutputs[node.output[0]] = node

    dropped = set()
    for node in graph.node:
        if node.op_type != "Mul":
            continue
        for index, name in enumerate(node.input):
            expand = expandOutputs.get(name)
            if expand is None:
                continue
            shapeInit = expand.input[1]
            # 只折叠"输出的唯一消费者就是这个 Mul"的情况，避免改坏别处语义
            consumers = [n for n in graph.node if name in list(n.input)]
            if len(consumers) != 1:
                continue
            node.input[index] = expand.input[0]      # [N,C,1,1] 直接广播相乘
            dropped.add(expand.output[0])
            if not any(shapeInit in list(n.input) for n in graph.node if n is not expand):
                dropped.add(shapeInit)

    keep = []
    for node in graph.node:
        if node.output and node.output[0] in dropped:
            continue
        if node.op_type == "Pad" and len(node.input) == 3 and node.input[2] == "":
            # 去掉尾随的可选输入占位
            while node.input and node.input[-1] == "":
                del node.input[-1]
        keep.append(node)
    del graph.node[:]
    graph.node.extend(keep)

    for name in dropped:
        for vi in list(graph.value_info):
            if vi.name == name:
                graph.value_info.remove(vi)
    inits = [i for i in graph.initializer if i.name not in dropped]
    del graph.initializer[:]
    graph.initializer.extend(inits)
    return model, len(dropped)


def Main():
    parser = argparse.ArgumentParser()
    parser.add_argument("models_dir", help="models 目录(含 *.onnx 与 models.txt)")
    parser.add_argument("--write", action="store_true", help="写回(覆盖)原模型文件")
    parser.add_argument("--backup", default="", help="--write 时把原文件备份到该目录")
    args = parser.parse_args()

    np, onnx, onnxsim, ort = _imports()
    feed = TestInput(np)
    names = sorted(f for f in os.listdir(args.models_dir) if f.endswith(".onnx"))
    if not names:
        print("目录里没有 onnx: {}".format(args.models_dir))
        return 2
    if args.backup:
        os.makedirs(args.backup, exist_ok=True)
        for name in names:
            shutil.copy2(os.path.join(args.models_dir, name), os.path.join(args.backup, name))
        print("已备份原模型到 {}".format(args.backup))

    failed = []
    for name in names:
        scale = 1 if "up1x" in name else 2
        src = os.path.join(args.models_dir, name)
        model = FixShapes(onnx.load(src), onnx, scale)
        nodeBefore = len(model.graph.node)
        before = collections.Counter(node.op_type for node in model.graph.node)
        badBefore = sorted(set(before) - QNN_OPS)
        try:
            ref = _run(ort, src, feed)
        except Exception as es:
            print("%-38s 原模型推理失败: %s" % (name, es))
            failed.append(name)
            continue
        try:
            sim, ok = onnxsim.simplify(model, overwrite_input_shapes={"x": [1, 3, TILE, TILE]}, check_n=0)
        except Exception as es:
            print("%-38s simplify 异常: %s" % (name, es))
            failed.append(name)
            continue
        if not ok:
            print("%-38s simplify 自检失败" % name)
            failed.append(name)
            continue
        sim, constCount = ConstantsToInitializers(sim, onnx)
        sim, foldedCount = QnnFriendlyPass(sim, onnx)
        if foldedCount:
            print("   QNN 友好化: 折叠 %d 个 Expand/空输入" % foldedCount)
        after = collections.Counter(node.op_type for node in sim.graph.node)
        badAfter = sorted(set(after) - QNN_OPS)

        tmp = src + ".tmp.onnx"
        onnx.save(sim, tmp)
        try:
            got = _run(ort, tmp, feed)
        except Exception as es:
            print("%-38s 简化后推理失败: %s" % (name, es))
            failed.append(name)
            os.remove(tmp)
            continue
        diff = float(np.abs(np.asarray(ref, np.float32) - np.asarray(got, np.float32)).max())
        print("%-38s 节点 %3d -> %3d | 非QNN算子 %-46s -> %-6s | 输出 %s | max|Δ|=%.5f" % (
            name, nodeBefore, len(sim.graph.node),
            ",".join(badBefore) or "-", ",".join(badAfter) or "-", tuple(got.shape), diff))
        bad = diff > 2e-3 or bool(badAfter)
        if bad:
            failed.append(name)
        if args.write and not bad:
            os.replace(tmp, src)
        elif os.path.exists(tmp):
            os.remove(tmp)

    print()
    if failed:
        print("未通过:", failed)
        return 1
    print("全部模型静态化通过" + ("（已写回）" if args.write else "（dry-run，未写回）"))
    return 0


if __name__ == "__main__":
    sys.exit(Main())
