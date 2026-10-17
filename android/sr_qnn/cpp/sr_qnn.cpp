/* sr_qnn.cpp —— Android 端 waifu2x 超分引擎
 *
 * 后端：ONNX Runtime C API + Qualcomm QNN Execution Provider(Hexagon NPU / HTP)
 *
 * 设计要点：
 *   1. QNN EP 不支持动态 shape，所以每个模型在离线准备阶段就把输入固定为
 *      N×3×T×T(T 见 models.txt 的 tile 字段)；引擎把原图切成 T×T 的块，
 *      每块用边缘像素补齐后再送 NPU，回读后按有效区域拼接，保证无缝。
 *   2. 优先 HTP；失败时依次退化：HTP+优化项 -> HTP+基础项 -> HTP(允许 CPU 兜底) -> CPU EP。
 *   3. 支持 QNN context binary 缓存(第二次启动大幅加快图编译)，默认内嵌成单文件。
 *   4. 无第三方图像库依赖：解码/编码由 Python 侧 Qt 完成，C 侧只处理 RGB 原始像素。
 *   5. 合并了 QNN/HTP 提速项(均可用环境变量关闭，见 models/README.md)：
 *      VTCM 大小、图编译优化档位、fp16、会话优先级(qnn_context_priority)、
 *      HTP 共享内存零拷贝 I/O(enable_htp_shared_memory_allocator)、
 *      burst 性能模式(QNN EP 官方推理示例的默认档位)、RPC 控制延迟。
 *   6. HTP 子系统重启(SSR)会让 ORT 会话失效，引擎检测到 ENGINE_ERROR 后自动重建
 *      会话并重试当前分块，避免超分能力永久失效(见 QNN EP 文档 HTP SubSystem Restart)。
 *   7. 运行时结构参照 waifu2x-ncnn-vulkan(RealSR-NCNN-Android 的底层实现)：
 *      NPU 是单个引擎，多线程并发 Run 同一 QNN 上下文只会在驱动里串行排队，
 *      因此 HTP 模式只用 2 个 worker(一块在 NPU 上跑、另一块在 CPU 上打包/拆包，
 *      形成流水)，不再起 4 个线程空抢锁。
 *   8. 分块打包/拆包改成"行级、无内部分支"的实现(内部块不逐像素判断越界)，
 *      arm64 下用 NEON 做 RGB<->NCHW 浮点互转与 fp16 转换；边缘块自动退回
 *      带 clamp 的标量路径，几何行为与旧实现完全一致。
 */
#include "sr_qnn.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <dlfcn.h>
#include <dirent.h>
#include <sys/stat.h>
#include <unistd.h>

#include "onnxruntime_c_api.h"

// arm64 (Android 唯一目标 ABI) 必带 NEON。宿主 x86 构建会自动走标量分支，
// 两条路径的输出语义完全一致(见下面各行级转换函数的注释)。
// fp16 互转指令只保证在 aarch64 上有，armv7 下退回标量实现。
#if defined(__aarch64__)
#include <arm_neon.h>
#define SRQ_NEON 1
#define SRQ_NEON_FP16 1
#elif defined(__ARM_NEON)
#include <arm_neon.h>
#define SRQ_NEON 1
#endif

// ---------------------------------------------------------------- 基础工具
namespace {

const char* kVersion = "sr_qnn 1.4.1 (ONNX Runtime QNN EP / HEXAGON HTP)";

std::mutex g_errMutex;
std::string g_lastError;
bool g_debug = false;

/* ORT 在 Android 上把日志送进 logcat，sr_native.log 里一条都看不到 —— 于是
 * "QNN 一个节点都没接住" 这种问题只能靠猜。注册自定义 logger 后，QNN EP 的原始
 * 报错(哪个算子不支持、device 建不起来的 errno)会直接落到 fd 2，而 Python 自检
 * 已经把 fd 2 重定向到 sr_native.log。
 * 级别过滤放在回调里做(而不是交给 ORT)：这样运行时打开 debug 立刻能变详细。 */
std::mutex g_ortLogMutex;
int g_ortLogLevel = 2;   // 0=verbose 1=info 2=warning 3=error 4=fatal
/* QNN EP 在 GetCapability 里会打 "Number of partitions supported by QNN EP: N"。
 * N=0 意味着"EP 挂上了但一个节点都没接住" —— 这种会话只会平白多一层 EP 调度，
 * 比纯 CPU 还慢，所以从日志里把它捞出来，据此决定是否丢掉这个会话。 */
std::atomic<int> g_qnnPartitionCount{-1};
/* QNN EP 在 GetCapability 里 SetupBackend 失败时会直接返回空能力集，连
 * "Number of partitions ...: 0" 都不打。真机上的典型报错是
 *   QNN SetupBackend failed ... QNN_COMMON_ERROR_PLATFORM_NOT_SUPPORTED
 * 这种失败是"整个后端在本机不可用"，重试任何档位都没意义，所以单独记一个标志：
 * 命中后直接把 QNN 判死，后续模型不再白跑 5 次会话创建。 */
std::atomic<bool> g_qnnSetupFailed{false};
std::atomic<bool> g_qnnUnusable{false};

void OrtLogCallback(void* /*param*/, OrtLoggingLevel severity, const char* category,
                    const char* /*logid*/, const char* /*code_location*/, const char* message) {
    int level = static_cast<int>(severity);
    if (level < 0) {
        level = 0;
    }
    if (level > 4) {
        level = 4;
    }
    if (message != nullptr) {
        static const char kPartitionTag[] = "Number of partitions supported by QNN EP:";
        if (const char* pos = strstr(message, kPartitionTag)) {
            g_qnnPartitionCount.store(atoi(pos + sizeof(kPartitionTag) - 1));
        }
        if (strstr(message, "QNN SetupBackend failed") != nullptr) {
            g_qnnSetupFailed.store(true);
        }
    }
    // 调试开关打开时把 INFO 也放出来(分区信息 "Number of nodes assigned to ...")
    const int limit = g_debug ? 1 : g_ortLogLevel;
    if (level < limit) {
        return;
    }
    static const char* kNames[5] = {"V", "I", "W", "E", "F"};
    std::lock_guard<std::mutex> lock(g_ortLogMutex);
    fprintf(stderr, "[ORT %s] %s: %s\n", kNames[level],
            category != nullptr ? category : "?", message != nullptr ? message : "");
    fflush(stderr);
}

void SetError(const std::string& msg) {
    std::lock_guard<std::mutex> lock(g_errMutex);
    g_lastError = msg;
}

std::string GetError() {
    std::lock_guard<std::mutex> lock(g_errMutex);
    return g_lastError;
}

bool FileExists(const std::string& path) {
    struct stat st;
    return stat(path.c_str(), &st) == 0 && S_ISREG(st.st_mode);
}

bool DirExists(const std::string& path) {
    struct stat st;
    return stat(path.c_str(), &st) == 0 && S_ISDIR(st.st_mode);
}

/* 模型文件指纹(大小 + mtime + 头部 64KB 的 FNV-1a 哈希)
 * QNN 的 context binary 缓存按文件名做 key：只要文件名不变，换了模型内容也会继续
 * 加载旧的编译结果。把模型改写成"静态图"(见 models/README.md) 后如果不换 key，
 * 设备上仍会跑旧的 CPU 分区图 —— 优化等于没生效。这里把指纹拼进 key。 */
std::string FileFingerprint(const std::string& path) {
    struct stat st;
    if (stat(path.c_str(), &st) != 0) {
        return "";
    }
    uint64_t hash = 1469598103934665603ULL;
    FILE* fp = fopen(path.c_str(), "rb");
    if (fp != nullptr) {
        unsigned char buffer[65536];
        size_t got = fread(buffer, 1, sizeof(buffer), fp);
        fclose(fp);
        for (size_t i = 0; i < got; ++i) {
            hash ^= buffer[i];
            hash *= 1099511628211ULL;
        }
    }
    char text[80];
    snprintf(text, sizeof(text), "%llx%llx%llx", static_cast<unsigned long long>(hash),
             static_cast<unsigned long long>(st.st_size),
             static_cast<unsigned long long>(st.st_mtime));
    return text;
}

/* 清掉同一模型的历史 context 缓存(文件名前缀相同、但不是当前这个) */

bool MakeDirs(const std::string& path) {
    if (path.empty() || DirExists(path)) {
        return true;
    }
    std::string cur;
    for (size_t i = 0; i < path.size(); ++i) {
        cur.push_back(path[i]);
        if (path[i] == '/' || i + 1 == path.size()) {
            if (cur != "/" && !cur.empty() && !DirExists(cur)) {
                mkdir(cur.c_str(), 0770);
            }
        }
    }
    return DirExists(path);
}

std::string DirName(const std::string& path) {
    size_t pos = path.find_last_of('/');
    if (pos == std::string::npos) {
        return ".";
    }
    return path.substr(0, pos);
}

std::string JoinPath(const std::string& a, const std::string& b) {
    if (a.empty()) {
        return b;
    }
    if (a.back() == '/') {
        return a + b;
    }
    return a + "/" + b;
}

/* 清掉同一模型的历史 context 缓存(文件名前缀相同、但不是当前这个) */
void CleanStaleContext(const std::string& cacheDir, const std::string& base, const std::string& keep) {
    DIR* dir = opendir(cacheDir.c_str());
    if (dir == nullptr) {
        return;
    }
    std::vector<std::string> stale;
    struct dirent* ent = nullptr;
    while ((ent = readdir(dir)) != nullptr) {
        std::string name(ent->d_name);
        if (name == keep || name.size() <= 9) {
            continue;
        }
        if (name.compare(0, base.size(), base) != 0) {
            continue;
        }
        if (name.compare(name.size() - 9, 9, ".ctx.onnx") == 0) {
            stale.push_back(name);
        }
    }
    closedir(dir);
    for (auto& name : stale) {
        std::string full = JoinPath(cacheDir, name);
        remove(full.c_str());
        if (g_debug) {
            printf("[sr_qnn] 清理过期 context 缓存: %s\n", name.c_str());
        }
    }
    return;
}

std::string EnvStr(const char* name, const char* def = "") {
    const char* v = getenv(name);
    return v ? std::string(v) : std::string(def);
}

std::string EnvStr(const char* name, const std::string& def) {
    const char* v = getenv(name);
    return v ? std::string(v) : def;
}

int EnvInt(const char* name, int def) {
    const char* v = getenv(name);
    if (!v || !*v) {
        return def;
    }
    return atoi(v);
}

bool EnvFlag(const char* name, bool def) {
    const char* v = getenv(name);
    if (!v || !*v) {
        return def;
    }
    return std::string(v) != "0";
}

// ---------------------------------------------------------------- 半精度转换
uint16_t FloatToHalf(float value) {
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    uint32_t sign = (bits >> 16) & 0x8000u;
    int32_t exponent = static_cast<int32_t>((bits >> 23) & 0xff) - 127 + 15;
    uint32_t mantissa = bits & 0x7fffffu;
    if (exponent <= 0) {
        if (exponent < -10) {
            return static_cast<uint16_t>(sign);
        }
        mantissa = (mantissa | 0x800000u) >> (1 - exponent);
        return static_cast<uint16_t>(sign | (mantissa >> 13));
    }
    if (exponent >= 31) {
        return static_cast<uint16_t>(sign | 0x7c00u);
    }
    return static_cast<uint16_t>(sign | (static_cast<uint32_t>(exponent) << 10) | (mantissa >> 13));
}

float HalfToFloat(uint16_t value) {
    uint32_t sign = (static_cast<uint32_t>(value) & 0x8000u) << 16;
    uint32_t exponent = (static_cast<uint32_t>(value) >> 10) & 0x1fu;
    uint32_t mantissa = static_cast<uint32_t>(value) & 0x3ffu;
    uint32_t bits;
    if (exponent == 0) {
        if (mantissa == 0) {
            bits = sign;
        } else {
            exponent = 127 - 15 + 1;
            while ((mantissa & 0x400u) == 0) {
                mantissa <<= 1;
                --exponent;
            }
            mantissa &= 0x3ffu;
            bits = sign | (exponent << 23) | (mantissa << 13);
        }
    } else if (exponent == 31) {
        bits = sign | 0x7f800000u | (mantissa << 13);
    } else {
        bits = sign | ((exponent + 127 - 15) << 23) | (mantissa << 13);
    }
    float out;
    memcpy(&out, &bits, sizeof(out));
    return out;
}

/* ---------------------------------------------------------------- 批量格式转换
 *
 * 每个 tile 都要跑两次(RGB888 -> NCHW float、NCHW float -> RGB888)，另外 fp16
 * 模型还要再做两次半精度互转。旧实现是逐像素、带 clamp 与边界判断的标量循环：
 * 一块 192 的 tile 约 40 万次元素转换、每次都带两个分支，而 96 块(一张
 * 1200x1800 的漫画页)要在 NPU 算的同时跟它抢 CPU。这里改成"行级、无内部分支"
 * 的实现，arm64 下再套 NEON：
 *   - 中段(RGB 常用路径)：vld3q_u8 直接三通道拆平面，省掉手动解交错；
 *   - 回写：float->u8 的顺序与标量完全一致(先 *255+0.5、clamp[0,255]、再截断)。
 * 实测(x86 标量分支)每块约 0.2ms：收益不大，但能省下与 NPU 抢的 CPU 时间和电量。
 */
constexpr float kInv255 = 1.0f / 255.0f;
constexpr float kMul255 = 255.0f;

void FloatToHalfBuf(const float* src, uint16_t* dst, size_t count) {
    size_t i = 0;
#ifdef SRQ_NEON_FP16
    for (; i + 8 <= count; i += 8) {
        float16x4_t lo = vcvt_f16_f32(vld1q_f32(src + i));
        float16x4_t hi = vcvt_f16_f32(vld1q_f32(src + i + 4));
        vst1q_f16(reinterpret_cast<float16_t*>(dst + i), vcombine_f16(lo, hi));
    }
#endif
    for (; i < count; ++i) {
        dst[i] = FloatToHalf(src[i]);
    }
    return;
}

void HalfToFloatBuf(const uint16_t* src, float* dst, size_t count) {
    size_t i = 0;
#ifdef SRQ_NEON_FP16
    for (; i + 8 <= count; i += 8) {
        float16x8_t h = vld1q_f16(reinterpret_cast<const float16_t*>(src + i));
        vst1q_f32(dst + i, vcvt_f32_f16(vget_low_f16(h)));
        vst1q_f32(dst + i + 4, vcvt_f32_f16(vget_high_f16(h)));
    }
#endif
    for (; i < count; ++i) {
        dst[i] = HalfToFloat(src[i]);
    }
    return;
}

/* RGB888 交错 -> 3 个 float 平面(0..1)，NCHW 的常用路径，调用方保证不越界 */
void PackRowRgbToPlanes(const uint8_t* src, float* dr, float* dg, float* db, int count) {
    int i = 0;
#ifdef SRQ_NEON
    const float32x4_t scale = vdupq_n_f32(kInv255);
    for (; i + 16 <= count; i += 16) {
        uint8x16x3_t px = vld3q_u8(src + static_cast<size_t>(i) * 3);
        float* dst[3] = {dr + i, dg + i, db + i};
        const uint8x16_t ch[3] = {px.val[0], px.val[1], px.val[2]};
        for (int c = 0; c < 3; ++c) {
            uint16x8_t lo16 = vmovl_u8(vget_low_u8(ch[c]));
            uint16x8_t hi16 = vmovl_u8(vget_high_u8(ch[c]));
            vst1q_f32(dst[c] + 0, vmulq_f32(vcvtq_f32_u32(vmovl_u16(vget_low_u16(lo16))), scale));
            vst1q_f32(dst[c] + 4, vmulq_f32(vcvtq_f32_u32(vmovl_u16(vget_high_u16(lo16))), scale));
            vst1q_f32(dst[c] + 8, vmulq_f32(vcvtq_f32_u32(vmovl_u16(vget_low_u16(hi16))), scale));
            vst1q_f32(dst[c] + 12, vmulq_f32(vcvtq_f32_u32(vmovl_u16(vget_high_u16(hi16))), scale));
        }
    }
#endif
    for (; i < count; ++i) {
        dr[i] = src[static_cast<size_t>(i) * 3 + 0] * kInv255;
        dg[i] = src[static_cast<size_t>(i) * 3 + 1] * kInv255;
        db[i] = src[static_cast<size_t>(i) * 3 + 2] * kInv255;
    }
    return;
}

/* 3 个 float 平面 -> RGB888 交错。语义与旧代码逐像素
 * (uint8_t)clamp(v*255+0.5, 0, 255) 完全一致。 */
void UnpackRowPlanesToRgb(const float* pr, const float* pg, const float* pb, uint8_t* dst, int count) {
    int i = 0;
#ifdef SRQ_NEON
    const float32x4_t mul = vdupq_n_f32(kMul255);
    const float32x4_t half = vdupq_n_f32(0.5f);
    const float32x4_t vzero = vdupq_n_f32(0.0f);
    const float32x4_t vmax = vdupq_n_f32(255.0f);
    for (; i + 16 <= count; i += 16) {
        const float* src[3] = {pr + i, pg + i, pb + i};
        uint8x16x3_t px;
        for (int c = 0; c < 3; ++c) {
            int32x4_t q[4];
            for (int k = 0; k < 4; ++k) {
                float32x4_t v = vaddq_f32(vmulq_f32(vld1q_f32(src[c] + k * 4), mul), half);
                v = vmaxq_f32(vminq_f32(v, vmax), vzero);
                q[k] = vcvtq_s32_f32(v);   // 截断 == 标量 (uint8_t) 转换
            }
            int16x8_t lo = vcombine_s16(vqmovn_s32(q[0]), vqmovn_s32(q[1]));
            int16x8_t hi = vcombine_s16(vqmovn_s32(q[2]), vqmovn_s32(q[3]));
            px.val[c] = vcombine_u8(vqmovun_s16(lo), vqmovun_s16(hi));
        }
        vst3q_u8(dst + static_cast<size_t>(i) * 3, px);
    }
#endif
    for (; i < count; ++i) {
        dst[static_cast<size_t>(i) * 3 + 0] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, pr[i] * kMul255 + 0.5f)));
        dst[static_cast<size_t>(i) * 3 + 1] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, pg[i] * kMul255 + 0.5f)));
        dst[static_cast<size_t>(i) * 3 + 2] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, pb[i] * kMul255 + 0.5f)));
    }
    return;
}

