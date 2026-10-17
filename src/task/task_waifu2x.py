import json
import os
import threading
import time
from zlib import crc32

from config import config
from config.setting import Setting
from task.qt_task import TaskBase
from task.task_multi import TaskMulti
from tools.log import Log
from tools.status import Status
from tools.str import Str
from tools.tool import CTime, ToolUtil


class QConvertTask(object):
    def __init__(self, taskId=0):
        self.taskId = taskId
        self.callBack = None       # addData, laveSize
        self.backParam = None
        self.cleanFlag = ""
        self.status = Status.Ok
        self.tick = 0
        self.loadPath = ""  #
        self.preDownPath = ""  #
        self.saveParams = ""  #
        self.noSaveCache = False
        self.cachePath = ""  #
        self.savePath = ""  #
        self.imgData = b""
        self.saveData = b""

        self.model = {
            "isForce":0,
            "model": 1,
            "scale": 2,
            "toH": 100,
            "toW": 100,
        }

class TaskWaifu2x(TaskBase):

    def __init__(self):
        TaskBase.__init__(self)
        self.taskObj.convertBack.connect(self.HandlerTask)
        self.thread.start()

        self.thread2 = threading.Thread(target=self.RunLoad2)
        self.thread2.setName("Task-" + str("Waifu2x"))
        self.thread2.setDaemon(True)

    def Start(self):
        self.thread2.start()
        return

    def Run(self):
        while True:
            taskId = self._inQueue.get(True)
            self._inQueue.task_done()
            if taskId == "":
                break

            task = self.tasks.get(taskId)
            if not task:
                continue
            assert isinstance(task, QConvertTask)
            try:
                assert isinstance(task, QConvertTask)
                isFind = False

                if task.cachePath:
                    data = ToolUtil.LoadCachePicture(task.cachePath)
                    if data:
                        task.saveData = data
                        self.taskObj.convertBack.emit(taskId)
                        continue

                if task.preDownPath:
                    data = ToolUtil.LoadCachePicture(task.preDownPath)
                    if data:
                        task.saveData = data
                        self.taskObj.convertBack.emit(taskId)
                        continue

                if task.savePath:
                    if ToolUtil.IsHaveFile(task.savePath):
                        self.taskObj.convertBack.emit(taskId)
                        continue

                if task.loadPath:
                    data = ToolUtil.LoadCachePicture(task.loadPath)
                    if data:
                        w, h, mat,_ = ToolUtil.GetPictureSize(data)
                        model = ToolUtil.GetDownloadScaleModel(w, h, mat)
                        if not task.model.get("isForce"):
                            task.model = model
                        task.imgData = data

                if not task.imgData:
                    task.status = Status.FileError
                    self.taskObj.convertBack.emit(taskId)
                    continue

                if isFind:
                    continue

                err = ""
                if config.CanWaifu2x:
                    if task.saveParams:
                        # 在线页是"打乱"的，超分前必须先还原(还原失败就别硬跑，
                        # 否则超分会作用在错位的像素上，出图也是花的)
                        data = TaskMulti().GetJmPicResultsResult(task.imgData, task.saveParams[0], task.saveParams[1], task.saveParams[2])
                        if not data:
                            Log.Warn("Waifu2x segment failed, taskId: {}, 跳过本页超分".format(str(task.taskId)))
                            task.status = Status.FileFormatError
                            self.taskObj.convertBack.emit(taskId)
                            continue
                        task.imgData = data

                    from sr_vulkan import sr_vulkan as sr
                    scale = task.model.get("scale", 0)
                    mat = task.model.get("format", "")
                    tileSize = Setting.Waifu2xTileSize.GetIndexV()
                    if scale <= 0:
                        sts = sr.add(task.imgData, task.model.get('model', 0), task.taskId, task.model.get("width", 0), task.model.get("high", 0), format=mat, tileSize=tileSize)
                    else:
                        sts = sr.add(task.imgData, task.model.get('model', 0), task.taskId, scale, format=mat, tileSize=tileSize)
                    Log.Info("[SRUI] sr.add taskId:{}, scale:{}, sts:{}, imgLen:{}B".format(
                        task.taskId, scale, sts, len(task.imgData) if task.imgData else 0))
                    if sts <= 0:
                        err = sr.getLastError()

                else:
                    sts = -1
                if sts <= 0:
                    task.status = Status.AddError
                    self.taskObj.convertBack.emit(taskId)
                    Log.Warn("Waifu2x convert error, taskId: {}, model:{}, err:{}".format(str(task.taskId), task.model,
                                                                                     str(err)))
                    continue
            except Exception as es:
                Log.Error(es)
                task.status = Status.PathError
                self.taskObj.convertBack.emit(taskId)
                continue

    def LoadData(self):
        if not config.CanWaifu2x:
            time.sleep(100)
            return None
        from sr_vulkan import sr_vulkan as sr
        return sr.load(0)

    def RunLoad2(self):
        while True:
            info = self.LoadData()
            if not info:
                break
            t1 = CTime()
            data, format, taskId, tick = info
            Log.Info("[SRUI] sr.load 拿到结果 taskId:{}, len:{}B, format:{}, tick:{:.2f}s".format(
                taskId, len(data) if data else 0, format, tick))
            info = self.tasks.get(taskId)
            tick = round(tick, 2)
            if not info:
                continue
            if not data:
                lenData = 0
            else:
                lenData = len(data)
            if lenData <= 0:
                info.status = Status.FileFormatError
                err = ""
                try:
                    if config.CanWaifu2x:
                        from sr_vulkan import sr_vulkan as sr
                        err = sr.getLastError() or ""
                except Exception:
                    err = ""
                Log.Warn("convert error, taskId: {}, dataLen:{}, sts:{} tick:{}, skip:{}, err:{}".format(
                    str(taskId), lenData, str(format), str(tick), str(Setting.IsSkipPic.value), str(err)))
                # 只有引擎没有明确报错(如偶发超时)时才允许用原图顶替；
                # 明确报错(模型文件缺失等)必须走错误状态——把原图当超分结果
                # 存盘，表现就是"超分没生效但任务显示成功"
                if info.savePath and Setting.IsSkipPic.value and not err:
                    info.status = Status.Ok
                    data = info.imgData

            assert isinstance(info, QConvertTask)
            info.saveData = data
            info.tick = tick
            try:
                if not info.noSaveCache:
                    for path in [info.cachePath, info.savePath]:
                        if path and not os.path.isdir(os.path.dirname(path)):
                            os.makedirs(os.path.dirname(path))

                        formatList = [".jpg", ".png", ".gif", ".webp", ".bmp", ".apng"]
                        if path and data:
                            if path[-4:] in formatList:
                                pass
                            elif path[-5:] in formatList:
                                pass
                            else:
                                path = path + "." + format
                            with open(path, "wb+") as f:
                                f.write(data)
            except Exception as es:
                info.status = Status.SaveError
                Log.Error(es)

            self.taskObj.convertBack.emit(taskId)
            t1.Refresh("RunLoad")

    def AddConvertTaskByData(self, path, imgData, model, callBack, backParam=None, preDownPath=None, noSaveCache=False, saveParams=None, cleanFlag=None):
        info = QConvertTask()
        info.callBack = callBack
        info.backParam = backParam
        self.taskId += 1
        self.tasks[self.taskId] = info
        info.taskId = self.taskId
        info.imgData = imgData
        info.model = model
        info.preDownPath = preDownPath
        info.noSaveCache = noSaveCache
        info.saveParams = saveParams
        # 超分结果一律进应用缓存目录(不再依赖"下载保存目录"是否设置)：
        # 手机上算一张 2x 页可能要好几秒甚至几十秒，翻走再翻回来必须能秒开，
        # 否则每次都要重算一遍，表现就是"超分一直没生效"。
        if not noSaveCache and path:
            a = crc32(json.dumps(model).encode("utf-8"))
            cachePath = os.path.join(Setting.GetCachePath(), config.Waifu2xPath, path)
            info.cachePath = cachePath + "-{}".format(a)

        if cleanFlag:
            info.cleanFlag = cleanFlag
            taskIds = self.flagToIds.setdefault(cleanFlag, set())
            taskIds.add(self.taskId)
        Log.Debug("add convert info, taskId:{}, cachePath:{}".format(info.taskId, info.cachePath))
        self._inQueue.put(self.taskId)
        return self.taskId

    def AddConvertTaskByPath(self, loadPath, savePath, callBack, backParam=None, cleanFlag=None):
        info = QConvertTask()
        info.loadPath = loadPath
        info.savePath = savePath
        info.callBack = callBack
        info.backParam = backParam
        self.taskId += 1
        self.tasks[self.taskId] = info
        info.taskId = self.taskId
        if cleanFlag:
            info.cleanFlag = cleanFlag
            taskIds = self.flagToIds.setdefault(cleanFlag, set())
            taskIds.add(self.taskId)
        Log.Debug("add convert info, loadPath:{}, savePath:{}".format(info.loadPath, info.savePath))
        self._inQueue.put(self.taskId)
        return self.taskId

    def AddConvertTaskByPathSetModel(self, loadPath, savePath, callBack, backParam=None, model=None, cleanFlag=None):
        info = QConvertTask()
        info.loadPath = loadPath
        info.savePath = savePath
        info.callBack = callBack
        info.backParam = backParam
        info.model = model
        self.taskId += 1
        self.tasks[self.taskId] = info
        info.taskId = self.taskId
        if cleanFlag:
            info.cleanFlag = cleanFlag
            taskIds = self.flagToIds.setdefault(cleanFlag, set())
            taskIds.add(self.taskId)
        Log.Debug("add convert info, loadPath:{}, savePath:{}".format(info.loadPath, info.savePath))
        self._inQueue.put(self.taskId)
        return self.taskId

    def HandlerTask(self, taskId, isCallBack=True):
        try:
            info = self.tasks.get(taskId)
            if not info:
                return

            assert isinstance(info, QConvertTask)
            info.callBack(info.saveData, info.status, info.backParam, info.tick)
            if info.cleanFlag:
                taskIds = self.flagToIds.get(info.cleanFlag, set())
                taskIds.discard(info.taskId)
            del self.tasks[taskId]
        except Exception as es:
            Log.Error(es)

    def ClearWaitConvertIds(self, taskIds):
        if not taskIds:
            return
        for taskId in taskIds:
            if taskId in self.tasks:
                del self.tasks[taskId]
        Log.Info("cancel wait convert taskId, {}".format(taskIds))
        if config.CanWaifu2x:
            from sr_vulkan import sr_vulkan as sr
            sr.removeWaitProc(list(taskIds))

    def Cancel(self, cleanFlag):
        taskIds = self.flagToIds.get(cleanFlag, set())
        if not taskIds:
            return
        removeIds = []
        for taskId in taskIds:
            if taskId in self.tasks:
                del self.tasks[taskId]
                removeIds.append(taskId)
        Log.Info("cancel convert taskId, {}".format(removeIds))
        self.flagToIds.pop(cleanFlag)
        if config.CanWaifu2x:
            from sr_vulkan import sr_vulkan as sr
            sr.remove(removeIds)

