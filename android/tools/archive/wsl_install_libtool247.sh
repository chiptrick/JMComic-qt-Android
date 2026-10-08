#!/usr/bin/env bash
# libffi 3.4.2 的 autotools 需要 libtool 2.4.x 的宏(AC_PROG_LD / LT_SYS_SYMBOL_USCORE)，
# 而系统是 libtool 2.5.4(已删除这些宏) -> 单独装 GNU libtool 2.4.7 并让 recipe 用它
set -uo pipefail
WORK=/root/jmcomic-build
P4A="$WORK/p4a"
PFX=/opt/libtool247
PY="$WORK/venv311/bin/python"
exec > >(tee -a "$WORK/logs/libtool247.log") 2>&1

echo "===== [$(date +%T)] 下载 GNU libtool 2.4.7 ====="
cd "$WORK"
if [ ! -x "$PFX/bin/libtoolize" ]; then
    T=libtool-2.4.7.tar.gz
    if [ ! -s "$T" ]; then
        for u in "https://mirrors.tuna.tsinghua.edu.cn/gnu/libtool/$T" \
                 "https://mirrors.aliyun.com/gnu/libtool/$T" \
                 "https://mirrors.ustc.edu.cn/gnu/libtool/$T" \
                 "https://ftp.gnu.org/gnu/libtool/$T"; do
            echo "尝试 $u"
            curl -sSL --retry 2 -m 600 -o "$T" "$u" && [ -s "$T" ] && break
            rm -f "$T"
        done
    fi
    ls -sh "$T" || { echo "下载失败"; exit 1; }
    rm -rf libtool-2.4.7 && tar -xzf "$T"
    cd libtool-2.4.7
    ./configure --prefix="$PFX" >/dev/null 2>&1 || { echo "configure 失败"; exit 1; }
    make -j"$(nproc)" >/dev/null 2>&1 || { echo "make 失败"; exit 1; }
    make install >/dev/null 2>&1 || { echo "install 失败"; exit 1; }
    cd "$WORK"
fi
echo "libtoolize: $("$PFX/bin/libtoolize" --version | head -1)"
echo "宏文件: $(ls "$PFX/share/aclocal/" | tr '\n' ' ')"
echo -n "libtool247 里有 LT_SYS_SYMBOL_USCORE: "
grep -c 'LT_SYS_SYMBOL_USCORE' "$PFX/share/aclocal/libtool.m4" || true

echo
echo "===== [$(date +%T)] 还原 libffi recipe 为原始实现 ====="
R="$P4A/pythonforandroid/recipes/libffi/__init__.py"
if [ -f "$R.orig" ]; then
    cp -f "$R.orig" "$R"
    echo "已还原"
fi

echo
echo "===== [$(date +%T)] 让 recipe 使用 libtool 2.4.7 ====="
"$PY" - "$R" "$PFX" <<'EOF'
import sys
path, pfx = sys.argv[1], sys.argv[2]
lines = open(path, encoding='utf-8').read().splitlines()
out, done = [], False
for line in lines:
    out.append(line)
    if not done and line.strip().startswith('env = self.get_recipe_env(arch)'):
        ind = line[:len(line) - len(line.lstrip())]
        out.append(ind + "# libffi 3.4.2 需要 libtool 2.4.x 的 AC_PROG_LD/LT_SYS_SYMBOL_USCORE 宏，")
        out.append(ind + "# 系统 libtool 2.5 已移除，这里改用单独安装的 2.4.7")
        out.append(ind + f"env['PATH'] = '{pfx}/bin:' + env.get('PATH', '')")
        out.append(ind + f"env['ACLOCAL_PATH'] = '{pfx}/share/aclocal'")
        out.append(ind + f"env['LIBTOOLIZE'] = '{pfx}/bin/libtoolize'")
        out.append(ind + f"env['ACLOCAL'] = '{pfx}/bin/aclocal'")
        out.append(ind + f"env['LTMAIN'] = '{pfx}/share/libtool/ltmain.sh'")
        done = True
open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print('注入 libtool 2.4.7 环境:', done)
EOF
sed -n '24,36p' "$R"
"$PY" -c "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read());print('语法 OK')" "$R" || { cp -f "$R.orig" "$R"; echo "语法错误已还原"; exit 1; }

echo
echo "===== [$(date +%T)] 清 libffi build 目录并重启构建 ====="
B="$WORK/src/android/.buildozer/android/platform/build-arm64-v8a"
rm -rf "$B/build/other_builds/libffi"
bash /path/to/JMComic-qt/android/tools/wsl_start_detached_build.sh
