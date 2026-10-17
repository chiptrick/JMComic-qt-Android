""" 进程模式(sr_qnn_proc)宿主测试：hello / add / cancel / 错误路径 / stop。

用法(WSL)：
  LD_LIBRARY_PATH=$ORT/linux-x64:$PWD/build-host \
  JM_SR_MODELS=$SRC/android/sr_qnn/models \
  JM_SR_QNN_PROC=$PWD/build-host/sr_qnn_proc \
  python host_test_sr_proc.py
"""
import os
import sys

SRC = os.environ.get("SRC", "/root/jmcomic-build/src")
sys.path.insert(0, os.path.join(SRC, "android"))
sys.path.insert(0, os.path.join(SRC, "src"))

os.environ.setdefault("JM_QNN_DEBUG", "1")
os.environ.setdefault("JM_SR_CACHE", "/tmp/sr_proc_ctx")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage

import sr_qnn

failures = []


def Check(name, ok, detail=""):
    print("{}: {}{}".format("OK " if ok else "FAIL", name, ("  " + detail) if detail else ""))
    if not ok:
        failures.append(name)


# 1. 进程模式加载
os.environ["JM_SR_PROC"] = "1"
ok = sr_qnn.LoadEngine(os.environ.get("JM_SR_MODELS"))
Check("LoadEngine(proc)", ok, sr_qnn.GetLoadError())
Check("IsProcMode", sr_qnn.IsProcMode())
print("  version:", sr_qnn.getVersion())
print("  backend:", sr_qnn.GetBackendInfo(), "| htp:", sr_qnn.HasHtp(), "| cores:", sr_qnn.getCpuCoreNum())
print("  models:", len(sr_qnn.GetModelList()), "available:", sr_qnn.CountAvailableModels())
Check("模型表非空", len(sr_qnn.GetModelList()) > 0)
info = sr_qnn.GetModelInfo(sr_qnn.GetModelId("WAIFU2X_CUNET_UP2X_DENOISE3X"))
print("  modelInfo:", info)
Check("模型信息", info is not None and info[1] == 2 and info[3] == 192)

# 2. 正常超分：200x300 -> 400x600
def MakeImg(w, h):
    img = QImage(w, h, QImage.Format.Format_RGB888)
    img.fill(0x6080A0)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)

raw = MakeImg(200, 300)
tid = sr_qnn.add(raw, "WAIFU2X_CUNET_UP2X_DENOISE3X", 501, 2.0, format="png")
Check("add", tid > 0, "tid=%d" % tid)
res = sr_qnn.load(120000)
if res and res[0]:
    data, fmt, backId, tick = res
    got = QImage.fromData(data)
    Check("结果尺寸", got.width() == 400 and got.height() == 600,
          "%dx%d tick=%.2fs" % (got.width(), got.height(), tick))
    Check("回传 taskId", backId == 501, str(backId))
else:
    Check("结果非空", False, str(res))

# 3. cancel 队列任务：add 两个再 remove 第一个
tid2 = sr_qnn.add(raw, "WAIFU2X_CUNET_UP2X_DENOISE3X", 502, 2.0, format="png")
tid3 = sr_qnn.add(raw, "WAIFU2X_CUNET_UP2X_DENOISE3X", 503, 2.0, format="png")
sr_qnn.remove([502])
res = sr_qnn.load(120000)
if res and res[0]:
    Check("cancel 后取到 503", res[2] == 503, "taskId=%d" % res[2])
else:
    Check("cancel 后结果非空", False, str(res))

# 4. 未知模型名 -> 拒绝
Check("未知模型拒绝", sr_qnn.add(raw, "NO_SUCH_MODEL", 504, 2.0) < 0)

# 5. 坏图片 -> 拒绝
Check("坏图拒绝", sr_qnn.add(b"not an image", "WAIFU2X_CUNET_UP2X_DENOISE3X", 505, 2.0) < 0)

# 6. stop
sr_qnn.stop()
print("结果:", "全部通过" if not failures else "失败 %d 项: %s" % (len(failures), failures))
sys.exit(0 if not failures else 1)
