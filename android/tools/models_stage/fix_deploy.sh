#!/bin/bash
# 修复 models 部署：清理误落到 WSL / 的 31 个 onnx，从 models_out 正确部署到仓库
set -e
SRC=/root/jmcomic-build/models_out
DST=/mnt/c/Users/WQ159/source/repos/JMComic-qt/android/sr_qnn/models

echo "=== 1. 清理误落到 / 的 onnx（models_out 有完整副本，删除安全） ==="
rm -f /realcugan_*.onnx /realesrgan_*.onnx /waifu2x_*.onnx
ls /*.onnx 2>/dev/null | wc -l

echo "=== 2. 从 models_out 部署 31 个到仓库 ==="
cp "$SRC/waifu2x/"*.onnx "$DST/"
cp "$SRC/cugan/"*.onnx "$DST/"
cp "$SRC/esrgan/"*.onnx "$DST/"

echo "=== 3. 验证 ==="
cd "$DST"
echo "onnx 数量: $(ls *.onnx | wc -l)（期望 31）"
echo "总大小: $(du -ch *.onnx | tail -1)"
echo "--- models.txt 引用 vs 实际文件对账 ---"
python3 - << 'PYEOF'
import os, re
missing = []
total = 0
with open("/mnt/c/Users/WQ159/source/repos/JMComic-qt/android/sr_qnn/models/models.txt") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1].endswith(".onnx"):
            total += 1
            p = os.path.join("/mnt/c/Users/WQ159/source/repos/JMComic-qt/android/sr_qnn/models", parts[1])
            if not os.path.exists(p):
                missing.append(parts[1])
print(f"models.txt 引用 {total} 个 onnx，缺失 {len(missing)} 个")
for m in missing:
    print("  MISSING:", m)
# 反向：目录里多出的文件
listed = set()
with open("/mnt/c/Users/WQ159/source/repos/JMComic-qt/android/sr_qnn/models/models.txt") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].endswith(".onnx"):
                listed.add(parts[1])
extra = [f for f in os.listdir("/mnt/c/Users/WQ159/source/repos/JMComic-qt/android/sr_qnn/models")
         if f.endswith(".onnx") and f not in listed]
print("目录中未列入 models.txt 的文件:", extra or "无")
PYEOF