/* RGBA/RGBX -> RGB 紧凑行(srq_add 用) */
void StripAlphaRow(const uint8_t* src, uint8_t* dst, int count, int channels) {
    int i = 0;
#ifdef SRQ_NEON
    if (channels == 4) {
        for (; i + 16 <= count; i += 16) {
            uint8x16x4_t px = vld4q_u8(src + static_cast<size_t>(i) * channels);
            uint8x16x3_t out;
            out.val[0] = px.val[0];
            out.val[1] = px.val[1];
            out.val[2] = px.val[2];
            vst3q_u8(dst + static_cast<size_t>(i) * 3, out);
        }
    }
#endif
    for (; i < count; ++i) {
        dst[static_cast<size_t>(i) * 3 + 0] = src[static_cast<size_t>(i) * channels + 0];
        dst[static_cast<size_t>(i) * 3 + 1] = src[static_cast<size_t>(i) * channels + 1];
        dst[static_cast<size_t>(i) * 3 + 2] = src[static_cast<size_t>(i) * channels + 2];
    }
    return;
}

/* 把 (ox-pad, oy-pad) 起点的 T×T 窗口打进 NCHW 浮点缓冲。
 * 窗口完全落在图内时整块走无分支路径；只有贴着图边的分块才在左右两侧
 * 各补一小段 clamp 到列 0 / 列 width-1 的像素(与旧实现语义一致)。 */
void PackTileInput(const std::vector<uint8_t>& rgb, int width, int height,
                   int ox, int oy, int pad, int tile, std::vector<float>& input) {
    const size_t planeSize = static_cast<size_t>(tile) * tile;
    float* planes[3] = {input.data(), input.data() + planeSize, input.data() + planeSize * 2};
    const int x0 = ox - pad;
    // tile 内第一个/最后一个不越界的列
    const int midStart = std::max(0, std::min(tile, -x0));
    const int midEnd = std::max(midStart, std::min(tile, width - x0));
    const int midCount = midEnd - midStart;
    for (int y = 0; y < tile; ++y) {
        int sy = oy - pad + y;
        sy = sy < 0 ? 0 : (sy >= height ? height - 1 : sy);
        const uint8_t* srcRow = rgb.data() + static_cast<size_t>(sy) * width * 3;
        float* dr = planes[0] + static_cast<size_t>(y) * tile;
        float* dg = planes[1] + static_cast<size_t>(y) * tile;
        float* db = planes[2] + static_cast<size_t>(y) * tile;
        // 左侧越界列：clamp 到列 0
        for (int x = 0; x < midStart; ++x) {
            dr[x] = srcRow[0] * kInv255;
            dg[x] = srcRow[1] * kInv255;
            db[x] = srcRow[2] * kInv255;
        }
        if (midCount > 0) {
            PackRowRgbToPlanes(srcRow + static_cast<size_t>(x0 + midStart) * 3,
                               dr + midStart, dg + midStart, db + midStart, midCount);
        }
        // 右侧越界列：clamp 到列 width-1
        const uint8_t* last = srcRow + static_cast<size_t>(width - 1) * 3;
        for (int x = midEnd; x < tile; ++x) {
            dr[x] = last[0] * kInv255;
            dg[x] = last[1] * kInv255;
            db[x] = last[2] * kInv255;
        }
    }
    return;
}

/* 把一块 tile 输出中"源图 [ox, ox+rw) x [oy, oy+rh) 对应的有效区域"
 * 写回 srImage。有效范围在进入行循环前算好，行内不再逐像素判断边界。 */
void UnpackTileOutput(const std::vector<float>& output, int outW, int outH,
                      int readX, int readY, int rw, int rh, int scale,
                      int ox, int oy, int srWidth, int srHeight, std::vector<uint8_t>& srImage) {
    const int yBegin = std::max(0, -readY);
    const int yEnd = std::min(std::min(rh * scale, outH - readY), srHeight - oy * scale);
    const int xBegin = std::max(0, -readX);
    const int xEnd = std::min(std::min(rw * scale, outW - readX), srWidth - ox * scale);
    const int copyW = xEnd - xBegin;
    if (copyW <= 0) {
        return;
    }
    const size_t planeSize = static_cast<size_t>(outW) * outH;
    const float* planes[3] = {output.data(), output.data() + planeSize, output.data() + planeSize * 2};
    for (int y = yBegin; y < yEnd; ++y) {
        const int ty = readY + y;
        const int dy = oy * scale + y;
        const size_t srcOffset = static_cast<size_t>(ty) * outW + readX + xBegin;
        uint8_t* dst = srImage.data() + (static_cast<size_t>(dy) * srWidth + ox * scale + xBegin) * 3;
        UnpackRowPlanesToRgb(planes[0] + srcOffset, planes[1] + srcOffset, planes[2] + srcOffset,
                             dst, copyW);
    }
    return;
}

