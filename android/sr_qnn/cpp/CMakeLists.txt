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
