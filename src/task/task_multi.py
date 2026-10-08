from multiprocessing import Process, Queue
import  multiprocessing
import threading
from queue import Queue as ThreadQueue
from queue import Empty as QueueEmpty
from config.setting import Setting
from task.qt_task import TaskBase
from tools import platform_mobile
from tools.log import Log
from tools.tool import ToolUtil


# 等空闲 worker 槽位 / 等结果的上限：这两个 get 原来是无限阻塞的，
# 一旦 worker 数为 0 或 worker 死了，看图线程就永远卡在这里(界面看起来像卡死)。
SLOT_TIMEOUT = 20.0
RESULT_TIMEOUT = 60.0
# Android 上线程太多只会互相抢 GIL
ANDROID_MAX_WORKERS = 8


# 定义消费者函数
def consumer(num, queue, finishQue):
    print(f"start consumer multiprocess, index:{num}")
    while True:
        item = queue.get()
        if item is None:
            break  # 结束信号
        try:
            (taskType, args) = item
            if taskType == TaskMulti.MultiTaskSegment:
                result = ToolUtil.SegmentationPicture(*args)
            elif taskType == TaskMulti.MultiTaskSegmentToDisk:
                result = ToolUtil.SegmentationPictureToDisk(*args)
            else:
                result = None
            finishQue.put(result)
        except Exception as es:
            print("error, es:{}".format(es))
            finishQue.put(None)

        # print(f"finish consumer multiprocess, index:{num}")


# 多进程
class TaskMulti(TaskBase):
    MultiTaskSegment = 1
    MultiTaskSegmentToDisk = 2

    def __init__(self) -> None:
        TaskBase.__init__(self)
        self.multi_list = []
        self.threadList = []
        self.startNum = 0
        self.queueList = []
        self.queueFinishList = []
        self.allMultiState = {}

    def Start(self):
        # 幂等：TaskMulti 是单例，Start() 被重复调用时绝不能再起一批 worker，
        # 否则 _inQueue 里会出现重复槽位、结果队列也会错位。
        if self.queueList or self.threadList or self.multi_list:
            Log.Warn("TaskMulti: already started, skip")
            return
        # Android 的应用进程里 fork/多进程不稳定(python-for-android)，改用线程 +
        # 纯 python 队列(完全不碰 multiprocessing)；拼图用的是 PIL，重活会释放 GIL。
        # 桌面端行为不变(仍用多进程)。
        useThread = platform_mobile.IsAndroid()
        if useThread:
            # MultiNum 是用户可改的设置，误触成 0 会让"取图→分割"永远没人处理；
            # 这里强制至少 1 个 worker，并封顶避免线程过多抢 GIL。
            try:
                num = int(Setting.MultiNum.value or 0)
            except (TypeError, ValueError):
                num = 0
            num = min(ANDROID_MAX_WORKERS, max(1, num))
        else:
            num = Setting.MultiNum.value
        for i in range(num):
            if useThread:
                queue = ThreadQueue()
                queue2 = ThreadQueue()
            else:
                queue = Queue()
                queue2 = Queue()
            self.queueList.append(queue)
            self.queueFinishList.append(queue2)
            if useThread:
                thread = threading.Thread(target=consumer, args=(i, queue, queue2), daemon=True)
                thread.start()
                self.threadList.append(thread)
            else:
                process = Process(target=consumer, args=(i, queue, queue2), daemon=True)
                process.start()
                self.multi_list.append(process)
            self._inQueue.put(i)
        self.startNum = num
        Log.Warn("TaskMulti: {} workers ({})".format(num, "thread" if useThread else "process"))

    def Stop(self):
        for queue in self.queueList:
            queue.put(None)
            self._inQueue.put(-1)
        # for process in self.multi_list:
        #     process.stop()
        return

    def _GetFreeWorker(self, timeout=SLOT_TIMEOUT):
        """ 取一个空闲 worker 槽位；取不到返回 None(调用方已把 None 当失败处理)，绝不抛异常 """
        try:
            index = self._inQueue.get(True, timeout)
        except QueueEmpty:
            Log.Error("TaskMulti: no free worker in {}s (workers={})".format(timeout, len(self.queueList)))
            return None
        except Exception as es:
            Log.Error("TaskMulti: get free worker error:{}".format(es))
            return None
        if index is None or index < 0:
            # Stop() 塞进来的结束信号：返回失败，但绝不能在这里永久阻塞
            Log.Error("TaskMulti: no worker available, index:{}".format(index))
            return None
        return index

    def _GetWorkerResult(self, index, timeout=RESULT_TIMEOUT):
        """ 等 worker 结果；超时/异常返回 None，绝不抛异常 """
        try:
            return self.queueFinishList[index].get(True, timeout)
        except QueueEmpty:
            Log.Error("TaskMulti: wait result timeout {}s, worker:{}".format(timeout, index))
            return None
        except Exception as es:
            Log.Error("TaskMulti: wait result error:{}, worker:{}".format(es, index))
            return None

    def _PutFreeWorker(self, index):
        try:
            self._inQueue.put(index)
        except Exception as es:
            Log.Error("TaskMulti: put back worker error:{}, index:{}".format(es, index))

    def GetJmPicResultsResult(self, imgData, saveParam1, saveParam2, saveParam3):
        index = self._GetFreeWorker()
        if index is None:
            return None
        try:
            self.queueList[index].put((TaskMulti.MultiTaskSegment, (imgData, saveParam1, saveParam2, saveParam3)))
            result = self._GetWorkerResult(index)
        except Exception as es:
            Log.Error("TaskMulti: submit segment task error:{}".format(es))
            result = None
        finally:
            # 槽位必须还回去，否则队列很快就不平衡了(原来超时路径根本走不到这里)
            self._PutFreeWorker(index)
        return result

    def SaveJmPicResultsResult(self, imgData, saveParam1, saveParam2, saveParam3, path, format):
        index = self._GetFreeWorker()
        if index is None:
            return None
        try:
            self.queueList[index].put((TaskMulti.MultiTaskSegmentToDisk, (imgData, saveParam1, saveParam2, saveParam3, path, format)))
            result = self._GetWorkerResult(index)
        except Exception as es:
            Log.Error("TaskMulti: submit segment-to-disk task error:{}".format(es))
            result = None
        finally:
            self._PutFreeWorker(index)
        return result