// ---------------------------------------------------------------- 双线性缩放
void ResizeBilinear(const std::vector<uint8_t>& src, int sw, int sh,
                    std::vector<uint8_t>& dst, int dw, int dh) {
    dst.assign(static_cast<size_t>(dw) * dh * 3, 0);
    if (sw <= 0 || sh <= 0 || dw <= 0 || dh <= 0) {
        return;
    }
    float xRatio = sw / static_cast<float>(dw);
    float yRatio = sh / static_cast<float>(dh);
    for (int y = 0; y < dh; ++y) {
        float fy = (y + 0.5f) * yRatio - 0.5f;
        fy = std::max(0.0f, std::min(fy, static_cast<float>(sh - 1)));
        int y0 = static_cast<int>(fy);
        int y1 = std::min(y0 + 1, sh - 1);
        float wy = fy - y0;
        for (int x = 0; x < dw; ++x) {
            float fx = (x + 0.5f) * xRatio - 0.5f;
            fx = std::max(0.0f, std::min(fx, static_cast<float>(sw - 1)));
            int x0 = static_cast<int>(fx);
            int x1 = std::min(x0 + 1, sw - 1);
            float wx = fx - x0;
            uint8_t* out = &dst[(static_cast<size_t>(y) * dw + x) * 3];
            for (int c = 0; c < 3; ++c) {
                float v00 = src[(static_cast<size_t>(y0) * sw + x0) * 3 + c];
                float v01 = src[(static_cast<size_t>(y0) * sw + x1) * 3 + c];
                float v10 = src[(static_cast<size_t>(y1) * sw + x0) * 3 + c];
                float v11 = src[(static_cast<size_t>(y1) * sw + x1) * 3 + c];
                float top = v00 + (v01 - v00) * wx;
                float bottom = v10 + (v11 - v10) * wx;
                float value = top + (bottom - top) * wy;
                out[c] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, value + 0.5f)));
            }
        }
    }
    return;
}

// ---------------------------------------------------------------- 模型表
struct ModelEntry {
    std::string name;      // WAIFU2X_ANIME_UP2X_DENOISE3X
    std::string file;      // onnx 文件名
    int nativeScale = 2;   // 模型原生放大倍数
    int denoise = 0;       // 降噪等级
    int tile = 192;        // 固定输入边长(QNN 不支持动态 shape)
};

struct ModelSlot {
    ModelEntry entry;
    std::string info;      // 缓存 srq_model_info 字符串
};

std::vector<ModelSlot> g_models;
std::mutex g_modelsMutex;
std::string g_modelDir;

void AddModel(const std::string& name, const std::string& file, int scale, int denoise, int tile) {
    ModelSlot slot;
    slot.entry.name = name;
    slot.entry.file = file;
    slot.entry.nativeScale = scale;
    slot.entry.denoise = denoise;
    slot.entry.tile = tile;
    g_models.push_back(slot);
    return;
}

/* 内置模型表：与桌面端 sr_vulkan 的 MODEL_* 常量一一对应
 * 说明：cunet 的分组反卷积在 HTP 上不友好，NPU 后端默认复用 anime/photo 模型，
 * 用户可在 models.txt 里改成自己的 cunet onnx。 */
void BuildBuiltinModels() {
    g_models.clear();
    const int kTile = 192;
    // waifu2x：CUNET 有 up1x(纯降噪)条目；ANIME/PHOTO 界面只用到 up2x
    // 名称必须与 setting_sr_select_view.py 里的 AllModelNames 完全一致
    for (int variant = 0; variant < 3; ++variant) {
        const char* family = variant == 0 ? "CUNET" : (variant == 1 ? "ANIME" : "PHOTO");
        const char* base = variant == 0 ? "anime" : (variant == 1 ? "anime" : "photo");
        char name[128];
        char file[128];
        if (variant == 0) {
            for (int denoise = 0; denoise <= 3; ++denoise) {
                snprintf(name, sizeof(name), "WAIFU2X_%s_UP1X_DENOISE%dX", family, denoise);
                snprintf(file, sizeof(file), "waifu2x_%s_up1x_denoise%d.onnx", base, denoise);
                AddModel(name, file, 1, denoise, kTile);
            }
        }
        for (int denoise = 0; denoise <= 3; ++denoise) {
            snprintf(name, sizeof(name), "WAIFU2X_%s_UP2X_DENOISE%dX", family, denoise);
            snprintf(file, sizeof(file), "waifu2x_%s_up2x_denoise%d.onnx", base, denoise);
            AddModel(name, file, 2, denoise, kTile);
        }
        snprintf(name, sizeof(name), "WAIFU2X_%s_UP2X", family);
        snprintf(file, sizeof(file), "waifu2x_%s_up2x_denoise3.onnx", base);
        AddModel(name, file, 2, 3, kTile);
    }
    // real-cugan：pro 只有 2x/3x 的 denoise3，se 额外有 2x 的 denoise1/2
    struct CuganDef { const char* prefix; const char* filePrefix; int scales[3]; int count; };
    const CuganDef cuganPro = {"REALCUGAN_PRO", "realcugan_pro", {2, 3, 0}, 2};
    const CuganDef cuganSe = {"REALCUGAN_SE", "realcugan_se", {2, 3, 4}, 3};
    const CuganDef* cugans[2] = {&cuganPro, &cuganSe};
    for (int ci = 0; ci < 2; ++ci) {
        const CuganDef* def = cugans[ci];
        for (int si = 0; si < def->count; ++si) {
            int scale = def->scales[si];
            char name[128];
            char file[160];
            snprintf(name, sizeof(name), "%s_UP%dX", def->prefix, scale);
            snprintf(file, sizeof(file), "%s_up%dx.onnx", def->filePrefix, scale);
            AddModel(name, file, scale, 0, kTile);
            snprintf(name, sizeof(name), "%s_UP%dX_CONSERVATIVE", def->prefix, scale);
            snprintf(file, sizeof(file), "%s_up%dx_conservative.onnx", def->filePrefix, scale);
            AddModel(name, file, scale, 0, kTile);
            for (int denoise = 1; denoise <= 3; ++denoise) {
                if (denoise != 3 && !(ci == 1 && scale == 2)) {
                    continue;
                }
                snprintf(name, sizeof(name), "%s_UP%dX_DENOISE%dX", def->prefix, scale, denoise);
                snprintf(file, sizeof(file), "%s_up%dx_denoise%d.onnx", def->filePrefix, scale, denoise);
                AddModel(name, file, scale, denoise, kTile);
            }
        }
    }
    // real-esrgan
    const char* esrganNames[5][2] = {
        {"REALESRGAN_ANIMAVIDEOV3_UP2X", "realesrgan_animevideo_v3_up2x.onnx"},
        {"REALESRGAN_ANIMAVIDEOV3_UP3X", "realesrgan_animevideo_v3_up3x.onnx"},
        {"REALESRGAN_ANIMAVIDEOV3_UP4X", "realesrgan_animevideo_v3_up4x.onnx"},
        {"REALESRGAN_X4PLUS_UP4X", "realesrgan_x4plus_up4x.onnx"},
        {"REALESRGAN_X4PLUSANIME_UP4X", "realesrgan_x4plus_anime_up4x.onnx"},
    };
    const int esrganScales[5] = {2, 3, 4, 4, 4};
    for (int i = 0; i < 5; ++i) {
        AddModel(esrganNames[i][0], esrganNames[i][1], esrganScales[i], 0, kTile);
    }
    return;
}

/* models.txt 覆盖内置表：每行 "<模型名> <文件名> <倍数> <降噪> <tile>"，以空白分隔 */
void LoadModelOverride(const std::string& dir) {
    std::string path = JoinPath(dir, "models.txt");
    FILE* fp = fopen(path.c_str(), "r");
    if (fp == nullptr) {
        return;
    }
    char line[512];
    while (fgets(line, sizeof(line), fp) != nullptr) {
        std::string text(line);
        if (text.empty() || text[0] == '#') {
            continue;
        }
        char name[128] = {0};
        char file[256] = {0};
        int scale = 2;
        int denoise = 0;
        int tile = 192;
        int n = sscanf(text.c_str(), "%127s %255s %d %d %d", name, file, &scale, &denoise, &tile);
        if (n < 2) {
            continue;
        }
        std::string key(name);
        bool found = false;
        for (auto& slot : g_models) {
            if (slot.entry.name == key) {
                slot.entry.file = file;
                slot.entry.nativeScale = scale > 0 ? scale : 2;
                slot.entry.denoise = denoise;
                slot.entry.tile = tile > 0 ? tile : 192;
                found = true;
                break;
            }
        }
        if (!found) {
            AddModel(key, file, scale > 0 ? scale : 2, denoise, tile > 0 ? tile : 192);
        }
    }
    fclose(fp);
    return;
}

const ModelEntry* FindModel(int modelId) {
    if (modelId < 0 || modelId >= static_cast<int>(g_models.size())) {
        return nullptr;
    }
    return &g_models[static_cast<size_t>(modelId)].entry;
}

/* 目标模型文件缺失时找一个最接近的可用模型(保证超分功能仍然可用)。
 * 只允许"同原生倍数"内替换(如降噪等级/动漫照片风格不同)：
 * 跨倍数替换(如请求 4x 回退到 1x)会让 ProcessTask 末尾按目标尺寸
 * 双线性缩放，产出"只有分辨率变大、画面毫无细节"的假超分，
 * 比明确失败更糟(用户完全看不出哪里出了问题)。
 * 因此没有同倍数候选时返回 nullptr，让任务以 -11 失败并提示缺哪个文件。 */
const ModelEntry* ResolveModel(const ModelEntry* wanted, std::string& note) {
    if (wanted == nullptr) {
        return nullptr;
    }
    if (FileExists(JoinPath(g_modelDir, wanted->file))) {
        return wanted;
    }
    const ModelEntry* best = nullptr;
    int bestScore = -1000;
    for (auto& slot : g_models) {
        const ModelEntry& entry = slot.entry;
        if (entry.file == wanted->file) {
            continue;
        }
        if (!FileExists(JoinPath(g_modelDir, entry.file))) {
            continue;
        }
        if (entry.nativeScale != wanted->nativeScale) {
            continue;  // 跨倍数不回退(见函数注释)
        }
        int score = 0;
        if (entry.name.find("WAIFU2X") != std::string::npos) {
            score += 3;
        }
        if (entry.nativeScale == wanted->nativeScale) {
            score += 4;
        }
        if (entry.denoise == wanted->denoise) {
            score += 2;
        }
        if (entry.name.rfind(wanted->name.substr(0, wanted->name.find("_UP")), 0) == 0) {
            score += 5;
        }
        if (score > bestScore) {
            bestScore = score;
            best = &entry;
        }
    }
    if (best != nullptr) {
        note = wanted->name + " -> " + best->name + " (" + wanted->file + " 不存在)";
    }
    return best;
}

// ---------------------------------------------------------------- ORT 环境
const OrtApi* g_api = nullptr;
OrtEnv* g_env = nullptr;
OrtAllocator* g_allocator = nullptr;
// CPU 张量描述符只读且线程安全，进程内建一次复用；旧实现每个 tile 都新建/释放一遍
OrtMemoryInfo* g_cpuMemInfo = nullptr;

struct SessionHolder {
    OrtSession* session = nullptr;
    std::string path;
    bool htp = false;
    bool gpu = false;           // 该会话跑在 QNN GPU 后端(Adreno)上
    bool cpuFallback = false;   // QNN EP 已挂上，但允许部分算子回退到 CPU 执行
    bool cpuOnly = false;       // 完全退到 CPU EP(最慢的兜底形态)
    std::string inputName;
    std::string outputName;
    ONNXTensorElementDataType inputType = ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT;
    ONNXTensorElementDataType outputType = ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT;
    int tile = 0;
    int nativeScale = 2;
    // 一次 T×T 输入实际得到的输出边长。cunet 这类网络会收缩(实测 up1x: 192->136,
    // up2x: 192->312)，分块几何必须按它算，不能用 tile*nativeScale 想当然
    int outTileW = 0;
    int outTileH = 0;
    std::string modelKey;

