# coding:utf-8
"""16 KB 页面大小对齐门禁：检查 APK / 目录里的原生库是否满足 16 KB 页要求

背景
------------------------------------------------------------------
Android 15 起系统可以跑在 16 KB 页上，这类设备要求 .so 的 ELF `PT_LOAD` 段按
16 KB 对齐（`p_align >= 0x4000`，且 `p_offset` 与 `p_vaddr` 对 16 KB 同余）。
不满足时：

  * 系统把应用塞进 "16 KB 向后兼容模式"（bionic 走 linker_phdr_16kib_compat
    路径重映射段；复杂布局还要 memfd 双映射 + SIGSEGV 模拟），首次启动弹警告；
  * Android 17 可以把兼容模式设成 fatal（`bionic.linker.16kb.app_compat.enabled=fatal`），
    这时不合规的库直接 SIGABRT，表现为"装完即闪退"；
  * Google Play 对 targetSdk>=35 的更新自 2025-11 起强制要求 16 KB 兼容。

所以"能跑"和"合规"是两件事：靠人肉记忆必然漏，必须在打包后自动判定。

判定口径
------------------------------------------------------------------
1. `PT_LOAD` 的 `p_align` 必须 >= 阈值（默认 16384）
2. 文件偏移与虚拟地址必须对阈值同余（`(p_offset - p_vaddr) % align == 0`），
   否则 mmap 无法把段直接映射进 16 KB 页
3. `p_filesz == 0` 的段跳过第 2 条（纯 bss 占位段不读文件，lld 常用来占位对齐）
4. 32 位 ELF 跳过：它们不进 64 位进程，bionic 不做这项校验。典型是 QNN 的
   Hexagon skel（e_machine=164），由 DSP RPC 加载
5. 非 ELF 的 `.so`（打包成 .so 的数据文件，如 libpybundle.so）跳过并单独列出
6. 若原生库在包内是未压缩存储（extractNativeLibs=false），额外校验 ZIP 数据
   偏移是否落在 16 KB 边界（等价于 `zipalign -c -P 16`）

用法
------------------------------------------------------------------
    python tools/check_elf_page_align.py <apk|aab|目录|单个.so> [选项]

    --abi arm64-v8a|x86_64   只查某个 ABI（默认自动识别全部）
    --min-align 16384        对齐阈值（默认 16384；传 4096 可做 4KB 对照）
    --json                   输出 JSON（CI 用）
    --soft                   只报不拦（返回 0，用于过渡期）
    --list-ok                连通过的库也逐条列出

退出码: 0 全部通过 / 1 存在不合规 / 2 参数或输入有问题
"""
import argparse
import json
import os
import struct
import sys
import zipfile

ELF_MAGIC = b"\x7fELF"
PT_LOAD = 1
PT_GNU_RELRO = 0x6474E552
EM_HEXAGON = 164
MACHINE_NAMES = {62: "x86_64", 183: "aarch64", 164: "hexagon", 40: "arm", 3: "i386"}

DEFAULT_ALIGN = 16384
# 先读这么多，不够再翻倍重读（程序头表基本都在文件头几 KB 内，避免全量解压 500MB）
PREFIX_BYTES = 128 * 1024


class ElfError(Exception):
    pass


# ------------------------------------------------------------------ ELF 解析
def ParseElf(buf):
    """解析 ELF 头。返回 dict；非 ELF 返回 None；头部不完整抛 ElfError"""
    if len(buf) < 52 or buf[:4] != ELF_MAGIC:
        return None
    bits = {1: 32, 2: 64}.get(buf[4])
    if bits is None:
        return None
    machine = struct.unpack_from("<H", buf, 0x12)[0]
    if bits == 64:
        phoff = struct.unpack_from("<Q", buf, 0x20)[0]
        phentsize, phnum = struct.unpack_from("<HH", buf, 0x36)
    else:
        phoff = struct.unpack_from("<I", buf, 0x1C)[0]
        phentsize, phnum = struct.unpack_from("<HH", buf, 0x2A)
    if phnum == 0 or phnum > 1024 or phentsize not in (32, 56):
        raise ElfError("程序头表异常(phnum={}, phentsize={})".format(phnum, phentsize))
    if phoff + phnum * phentsize > len(buf):
        raise ElfError("程序头表超出已读缓冲区")
    return {"bits": bits, "machine": machine, "phoff": phoff,
            "phentsize": phentsize, "phnum": phnum}


