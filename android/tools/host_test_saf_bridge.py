# coding:utf-8
""" 宿主自检：SAF 桥的"文件信箱"协议(Python 侧)

真机上 Python 与 Java 靠 <filesDir>/saf/{inbox,outbox} 里的 JSON 文件通信，
这里用一个假 Service 线程代替 Java 侧，把协议的每条路径都跑一遍：

    ping / pick(file, tree) / copyIn / copyOut / writeFile / open(sandbox)

为什么值得单独测：这条链路一旦错位(文件名、字段名、ok/cancel 语义)，
真机上只会表现成"点了选目录没反应"，没有任何栈可看。

用法：python3 android/tools/host_test_saf_bridge.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

from tools import platform_mobile  # noqa: E402
from tools import saf_bridge  # noqa: E402

Root = tempfile.mkdtemp(prefix="jm_saf_")
Failures = []


def Check(ok, name):
    print("  {} {}".format("OK  " if ok else "FAIL", name))
    if not ok:
        Failures.append(name)


# ---------------------------------------------------------------------------
# 假 Service：轮询 inbox，按 op 写 outbox
# ---------------------------------------------------------------------------

class FakeService(threading.Thread):
    def __init__(self, root):
        threading.Thread.__init__(self)
        self.daemon = True
        self.root = root
        self.inbox = os.path.join(root, "saf", "inbox")
        self.outbox = os.path.join(root, "saf", "outbox")
        os.makedirs(self.inbox, exist_ok=True)
        os.makedirs(self.outbox, exist_ok=True)
        self.running = True
        self.seen = []

    def run(self):
        while self.running:
            names = sorted(n for n in os.listdir(self.inbox) if n.endswith(".json"))
            for name in names:
                path = os.path.join(self.inbox, name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        request = json.load(f)
                except Exception:
                    continue
                try:
                    os.remove(path)
                except Exception:
                    pass
                self.seen.append(request.get("op"))
                self.Handle(request)
            time.sleep(0.02)

    def Handle(self, request):
        op = request.get("op")
        result = {"ok": True}
        if op == "ping":
            result["pid"] = 1234
        elif op == "pick":
            kind = request.get("kind")
            if kind == "tree":
                result.update({"uri": "content://tree/demo", "name": "JMComic"})
                self.Write(request, result)
                return
            # 单文件：模拟 Java 侧"拷进 copyTo 并返回本地路径"
            target = request.get("copyTo") or self.root
            os.makedirs(target, exist_ok=True)
            local = os.path.join(target, "picked.jpg")
            with open(local, "wb") as f:
                f.write(b"jpeg-bytes")
            result.update({"uri": "content://doc/1", "name": "picked.jpg", "path": local})
        elif op == "copyIn":
            target = request.get("to")
            os.makedirs(target, exist_ok=True)
            for index in range(3):
                with open(os.path.join(target, "p{}.jpg".format(index)), "wb") as f:
                    f.write(b"x")
            result.update({"path": target, "count": 3})
        elif op == "copyOut":
            result["count"] = 2
        elif op == "writeFile":
            result["uri"] = request.get("uri")
        elif op == "open":
            path = request.get("path") or ""
            if ".files" in path or "/data/" in path:
                result = {"ok": False, "reason": "sandbox"}
            else:
                result = {"ok": True}
        self.Write(request, result)

    def Write(self, request, result):
        target = os.path.join(self.outbox, request.get("id", "") + ".json")
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(result, f)
        os.replace(tmp, target)


def PatchPlatform(root):
    """ 把 platform_mobile 伪装成 Android(宿主上没有这些) """
    platform_mobile.IsAndroid = lambda: True
    platform_mobile.IsMobile = lambda: True
    platform_mobile.GetAppDataDir = lambda: root
    platform_mobile.GetAndroidPackage = lambda: "org.jmcomic.jmcomic"
    saf_bridge._ready = True            # 跳过 am 启 Service(宿主上没有 am)


def Main():
    print("== SAF 信箱协议自检 (root={})".format(Root))
    PatchPlatform(Root)
    service = FakeService(Root)
    service.start()

    # 1) ping
    data = saf_bridge._Call("ping", {}, 5.0)
    Check(bool(data and data.get("ok")), "ping 有回包")

    # 2) 选单个文件 -> 落地成本地路径
    picked = saf_bridge.PickFile("自检", "Image Files(*.jpg)")
    Check(isinstance(picked, tuple) and os.path.isfile(picked[0]), "PickFile 返回本地可读路径")
    Check(picked and picked[1] == "picked.jpg", "PickFile 带回显示名")

    # 3) 选目录(不拷贝) -> uri + 名字
    tree = saf_bridge.PickTree("自检")
    Check(bool(tree and tree.get("uri", "").startswith("content://")), "PickTree 返回 tree uri")

    # 4) 选目录 + 拷贝 -> 本地目录里有文件
    target = os.path.join(Root, "import", "demo")
    copied = saf_bridge.CopyTreeIn(tree.get("uri"), target)
    Check(bool(copied and len(os.listdir(target)) == 3), "CopyTreeIn 把文件拷进本地目录")

    # 5) 导出
    out = saf_bridge.CopyTreeOut(target, tree.get("uri"), "书/第1话", wait=True)
    Check(bool(out and out.get("ok")), "CopyTreeOut 走通(投递+回执)")

    # 6) 另存为写文件
    local = os.path.join(Root, "save.jpg")
    with open(local, "wb") as f:
        f.write(b"x")
    Check(saf_bridge.WriteFile("content://doc/9", local), "WriteFile 回执 ok")

    # 7) 打开目录：应用专属目录 -> sandbox(界面据此给提示)
    ok, reason = saf_bridge.OpenPath("/data/user/0/org.jmcomic.jmcomic/files/commies")
    Check((not ok) and reason == "sandbox", "OpenPath 应用私有目录报 sandbox")
    ok, reason = saf_bridge.OpenPath("/storage/emulated/0/Download")
    Check(ok, "OpenPath 普通目录可以交给系统")

    # 8) 取消语义：pick 返回 cancel 时 PickFile 必须是 False(而不是 None)
    def CancelNext():
        original = service.Handle

        def Handle(request):
            if request.get("op") == "pick":
                service.Write(request, {"ok": False, "cancel": True})
                return
            original(request)
        return Handle
    service.Handle = CancelNext()
    Check(saf_bridge.PickFile("自检") is False, "取消时 PickFile 返回 False(不再回落弹窗)")
    Check(saf_bridge.PickTree("自检") is False, "取消时 PickTree 返回 False")

    service.running = False
    time.sleep(0.1)
    print("== 请求序列: {}".format(service.seen))
    if Failures:
        print("!! {} 项失败: {}".format(len(Failures), ", ".join(Failures)))
        return 1
    print("== 全部通过")
    return 0


if __name__ == "__main__":
    try:
        code = Main()
    finally:
        shutil.rmtree(Root, ignore_errors=True)
    sys.exit(code)
