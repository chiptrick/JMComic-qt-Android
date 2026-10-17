#!/usr/bin/env python3
"""CUGAN/ESRGAN onnx 简化 + QNN 友好化 + ORT 校验（通用版）

复刻 android/tools/simplify_models.py 的核心逻辑，但:
- 不硬编码 scale/REAL_OUT，按 models.txt 规则从文件名推断
- 输入名统一 "x"，固定 1x3x192x192
- 校验参考值由调用方通过 --ref-npy 提供（torch wrapper 输出），或用内置测试输入自校验（仅简化等价性）
"""
import argparse, collections, os, sys
import numpy as np

TILE = 192
# waifu2x cunet 的真实输出边长(实测：模型内部有 crop，输出比 tile*scale 小 72/56)
REAL_OUT_WAIFU2X = {1: 136, 2: 312}

QNN_OPS = set("""Abs Add And ArgMax ArgMin Asin Atan AveragePool BatchNormalization Cast
Clip Concat Conv ConvTranspose Cos DepthToSpace DequantizeLinear Div Elu Equal Exp Expand
Flatten Floor Gather Gelu Gemm GlobalAveragePool Greater GreaterOrEqual GridSample HardSwish
InstanceNormalization LRN LayerNormalization LeakyRelu Less LessOrEqual Log LogSoftmax
LpNormalization MatMul Max MaxPool Min Mul Neg Not Or Pad Pow PRelu QuantizeLinear ReduceMax
ReduceMean ReduceMin ReduceProd ReduceSum Relu Resize Round Sigmoid Sign Sin Slice Softmax
Split Sqrt Squeeze Sub Tanh Tile TopK Transpose Unsqueeze Where""".split())


def _imports():
    import onnx, onnxsim, onnxruntime
    return onnx, onnxsim, onnxruntime


def ConstantsToInitializers(model, onnx):
    graph = model.graph
    if not any(node.op_type == "Constant" for node in graph.node):
        return model, 0
    keep, added = [], 0
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


def QnnFriendlyPass(model, onnx):
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
            consumers = [n for n in graph.node if name in list(n.input)]
            if len(consumers) != 1:
                continue
            node.input[index] = expand.input[0]
            dropped.add(expand.output[0])
            shapeInit = expand.input[1]
            if not any(shapeInit in list(n.input) for n in graph.node if n is not expand):
                dropped.add(shapeInit)
    keep = []
    for node in graph.node:
        if node.output and node.output[0] in dropped:
            continue
        if node.op_type == "Pad" and len(node.input) == 3 and node.input[2] == "":
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


def GuessScale(name):
    lower = name.lower()
    for key, scale in (("up4x", 4), ("up3x", 3), ("up2x", 2), ("up1x", 1)):
        if key in lower:
            return scale
    return 0


def TestInput(np):
    gridY, gridX = np.mgrid[0:TILE, 0:TILE]
    x = np.zeros((1, 3, TILE, TILE), dtype=np.float32)
    x[0, 0] = 0.9 + 0.1 * np.sin(gridX / 7.0)
    x[0, 1] = 0.9 + 0.1 * np.cos(gridY / 9.0)
    x[0, 2] = 0.95
    x[0, :, ::13, :] = 0.05
    x[0, :, :, ::17] = 0.05
    rng = np.random.default_rng(11)
    return np.clip(x + rng.normal(0, 0.01, x.shape), 0, 1).astype(np.float32)


def Main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="onnx 文件或目录")
    ap.add_argument("--write", action="store_true", help="写回(覆盖)原文件")
    ap.add_argument("--backup", default="", help="写回前备份目录")
    ap.add_argument("--ref-dir", default="", help="torch 参考输出目录(<name>.npy)，提供则做 torch↔onnx 对账")
    args = ap.parse_args()

    onnx, onnxsim, ort = _imports()
    files = []
    for p in args.paths:
        if os.path.isdir(p):
            files += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith(".onnx")]
        else:
            files.append(p)
    if not files:
        print("没有 onnx 文件")
        return 2

    if args.backup:
        os.makedirs(args.backup, exist_ok=True)
        import shutil
        for f in files:
            shutil.copy2(f, os.path.join(args.backup, os.path.basename(f)))
        print("已备份到", args.backup)

    feed = TestInput(np)
    failed = []
    for src in files:
        name = os.path.basename(src)
        scale = GuessScale(name)
        model = onnx.load(src)
        nodeBefore = len(model.graph.node)
        before = collections.Counter(n.op_type for n in model.graph.node)
        badBefore = sorted(set(before) - QNN_OPS)

        def _run(path):
            so = ort.SessionOptions()
            so.log_severity_level = 3
            sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
            iname = sess.get_inputs()[0].name
            return sess.run(None, {iname: feed})[0]

        try:
            ref = _run(src)
        except Exception as es:
            print(f"{name}: 原模型推理失败: {es}")
            failed.append(name)
            continue
        try:
            sim, ok = onnxsim.simplify(model, overwrite_input_shapes={"x": [1, 3, TILE, TILE]}, check_n=0)
        except Exception as es:
            print(f"{name}: simplify 异常: {es}")
            failed.append(name)
            continue
        if not ok:
            print(f"{name}: simplify 自检失败")
            failed.append(name)
            continue
        sim, constCount = ConstantsToInitializers(sim, onnx)
        sim, foldedCount = QnnFriendlyPass(sim, onnx)
        after = collections.Counter(n.op_type for n in sim.graph.node)
        badAfter = sorted(set(after) - QNN_OPS)

        tmp = src + ".tmp.onnx"
        onnx.save(sim, tmp)
        try:
            got = _run(tmp)
        except Exception as es:
            print(f"{name}: 简化后推理失败: {es}")
            failed.append(name)
            os.remove(tmp)
            continue
        diff = float(np.abs(np.asarray(ref, np.float32) - np.asarray(got, np.float32)).max())

        # torch 参考对账（可选）
        refNote = ""
        if args.ref_dir:
            refNpy = os.path.join(args.ref_dir, os.path.splitext(name)[0] + ".npy")
            if os.path.exists(refNpy):
                tref = np.load(refNpy)
                if tref.shape == got.shape:
                    tdiff = float(np.abs(tref.astype(np.float64) - got.astype(np.float64)).max())
                    refNote = f" | torchΔ={tdiff:.6f}"
                else:
                    refNote = f" | torchΔ=SHAPE({tref.shape} vs {got.shape})"
            else:
                refNote = " | torchΔ=NO_REF"

        expect = TILE * scale if scale else got.shape[-1]
        if scale and ("waifu2x" in name.lower() or "cunet" in name.lower()):
            expect = REAL_OUT_WAIFU2X.get(scale, expect)
        sizeNote = "" if got.shape[-1] == expect else f" !! 期望 {expect}"
        print(f"{name}: 节点 {nodeBefore} -> {len(sim.graph.node)} | 非QNN {','.join(badBefore) or '-'} -> {','.join(badAfter) or '-'} "
              f"| 输出 {tuple(got.shape)}{sizeNote} | max|Δ|={diff:.5f}{refNote}")
        bad = diff > 2e-3 or bool(badAfter) or bool(sizeNote)
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
    print("全部通过" + ("（已写回）" if args.write else "（dry-run）"))
    return 0


if __name__ == "__main__":
    sys.exit(Main())
