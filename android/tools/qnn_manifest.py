# coding:utf-8
"""QNN 运行库清单 + 校验（构建期唯一事实来源）

为什么需要这个模块
------------------
libQnnHtp.so / libQnnSystem.so / libQnnHtpV*Stub.so 这些库来自
com.qualcomm.qti:qnn-runtime 这个 AAR，由 tools/wsl_fetch_qnn.sh 解包到
android/libs/<abi>/。而 android/libs/ 同时被两处排除：

  · .gitignore           —— 不进仓库
  · tools/wsl_sync.sh    —— 不参与 Windows -> WSL 的 rsync

结果：QNN 运行库只存在于"当初跑过 wsl_fetch_qnn.sh 的那棵树"里。
换一棵树构建（直接在 /mnt/c 上跑、WSL 目录被清、换了机器）就一个 QNN 库都
没有，而 patch_buildozer_spec.py 的 add_libs 是**按目录 glob** 生成的 ——
目录空 => add_libs 里没有 Qnn 条目 => APK 少库，buildozer 全程不报错。
装到真机上 QNN EP 起不来，超分静默退回 CPU，界面只提示"超分未使用 NPU"。

本模块负责把"缺库"从静默变成硬失败，并把清单收敛到一处：
    list       打印该目录里会被打进包的全部 .so（给 add_libs / local_libs 用）
    verify     校验必需库齐全、Stub/Skel 成对、ELF 架构与 ABI 对得上
    verify-apk 校验成品 APK 里真的带着这些库（打包后最后一道关）
    prune      可选裁剪（去 GPU/DSP/Prepare 与非目标 HTP 架构），减小 APK

用法示例
--------
    python android/tools/qnn_manifest.py verify --libs-dir android/libs/arm64-v8a
    python android/tools/qnn_manifest.py list   --libs-dir android/libs/arm64-v8a \
                                                --prefix libs/arm64-v8a
    python android/tools/qnn_manifest.py verify-apk --apk android/JMComic-arm64.apk
    python android/tools/qnn_manifest.py prune  --libs-dir android/libs/arm64-v8a \
                                                --keep 79               # 只留 V79
    python android/tools/qnn_manifest.py prune  --libs-dir android/libs/arm64-v8a --drop-optional

退出码：0 通过 / 1 库缺失或不合规 / 2 用法或环境错误
"""
from __future__ import annotations

import argparse
import os
import re
import struct
import sys
import zipfile

# ------------------------------------------------------------------ 清单定义
# 必需项：ORT 的 QNN EP 一定会 dlopen 这两个。
#   · libQnnHtp.so     —— backend_path 指的库，QnnInterface_getProviders 在里面
#   · libQnnSystem.so  —— QNN 系统接口，ORT 用 backend_path 的**目录部分**找它
#                         (见 onnxruntime qnn_backend_manager.cc: LoadQnnSystemLib)
CORE_LIBS = ("libQnnHtp.so", "libQnnSystem.so")

# HTP 架构号 -> 设备代次（Stub 跑在 CPU 侧，Skel 跑在 Hexagon DSP 侧）
HTP_ARCHS = (68, 69, 73, 75, 79, 81)
HTP_ARCH_HINT = {
    68: "骁龙 888 / 8 Gen1 之前",
    69: "骁龙 8 Gen1 / 8+ Gen1",
    73: "骁龙 8 Gen2",
    75: "骁龙 8 Gen3",
    79: "骁龙 8 Elite (SM8750)",
    81: "骁龙 8 Elite Gen5 (SM8850)",
}

# 真机上大概率用不到的胖库（80MB 的 Prepare + Adreno GPU/DSP 后端）
OPTIONAL_LIBS = ("libQnnHtpPrepare.so", "libQnnGpu.so",
                 "libQnnDsp.so", "libQnnDspV66Stub.so", "libQnnDspV66Skel.so")

# ELF e_machine
EM_AARCH64 = 183
EM_X86_64 = 62
EM_QDSP6 = 164      # Hexagon DSP 的 Skel 库：ELF32、machine 164

_ARCH_RE = re.compile(r"^libQnnHtpV(\d+)(Stub|Skel)\.so$")


def Stub(arch: int) -> str:
    return "libQnnHtpV{}Stub.so".format(arch)


def Skel(arch: int) -> str:
    return "libQnnHtpV{}Skel.so".format(arch)