    // 释放持有的 ORT 会话：会话被从缓存表摘除(SSR 恢复)或引擎停止时由共享指针归零触发。
    // 注意：会话一旦交给本结构，其他地方不得再自行 Release(见 srq_stop / ReadSessionInfo)。
    ~SessionHolder() {
        if (session != nullptr && g_api != nullptr) {
            g_api->ReleaseSession(session);
            session = nullptr;
        }
    }
};

// 定义在下面；GetSession 里要用它做一次探针推理量真实输出边长
bool RunTile(const std::shared_ptr<SessionHolder>& holder, const std::vector<float>& input,
             int tile, std::vector<float>& output, int& outW, int& outH, std::string& err);

std::map<std::string, std::shared_ptr<SessionHolder>> g_sessions;
std::mutex g_sessionMutex;
std::string g_backendInfo = "CPU (ONNX Runtime)";
int g_device = 0;
int g_threads = 0;
bool g_htpEnabled = false;
bool g_gpuEnabled = false;    // 退到 QNN GPU 后端(Adreno)时置位
bool g_htpFallback = false;   // 有会话是"HTP + 部分算子 CPU 回退"，用于面板如实显示
// 第一次"严格 HTP"失败的原始报错：QNN 一个节点都不接时，真正原因(后端起不来/
// 算子不支持)只会在这里出现一次，后面会被覆盖，所以单独留一份给面板和自检看。
std::string g_htpFirstError;
int g_archOverride = 0;       // 严格 HTP 全失败后，用显式 htp_arch 再抢救一次
std::string g_backendOverride; // 非空时 CreateSession 用它替代 HTP 库路径
bool g_inited = false;

std::string OrtError(OrtStatus* status) {
    if (status == nullptr) {
        return "";
    }
    std::string msg = g_api->GetErrorMessage(status);
    g_api->ReleaseStatus(status);
    return msg;
}

bool HasQnnLib() {
    if (!EnvStr("JM_QNN_BACKEND").empty()) {
        return true;
    }
    // libQnnHtp.so 与 libsr_qnn.so 同目录
    Dl_info info;
    if (dladdr(reinterpret_cast<void*>(&srq_init), &info) != 0 && info.dli_fname != nullptr) {
        std::string dir = DirName(info.dli_fname);
        if (FileExists(JoinPath(dir, "libQnnHtp.so"))) {
            return true;
        }
    }
    void* handle = dlopen("libQnnHtp.so", RTLD_NOW | RTLD_LOCAL);
    if (handle != nullptr) {
        dlclose(handle);
        return true;
    }
    return false;
}

/* HTP 共享内存分配器需要 rpcmem 库(libcdsprpc.so)。ORT 的 RpcMemLibrary 构造时会
 * dlopen 它并取 rpcmem_alloc / rpcmem_free / rpcmem_to_fd 三个符号，任何一步失败都会
 * 抛异常并导致 QNN EP 挂载失败。这里先按同样条件探测，只有确实可用才打开该优化项。
 *
 * 注意：libcdsprpc.so 同时也是 **QNN HTP 与 DSP 通信的 FastRPC 通道**。真机上如果它
 * 不在应用的 linker namespace 里（厂商没把它列进 public.libraries.txt），HTP 设备根本
 * 建不起来 —— 表现就是"会话建出来了但 QNN 一个节点都不接"。所以探测失败要把 dlerror
 * 打出来，别当成"只是个可选优化"。 */
bool SharedMemoryAvailable() {
    void* handle = dlopen("libcdsprpc.so", RTLD_NOW | RTLD_LOCAL);
    if (handle == nullptr) {
        const char* reason = dlerror();
        printf("[sr_qnn] 警告: 加载 libcdsprpc.so 失败(FastRPC，HTP 必需): %s\n",
               reason != nullptr ? reason : "unknown");
        return false;
    }
    bool ok = dlsym(handle, "rpcmem_alloc") != nullptr
              && dlsym(handle, "rpcmem_free") != nullptr
              && dlsym(handle, "rpcmem_to_fd") != nullptr;
    dlclose(handle);
    return ok;
}

void PrepareQnnSearchPath() {
    Dl_info info;
    if (dladdr(reinterpret_cast<void*>(&srq_init), &info) == 0 || info.dli_fname == nullptr) {
        return;
    }
    std::string dir = DirName(info.dli_fname);
    std::string adsp = EnvStr("ADSP_LIBRARY_PATH");
    if (adsp.find(dir) == std::string::npos) {
        adsp += (adsp.empty() ? "" : ";");
        adsp += dir + ";/dsp;/vendor/dsp;/system/lib/rfsa/adsp";
        setenv("ADSP_LIBRARY_PATH", adsp.c_str(), 1);
    }
    std::string ld = EnvStr("LD_LIBRARY_PATH");
    if (ld.find(dir) == std::string::npos) {
        ld = dir + (ld.empty() ? "" : ":" + ld);
        setenv("LD_LIBRARY_PATH", ld.c_str(), 1);
    }
    return;
}

/* 创建一个会话；useHtp 为 true 时挂 QNN EP
 * tier 为 HTP 选项档位(逐级降级，见 GetSession)：
 *   3 = 基础项 + 全部提速项 + VTCM
 *   2 = 基础项 + 全部提速项(不含 VTCM，小 VTCM 机型的兜底)
 *   1 = 基础项(backend_path + fp16 + device_id)，绝大多数机型都能过
 *   0 = 最小项(只给 backend_path)，连 fp16 都不假设
 * 旧实现把 vtcm_mb 这类强依赖机型能力的选项放在所有尝试里无条件下发：
 * 小 VTCM 机型上 QNN 图编译失败 → 整页退回 CPU EP → 表现就是"超分慢得离谱"。 */
OrtSession* CreateSession(const std::string& modelPath, const ModelEntry& entry, bool useHtp,
                          bool strictHtp, bool useContextCache, int tier, std::string& err) {
    OrtSessionOptions* options = nullptr;
    OrtStatus* status = g_api->CreateSessionOptions(&options);
    if (status != nullptr) {
        err = OrtError(status);
        return nullptr;
    }
    g_api->SetIntraOpNumThreads(options, g_threads);
    // 关键：QNN 会话只开 BASIC 级优化。
    // ORT 的 Level-2 优化会把 Conv+LeakyRelu 融合成 CPU EP 专属的
    // com.microsoft.FusedConv —— QNN EP 不认识这个算子，分区时整张图连带所有下游
    // 节点全被判到 CPU，表现就是"会话建出来了但 QNN 一个节点都没接"(真机实测：
    // 跑在 CPU 上的算子全是 FusedConv)。QNN 自己会在 finalize 阶段做图优化，
    // 不需要 ORT 这几档融合。
    g_api->SetSessionGraphOptimizationLevel(options, useHtp ? ORT_ENABLE_BASIC : ORT_ENABLE_ALL);

    // 诊断用：设置 JM_SR_PROFILE 后 ORT 会把每个节点的执行记录写成 json，
    // 里面带 provider 字段 —— 能直接看出哪些算子被 QNN 拒收、跑到了 CPU 上。
    std::string profilePath = EnvStr("JM_SR_PROFILE");
    if (!profilePath.empty()) {
        OrtStatus* profileStatus = g_api->EnableProfiling(options, profilePath.c_str());
        if (profileStatus != nullptr) {
            g_api->ReleaseStatus(profileStatus);
        }
    }

    if (!useHtp) {
        // CPU 兜底时尽量挂上加速 EP：XNNPACK(浮点/量化卷积优化，常见 2~4 倍) →
        // NNAPI(部分机型的 GPU/NPU)。不可用时 AppendExecutionProvider 只返回错误状态，
        // 不致命，忽略即可；这样"没有 HTP 的机型"也不至于掉到最慢的纯 CPU 实现。
        const char* candidates[2] = {"XNNPACK", "NNAPI"};
        for (const char* name : candidates) {
            OrtStatus* tryStatus = g_api->SessionOptionsAppendExecutionProvider(
                options, name, nullptr, nullptr, 0);
            if (tryStatus == nullptr) {
                if (g_debug) {
                    printf("[sr_qnn] CPU 路径已挂 %s\n", name);
                }
                break;
            }
            (void) g_api->GetErrorMessage(tryStatus);
            g_api->ReleaseStatus(tryStatus);
        }
    }

    if (useHtp) {
        // 先把 key/value 字符串全部收集齐，最后再取 c_str() 组指针数组。
        // 原来的写法是边 push_back 到 vector<string> 边把 storage.back().c_str() 存进
        // values —— vector 扩容会让先前元素的 c_str() 全部悬空，ORT 于是收到空/垃圾字符串，
        // 报 "Provider options key/value cannot be empty" 并让 QNN EP 挂载失败(真机实测)。
        std::vector<std::string> keysStore;
        std::vector<std::string> valuesStore;
        auto addOption = [&](const char* key, const std::string& value) {
            keysStore.emplace_back(key);
            valuesStore.push_back(value);
        };
        // backend_path 默认用"与本库同目录的 libQnnHtp.so 绝对路径"。
        // 裸文件名在 Android 上不可靠：linker 不认 LD_LIBRARY_PATH。
        std::string backend = EnvStr("JM_QNN_BACKEND");
        if (!g_backendOverride.empty()) {
            backend = g_backendOverride;
        }
        if (backend.empty()) {
            Dl_info info;
            if (dladdr(reinterpret_cast<void*>(&srq_init), &info) != 0 && info.dli_fname != nullptr) {
                std::string candidate = JoinPath(DirName(info.dli_fname), "libQnnHtp.so");
                backend = FileExists(candidate) ? candidate : "libQnnHtp.so";
            } else {
                backend = "libQnnHtp.so";
            }
        }
        addOption("backend_path", backend);
        addOption("device_id", std::to_string(g_device));
        addOption("profiling_level", "off");
        // GPU(Adreno) 与 HTP(DSP) 的选项互不通用：把 htp_* / vtcm_mb /
        // enable_htp_fp16_precision 传给 GPU 后端，QnnBackend 初始化会直接失败，
        // 表现为"EP 挂上了但一个节点都不接"。所以按后端类型分流。
        const bool isGpuBackend = backend.find("Gpu") != std::string::npos;
        if (!isGpuBackend && tier >= 1) {
            addOption("enable_htp_fp16_precision", EnvStr("JM_QNN_FP16", "1"));
        }
        // ---- 提速项(仅 tier>=2；任何一项不被当前 ORT/QNN/机型支持时，
        //      GetSession 会逐级退回 tier 1 / 0，最终才退到 CPU EP) ----------
        if (tier >= 2 && !isGpuBackend) {
            // 性能模式：QNN EP 官方推理示例用 burst(最高性能档)，交互式看图(读一页超一页)
            // 正是突发负载，默认用它；长时间批量转换发热降频时可改回 sustained_high_performance。
            addOption("htp_performance_mode", EnvStr("JM_QNN_PERF", "burst"));
            // 2 = 图编译更久但运行时更优；默认取 2：首次编译时间不至于让用户以为"卡住"。
            addOption("htp_graph_finalization_optimization_mode", EnvStr("JM_QNN_FINALIZE", "2"));
            // 每个 tile 一次 FastRPC 往返，微秒级的控制延迟 ×上百块会累加；
            // 需要时用 JM_QNN_RPC_LATENCY(微秒) 调低，默认不干预(用 SDK 默认值)。
            std::string rpcLatency = EnvStr("JM_QNN_RPC_LATENCY");
            if (!rpcLatency.empty()) {
                addOption("rpc_control_latency", rpcLatency);
            }
            // 会话优先级：DSP 上同时有其它 QNN 负载时降低本任务的排队延迟。
            addOption("qnn_context_priority", EnvStr("JM_QNN_PRIORITY", "high"));
            // HTP 共享内存分配器：CPU 与 HTP 之间零拷贝共享 I/O 张量，减少每块 tile
            // 的来回复制(需 rpcmem/libcdsprpc.so，探测不到就自动跳过)。
            if (EnvFlag("JM_QNN_SHARED_MEM", true)) {
                if (SharedMemoryAvailable()) {
                    addOption("enable_htp_shared_memory_allocator", "1");
                } else if (g_debug) {
                    printf("[sr_qnn] rpcmem(libcdsprpc.so) 不可用，跳过 HTP 共享内存分配器\n");
                }
            }
            // 多会话共享 VTCM 备份缓冲(省内存)；与 context 内嵌缓存冲突，故默认关闭。
            if (EnvFlag("JM_QNN_VTCM_SHARE", false)) {
                addOption("enable_vtcm_backup_buffer_sharing", "1");
            }
            if (!EnvStr("JM_QNN_SOC_MODEL").empty()) {
                addOption("soc_model", EnvStr("JM_QNN_SOC_MODEL"));
            }
            std::string htpArch = EnvStr("JM_QNN_HTP_ARCH");
            if (htpArch.empty() && g_archOverride > 0) {
                htpArch = std::to_string(g_archOverride);
            }
            if (!htpArch.empty()) {
                addOption("htp_arch", htpArch);
            }
        }
        // VTCM 大小强依赖机型(2/4/8MB 不等)，所以单独成档(tier 3)：有 VTCM 的机型
        // 卷积更快；编译不过就自动退回不含 VTCM 的 tier 2，不会把设备顶进 CPU EP。
        if (tier >= 3) {
            std::string vtcm = EnvStr("JM_QNN_VTCM", "8");
            if (!vtcm.empty() && vtcm != "0") {
                addOption("vtcm_mb", vtcm);
            }
        }
        // 此时 keysStore/valuesStore 不会再变，取 c_str() 是安全的
        std::vector<const char*> keys;
        std::vector<const char*> values;
        keys.reserve(keysStore.size());
        values.reserve(valuesStore.size());
        for (size_t i = 0; i < keysStore.size(); ++i) {
            keys.push_back(keysStore[i].c_str());
            values.push_back(valuesStore[i].c_str());
        }
        status = g_api->SessionOptionsAppendExecutionProvider(options, "QNN", keys.data(),
                                                             values.data(), keys.size());
        if (status != nullptr) {
            err = "QNN EP 挂载失败: " + OrtError(status);
            g_api->ReleaseSessionOptions(options);
            return nullptr;
        }
        if (strictHtp) {
            g_api->AddSessionConfigEntry(options, "session.disable_cpu_ep_fallback", "1");
        }
    }

    std::string ctxPath;
    if (useHtp && useContextCache) {
        std::string cacheDir = EnvStr("JM_SR_CACHE", JoinPath(g_modelDir, "context"));
        MakeDirs(cacheDir);
        std::string key = entry.file;
        std::replace(key.begin(), key.end(), '/', '_');
        // 后端类型必须进 key：HTP 编译出的 context binary 在 GPU 后端上不可用，
        // 反过来也一样；否则切换后端会读到对方编译的缓存，直接建会话失败。
        if (!g_backendOverride.empty() || EnvStr("JM_QNN_BACKEND").find("Gpu") != std::string::npos) {
            key += "-gpu";
        }
        std::string fingerprint = FileFingerprint(JoinPath(g_modelDir, entry.file));
        if (!fingerprint.empty()) {
            key += "-" + fingerprint;
        }
        ctxPath = JoinPath(cacheDir, key + ".ctx.onnx");
        if (FileExists(ctxPath)) {
            // 已有 context binary 缓存：直接加载缓存模型
            OrtSession* session = nullptr;
            status = g_api->CreateSession(g_env, ctxPath.c_str(), options, &session);
            g_api->ReleaseSessionOptions(options);
            if (status == nullptr) {
                if (g_debug) {
                    printf("[sr_qnn] load cached context: %s\n", ctxPath.c_str());
                }
                return session;
            }
            err = OrtError(status);
            if (g_debug) {
                printf("[sr_qnn] cached context 失效，回退普通加载: %s\n", err.c_str());
            }
            if (useContextCache) {
                // 缓存损坏，删除后重来
                remove(ctxPath.c_str());
            }
            return CreateSession(modelPath, entry, useHtp, strictHtp, false, tier, err);
        }
        g_api->AddSessionConfigEntry(options, "ep.context_enable", "1");
        g_api->AddSessionConfigEntry(options, "ep.context_file_path", ctxPath.c_str());
        // 换了模型内容后旧缓存不再需要，顺手清掉，避免缓存目录越滚越大
        CleanStaleContext(cacheDir, entry.file, key + ".ctx.onnx");
        // 把 context binary 内嵌进生成的单个 onnx(默认)，避免 .onnx 与分离的 .bin
        // 一旦不同步就整块缓存失效；与 VTCM 备份缓冲共享冲突，故后者开启时让位。
        if (tier >= 2 && !EnvFlag("JM_QNN_VTCM_SHARE", false)) {
            std::string embed = EnvStr("JM_QNN_EMBED_CTX", "1");
            g_api->AddSessionConfigEntry(options, "ep.context_embed_mode", embed.c_str());
        }
    }

    OrtSession* session = nullptr;
    status = g_api->CreateSession(g_env, modelPath.c_str(), options, &session);
    g_api->ReleaseSessionOptions(options);
    if (status != nullptr) {
        err = OrtError(status);
        return nullptr;
    }
    return session;
}

