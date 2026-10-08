from PySide6.QtGui import QImage
from PySide6.QtCore import Qt

from task.qt_task import TaskBase
from task.task_multi import TaskMulti
from tools import platform_mobile
from tools.log import Log
from tools.tool import ToolUtil, time_me


# 解码统计：真机"图片无法解密"时用来一眼看出是"全在失败"还是"根本没跑"。
# task=取到的任务数, ok=成功出图, fail=异常失败, null=空数据/解不出图, lastLen/lastError=最后一次线索
# segQt=用 Qt 在 QImage 域里做的分割还原, segBytes=走 TaskMulti/PIL 的分割还原
Stats = {"task": 0, "ok": 0, "fail": 0, "null": 0, "segQt": 0, "segBytes": 0,
         "lastLen": 0, "lastError": ""}


def QImageStats():
    return dict(Stats)


def _HexHead(data):
    """ 取前 8 字节的 hex(密文/截断数据的特征) """
    try:
        return bytes(data[:8]).hex()
    except Exception:
        return "?"


class QtQImageTask(object):
    def __init__(self, taskId):
        self.taskId = taskId
        self.callBack = None
        self.backParam = None
        self.cleanFlag = ""
        self.data = ""
        self.radio = 1
        self.toH = 0
        self.toW = 0
        self.model = 0
        self.saveParams = None


class TaskQImage(TaskBase):

    def __init__(self):
        TaskBase.__init__(self)
        self.taskObj.imageBack.connect(self.HandlerTask)
        self.thread.start()

    def Run(self):
        # 外层 while 绝不能被异常退出：线程一旦死掉，后面所有页都再也不解码，
        # 界面就表现为"图片无法解密"(其实是一个任务把 worker 打死了)。
        while True:
            try:
                v = self._inQueue.get(True)
                if v == "":
                    break
                taskId = v
            except Exception as es:
                continue
            try:
                self._inQueue.task_done()
            except Exception:
                pass

            if taskId < 0:
                break

            # 每轮都必须重置：否则异常路径会把上一轮的 QImage 当成这一页发出去
            newQ = None
            try:
                info = self.tasks.get(taskId)
                if not info:
                    continue

                Stats["task"] += 1
                Stats["lastLen"] = len(info.data) if info.data else 0

                if not info.data:
                    # 空数据只跳过这一个任务，绝不能 return(那会直接杀死工作线程)
                    Stats["null"] += 1
                    Stats["lastError"] = "empty data"
                    Log.Warn("task_qimage: empty data, skip taskId:{}".format(taskId))
                    continue

                # 分块还原("图片分割合成")：Android 上直接在 QImage 域里做 ——
                # p4a 编出来的 Pillow 没有 webp 解码器(JM 的图就是 webp)，走 PIL 必然
                # "cannot identify image file"，然后兜底返回被打乱的原图，用户看到的就是
                # "图片分割异常、图像错位"。这里和显示用同一套 Qt 解码器，还省掉
                # "还原→编码→再解码"的一次来回。桌面端行为不变(仍走 TaskMulti + PIL)。
                q = None
                if isinstance(info.saveParams, tuple) and len(info.saveParams) > 1:
                    epsId, scrambleId, pitureName = info.saveParams
                    if platform_mobile.IsAndroid():
                        q = self._SegmentQImage(info.data, epsId, scrambleId, pitureName)
                        if q is not None:
                            Stats["segQt"] += 1
                    if q is None:
                        info.data = TaskMulti().GetJmPicResultsResult(info.data, epsId, scrambleId, pitureName)
                        if info.data:
                            Stats["segBytes"] += 1
                if q is None and not info.data:
                    # TaskMulti 失败/超时返回 None；这里只当这一页失败，不能发图
                    Stats["fail"] += 1
                    Stats["lastError"] = "segmentation returned no data"
                    Log.Error("task_qimage: segmentation failed, taskId:{}".format(taskId))
                    info.data = None
                    continue

                newQ = self.ConverQImage(info, q)
                if newQ is None or newQ.isNull():
                    Stats["null"] += 1
                    Stats["lastError"] = "null QImage"
                    Log.Error("task_qimage: decode failed (null QImage), taskId:{} len:{} head:{}".format(
                        taskId, len(info.data) if info.data else 0, _HexHead(info.data)))
                    info.data = None
                    continue
                Stats["ok"] += 1

            except Exception as es:
                Stats["fail"] += 1
                Stats["lastError"] = str(es)
                Log.Error("task_qimage: taskId:{} error:{}".format(taskId, es))
                try:
                    info = self.tasks.get(taskId)
                    if info is not None:
                        info.data = None
                except Exception:
                    pass
                continue

            # 只有真正解出来的图片才回调，绝不发 None/上一页的图
            try:
                self.taskObj.imageBack.emit(taskId, newQ)
            except Exception as es:
                Log.Error("task_qimage: emit taskId:{} error:{}".format(taskId, es))

    def _SegmentQImage(self, data, epsId, scrambleId, pictureName):
        """ 用 Qt 把"被打乱的图"还原成能显示的 QImage；做不到返回 None """
        try:
            return ToolUtil.SegmentationQImage(data, epsId, scrambleId, pictureName)
        except Exception as es:
            Log.Error("task_qimage: SegmentationQImage error:{}".format(es))
            return None

    @time_me
    def ConverQImage(self, info, img=None):
        # img: 已经还原/解码好的 QImage(分割还原走 Qt 时直接用它，不再来回编解码)
        q = img
        if q is None or q.isNull():
            if not info.data:
                Log.Warn("task_qimage: ConverQImage with empty data")
                return None
            q = QImage()
            q.loadFromData(info.data)
            if q.isNull():
                # 数据仍是密文/下载不完整时的典型现象(真机上伴随一堆 PIL.UnidentifiedImageError)
                Log.Warn("task_qimage: invalid image data len:{} head:{}".format(
                    len(info.data), _HexHead(info.data)))
                return None
        q.setDevicePixelRatio(info.radio)
        if info.toW > 0:
            newQ = q.scaled(info.toW * info.radio, info.toH * info.radio, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            newQ = q
        return newQ

    def AddQImageTask(self, data, radio, toW, toH, model, saveParams, callBack=None, backParam=None, cleanFlag=None):
        self.taskId += 1
        info = QtQImageTask(self.taskId)
        info.callBack = callBack
        info.backParam = backParam
        info.data = data
        info.radio = radio
        info.toW = toW
        info.toH = toH
        info.model = model
        info.saveParams = saveParams

        self.tasks[self.taskId] = info
        if cleanFlag:
            info.cleanFlag = cleanFlag
            taskIds = self.flagToIds.setdefault(cleanFlag, set())
            taskIds.add(self.taskId)
        self._inQueue.put(self.taskId)
        return self.taskId

    def ClearQImageTaskById(self, taskId):
        if taskId in self.tasks:
            self.tasks.pop(taskId)

    def HandlerTask(self, taskId, newData):
        try:
            info = self.tasks.get(taskId)
            if not info:
                Log.Warn("[Task] not find taskId:{}".format(taskId))
                return
            assert isinstance(info, QtQImageTask)
            if info.cleanFlag:
                taskIds = self.flagToIds.get(info.cleanFlag, set())
                taskIds.discard(info.taskId)
            if info.callBack:
                if info.backParam is None:
                    info.callBack(newData)
                else:
                    info.callBack(newData, info.backParam)
                del info.callBack
            del self.tasks[taskId]
        except Exception as es:
            Log.Error(es)