# ------------------------------------------------------------------ ELF 探测
def ElfInfo(path_or_bytes):
    """返回 (class, machine) 或 None；class 2=ELF64 1=ELF32

    只读前 20 字节，不解符号表，够判断架构就行（判断错架构是"装完闪退"的
    经典事故：x86_64 的 .so 混进 arm64 包，安装器照收，运行期 linker 才报
    "is 64-bit instead of 32-bit" 之类，且只在新装的那台设备上出现）。
    """
    try:
        if isinstance(path_or_bytes, (bytes, bytearray)):
            head = bytes(path_or_bytes[:20])
        else:
            with open(path_or_bytes, "rb") as fp:
                head = fp.read(20)
    except OSError:
        return None
    if len(head) < 20 or head[:4] != b"\x7fELF":
        return None
    cls = head[4]
    machine = struct.unpack("<H", head[18:20])[0]
    return cls, machine


def ElfName(info) -> str:
    if info is None:
        return "非 ELF"
    cls, machine = info
    if machine == EM_AARCH64:
        return "arm64"
    if machine == EM_X86_64:
        return "x86_64"
    if machine == EM_QDSP6:
        return "hexagon-dsp32"
    return "machine={}".format(machine)


# ------------------------------------------------------------------ 目录校验
class Report(object):
    def __init__(self):
        self.fatal = []      # 会让 NPU 一定起不来的问题
        self.warn = []       # 能跑但值得处理的问题
        self.info = []

    def Ok(self) -> bool:
        return not self.fatal


def _AbiExpect(abi):
    """该 ABI 下"CPU 侧可加载的 .so"应有的 ELF 架构名"""
    return "arm64" if abi.startswith("arm64") else "x86_64"


def VerifyDir(libs_dir, abi="arm64-v8a", quiet=False):
    """校验 libs/<abi> 里的 QNN 运行库；返回 Report"""
    rep = Report()
    libs_dir = os.path.abspath(libs_dir)

    if not os.path.isdir(libs_dir):
        rep.fatal.append(
            "目录不存在: {}\n"
            "          原因：android/libs/ 被 .gitignore 与 tools/wsl_sync.sh 同时排除，\n"
            "                不会跟着仓库走，只有跑过 tools/wsl_fetch_qnn.sh 的树里才有。\n"
            "          修复：bash android/tools/wsl_fetch_qnn.sh --libs-dir {}".format(
                libs_dir, libs_dir))
        if not quiet:
            _PrintDirReport(rep, libs_dir, abi, [])
        return rep

    present = {n for n in os.listdir(libs_dir) if n.endswith(".so")}
    if not present:
        rep.fatal.append(
            "{} 里一个 .so 都没有\n"
            "          修复：bash android/tools/wsl_fetch_qnn.sh --libs-dir {}".format(
                libs_dir, libs_dir))
        if not quiet:
            _PrintDirReport(rep, libs_dir, abi, [])
        return rep

    # ---- 1. 必需库 ----
    for name in CORE_LIBS:
        if name not in present:
            rep.fatal.append(
                "缺少必需库 libs/{}/{}（ORT 的 QNN EP 找不到它，HTP 起不来 -> 回落 CPU）".format(
                    abi, name))

    # ---- 2. Stub / Skel 配对 ----
    stubs, skels = {}, {}
    for name in present:
        m = _ARCH_RE.match(name)
        if not m:
            continue
        arch = int(m.group(1))
        (stubs if m.group(2) == "Stub" else skels)[arch] = name

    if stubs or skels:
        for arch in sorted(set(stubs) | set(skels)):
            if arch not in stubs:
                rep.warn.append(
                    "有 {} 但没有 {}（该架构只会用到 Skel 的场景不存在，可删掉 Skel）".format(
                        Skel(arch), Stub(arch)))
            if arch not in skels:
                rep.fatal.append(
                    "有 {} 但没有配对的 {}：HTP 会在 stubInit 阶段失败\n"
                    "          影响：{}（{}）等机型 HTP 起不来".format(
                        Stub(arch), Skel(arch),
                        "、".join("V{}".format(a) for a in HTP_ARCHS if a >= arch),
                        HTP_ARCH_HINT.get(arch, "未知代次")))
        rep.info.append(
            "HTP 架构: {}".format(", ".join(
                "V{}({}{})".format(a, HTP_ARCH_HINT.get(a, "?"),
                                   "" if a in skels else "/缺Skel")
                for a in sorted(stubs))))
    else:
        rep.fatal.append(
            "一个 libQnnHtpV*Stub.so / *Skel.so 都没有："
            "libQnnHtp.so 运行时要按设备 HTP 架构 dlopen 对应的 Stub，缺了它 HTP 后端建不起来")

    # ---- 3. ELF 架构 ----
    expect = _AbiExpect(abi)
    for name in sorted(present):
        path = os.path.join(libs_dir, name)
        info = ElfInfo(path)
        got = ElfName(info)
        if info is None:
            rep.fatal.append("{}: 不是有效 ELF（下载/解包被截断？）".format(name))
            continue
        is_skel = name.endswith("Skel.so")
        want = "hexagon-dsp32" if is_skel else expect
        if got != want:
            rep.fatal.append(
                "{}: 架构是 {}，{} 包里应该是 {}{}".format(
                    name, got, abi, want,
                    "（Skel 是 32 位 Hexagon DSP 库，size 小且 ELF32 属正常）" if is_skel else ""))

    # ---- 4. 依赖链抽查 ----
    for name in ("libonnxruntime.so", "libsr_qnn.so"):
        if name not in present:
            rep.warn.append("{} 缺失（本脚本只管 QNN；它由 wsl_fetch_ort.sh / "
                            "wsl_build_native.sh 负责，超分后端会整体不可用）".format(name))

    if not quiet:
        _PrintDirReport(rep, libs_dir, abi, sorted(present))
    return rep