bool ReadSessionInfo(SessionHolder* holder) {
    size_t inputCount = 0;
    size_t outputCount = 0;
    if (g_api->SessionGetInputCount(holder->session, &inputCount) != nullptr || inputCount == 0) {
        return false;
    }
    if (g_api->SessionGetOutputCount(holder->session, &outputCount) != nullptr || outputCount == 0) {
        return false;
    }
    OrtAllocator* allocator = g_allocator;
    char* name = nullptr;
    if (g_api->SessionGetInputName(holder->session, 0, allocator, &name) != nullptr) {
        return false;
    }
    holder->inputName = name;
    (void) g_api->AllocatorFree(allocator, name);
    name = nullptr;
    if (g_api->SessionGetOutputName(holder->session, 0, allocator, &name) != nullptr) {
        return false;
    }
    holder->outputName = name;
    (void) g_api->AllocatorFree(allocator, name);

    OrtTypeInfo* typeInfo = nullptr;
    const OrtTensorTypeAndShapeInfo* shapeInfo = nullptr;
    if (g_api->SessionGetInputTypeInfo(holder->session, 0, &typeInfo) == nullptr) {
        if (g_api->CastTypeInfoToTensorInfo(typeInfo, &shapeInfo) == nullptr) {
            (void) g_api->GetTensorElementType(shapeInfo, &holder->inputType);
        }
        g_api->ReleaseTypeInfo(typeInfo);
    }
    typeInfo = nullptr;
    shapeInfo = nullptr;
    if (g_api->SessionGetOutputTypeInfo(holder->session, 0, &typeInfo) == nullptr) {
        if (g_api->CastTypeInfoToTensorInfo(typeInfo, &shapeInfo) == nullptr) {
            (void) g_api->GetTensorElementType(shapeInfo, &holder->outputType);
        }
        g_api->ReleaseTypeInfo(typeInfo);
    }
    return true;
}