def ParseSegments(buf, meta):
    """返回 [(p_offset, p_vaddr, p_filesz, p_memsz, p_align) for PT_LOAD]"""
    loads = []
    for i in range(meta["phnum"]):
        off = meta["phoff"] + i * meta["phentsize"]
        if struct.unpack_from("<I", buf, off)[0] != PT_LOAD:
            continue
        if meta["bits"] == 64:
            vals = struct.unpack_from("<QQQQQQ", buf, off + 8)
        else:
            vals = struct.unpack_from("<IIIIII", buf, off + 4)
        loads.append(vals)  # offset, vaddr, paddr, filesz, memsz, align
    return [(v[0], v[1], v[3], v[4], v[5]) for v in loads]


def CheckElf(segments, align):
    """返回 (是否合规, 最小 p_align, 不合规段, 可疑段)

    两档判定，刻意分开：
      * 不合规：有 PT_LOAD 的 p_align < 阈值 -> bionic 会明确判为"对齐小于系统页大小"，
        16KB 设备上只能走兼容模式（fatal 模式下直接 abort）。这是硬失败。
      * 可疑：p_align 达标，但文件偏移与虚拟地址对阈值不同余 -> 段无法直接 mmap，
        也可能加载失败；不过 Google 官方的 check_elf_alignment.sh 只看 p_align，
        且这类库（如 Qt 自带的 libavformat）我们并不总能重编，所以默认只告警。
    """
    if not segments:
        return False, 0, [], []
    min_align = min(seg[4] for seg in segments)
    bad, suspect = [], []
    for p_offset, p_vaddr, p_filesz, _memsz, p_align in segments:
        if p_align < align:
            bad.append({"offset": p_offset, "vaddr": p_vaddr, "align": p_align})
            continue
        if p_filesz == 0:          # 纯 bss 占位段：不读文件，跳过同余校验
            continue
        if (p_offset - p_vaddr) % align:
            suspect.append({"offset": p_offset, "vaddr": p_vaddr, "align": p_align})
    return (not bad), min_align, bad, suspect


def LoadElfFile(path):
    """读本地 .so：返回 (meta, segments, buf)"""
    with open(path, "rb") as fh:
        buf = fh.read(PREFIX_BYTES)
        while True:
            try:
                meta = ParseElf(buf)
                return meta, (ParseSegments(buf, meta) if meta else None), buf
            except ElfError:
                more = fh.read(PREFIX_BYTES)
                if not more:
                    return None, None, buf
                buf += more


def LoadElfZip(zf, info):
    """读 zip 内的 .so：只解压到够解析程序头为止"""
    size = PREFIX_BYTES
    while True:
        with zf.open(info) as handle:
            buf = handle.read(size)
        try:
            meta = ParseElf(buf)
            return meta, (ParseSegments(buf, meta) if meta else None), buf
        except ElfError:
            if size >= info.file_size:
                return None, None, buf
            size = min(size * 8, info.file_size)


# ------------------------------------------------------------------ 条目枚举
def IterDir(target, only_abi):
    for root, _dirs, files in os.walk(target):
        abi = os.path.basename(root)
        if only_abi and abi != only_abi:
            continue
        for name in sorted(files):
            if name.endswith(".so"):
                yield abi, name, os.path.join(root, name)


def IterZip(zf, only_abi):
    for info in zf.infolist():
        if not info.filename.endswith(".so"):
            continue
        parts = info.filename.split("/")
        if "lib" not in parts or parts.index("lib") + 1 >= len(parts):
            continue
        abi = parts[parts.index("lib") + 1]
        if only_abi and abi != only_abi:
            continue
        yield abi, parts[-1], info