def _PrintDirReport(rep, libs_dir, abi, names):
    total = sum(os.path.getsize(os.path.join(libs_dir, n)) for n in names
                if os.path.isfile(os.path.join(libs_dir, n)))
    print("QNN 库目录: {} ({}, {} 个 .so, {:.1f} MB)".format(
        libs_dir, abi, len(names), total / 1024.0 / 1024.0))
    for line in rep.info:
        print("  [信息] " + line)
    for line in rep.warn:
        print("  [注意] " + line)
    for line in rep.fatal:
        print("  [致命] " + line)
    print("  [{}] 校验{}".format("OK" if rep.Ok() else "FAIL",
                                "通过" if rep.Ok() else "失败：NPU 加速不可用"))


# ------------------------------------------------------------------ APK 校验
def VerifyApk(apk, abi="arm64-v8a", quiet=False):
    """校验成品 APK 的 lib/<abi>/ 里确实带着 QNN 运行库"""
    rep = Report()
    if not os.path.isfile(apk):
        rep.fatal.append("找不到 APK: {}".format(apk))
        return rep
    prefix = "lib/{}/".format(abi)
    with zipfile.ZipFile(apk) as z:
        names = [n for n in z.namelist() if n.startswith(prefix) and n.endswith(".so")]
        base = {n[len(prefix):]: n for n in names}
        # 包内库的架构也必须对（安装器不校验，运行期才炸）
        arch_bad = []
        not_elf = []
        for name in sorted(base):
            if name.endswith("Skel.so"):
                continue          # DSP 侧库，ELF32 Hexagon，跳过
            with z.open(base[name]) as fp:
                info = ElfInfo(fp.read(20))
            got = ElfName(info)
            if info is None:
                # p4a 会把 python 字节码包命名成 libpybundle.so（其实是 gzip），
                # 这类"挂羊头"的条目不是可加载 ELF，跳过即可
                not_elf.append(name)
                continue
            if got != _AbiExpect(abi):
                arch_bad.append("{} ({})".format(name, got))
        if not quiet:
            print("APK: {} ({} 字节)".format(os.path.basename(apk), os.path.getsize(apk)))
            print("  lib/{} 下 {} 个 .so".format(abi, len(names)))
            if not_elf:
                print("  (非 ELF 条目已跳过: {})".format(", ".join(not_elf)))

    if abi.startswith("arm64"):
        for name in CORE_LIBS:
            if name not in base:
                rep.fatal.append(
                    "APK 里没有 {}：该包在真机上一定退回 CPU（界面提示"
                    "\"超分未使用 NPU\"）".format(prefix + name))
        if not any(_ARCH_RE.match(n) and n.endswith("Stub.so") for n in base):
            rep.fatal.append("APK 里没有任何 libQnnHtpV*Stub.so，HTP 后端无法初始化")
        for name in ("libsr_qnn.so", "libsr_qnn_proc.so"):
            if name not in base:
                rep.fatal.append(
                    "APK 里没有 {}（{}）".format(
                        prefix + name,
                        "超分后端本体" if name == "libsr_qnn.so" else
                        "进程模式宿主：QNN 需要它才能拿到 /vendor/lib64 的 libcdsprpc"))
    if arch_bad:
        rep.fatal.append("包内架构与 {} 不符: {}".format(abi, ", ".join(arch_bad)))

    if not quiet:
        qnn = sorted(n for n in base if n.startswith("libQnn"))
        print("  QNN 库 {} 个: {}".format(len(qnn), ", ".join(qnn) or "<无>"))
        for line in rep.fatal:
            print("  [致命] " + line)
        print("  [{}] {}".format(
            "OK" if rep.Ok() else "FAIL",
            ("包内 QNN 运行库齐全" if rep.Ok() else "包内缺 QNN 运行库")
            if abi.startswith("arm64") else "原生库架构正确"))
    return rep


