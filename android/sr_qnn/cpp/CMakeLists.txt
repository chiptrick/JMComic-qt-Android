# libsr_qnn.so —— Android NPU(高通 QNN/HTP) 超分后端
#
# 用法(见 android/build_android.sh)：
#   cmake -S . -B build -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
#         -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-34 \
#         -DONNXRUNTIME_INCLUDE_DIR=<onnxruntime>/include/onnxruntime/core/session \
#         -DONNXRUNTIME_LIB_DIR=<解压后的 onnxruntime-android-qnn AAR>/jni/arm64-v8a
#   cmake --build build -j
cmake_minimum_required(VERSION 3.20)
project(sr_qnn CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# onnxruntime_c_api.h 所在目录
if(NOT ONNXRUNTIME_INCLUDE_DIR)
    message(FATAL_ERROR "请设置 -DONNXRUNTIME_INCLUDE_DIR=<onnxruntime 头文件目录>")
endif()

# libonnxruntime.so 所在目录(onnxruntime-android-qnn AAR 的 jni/<abi>/)
# 注意：NDK 工具链下 find_library 受 CMAKE_FIND_ROOT_PATH 限制，直接指定文件路径最稳
if(ONNXRUNTIME_LIB_DIR)
    if(EXISTS "${ONNXRUNTIME_LIB_DIR}/libonnxruntime.so")
        set(ONNXRUNTIME_LIB "${ONNXRUNTIME_LIB_DIR}/libonnxruntime.so")
    else()
        find_library(ONNXRUNTIME_LIB onnxruntime PATHS ${ONNXRUNTIME_LIB_DIR} NO_DEFAULT_PATH)
    endif()
else()
    find_library(ONNXRUNTIME_LIB onnxruntime)
endif()
if(NOT ONNXRUNTIME_LIB)
    message(FATAL_ERROR "找不到 libonnxruntime.so，请设置 -DONNXRUNTIME_LIB_DIR")
endif()
message(STATUS "ONNXRUNTIME_LIB = ${ONNXRUNTIME_LIB}")

add_library(sr_qnn SHARED sr_qnn.cpp)

target_include_directories(sr_qnn PRIVATE ${ONNXRUNTIME_INCLUDE_DIR})
target_link_libraries(sr_qnn PRIVATE ${ONNXRUNTIME_LIB} dl)

if(ANDROID)
    target_link_libraries(sr_qnn PRIVATE log android)
endif()

# 注意：不能加 -fvisibility=hidden，否则 ctypes 找不到 srq_* 符号
target_compile_options(sr_qnn PRIVATE -O3 -ffunction-sections -fdata-sections)
target_link_options(sr_qnn PRIVATE -Wl,--gc-sections)

set_target_properties(sr_qnn PROPERTIES
    PREFIX "lib"
    OUTPUT_NAME "sr_qnn"
    BUILD_RPATH "$ORIGIN"
    INSTALL_RPATH "$ORIGIN")

# ---------------------------------------------------------------------------
# 独立进程入口(见 sr_qnn_proc.cpp 头注释)：App 进程的链接器命名空间加载不了
# /vendor/lib64/libcdsprpc.so(FastRPC)，HTP 因此永远起不来；放到子进程里用
# LD_LIBRARY_PATH 就能用设备自带的厂商库 —— local-dream 等项目的通行做法。
# 产物按 buildozer 约定命名成 libsr_qnn_proc.so 随 APK 分发(extractNativeLibs
# 会解到 nativeLibraryDir，可执行)。
# 注意：可执行文件**故意不链接** libonnxruntime.so(下面 target_link_libraries 里没有
# ONNXRUNTIME_LIB)。App lib 目录在 exec 出来的进程里不在链接器搜索路径内，DT_NEEDED
# 会导致 main() 之前就被 "CANNOT LINK EXECUTABLE" 杀掉；改为运行时 dlopen 注入。
add_executable(sr_qnn_proc sr_qnn.cpp sr_qnn_proc.cpp)
target_include_directories(sr_qnn_proc PRIVATE ${ONNXRUNTIME_INCLUDE_DIR})
target_link_libraries(sr_qnn_proc PRIVATE dl)
target_compile_definitions(sr_qnn_proc PRIVATE SRQ_NO_DIRECT_ORT=1)
# 注意：这里**故意不链接 log / android**。
# 真机上 exec 报过：
#   CANNOT LINK EXECUTABLE ".../libsr_qnn_proc.so": cannot locate symbol
#   fmt::v11::vformat ... referenced by "/system/lib64/libinput.so"
# 原因是 libandroid.so 会把系统的 libinput.so 带进依赖链，而它在这个命名空间里
# 找不到 fmt 提供者，于是进程起不来。引擎只用 printf/fprintf(不调 ALOG)，
# 所以把这两个 Android 专属库去掉，NEEDED 只剩 libc/libm/libdl —— 启动路径最短。
target_compile_options(sr_qnn_proc PRIVATE -O3)
# $ORIGIN：让可执行文件从自己所在目录(nativeLibraryDir)解析 libonnxruntime.so。
# Android 上 app uid 进程是否认 LD_LIBRARY_PATH 并不保证，RUNPATH 一定会被用上 ——
# 少了这个，子进程 exec 后会直接因为找不到 libonnxruntime.so 死掉(静默退出)。
target_link_options(sr_qnn_proc PRIVATE "-Wl,-rpath,$ORIGIN")
set_target_properties(sr_qnn_proc PROPERTIES
    OUTPUT_NAME "sr_qnn_proc"
    BUILD_RPATH "$ORIGIN"
    INSTALL_RPATH "$ORIGIN")
