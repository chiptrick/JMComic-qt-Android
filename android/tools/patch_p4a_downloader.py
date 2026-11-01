# coding:utf-8
"""给 p4a 的 Recipe.download_file 注入 aria2c 多线程下载（幂等本地补丁）

背景：p4a 用 urllib 的 urlretrieve 串行下载，单线程 + 无断点续传，
在国内网络下就是"卡在下载 openssl/sqlite3"。这个补丁让所有 p4a 下载
优先走 aria2c（-x16 并发、断点续传、自动重试），aria2 不可用或下载失败时
自动回落到原有逻辑，所以不影响其它环境。

用法:
    python tools/patch_p4a_downloader.py <pythonforandroid>/recipe.py
    JM_USE_ARIA2=0      # 运行时关闭（走回原逻辑）
    JM_ARIA2_CONN=16    # 每服务器连接数
"""
import sys


HELPER = '''

# ==== JM 本地补丁开始：aria2c 多线程下载 ====
def _jm_try_aria2(url, target):
    """优先用 aria2c 多线程下载；未启用/不可用/失败时返回 False，交回原有逻辑。"""
    import os as _os
    import shutil as _shutil
    import subprocess as _subprocess

    if _os.environ.get("JM_USE_ARIA2", "1") != "1":
        return False
    aria2c = _shutil.which("aria2c")
    if not aria2c:
        return False
    target = _os.path.abspath(str(target))
    directory = _os.path.dirname(target) or "."
    name = _os.path.basename(target)
    conn = _os.environ.get("JM_ARIA2_CONN", "16")
    cmd = [aria2c, "-x", conn, "-s", conn, "-k", "1M",
           "--file-allocation=none", "--allow-overwrite=true",
           "--auto-file-renaming=false", "--max-tries=5", "--retry-wait=3",
           "--console-log-level=warn", "--summary-interval=0",
           "--connect-timeout=20", "--timeout=60",
           "-d", directory, "-o", name, url]
    try:
        rc = _subprocess.call(cmd)
    except Exception:
        return False
    return rc == 0 and _os.path.exists(target) and _os.path.getsize(target) > 0
# ==== JM 本地补丁结束 ====
'''

OLD = """        parsed_url = urlparse(url)
        if parsed_url.scheme in ('http', 'https'):
"""
NEW = """        parsed_url = urlparse(url)
        if parsed_url.scheme in ('http', 'https') and _jm_try_aria2(url, target):
            info('[JM] aria2c 下载完成: {}'.format(url))
            return
        if parsed_url.scheme in ('http', 'https'):
"""


def Main():
    if len(sys.argv) != 2:
        print("用法: {} <pythonforandroid>/recipe.py".format(sys.argv[0]))
        return 2
    path = sys.argv[1]
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        print("[FAIL] 读不了 {}: {}".format(path, exc))
        return 2

    if "_jm_try_aria2" in text:
        print("[OK]   {} 已打过 aria2 补丁，跳过".format(path))
        return 0

    if text.count(OLD) != 1:
        print("[FAIL] {} 里 download_file 的 http 分支定位失败"
              "（p4a 版本变了？找到 {} 处）".format(path, text.count(OLD)))
        return 2

    # helper 追加到文件末尾（模块级函数，方法在调用期才解析，顺序无所谓）
    patched = text.replace(OLD, NEW, 1) + HELPER
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(patched)

    import py_compile
    py_compile.compile(path, doraise=True)
    print("[OK]   {} 已注入 aria2c 多线程下载".format(path))
    return 0


if __name__ == "__main__":
    sys.exit(Main())