# ------------------------------------------------------------------ 裁剪
def Prune(libs_dir, keep=(), drop_optional=False, dry=False):
    """删掉用不到的胖库，减小 APK（默认不动，只有显式调用才裁剪）

    keep 为空时保留全部 HTP 架构；给了 keep 就只留这些架构的 Stub/Skel。
    被删的文件名会打印出来，可重复执行（幂等）。
    """
    removed = []
    keep_set = {int(a) for a in keep} if keep else set()
    for name in sorted(os.listdir(libs_dir)):
        if not name.endswith(".so"):
            continue
        path = os.path.join(libs_dir, name)
        drop = False
        m = _ARCH_RE.match(name)
        if m and keep_set and int(m.group(1)) not in keep_set:
            drop = True
        elif drop_optional and name in OPTIONAL_LIBS:
            drop = True
        if not drop:
            continue
        removed.append((name, os.path.getsize(path)))
        if not dry:
            os.remove(path)
    total = sum(sz for _, sz in removed) / 1024.0 / 1024.0
    print("{} {:.1f} MB:".format("将删除" if dry else "已删除", total))
    for name, sz in removed:
        print("  - {} ({:.1f} MB)".format(name, sz / 1024.0 / 1024.0))
    if not removed:
        print("  (无需裁剪)")
    return removed


# ------------------------------------------------------------------ CLI
def main(argv):
    parser = argparse.ArgumentParser(
        description="QNN 运行库清单/校验(构建期唯一事实来源)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="打印会被打进包的 .so 列表")
    p_list.add_argument("--libs-dir", required=True)
    p_list.add_argument("--prefix", default="", help="输出前缀，如 libs/arm64-v8a")
    p_list.add_argument("--sep", default=",", help="分隔符(默认逗号，给 buildozer 用)")

    p_ver = sub.add_parser("verify", help="校验库目录")
    p_ver.add_argument("--libs-dir", required=True)
    p_ver.add_argument("--abi", default=os.environ.get("JM_ABI", "arm64-v8a"))
    p_ver.add_argument("--quiet", action="store_true")

    p_apk = sub.add_parser("verify-apk", help="校验 APK 里的 QNN 运行库")
    p_apk.add_argument("--apk", required=True)
    p_apk.add_argument("--abi", default=os.environ.get("JM_ABI", "arm64-v8a"))
    p_apk.add_argument("--quiet", action="store_true")

    p_prune = sub.add_parser("prune", help="裁剪用不到的库")
    p_prune.add_argument("--libs-dir", required=True)
    p_prune.add_argument("--keep", default="", help="只保留这些 HTP 架构，如 79 或 79,81")
    p_prune.add_argument("--drop-optional", action="store_true",
                         help="同时删掉 Prepare/Gpu/Dsp 等可选胖库")
    p_prune.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "list":
        if not os.path.isdir(args.libs_dir):
            sys.stderr.write("qnn_manifest: 目录不存在: {}\n".format(args.libs_dir))
            return 1
        names = sorted(n for n in os.listdir(args.libs_dir) if n.endswith(".so"))
        items = [os.path.join(args.prefix, n) if args.prefix else n for n in names]
        print(args.sep.join(items), end="")
        return 0 if names else 1

    if args.cmd == "verify":
        rep = VerifyDir(args.libs_dir, args.abi, args.quiet)
        return 0 if rep.Ok() else 1

    if args.cmd == "verify-apk":
        rep = VerifyApk(args.apk, args.abi, args.quiet)
        return 0 if rep.Ok() else 1

    if args.cmd == "prune":
        keep = [s for s in args.keep.replace(" ", ",").split(",") if s.isdigit()]
        Prune(args.libs_dir, keep=keep, drop_optional=args.drop_optional,
              dry=args.dry_run)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
