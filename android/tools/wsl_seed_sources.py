#!/usr/bin/env python3
"""把 recipe 需要的源码包用国内镜像预置到 p4a 下载缓存

背景：
    * p4a 按 recipe 里 url 的 basename 作为缓存文件名，缓存命中(文件+marker 都在)就跳过下载
    * 有些 recipe 的 url 指向 GitHub 归档(Pillow/pycryptodome)，走代理只有几 KB/s；
      有些指向已失效的 pypi.python.org
    * 这里统一从清华镜像取 **PyPI sdist**(与 GitHub 归档同为"单层目录 + setup.py/pyproject"，
      p4a 解包后照样能编译)，改名为 recipe 期望的文件名放进缓存
"""
import os
import re
import ssl
import sys
import urllib.request

WORK = os.environ.get("WORK") or os.environ.get("JM_WORK") or "/root/jmcomic-build"
P4A = os.environ.get("P4A", os.path.join(WORK, "p4a"))
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
STORES = [
    os.path.join(WORK, "src/android/.buildozer/android/platform/build-arm64-v8a/packages"),
    os.path.join(WORK, ".buildozer/android/platform/build-arm64-v8a/packages"),
]
RECIPES = os.path.join(P4A, "pythonforandroid/recipes")

# recipe 目录名 -> PyPI 包名
Targets = {
    "Pillow": "pillow",
    "lxml": "lxml",
    "pycryptodome": "pycryptodome",
}

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()


def Fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "p4a-seeder"})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return resp.read()


def RecipeInfo(recipe):
    path = os.path.join(RECIPES, recipe, "__init__.py")
    text = open(path, encoding="utf-8").read()
    version = re.search(r"\n\s*version\s*=\s*['\"]([^'\"]+)['\"]", text)
    url = re.search(r"\n\s*url\s*=\s*['\"]([^'\"]+)['\"]", text)
    if not version or not url:
        return None, None, None
    ver = version.group(1)
    full = url.group(1).replace("{version}", ver)
    return ver, full, os.path.basename(full)


def FindSdist(pkg, ver):
    """ 在镜像索引里找该版本的 sdist 直链 """
    html = Fetch(f"{MIRROR}/{pkg}/", timeout=90).decode("utf-8", "ignore")
    links = re.findall(r'href="([^"]+)"', html)
    cands = []
    for link in links:
        name = link.split("#")[0].rstrip("/").split("/")[-1]
        if not name.endswith((".tar.gz", ".zip", ".tar.bz2")):
            continue
        low = name.lower()
        if ver not in low:
            continue
        if not low.startswith(pkg.lower().replace("-", "_")[:6]):
            # 名字前缀可能不同(如 pycryptodome 的 sdist 名就是 pycryptodome-...)，
            # 这里放宽：只要版本匹配且不是别的包
            pass
        cands.append((name, link))
    if not cands:
        return None, None
    # 优先 .tar.gz
    cands.sort(key=lambda x: (not x[0].endswith(".tar.gz"), len(x[0])))
    name, link = cands[0]
    if link.startswith("http"):
        url = link
    elif link.startswith("/"):
        url = "https://pypi.tuna.tsinghua.edu.cn" + link
    else:
        url = f"{MIRROR}/{pkg}/" + link
    return name, url


def Main():
    ok = 0
    for recipe, pkg in Targets.items():
        if not os.path.isdir(os.path.join(RECIPES, recipe)):
            print(f"[skip] 没有 {recipe} recipe")
            continue
        ver, full, want = RecipeInfo(recipe)
        if not ver:
            print(f"[skip] {recipe} 解析失败")
            continue
        print(f"== {recipe}: version={ver} 期望文件名={want}")
        print(f"   原 URL: {full[:100]}")
        name, url = FindSdist(pkg, ver)
        if not url:
            print("   [warn] 镜像索引里没找到 sdist")
            continue
        print(f"   镜像 sdist: {name}")
        try:
            data = Fetch(url, timeout=300)
        except Exception as es:
            print("   [warn] 下载失败:", str(es)[:120])
            continue
        print(f"   大小: {len(data) / 1024 / 1024:.1f} MB")
        for store in STORES:
            d = os.path.join(store, recipe)
            os.makedirs(d, exist_ok=True)
            target = os.path.join(d, want)
            with open(target, "wb") as f:
                f.write(data)
            with open(os.path.join(d, f".mark-{want}"), "w") as f:
                f.write("")
            print(f"   -> {target}")
        ok += 1
    print(f"\n完成 {ok} 个包")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(Main())