def ZipDataOffset(fp, info):
    """未压缩条目的数据起始偏移（ZIP 对齐校验用）"""
    fp.seek(info.header_offset)
    header = fp.read(30)
    if len(header) != 30:
        return -1
    name_len, extra_len = struct.unpack_from("<HH", header, 26)
    return info.header_offset + 30 + name_len + extra_len


def CheckZipAlign(path, infos, align):
    """未压缩的 .so 必须落在 align 边界上；返回 (检查数, 不合规列表)"""
    stored = [i for i in infos if i.compress_type == zipfile.ZIP_STORED]
    bad = []
    with open(path, "rb") as fp:
        for info in stored:
            offset = ZipDataOffset(fp, info)
            if offset < 0 or offset % align:
                bad.append({"name": info.filename, "offset": offset})
    return len(stored), bad


# ------------------------------------------------------------------ 主流程
def Main():
    parser = argparse.ArgumentParser(
        description="检查原生库的 16KB 页对齐（ELF 段对齐 + ZIP 对齐）")
    parser.add_argument("target", help="APK/AAB、含 lib/<abi>/*.so 的目录，或单个 .so")
    parser.add_argument("--abi", default="", help="只查某个 ABI（默认全部）")
    parser.add_argument("--min-align", type=int, default=DEFAULT_ALIGN,
                        help="对齐阈值，默认 16384")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--soft", action="store_true", help="只报不拦（返回 0）")
    parser.add_argument("--list-ok", action="store_true", help="逐条列出通过的库")
    parser.add_argument("--strict-congruence", action="store_true",
                        help="把\"p_align 达标但 offset/vaddr 不同余\"也算失败"
                             "（默认仅告警，与 Google check_elf_alignment.sh 口径一致）")
    args = parser.parse_args()

    if not os.path.exists(args.target):
        print("[FAIL] 找不到目标: {}".format(args.target))
        return 2

    align = args.min_align
    rows = []                       # 每个 64 位库一条
    skipped = {"notelf": [], "elf32": [], "hexagon": []}
    zip_stored, zip_bad = 0, []

    if os.path.isdir(args.target):
        for abi, name, path in IterDir(args.target, args.abi):
            meta, segs, buf = LoadElfFile(path)
            if meta is None:
                skipped["notelf"].append(name)
                continue
            if meta["bits"] == 32:
                key = "hexagon" if meta["machine"] == EM_HEXAGON else "elf32"
                skipped[key].append(name)
                continue
            ok, min_align, bad, suspect = CheckElf(segs, align)
            rows.append({"abi": abi, "name": name, "ok": ok,
                         "min_align": min_align, "bad": bad, "suspect": suspect,
                         "loads": len(segs),
                         "machine": MACHINE_NAMES.get(meta["machine"], str(meta["machine"]))})
    else:
        with zipfile.ZipFile(args.target) as zf:
            infos = [i for i in zf.infolist() if i.filename.endswith(".so")]
            entries = list(IterZip(zf, args.abi))
            for abi, name, info in entries:
                meta, segs, buf = LoadElfZip(zf, info)
                if meta is None:
                    skipped["notelf"].append(name)
                    continue
                if meta["bits"] == 32:
                    key = "hexagon" if meta["machine"] == EM_HEXAGON else "elf32"
                    skipped[key].append(name)
                    continue
                ok, min_align, bad, suspect = CheckElf(segs, align)
                rows.append({"abi": abi, "name": name, "ok": ok,
                             "min_align": min_align, "bad": bad, "suspect": suspect,
                             "loads": len(segs),
                             "machine": MACHINE_NAMES.get(meta["machine"], str(meta["machine"]))})
            zip_stored, zip_bad = CheckZipAlign(args.target, infos, align)

    ok_rows = [r for r in rows if r["ok"]]
    bad_rows = [r for r in rows if not r["ok"]]
    warn_rows = [r for r in rows if r["ok"] and r["suspect"]]
    abis = sorted({r["abi"] for r in rows})
    has_problem = bool(bad_rows or zip_bad or (args.strict_congruence and warn_rows))

    if args.json:
        print(json.dumps({
            "target": args.target,
            "align": align,
            "abis": abis,
            "summary": {"ok": len(ok_rows), "bad": len(bad_rows),
                        "skipped": sum(len(v) for v in skipped.values())},
            "unaligned": [{"abi": r["abi"], "name": r["name"], "machine": r["machine"],
                           "min_align": r["min_align"],
                           "misaligned_segments": len(r["bad"]), "load_segments": r["loads"]}
                          for r in bad_rows],
            "suspect": [{"abi": r["abi"], "name": r["name"],
                         "segments": len(r["suspect"])} for r in warn_rows],
            "skipped": skipped,
            "zip": {"stored": zip_stored, "misaligned": zip_bad},
        }, ensure_ascii=False, indent=2))
    else:
        print("目标: {}".format(args.target))
        if os.path.isdir(args.target):
            print("扫描: 目录模式，共 {} 个 .so   ABI: {}".format(
                len(rows) + sum(len(v) for v in skipped.values()), ", ".join(abis) or "-"))
        else:
            print("大小: {:.1f} MB   ABI: {}".format(
                os.path.getsize(args.target) / 1048576.0, ", ".join(abis) or "-"))
        print("阈值: {} 字节".format(align))

        if bad_rows:
            print("\n{} {} 个 64 位库的 PT_LOAD 段不满足 {} 字节对齐（16KB 设备上会退回"
                  "兼容模式，fatal 模式下直接闪退）：".format(
                      "[WARN]" if args.soft else "[FAIL]", len(bad_rows), align))
            for r in sorted(bad_rows, key=lambda x: (x["abi"], x["name"])):
                print("  {:<40s} p_align={:<5d} 不合规段 {}/{}  [{}]".format(
                    r["name"], r["min_align"], len(r["bad"]), r["loads"], r["machine"]))

        if warn_rows:
            print("\n[WARN] {} 个库 p_align 已达标，但存在 offset/vaddr 不同余的段"
                  "（可能加载失败，建议单独核对；不影响本门禁结论）：".format(len(warn_rows)))
            for r in sorted(warn_rows, key=lambda x: x["name"]):
                print("  {:<40s} p_align={:<5d} 可疑段 {}/{}".format(
                    r["name"], r["min_align"], len(r["suspect"]), r["loads"]))

        if zip_bad:
            print("\n{} 未压缩原生库没有落到 {} 字节边界（需 zipalign -P 16）：".format(
                "[WARN]" if args.soft else "[FAIL]", align))
            for item in zip_bad:
                print("  {:<40s} data_offset={} (余 {})".format(
                    item["name"], item["offset"], item["offset"] % align))

        if skipped["notelf"]:
            print("\n[SKIP] 非 ELF 的 .so（数据包，不参与加载）: {}".format(
                ", ".join(skipped["notelf"])))
        if skipped["hexagon"]:
            print("[SKIP] Hexagon skel {} 个（DSP RPC 加载，bionic 不校验页对齐）".format(
                len(skipped["hexagon"])))
        if skipped["elf32"]:
            print("[SKIP] 其它 32 位 ELF {} 个: {}".format(
                len(skipped["elf32"]), ", ".join(skipped["elf32"][:6])))
        if not os.path.isdir(args.target):
            if zip_stored:
                print("[INFO] 包内原生库未压缩存储（extractNativeLibs=false），"
                      "已校验 ZIP 对齐 {} 个".format(zip_stored))
            else:
                print("[INFO] 包内原生库是压缩存储（extractNativeLibs=true），"
                      "ZIP 对齐不参与加载，跳过")

        if args.list_ok:
            print("\n[OK] 已对齐 {} 个:".format(len(ok_rows)))
            for r in sorted(ok_rows, key=lambda x: x["name"]):
                print("  {:<40s} p_align={}".format(r["name"], r["min_align"]))

        print("\n小结: 对齐 {} / 未对齐 {} / 跳过 {}".format(
            len(ok_rows), len(bad_rows), sum(len(v) for v in skipped.values())))
        if bad_rows:
            print("提示: 对齐由 NDK 决定 —— r28+ 默认 16KB；r26/r27 需 "
                  "-Wl,-z,max-page-size=16384。改完重编，不要试图改包内文件。")

    if has_problem and not args.soft:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(Main())