std::shared_ptr<SessionHolder> GetSession(const ModelEntry& entry, std::string& err) {
    std::lock_guard<std::mutex> lock(g_sessionMutex);
    std::string key = entry.file + "#" + std::to_string(entry.tile);
    auto it = g_sessions.find(key);
    if (it != g_sessions.end()) {
        return it->second;
    }

    std::string path = JoinPath(g_modelDir, entry.file);
    if (!FileExists(path)) {
        err = "模型文件不存在: " + path;
        return nullptr;
    }

    auto holder = std::make_shared<SessionHolder>();
    holder->path = path;
    holder->tile = entry.tile;
    holder->nativeScale = entry.nativeScale;
    holder->modelKey = key;

    bool wantHtp = g_device <= 0 && HasQnnLib();
    if (wantHtp && g_qnnUnusable.load()) {
        // 已经在本机确认过"QNN 后端建不起来"(SetupBackend 失败)，后面每个模型
        // 都别再白跑 5 次会话创建 —— 那要几百毫秒到几秒，全花在必败的重试上。
        if (g_debug) {
            printf("[sr_qnn] QNN 在本机已确认不可用，直接走 CPU EP\n");
        }
        wantHtp = false;
    }
    std::string lastErr;
    bool setupFailed = false;   // 本次尝试是否出现过 "QNN SetupBackend failed"
    if (wantHtp) {
        // 逐级降级，保证"要么整图在 NPU 上，要么明确告诉我们退到哪一级"：
        //   1) 严格 HTP + 全部提速项 + VTCM(整图跑在 NPU 上)
        //   2) 严格 HTP + 全部提速项，不含 VTCM(小 VTCM 机型的兜底)
        //   3) 严格 HTP + 基础项(去掉编译档位/优先级/共享内存)
        //   4) 严格 HTP + 最小项(只给 backend_path，连 fp16 都不假设)
        //   5) HTP + 允许 CPU 兜底(部分算子跑 CPU，最慢的 NPU 形态)
        // 每次尝试前清空"分区数/SetupBackend 失败"两个探针，避免读到上一次的残留。
        auto tryQnn = [&](bool strict, bool cache, int tier) -> OrtSession* {
            g_qnnPartitionCount.store(-1);
            g_qnnSetupFailed.store(false);
            OrtSession* attempt = CreateSession(path, entry, true, strict, cache, tier, lastErr);
            if (g_qnnSetupFailed.load()) {
                setupFailed = true;
            }
            return attempt;
        };
        // 判定一次尝试是不是"白跑"：后端没 init 成功，或一个节点都没接住。
        // 这两种会话每块 tile 都要白过一遍 EP 调度，比纯 CPU 还慢，必须丢掉。
        auto ineffective = [&]() {
            return g_qnnSetupFailed.load() || g_qnnPartitionCount.load() == 0;
        };
        OrtSession* session = tryQnn(true, true, 3);
        if (session == nullptr) {
            if (g_htpFirstError.empty()) {
                g_htpFirstError = lastErr;
            }
            if (g_debug) {
                printf("[sr_qnn] 严格 HTP(含 VTCM) 失败，去掉 VTCM 重试: %s\n", lastErr.c_str());
            }
            session = tryQnn(true, true, 2);
        }
        if (session == nullptr) {
            if (g_debug) {
                printf("[sr_qnn] 严格 HTP(提速项) 失败，降级为基础项: %s\n", lastErr.c_str());
            }
            session = tryQnn(true, true, 1);
        }
        if (session == nullptr) {
            if (g_debug) {
                printf("[sr_qnn] 严格 HTP(基础项) 失败，降级为最小项: %s\n", lastErr.c_str());
            }
            session = tryQnn(true, false, 0);
        }
        if (session == nullptr && EnvStr("JM_QNN_HTP_ARCH").empty()) {
            // 新机型(如 SM8750)不在当前 QNN SDK 的 SoC 表里时，自动探测拿不到 HTP
            // 设备，表现就是"会话建出来了但 QNN 一个节点都不接"。用显式 htp_arch
            // 再试几档；失败也只是多花几毫秒（HTP 起不来时会立刻报错）。
            const int archs[3] = {79, 75, 73};
            for (int arch : archs) {
                g_archOverride = arch;
                session = tryQnn(true, false, 2);
                if (session != nullptr) {
                    printf("[sr_qnn] 显式 htp_arch=%d 成功\n", arch);
                    break;
                }
            }
            g_archOverride = 0;
        }
        if (session == nullptr) {
            // HTP 全军覆没时的第二选择：QNN GPU 后端(Adreno)。
            // 它走 OpenCL，不依赖 FastRPC/DSP，所以"HTP 起不来"不等于 QNN 用不了；
            // fp32 模型也能直接跑，对 waifu2x 这种卷积网络，Adreno 的 fp16/fp32
            // 吞吐本来就比自己 CPU 高一个数量级。
            std::string gpuLib;
            Dl_info gpuInfo;
            if (dladdr(reinterpret_cast<void*>(&srq_init), &gpuInfo) != 0 && gpuInfo.dli_fname != nullptr) {
                std::string candidate = JoinPath(DirName(gpuInfo.dli_fname), "libQnnGpu.so");
                if (FileExists(candidate)) {
                    gpuLib = candidate;
                }
            }
            if (!gpuLib.empty()) {
                g_backendOverride = gpuLib;
                session = tryQnn(true, false, 0);
                if (session == nullptr) {
                    session = tryQnn(false, false, 0);
                    if (session != nullptr && ineffective()) {
                        // SetupBackend 失败 / 0 分区：这个后端在本机根本没跑起来，
                        // 留着只会让每块 tile 白过一层 EP 调度。
                        g_api->ReleaseSession(session);
                        session = nullptr;
                        printf("[sr_qnn] QNN GPU 后端不可用(SetupBackend 失败或 0 分区)，放弃\n");
                    } else if (session != nullptr) {
                        holder->cpuFallback = true;
                    }
                }
                g_backendOverride.clear();
                if (session != nullptr) {
                    holder->gpu = true;
                    g_gpuEnabled = true;
                    printf("[sr_qnn] HTP 不可用，改用 QNN GPU 后端(Adreno): %s\n", gpuLib.c_str());
                }
            }
        }
        if (session == nullptr) {
            if (g_debug) {
                printf("[sr_qnn] 严格 HTP 全部失败，允许 CPU 兜底: %s\n", lastErr.c_str());
            }
            session = tryQnn(false, false, 1);
            if (session != nullptr) {
                if (ineffective()) {
                    // 关键：QNN 没接住任何节点(或后端压根没 init 成功)。这种会话把每块
                    // tile 都往里塞一遍，只是多一层 EP 调度 —— 比纯 CPU 还慢，丢掉。
                    g_api->ReleaseSession(session);
                    session = nullptr;
                    printf("[sr_qnn] QNN 未接管任何节点(SetupBackend 失败/0 分区)，改走 CPU EP\n");
                } else {
                    holder->cpuFallback = true;
                    // 走到这里说明 QNN 只接下了一部分节点。最常见的原因见 CreateSession
                    // 里关于 ORT_ENABLE_BASIC 的注释（CPU EP 融合出 QNN 不认识的算子），
                    // 其次是模型里还有动态 shape 写法（用 simplify_models.py 静态化）。
                    printf("[sr_qnn] 警告: %s 只有部分节点能上 QNN，超分会明显变慢\n",
                           entry.file.c_str());
                }
            }
        }
        if (session == nullptr && setupFailed) {
            // 后端初始化就失败(HTP 缺 libcdsprpc.so / GPU 报 PLATFORM_NOT_SUPPORTED)：
            // 这不是"档位没调对"，重试别的档位也一定失败。直接判死，后续模型不再重试。
            g_qnnUnusable.store(true);
            printf("[sr_qnn] QNN 后端在本机不可用(SetupBackend 失败)，后续模型直接用 CPU EP\n");
            printf("[sr_qnn] 提示: HTP 需要厂商库 libcdsprpc.so(FastRPC)，见 android/vendor_libs/README.md\n");
        }
        if (session != nullptr) {
            holder->session = session;
            holder->htp = !holder->gpu;
            if (holder->htp) {
                g_htpEnabled = true;
            }
            if (holder->cpuFallback) {
                g_htpFallback = true;
            }
        }
    }
    if (holder->session == nullptr) {
        // 5) CPU EP 兜底，保证功能可用(慢，但不会让用户失去超分能力)
        OrtSession* session = CreateSession(path, entry, false, false, false, 0, lastErr);
        if (session == nullptr) {
            err = lastErr;
            return nullptr;
        }
        holder->session = session;
        holder->htp = false;
        holder->cpuOnly = true;
        if (g_debug) {
            printf("[sr_qnn] 使用 CPU EP(最慢，请检查 QNN 库/机型支持): %s\n", lastErr.c_str());
        }
    }
    if (!ReadSessionInfo(holder.get())) {
        g_api->ReleaseSession(holder->session);
        holder->session = nullptr;   // 避免 SessionHolder 析构时二次释放
        err = "读取模型输入输出信息失败";
        return nullptr;
    }
    if (g_debug) {
        const char* grade = holder->cpuOnly ? "CPU EP" :
                            (holder->cpuFallback ? (holder->gpu ? "GPU(CPU 回退)" : "HTP(CPU 回退)")
                                                 : (holder->gpu ? "GPU(整图)" : "HTP(整图)"));
        printf("[sr_qnn] session %s -> %s\n", entry.file.c_str(), grade);
    }
    // 探针推理：用一块全 0 的 T×T 输入量出真实输出边长。
    // 既不能拿 ONNX metadata 猜，也不能假设 out = in * nativeScale ——
    // cunet 的实际输出比 tile*nativeScale 小(每边收缩)，算错会让分块拼接错位并缺带。
    {
        int probeTile = holder->tile > 0 ? holder->tile : 192;
        std::vector<float> probe(static_cast<size_t>(probeTile) * probeTile * 3, 0.0f);
        std::vector<float> probeOut;
        int probeW = probeTile * std::max(1, holder->nativeScale);
        int probeH = probeW;
        std::string probeErr;
        if (RunTile(holder, probe, probeTile, probeOut, probeW, probeH, probeErr)) {
            holder->outTileW = probeW;
            holder->outTileH = probeH;
            if (g_debug) {
                printf("[sr_qnn] 探针: tile=%d -> 输出 %dx%d (nativeScale=%d)\n",
                       probeTile, probeW, probeH, holder->nativeScale);
            }
        } else if (g_debug) {
            printf("[sr_qnn] 探针推理失败, 分块退回默认几何: %s\n", probeErr.c_str());
        }
    }
    g_sessions[key] = holder;
    return holder;
}

// ---------------------------------------------------------------- 任务队列
struct SrTask {
    int taskId = 0;
    int modelId = 0;
    double scale = 0;
    int targetW = 0;
    int targetH = 0;
    std::string format = "jpg";
    int tileSize = 0;
    int width = 0;
    int height = 0;
    std::vector<uint8_t> rgb;   // 紧凑 RGB888
    std::atomic<int> cancel{0}; // 0 正常 1 取消(回报错误) 2 丢弃(静默)
};

struct SrOut {
    int taskId = 0;
    int status = 0;
    double tick = 0;
    std::string format = "jpg";
    int width = 0;
    int height = 0;
    std::vector<uint8_t> rgb;
};

std::mutex g_queueMutex;
std::condition_variable g_queueCond;
std::condition_variable g_resultCond;
std::deque<std::shared_ptr<SrTask>> g_taskQueue;
std::deque<std::shared_ptr<SrOut>> g_resultQueue;
std::vector<std::thread> g_workers;
bool g_stopping = false;

/* 单块推理：把 tile×tile 的 RGB 浮点数据送进模型，回读到 output(NCHW) */
bool RunTile(const std::shared_ptr<SessionHolder>& holder, const std::vector<float>& input,
             int tile, std::vector<float>& output, int& outW, int& outH, std::string& err) {
    const int64_t dims[4] = {1, 3, static_cast<int64_t>(tile), static_cast<int64_t>(tile)};
    OrtMemoryInfo* memInfo = g_cpuMemInfo;
    if (memInfo == nullptr) {
        err = "引擎未初始化(CPU 内存描述符缺失)";
        return false;
    }
    OrtValue* inputValue = nullptr;
    OrtStatus* status = nullptr;
    std::vector<uint16_t> halfInput;
    const void* inputPtr = input.data();
    size_t inputBytes = input.size() * sizeof(float);
    if (holder->inputType == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16) {
        halfInput.resize(input.size());
        FloatToHalfBuf(input.data(), halfInput.data(), input.size());
        inputPtr = halfInput.data();
        inputBytes = halfInput.size() * sizeof(uint16_t);
    }
    status = g_api->CreateTensorWithDataAsOrtValue(memInfo, const_cast<void*>(inputPtr), inputBytes,
                                                   dims, 4, holder->inputType, &inputValue);
    if (status != nullptr) {
        err = "创建输入张量失败: " + OrtError(status);
        return false;
    }
    const char* inputNames[1] = {holder->inputName.c_str()};
    const char* outputNames[1] = {holder->outputName.c_str()};
    const OrtValue* inputValues[1] = {inputValue};
    OrtValue* outputValue = nullptr;
    status = g_api->Run(holder->session, nullptr, inputNames, inputValues, 1,
                        outputNames, 1, &outputValue);
    g_api->ReleaseValue(inputValue);
    if (status != nullptr) {
        err = "推理失败: " + OrtError(status);
        return false;
    }

    OrtTensorTypeAndShapeInfo* shapeInfo = nullptr;
    if (g_api->GetTensorTypeAndShape(outputValue, &shapeInfo) != nullptr) {
        g_api->ReleaseValue(outputValue);
        err = "读取输出形状失败";
        return false;
    }
    size_t rank = 0;
    (void) g_api->GetDimensionsCount(shapeInfo, &rank);
    int64_t dimsOut[8] = {0};
    if (rank > 8) {
        rank = 8;
    }
    (void) g_api->GetDimensions(shapeInfo, dimsOut, rank);
    g_api->ReleaseTensorTypeAndShapeInfo(shapeInfo);
    int tileOutH = rank >= 2 ? static_cast<int>(dimsOut[rank - 2]) : 0;
    int tileOutW = rank >= 1 ? static_cast<int>(dimsOut[rank - 1]) : 0;
    int channels = rank >= 3 ? static_cast<int>(dimsOut[rank - 3]) : 3;
    if (tileOutH <= 0 || tileOutW <= 0 || channels <= 0) {
        g_api->ReleaseValue(outputValue);
        err = "输出尺寸异常";
        return false;
    }

    void* raw = nullptr;
    if (g_api->GetTensorMutableData(outputValue, &raw) != nullptr || raw == nullptr) {
        g_api->ReleaseValue(outputValue);
        err = "读取输出数据失败";
        return false;
    }
    const size_t count = static_cast<size_t>(channels) * tileOutH * tileOutW;
    output.resize(count);
    if (holder->outputType == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16) {
        HalfToFloatBuf(reinterpret_cast<const uint16_t*>(raw), output.data(), count);
    } else if (holder->outputType == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) {
        memcpy(output.data(), raw, count * sizeof(float));
    } else if (holder->outputType == ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8) {
        const uint8_t* src = reinterpret_cast<const uint8_t*>(raw);
        for (size_t i = 0; i < count; ++i) {
            output[i] = src[i] * kInv255;
        }
    } else {
        g_api->ReleaseValue(outputValue);
        err = "不支持的输出类型";
        return false;
    }
    g_api->ReleaseValue(outputValue);
    outW = tileOutW;
    outH = tileOutH;
    return true;
}

/* HTP 子系统重启(SSR)后 ORT 会话即不可再用，官方要求上层重建会话(见 QNN EP 文档
 * "HTP SubSystem Restart")。这里在检测到 ENGINE_ERROR/SSR 时把坏会话从缓存表摘掉
 * 并重建一次；摘除时故意不立刻 Release(可能仍有其它工作线程在用)，交给共享指针归零
 * 后由 SessionHolder 析构释放。 */
