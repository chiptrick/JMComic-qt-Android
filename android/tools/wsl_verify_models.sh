#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# 用 onnxruntime(CPU) 独立验证准备好的 9 个模型：能否加载、IO 形状、推理耗时
set -uo pipefail
WORK="$JM_WORK"
VPY="$WORK/venv311/bin/python"
MODELS="$JM_REPO/android/sr_qnn/models"
exec > >(tee -a "$WORK/logs/verify_models.log") 2>&1

echo "== 安装 onnxruntime(镜像) =="
"$VPY" -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple onnxruntime numpy 2>&1 | tail -2
"$VPY" -c "import onnxruntime; print('onnxruntime', onnxruntime.__version__)"

echo
echo "== 逐个模型验证 =="
"$VPY" - "$MODELS" <<'PYEOF'
import glob, os, sys, time
import numpy as np
import onnxruntime as ort

models = sorted(glob.glob(os.path.join(sys.argv[1], "*.onnx")))
print("模型数:", len(models))
ok = 0
for path in models:
    name = os.path.basename(path)
    try:
        so = ort.SessionOptions()
        so.log_severity_level = 3
        sess = ort.InferenceSession(path, sess_options=so, providers=["CPUExecutionProvider"])
        inp = sess.get_inputs()[0]
        out = sess.get_outputs()[0]
        data = np.random.rand(1, 3, 192, 192).astype(np.float32)
        t0 = time.time()
        res = sess.run(None, {inp.name: data})[0]
        dt = time.time() - t0
        print("  %-38s in=%s out=%s  %.0fms  range=[%.2f,%.2f]" % (
            name, inp.shape, res.shape, dt * 1000, float(res.min()), float(res.max())))
        ok += 1
    except Exception as es:
        print("  %-38s 失败: %s" % (name, str(es)[:110]))
print("可用: %d/%d" % (ok, len(models)))
PYEOF
