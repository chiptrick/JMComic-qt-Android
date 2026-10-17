""" 最小复现：只做 spawn + hello，逐步写文件，避免管道交互干扰 """
import os
import sys
import traceback

SRC = "/root/jmcomic-build/src"
sys.path.insert(0, os.path.join(SRC, "android"))
sys.path.insert(0, os.path.join(SRC, "src"))

LOG = open("/tmp/proc_step.log", "w", buffering=1)


def Step(msg):
    LOG.write(msg + "\n")
    LOG.flush()


try:
    Step("1 import sr_qnn")
    import sr_qnn
    Step("2 exe=%s" % sr_qnn._SearchFile(sr_qnn.ProcName))
    os.environ["JM_SR_PROC"] = "1"
    Step("3 LoadEngine")
    ok = sr_qnn.LoadEngine(os.environ.get("JM_SR_MODELS"))
    Step("4 LoadEngine -> %s proc=%s" % (ok, sr_qnn.IsProcMode()))
    Step("   backend=%s htp=%s models=%d" % (
        sr_qnn.GetBackendInfo(), sr_qnn.HasHtp(), len(sr_qnn.GetModelList())))
    if sr_qnn.IsProcMode():
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QImage
        img = QImage(64, 64, QImage.Format.Format_RGB888)
        img.fill(0x808080)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        Step("5 add")
        tid = sr_qnn.add(bytes(ba), "WAIFU2X_CUNET_UP2X_DENOISE3X", 1, 2.0, format="png")
        Step("   tid=%d" % tid)
        Step("6 load")
        res = sr_qnn.load(120000)
        Step("7 load -> %s" % (None if res is None else (res[2], len(res[0]) if res[0] else None, round(res[3], 2))))
    sr_qnn.stop()
    Step("8 done")
except Exception:
    Step("EXC:\n" + traceback.format_exc())
finally:
    LOG.close()