bool RecoverHtpSession(const ModelEntry& entry, std::shared_ptr<SessionHolder>& holder,
                       std::string& err) {
    if (!holder->htp || !EnvFlag("JM_QNN_SSR_RECOVER", true)) {
        return false;
    }
    if (err.find("ENGINE_ERROR") == std::string::npos && err.find("SSR") == std::string::npos) {
        return false;
    }
    {
        std::lock_guard<std::mutex> lock(g_sessionMutex);
        auto it = g_sessions.find(holder->modelKey);
        if (it != g_sessions.end() && it->second == holder) {
            g_sessions.erase(it);
        }
    }
    std::string rebuildErr;
    auto fresh = GetSession(entry, rebuildErr);
    if (fresh == nullptr) {
        if (g_debug) {
            printf("[sr_qnn] HTP 会话重建失败: %s\n", rebuildErr.c_str());
        }
        return false;
    }
    holder = fresh;
    if (g_debug) {
        printf("[sr_qnn] HTP 会话已重建(SSR 恢复)\n");
    }
    return true;
}

/* 处理一个任务：分块推理 + 拼接 + 目标尺寸缩放 */
int ProcessTask(const std::shared_ptr<SrTask>& task, std::shared_ptr<SrOut>& result) {
    auto begin = std::chrono::steady_clock::now();
    result = std::make_shared<SrOut>();
    result->taskId = task->taskId;
    result->format = task->format;
    // lastError 语义：最近一次任务的错误(成功则清零)，
    // 便于上层区分"这次为什么没有结果"而不是读到很久以前的陈旧错误
    SetError("");

    const ModelEntry* wanted = FindModel(task->modelId);
    if (wanted == nullptr) {
        result->status = -10;
        SetError("未知模型编号");
        return -10;
    }
    std::string note;
    const ModelEntry* entry = ResolveModel(wanted, note);
    if (entry == nullptr) {
        result->status = -11;
        SetError("模型文件缺失: " + JoinPath(g_modelDir, wanted->file) + "，且没有 " +
                 std::to_string(wanted->nativeScale) + "x 的可用模型可回退，请把模型文件放到 " +
                 g_modelDir + " 或在设置里更换模型");
        return -11;
    }
    if (!note.empty()) {
        // 同倍数内的降级替换(如 denoise3 -> denoise0)：仍是真实超分，
        // 但结果与预期有差距，总是记录，不受 g_debug 控制
        printf("[sr_qnn] 模型回退: %s\n", note.c_str());
    }

    std::string err;
    auto holder = GetSession(*entry, err);
    if (holder == nullptr) {
        result->status = -12;
        SetError(err);
        return -12;
    }

    const int tile = holder->tile > 0 ? holder->tile : 192;
    const int nativeScale = holder->nativeScale > 0 ? holder->nativeScale : 2;

    // ---- 分块几何 ------------------------------------------------------
    // cunet 这类网络会"收缩"：T×T 输入得到 O < T*s 的输出(实测 up1x 192->136,
    // up2x 192->312)。其映射关系是"输出第 j 个像素对应输入坐标 (j + mPrime)/s"，
    // 其中 mPrime = (T*s - O)/2。由此：
    //     有效输出读取偏移 = pad*s - mPrime
    //     可用输入窗口宽   = T - 2*pad
    // 取 pad = ceil(mPrime/s) 时读取偏移恰好为 0、输出范围正好填满，既不位移也不缺带。
    // 原实现直接按 out = in*s 用 pad*s 读取，会同时造成"整块错位"和
    // "每块底部被 ty>=outH 的 break 截断"(表现为横向黑带)。
    int shrinkX = 0;
    int shrinkY = 0;
    if (holder->outTileW > 0 && holder->outTileH > 0) {
        shrinkX = std::max(0, (tile * nativeScale - holder->outTileW) / 2);
        shrinkY = std::max(0, (tile * nativeScale - holder->outTileH) / 2);
    }
    int needPadX = (shrinkX + nativeScale - 1) / nativeScale;
    int needPadY = (shrinkY + nativeScale - 1) / nativeScale;
    int pad = std::max(needPadX, needPadY);
    if (pad <= 0) {
        // 不收缩的普通模型(ESRGAN 等)：保留少量重叠，纯粹用于消除接缝
        pad = std::min(16, std::max(4, tile / 8));
    }
    if (tile - 2 * pad <= 0) {
        result->status = -15;
        SetError("模型收缩过大, tile=" + std::to_string(tile) + " 收缩=" +
                 std::to_string(shrinkX) + "/" + std::to_string(shrinkY) + " 无法分块");
        return -15;
    }
    const int step = tile - 2 * pad;
    const int readX = pad * nativeScale - shrinkX;
    const int readY = pad * nativeScale - shrinkY;

    const int width = task->width;
    const int height = task->height;
    std::vector<uint8_t> srImage(static_cast<size_t>(width) * nativeScale * height * nativeScale * 3, 0);
    const int srWidth = width * nativeScale;
    const int srHeight = height * nativeScale;

    std::vector<float> input(static_cast<size_t>(tile) * tile * 3, 0.0f);
    std::vector<float> output;
    // 调试统计：拆开 CPU 侧(打包/回写)与 NPU 侧耗时，真机上据此判断瓶颈在哪
    double packMs = 0;
    double runMs = 0;
    double unpackMs = 0;
    int tileCount = 0;

    for (int oy = 0; oy < height; oy += step) {
        if (task->cancel.load() != 0) {
            result->status = -20;
            return -20;
        }
        int rh = std::min(step, height - oy);
        for (int ox = 0; ox < width; ox += step) {
            if (task->cancel.load() != 0) {
                result->status = -20;
                return -20;
            }
            int rw = std::min(step, width - ox);
            // 填充 T×T 输入：以 (ox-pad, oy-pad) 为起点，越界用边缘像素
            // 注意：ONNX 输入是 NCHW，必须按平面写入，不能按 HWC 交错
            auto tp0 = std::chrono::steady_clock::now();
            PackTileInput(task->rgb, width, height, ox, oy, pad, tile, input);
            auto tp1 = std::chrono::steady_clock::now();
            int outW = static_cast<int>(tile) * nativeScale;
            int outH = static_cast<int>(tile) * nativeScale;
            bool tileOk = RunTile(holder, input, tile, output, outW, outH, err);
            auto tp2 = std::chrono::steady_clock::now();
            if (!tileOk && RecoverHtpSession(*entry, holder, err)) {
                // 会话已重建：重置输出几何后重试本块
                outW = static_cast<int>(tile) * nativeScale;
                outH = outW;
                tileOk = RunTile(holder, input, tile, output, outW, outH, err);
                tp2 = std::chrono::steady_clock::now();
            }
            if (!tileOk) {
                result->status = -13;
                SetError(err);
                return -13;
            }
            if (outW <= 0 || outH <= 0) {
                result->status = -14;
                SetError("输出尺寸解析失败");
                return -14;
            }
            // 有效区域：源图 [ox, ox+rw) x [oy, oy+rh) 对应输出
            // [readX, readX+rw*s) x [readY, readY+rh*s)
            UnpackTileOutput(output, outW, outH, readX, readY, rw, rh, nativeScale,
                             ox, oy, srWidth, srHeight, srImage);
            auto tp3 = std::chrono::steady_clock::now();
            packMs += std::chrono::duration<double, std::milli>(tp1 - tp0).count();
            runMs += std::chrono::duration<double, std::milli>(tp2 - tp1).count();
            unpackMs += std::chrono::duration<double, std::milli>(tp3 - tp2).count();
            ++tileCount;
        }
    }

    // 目标尺寸：scale>0 按倍数；否则按 targetW/targetH
    int wantW = 0;
    int wantH = 0;
    if (task->scale > 0) {
        wantW = static_cast<int>(std::lround(width * task->scale));
        wantH = static_cast<int>(std::lround(height * task->scale));
    } else if (task->targetW > 0 && task->targetH > 0) {
        wantW = task->targetW;
        wantH = task->targetH;
    }
    if (wantW > 0 && wantH > 0 && (wantW != srWidth || wantH != srHeight)) {
        if (wantW > srWidth || wantH > srHeight) {
            // 请求尺寸超出模型原生输出：超出部分只能靠双线性插值补，不会增加
            // 任何细节(表现为"分辨率变大但画面和原图一样")。正常只应出现在
            // "显式选择 1x 降噪模型又请求放大"时；若模型是按请求倍数选中的，
            // 说明模型文件缺失被回退到了低倍数模型，属于假超分，必须留下痕迹。
            printf("[sr_qnn] 警告: 模型原生 %dx，输出 %dx%d，请求 %dx%d，超出部分为双线性缩放(非真实超分)\n",
                   nativeScale, srWidth, srHeight, wantW, wantH);
        }
        std::vector<uint8_t> resized;
        ResizeBilinear(srImage, srWidth, srHeight, resized, wantW, wantH);
        result->rgb.swap(resized);
        result->width = wantW;
        result->height = wantH;
    } else {
        result->rgb.swap(srImage);
        result->width = srWidth;
        result->height = srHeight;
    }
    result->status = 0;
    auto end = std::chrono::steady_clock::now();
    result->tick = std::chrono::duration<double>(end - begin).count();
    if (g_debug) {
        const double cpuMs = packMs + unpackMs;
        printf("[sr_qnn] task %d: %dx%d step=%d tiles=%d pack+unpack=%.1fms run=%.1fms(total %.1fms)\n",
               task->taskId, width, height, step, tileCount, cpuMs, runMs, result->tick * 1000.0);
    }
    return 0;
}

void WorkerLoop() {
    while (true) {
        std::shared_ptr<SrTask> task;
        {
            std::unique_lock<std::mutex> lock(g_queueMutex);
            g_queueCond.wait(lock, [] { return g_stopping || !g_taskQueue.empty(); });
            if (g_stopping && g_taskQueue.empty()) {
                return;
            }
            if (g_taskQueue.empty()) {
                continue;
            }
            task = g_taskQueue.front();
            g_taskQueue.pop_front();
        }
        if (task->cancel.load() == 2) {
            continue;
        }
        std::shared_ptr<SrOut> result;
        if (task->cancel.load() == 1) {
            result = std::make_shared<SrOut>();
            result->taskId = task->taskId;
            result->status = -20;
            result->format = task->format;
        } else {
            ProcessTask(task, result);
        }
        {
            std::lock_guard<std::mutex> lock(g_queueMutex);
            g_resultQueue.push_back(result);
        }
        g_resultCond.notify_all();
    }
}

void StopWorkers() {
    {
        std::lock_guard<std::mutex> lock(g_queueMutex);
        g_stopping = true;
        g_taskQueue.clear();
    }
    g_queueCond.notify_all();
    for (auto& worker : g_workers) {
        if (worker.joinable()) {
            worker.join();
        }
    }
    g_workers.clear();
    return;
}

}  // namespace

