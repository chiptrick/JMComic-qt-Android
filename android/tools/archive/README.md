# android/tools/archive

移植过程中写过的一次性排查脚本，**按历史原貌保留**。它们记录的是"当时踩了什么坑、
怎么定位出来的"，所以留着比删掉有价值；但请把它们当**档案**，不是工具。

## 重要说明

1. **不保证能跑。** 多数脚本只跑过一次、只针对当时那个失败现象，路径/变量/前提条件都
   可能已经变了。要复现某个坑，请对照 `android/README.md` 里的对应章节，而不是直接执行。
2. **已做字符串脱敏。** 机器名、Windows 用户名、设备串号、绝对路径都换成了占位符：

   | 原值形状 | 现在 |
   | --- | --- |
   | `/mnt/c/Users/<user>/source/repos/JMComic-qt` | `/path/to/JMComic-qt` |
   | `C:\Users\<user>\source\repos\JMComic-qt` | `C:\path\to\JMComic-qt` |
   | `...\platform-tools\adb.exe` | `adb` / `adb.exe` |
   | 真机串号 | `.ps1` 里是 `"<DEVICE_SERIAL>"`；`.sh` 里是 `DEVICE_SERIAL_HERE`（尖括号在 bash 里会被当成重定向，所以换成了这个写法） |
   | WSL 普通用户名 | `<wsl-user>` / `<windows-user>` |

   所以这些脚本**不能**直接照抄运行；要跑请先把占位符换成自己的值，或参照
   `../env.sh` / `../env.ps1` 改成用 `$JM_REPO`、`$JM_WORK`、`$JM_SERIAL`。
3. **不再维护。** bug 修在这里没有意义 —— 如果某个 archive 脚本重新变得常用，
   请把它按 `env.sh` 约定改写后移回 `android/tools/`。

## 大致分类

| 前缀 | 个数 | 当时在干什么 |
| --- | --- | --- |
| `probe_*` | 21 | 探针：某个 API/库/设备行为到底是怎么样的（QT 插件、jnius、pycryptodome、代理、AAR 结构…） |
| `wsl_check_*` | 18 | 查构建树/依赖/recipe/打包内容的状态，多数后来被 `wsl_check_*.sh` 的入口脚本取代 |
| `wsl_find_*` | 16 | 在 p4a/buildozer/deploy 的源码里翻某个符号、调用点、tarball 来源 |
| `wsl_fix_*` | 8 | 针对具体编译失败打的补丁（libffi、lxml、libxml2、openssl、Java CA…） |
| `wsl_diag_*` | 6 | 环境诊断（conda、gradle、lxml、bundle） |
| `wsl_install_*` | 5 | 装构建依赖（buildozer、deploy reqs、libtool 2.4.7、测试依赖…） |
| `wsl_seed_*` | 5 | 往 p4a 缓存里预置源码包/gradle 依赖，绕开下载失败 |
| `wsl_show_*` | 4 | 把某段日志/失败原因打出来看 |
| 其他 | 28 | `wsl_final_verify*`、`wsl_rebuild_all`、`wsl_start_rebuild`、`wsl_probe*`、`wsl_*_progress`、`probe_back_key*`、`run_device_selftest` 等一次性脚本 |

完整的 111 个文件可以直接 `ls` 看。按前缀就能大致判断它属于哪一类排查。
