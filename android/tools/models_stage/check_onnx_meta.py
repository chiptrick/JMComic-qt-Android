import onnx, collections
m = onnx.load("/root/jmcomic-build/models_src/scale2x.onnx")
print("opset:", [(op.domain or "ai.onnx", op.version) for op in m.opset_import])
print("inputs:", [(i.name, [d.dim_value or d.dim_param for d in i.type.tensor_type.shape.dim]) for i in m.graph.input])
print("outputs:", [(o.name, [d.dim_value or d.dim_param for d in o.type.tensor_type.shape.dim]) for o in m.graph.output])
print("ops:", dict(collections.Counter(n.op_type for n in m.graph.node)))
print("ir_version:", m.ir_version)
import onnxruntime, onnxsim, torch
print("ort", onnxruntime.__version__, "| torch", torch.__version__)
try:
    import onnxsim as _s
    print("onnxsim", getattr(_s, "__version__", "?"))
except Exception as e:
    print("onnxsim?", e)