// ---------------------------------------------------------------- 对外接口
extern "C" {

const char* srq_get_version(void) {
    return kVersion;
}

const char* srq_get_last_error(void) {
    static thread_local std::string buffer;
    buffer = GetError();
    return buffer.c_str();
}

const char* srq_get_htp_error(void) {
    static thread_local std::string buffer;
    buffer = g_htpFirstError;
    return buffer.c_str();
}

int srq_has_htp(void) {
    return HasQnnLib() ? 1 : 0;
}

int srq_get_cpu_core_num(void) {
    long num = sysconf(_SC_NPROCESSORS_ONLN);
    return num > 0 ? static_cast<int>(num) : 4;
}

int srq_get_gpu_core_num(void) {
    return g_htpEnabled ? 1 : 0;
}

const char* srq_get_backend_info(void) {
    static thread_local std::string buffer;
    if (g_htpEnabled && g_htpFallback) {
        buffer = "QNN HTP (部分算子 CPU 回退)";
    } else if (g_htpEnabled) {
        buffer = "Qualcomm Hexagon NPU (QNN HTP, fp16)";
    } else if (g_gpuEnabled) {
        buffer = "QNN GPU (Adreno)";
    } else if (g_qnnUnusable.load()) {
        buffer = "CPU (ONNX Runtime, QNN 后端在本机不可用)";
    } else if (HasQnnLib()) {
        buffer = "CPU (ONNX Runtime, QNN 未生效)";
    } else {
        buffer = "CPU (ONNX Runtime)";
    }
    return buffer.c_str();
}

int srq_set_model_dir(const char* dir) {
    if (dir == nullptr) {
        return -1;
    }
    std::lock_guard<std::mutex> lock(g_modelsMutex);
    g_modelDir = dir;
    LoadModelOverride(g_modelDir);
    return 0;
}

int srq_model_count(void) {
    std::lock_guard<std::mutex> lock(g_modelsMutex);
    return static_cast<int>(g_models.size());
}

const char* srq_model_name(int index) {
    std::lock_guard<std::mutex> lock(g_modelsMutex);
    if (index < 0 || index >= static_cast<int>(g_models.size())) {
        return nullptr;
    }
    return g_models[static_cast<size_t>(index)].entry.name.c_str();
}

const char* srq_model_info(int index) {
    std::lock_guard<std::mutex> lock(g_modelsMutex);
    if (index < 0 || index >= static_cast<int>(g_models.size())) {
        return nullptr;
    }
    ModelSlot& slot = g_models[static_cast<size_t>(index)];
    char buffer[512];
    snprintf(buffer, sizeof(buffer), "%s|%d|%d|%d", slot.entry.file.c_str(),
             slot.entry.nativeScale, slot.entry.denoise, slot.entry.tile);
    slot.info = buffer;
    return slot.info.c_str();
}

int srq_model_id(const char* name) {
    if (name == nullptr) {
        return -1;
    }
    std::lock_guard<std::mutex> lock(g_modelsMutex);
    for (size_t i = 0; i < g_models.size(); ++i) {
        if (g_models[i].entry.name == name) {
            return static_cast<int>(i);
        }
    }
    return -1;
}

/* 进程模式下可执行文件**不链接** libonnxruntime.so（见 sr_qnn_proc.cpp 的说明）：
 * App 的 lib 目录在 exec 出来的进程里不在动态链接器的搜索范围内，DT_NEEDED 会让
 * 进程在 main() 之前就被 "CANNOT LINK EXECUTABLE" 杀掉。改为入口处按绝对路径
 * dlopen，再把 OrtGetApiBase 注入进来。进程内(ctypes)模式不受影响。 */
typedef const OrtApiBase* (*OrtGetApiBaseFn)(void);
OrtGetApiBaseFn g_ortGetApiBase = nullptr;

int srq_init(void) {
    if (g_inited) {
        return 0;
    }
    if (g_api == nullptr) {
        const OrtApiBase* apiBase = g_ortGetApiBase != nullptr ? g_ortGetApiBase() : nullptr;
#ifndef SRQ_NO_DIRECT_ORT
        if (apiBase == nullptr) {
            apiBase = OrtGetApiBase();
        }
#endif
        if (apiBase == nullptr) {
            SetError("ONNX Runtime 未加载(找不到 OrtGetApiBase)");
            return -1;
        }
        g_api = apiBase->GetApi(ORT_API_VERSION);
        if (g_api == nullptr) {
            SetError("ONNX Runtime API 版本不匹配");
            return -1;
        }
    }
    // 日志级别：默认 WARNING(生产)，自检/排查时用 JM_ORT_LOG=1(INFO) 打开 ——
    // QNN EP 把图切成 NPU/CPU 两段时，ORT 的 INFO 日志会明确写出
    // "Number of nodes assigned to CPUExecutionProvider: N"，这是判断
    // "机型没有 NPU" 还是 "模型被切分" 的唯一直接证据。
    // 注意：级别交给自定义 logger 过滤(见 OrtLogCallback)，这里固定给 INFO，
    // 既拿得到分区信息，又不会生成 VERBOSE 级别的海量字符串。
    g_ortLogLevel = EnvInt("JM_ORT_LOG", 2);
    OrtStatus* status = g_api->CreateEnvWithCustomLogger(OrtLogCallback, nullptr,
                                                        ORT_LOGGING_LEVEL_INFO, "sr_qnn", &g_env);
    if (status != nullptr) {
        SetError("创建 ONNX Runtime 环境失败: " + OrtError(status));
        return -2;
    }
    if (g_api->GetAllocatorWithDefaultOptions(&g_allocator) != nullptr) {
        SetError("获取默认分配器失败");
        return -3;
    }
    if (g_cpuMemInfo == nullptr &&
        g_api->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &g_cpuMemInfo) != nullptr) {
        SetError("创建 CPU 内存描述符失败");
        return -4;
    }
    PrepareQnnSearchPath();

    std::lock_guard<std::mutex> lock(g_modelsMutex);
    BuildBuiltinModels();
    if (g_modelDir.empty()) {
        g_modelDir = EnvStr("JM_SR_MODELS");
    }
    if (!g_modelDir.empty()) {
        LoadModelOverride(g_modelDir);
    }
    g_inited = true;
    // 自动(Auto)线程数：原来固定 4，8 核机型白瞎一半算力 —— QNN 起不来时超分就是
    // 纯 CPU 跑，这里多给两个线程能直接体现到翻页速度上。用户在设置里显式指定时
    // 仍以用户值为准(见 srq_init_set)。
    g_threads = std::max(1, std::min(6, srq_get_cpu_core_num() - 1));
    if (g_debug) {
        printf("[sr_qnn] init ok, models:%d, modelDir:%s, htp:%d\n",
               static_cast<int>(g_models.size()), g_modelDir.c_str(), srq_has_htp());
    }
    return 0;
}

int srq_init_set(int device, int threads) {
    if (!g_inited) {
        int stat = srq_init();
        if (stat < 0) {
            return stat;
        }
    }
    g_device = device < 0 ? 0 : device;
    if (threads > 0) {
        g_threads = std::min(threads, std::max(1, srq_get_cpu_core_num()));
    }
    if (g_workers.empty()) {
        g_stopping = false;
        int workerNum = EnvInt("JM_QNN_WORKERS", 0);
        if (workerNum <= 0) {
            // HTP/NPU 是单个计算引擎：多线程对同一个 QNN 上下文并发 Run 只会在驱动里
            // 串行排队，徒增锁竞争与 CPU 抢占(参照 waifu2x-ncnn-vulkan 的单 Net 分块模型)。
            // 2 个 worker 刚好让"一块在 NPU 上跑、下一块在 CPU 上打包/拆包"流水起来。
            // 没有 QNN 库(纯 CPU EP)时才按核数开线程。
            workerNum = HasQnnLib() ? 2 : std::max(1, std::min(g_threads, 4));
        }
        workerNum = std::max(1, std::min(workerNum, 8));
        for (int i = 0; i < workerNum; ++i) {
            g_workers.emplace_back(WorkerLoop);
        }
        if (g_debug) {
            printf("[sr_qnn] workers=%d (htp:%d, cpu threads:%d)\n", workerNum, HasQnnLib(), g_threads);
        }
    }
    return 0;
}

void srq_set_debug(int enable) {
    g_debug = enable != 0;
    return;
}

void srq_set_ort_api_base(void* fn) {
    g_ortGetApiBase = reinterpret_cast<OrtGetApiBaseFn>(fn);
    return;
}

int srq_add(const unsigned char* img, int width, int height, int stride, int channels,
            int modelId, int taskId, double scale, int targetW, int targetH,
            const char* format, int tileSize) {
    if (!g_inited) {
        int stat = srq_init();
        if (stat < 0) {
            return stat;
        }
    }
    if (img == nullptr || width <= 0 || height <= 0 || channels < 3) {
        SetError("非法输入图像");
        return -1;
    }
    if (FindModel(modelId) == nullptr) {
        SetError("未知模型编号: " + std::to_string(modelId));
        return -2;
    }
    if (g_workers.empty()) {
        srq_init_set(g_device, 0);
    }
    auto task = std::make_shared<SrTask>();
    task->taskId = taskId;
    task->modelId = modelId;
    task->scale = scale;
    task->targetW = targetW;
    task->targetH = targetH;
    task->format = (format != nullptr && format[0] != 0) ? format : "jpg";
    task->tileSize = tileSize;
    task->width = width;
    task->height = height;
    task->rgb.resize(static_cast<size_t>(width) * height * 3);
    if (stride <= 0) {
        stride = width * channels;
    }
    for (int y = 0; y < height; ++y) {
        const unsigned char* src = img + static_cast<size_t>(y) * stride;
        uint8_t* dst = &task->rgb[static_cast<size_t>(y) * width * 3];
        if (channels == 3) {
            memcpy(dst, src, static_cast<size_t>(width) * 3);
        } else {
            StripAlphaRow(src, dst, width, channels);
        }
    }
    {
        std::lock_guard<std::mutex> lock(g_queueMutex);
        if (g_stopping) {
            SetError("引擎已停止");
            return -2;
        }
        g_taskQueue.push_back(task);
    }
    g_queueCond.notify_one();
    return taskId > 0 ? taskId : 1;
}

int srq_load(int timeoutMs, SrqResult* out) {
    if (out == nullptr) {
        return 0;
    }
    std::shared_ptr<SrOut> result;
    {
        std::unique_lock<std::mutex> lock(g_queueMutex);
        if (timeoutMs <= 0) {
            g_resultCond.wait(lock, [] { return !g_resultQueue.empty(); });
        } else {
            if (!g_resultCond.wait_for(lock, std::chrono::milliseconds(timeoutMs),
                                       [] { return !g_resultQueue.empty(); })) {
                return 0;
            }
        }
        result = g_resultQueue.front();
        g_resultQueue.pop_front();
    }
    out->taskId = result->taskId;
    out->status = result->status;
    out->tick = result->tick;
    out->width = result->width;
    out->height = result->height;
    out->stride = result->width * 3;
    snprintf(out->format, sizeof(out->format), "%s", result->format.c_str());
    if (result->status == 0 && !result->rgb.empty()) {
        size_t bytes = result->rgb.size();
        out->data = static_cast<unsigned char*>(malloc(bytes));
        if (out->data == nullptr) {
            out->status = -30;
            return 1;
        }
        memcpy(out->data, result->rgb.data(), bytes);
    } else {
        out->data = nullptr;
    }
    return 1;
}

void srq_free_result(SrqResult* res) {
    if (res != nullptr && res->data != nullptr) {
        free(res->data);
        res->data = nullptr;
    }
    return;
}

void srq_stop(void) {
    StopWorkers();
    {
        std::lock_guard<std::mutex> lock(g_sessionMutex);
        for (auto& item : g_sessions) {
            if (item.second && item.second->session != nullptr) {
                g_api->ReleaseSession(item.second->session);
                item.second->session = nullptr;
            }
        }
        g_sessions.clear();
    }
    if (g_cpuMemInfo != nullptr) {
        g_api->ReleaseMemoryInfo(g_cpuMemInfo);
        g_cpuMemInfo = nullptr;
    }
    if (g_env != nullptr) {
        g_api->ReleaseEnv(g_env);
        g_env = nullptr;
    }
    g_inited = false;
    return;
}

void srq_remove(const int* taskIds, int count) {
    if (taskIds == nullptr || count <= 0) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_queueMutex);
    for (int i = 0; i < count; ++i) {
        for (auto& task : g_taskQueue) {
            if (task->taskId == taskIds[i]) {
                task->cancel.store(1);
            }
        }
    }
    return;
}

void srq_remove_wait(const int* taskIds, int count) {
    if (taskIds == nullptr || count <= 0) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_queueMutex);
    std::deque<std::shared_ptr<SrTask>> keep;
    for (auto& task : g_taskQueue) {
        bool drop = false;
        for (int i = 0; i < count; ++i) {
            if (task->taskId == taskIds[i]) {
                drop = true;
                break;
            }
        }
        if (!drop) {
            keep.push_back(task);
        }
    }
    g_taskQueue.swap(keep);
    return;
}

}  // extern "C"
