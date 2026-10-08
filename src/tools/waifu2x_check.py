# coding:utf-8
""" waifu2x(sr_vulkan) 初始化探测

sr_vulkan 在部分显卡/驱动环境下调用 initSet() 会直接让进程崩溃(0xC0000005)或者卡死，
这种问题在进程内无法用 try/except 捕获，会导致整个程序启动就崩溃/卡住。
所以这里先在子进程里做一次初始化验证，验证不通过就自动禁用超分功能，
保证程序仍然能正常启动(用户可在设置里重新选择显卡/线程后再试)。
"""
import os
import subprocess
import sys
import tempfile
import time

from tools.log import Log

# 自动选择显卡时，优先使用 NVIDIA/AMD 独显
DiscreteGpuKeys = ("nvidia", "geforce", "rtx", "gtx", "quadro", "radeon", "amd")


class Waifu2xChecker:
    # 探测子进程整体超时时间(秒)：单文件版子进程需要重新解压，给足时间
    TimeOut = 90
    # 进入 initSet 阶段后的超时(秒)：正常几毫秒到几秒就有结果，超时说明驱动卡死
    InitSetTimeOut = 8
    # 探测子进程参数
    ProbeArg = "--sr-probe"

    @staticmethod
    def PreferGpuId(gpuList):
        """ 自动选择显卡：优先独显，其次第一个 """
        if not gpuList:
            return -1
        for index, name in enumerate(gpuList):
            lower = str(name).lower()
            for key in DiscreteGpuKeys:
                if key in lower:
                    return index
        return 0

    @staticmethod
    def MakeKey(gpuName, cpuNum):
        return "{}|{}".format("" if gpuName is None else str(gpuName), int(cpuNum or 0))

    @staticmethod
    def SaveCheckKey(gpuName, cpuNum, gpuId, realCpuNum):
        """ 记录验证通过的配置，下次启动可以直接初始化(不用再探测) """
        try:
            from config.setting import Setting
            Setting.Waifu2xCheckKey.SetValue("{}|{}|{}|ok".format(
                Waifu2xChecker.MakeKey(gpuName, cpuNum), int(gpuId), int(realCpuNum)))
        except Exception as es:
            Log.Error(es)

    @staticmethod
    def ClearCheckKey():
        try:
            from config.setting import Setting
            if Setting.Waifu2xCheckKey.value:
                Setting.Waifu2xCheckKey.SetValue("")
        except Exception as es:
            Log.Error(es)

    def Check(self, gpuName, cpuNum):
        """ 返回 (是否可用, gpuId, 实际使用的cpuNum, 失败原因) """
        gpuName = "" if gpuName is None else str(gpuName)
        cpuNum = int(cpuNum or 0)

        # 上次同样的配置初始化成功过，直接使用结果
        try:
            from config.setting import Setting
            parts = (Setting.Waifu2xCheckKey.value or "").split("|")
            if len(parts) == 5 and parts[4] == "ok" and \
                    "{}|{}".format(parts[0], parts[1]) == self.MakeKey(gpuName, cpuNum):
                # 先清掉记录：本次初始化如果崩溃了，下次启动会重新探测
                self.ClearCheckKey()
                Log.Info("Waifu2x check: use cached result, gpuId:{}, cpuNum:{}".format(parts[2], parts[3]))
                return True, int(parts[2]), int(parts[3]), ""
        except Exception as es:
            Log.Error(es)

        self.ClearCheckKey()
        return self.RunProbe(gpuName, cpuNum)

    @staticmethod
    def WriteResult(resultPath, text):
        """ 原子写入探测结果(父进程会轮询读取) """
        try:
            tmpPath = resultPath + ".tmp"
            with open(tmpPath, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmpPath, resultPath)
        except Exception:
            pass

    def RunProbe(self, gpuName, cpuNum):
        """ 在子进程里试一次初始化 """
        resultPath = os.path.join(tempfile.gettempdir(), "jmcomic_sr_probe_{}.txt".format(os.getpid()))
        try:
            if os.path.exists(resultPath):
                os.remove(resultPath)
        except Exception as es:
            Log.Error(es)

        proc = None
        result = ""
        code = None
        try:
            proc = subprocess.Popen(self.MakeCommand(gpuName, cpuNum, resultPath),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.time() + Waifu2xChecker.TimeOut
            initSetTick = None
            while True:
                text = ""
                try:
                    if os.path.exists(resultPath):
                        with open(resultPath, "r", encoding="utf-8") as f:
                            text = f.read().strip()
                except Exception:
                    text = ""
                if text.startswith("OK|") or text.startswith("ERR|"):
                    result = text
                    break
                if text == "phase=initSet":
                    # 已经进入底层初始化，正常几秒内就有结果
                    if initSetTick is None:
                        initSetTick = time.time()
                    elif time.time() - initSetTick > Waifu2xChecker.InitSetTimeOut:
                        Log.Warn("waifu2x check: initSet 卡住, 结束探测进程")
                        break
                if proc.poll() is not None:
                    code = proc.returncode
                    break
                if time.time() > deadline:
                    Log.Warn("waifu2x check: 探测进程超时")
                    break
                time.sleep(0.2)
        except Exception as es:
            Log.Error(es)
        finally:
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception as es:
                    Log.Error(es)
            try:
                if os.path.exists(resultPath):
                    os.remove(resultPath)
                if os.path.exists(resultPath + ".tmp"):
                    os.remove(resultPath + ".tmp")
            except Exception as es:
                Log.Error(es)

        Log.Info("waifu2x check probe: exit:{}, result:{}".format(code, result))
        parts = result.split("|")
        if len(parts) == 3 and parts[0] == "OK":
            return True, int(parts[1]), int(parts[2]), ""
        return False, 0, 0, "sr_vulkan 初始化失败，已自动禁用超分功能(GPU/驱动异常)"

    @staticmethod
    def MakeCommand(gpuName, cpuNum, resultPath):
        args = [Waifu2xChecker.ProbeArg, str(gpuName), str(cpuNum), resultPath]
        if getattr(sys, "frozen", False):
            return [sys.executable] + args
        startPy = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "start.py")
        return [sys.executable, startPy] + args

    @staticmethod
    def ProbeMain(gpuName, cpuNum, resultPath):
        """ 子进程入口(start.py 中调用)：--sr-probe <显卡名> <cpu线程数> <结果文件> """
        Waifu2xChecker.WriteResult(resultPath, "phase=import")
        try:
            from sr_vulkan import sr_vulkan as sr
            Waifu2xChecker.WriteResult(resultPath, "phase=init")
            stat = sr.init()
            gpuList = sr.getGpuInfo() or []
            gpuId = -1
            if gpuName and gpuName in gpuList:
                gpuId = gpuList.index(gpuName)
            elif gpuList:
                gpuId = Waifu2xChecker.PreferGpuId(gpuList)

            realCpuNum = int(cpuNum or 0)
            coreNum = sr.getCpuCoreNum()
            if coreNum and realCpuNum > coreNum:
                realCpuNum = coreNum

            if stat < 0:
                Waifu2xChecker.WriteResult(resultPath, "ERR|init={}".format(stat))
            else:
                Waifu2xChecker.WriteResult(resultPath, "phase=initSet")
                sts = sr.initSet(gpuId, realCpuNum)
                if sts >= 0:
                    Waifu2xChecker.WriteResult(resultPath, "OK|{}|{}".format(gpuId, realCpuNum))
                else:
                    Waifu2xChecker.WriteResult(resultPath, "ERR|initSet={}".format(sts))
        except Exception as es:
            Waifu2xChecker.WriteResult(resultPath, "ERR|{}".format(es))
        # 直接退出，避免底层库在析构时崩溃
        os._exit(0)
