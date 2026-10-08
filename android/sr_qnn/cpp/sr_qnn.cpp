/* sr_qnn.cpp —— Android 端 waifu2x 超分引擎
 *
 * 后端：ONNX Runtime C API + Qualcomm QNN Execution Provider(Hexagon NPU / HTP)
 *
 * 设计要点：
 *   1. QNN EP 不支持动态 shape，所以每个模型在离线准备阶段就把输入固定为
 *      N×3×T×T(T 见 models.txt 的 tile 字段)；引擎把原图切成 T×T 的块，
 *      每块用边缘像素补齐后再送 NPU，回读后按有效区域拼接，保证无缝。
 *   2. 优先 HTP(fp16 精度)；失败时依次退化：HTP(允许 CPU 兜底) -> CPU EP。
 *   3. 支持 QNN context binary 缓存(第二次启动大幅加快图编译)。
 *   4. 无第三方图像库依赖：解码/编码由 Python 侧 Qt 完成，C 侧只处理 RGB 原始像素。
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
#include <sys/stat.h>
#include <unistd.h>

#include "onnxruntime_c_api.h"

// ---------------------------------------------------------------- 基础工具
namespace {

const char* kVersion = "sr_qnn 1.1.0 (ONNX Runtime QNN EP / HEXAGON HTP)";

std::mutex g_errMutex;
std::string g_lastError;
bool g_debug = false;

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

/* 目标模型文件缺失时找一个最接近的可用模型(保证超分功能仍然可用) */
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

struct SessionHolder {
    OrtSession* session = nullptr;
    std::string path;
    bool htp = false;
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

/* 创建一个会话；useHtp 为 true 时挂 QNN EP */
OrtSession* CreateSession(const std::string& modelPath, const ModelEntry& entry, bool useHtp,
                          bool strictHtp, bool useContextCache, std::string& err) {
    OrtSessionOptions* options = nullptr;
    OrtStatus* status = g_api->CreateSessionOptions(&options);
    if (status != nullptr) {
        err = OrtError(status);
        return nullptr;
    }
    g_api->SetIntraOpNumThreads(options, g_threads);
    g_api->SetSessionGraphOptimizationLevel(options, ORT_ENABLE_ALL);

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
        addOption("htp_performance_mode", EnvStr("JM_QNN_PERF", "sustained_high_performance"));
        addOption("enable_htp_fp16_precision", EnvStr("JM_QNN_FP16", "1"));
        addOption("htp_graph_finalization_optimization_mode", EnvStr("JM_QNN_FINALIZE", "2"));
        addOption("device_id", std::to_string(g_device));
        addOption("profiling_level", "off");
        addOption("vtcm_mb", EnvStr("JM_QNN_VTCM", "8"));
        std::string socModel = EnvStr("JM_QNN_SOC_MODEL");
        if (!socModel.empty()) {
            addOption("soc_model", socModel);
        }
        std::string htpArch = EnvStr("JM_QNN_HTP_ARCH");
        if (!htpArch.empty()) {
            addOption("htp_arch", htpArch);
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
            return CreateSession(modelPath, entry, useHtp, strictHtp, false, err);
        }
        g_api->AddSessionConfigEntry(options, "ep.context_enable", "1");
        g_api->AddSessionConfigEntry(options, "ep.context_file_path", ctxPath.c_str());
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
    std::string lastErr;
    if (wantHtp) {
        // 1) 严格 HTP(整图跑在 NPU 上)
        OrtSession* session = CreateSession(path, entry, true, true, true, lastErr);
        if (session == nullptr) {
            if (g_debug) {
                printf("[sr_qnn] 严格 HTP 失败: %s\n", lastErr.c_str());
            }
            // 2) HTP + 允许 CPU 兜底
            session = CreateSession(path, entry, true, false, false, lastErr);
        }
        if (session != nullptr) {
            holder->session = session;
            holder->htp = true;
            g_htpEnabled = true;
        }
    }
    if (holder->session == nullptr) {
        // 3) CPU EP 兜底，保证功能可用(慢，但不会让用户失去超分能力)
        OrtSession* session = CreateSession(path, entry, false, false, false, lastErr);
        if (session == nullptr) {
            err = lastErr;
            return nullptr;
        }
        holder->session = session;
        holder->htp = false;
        if (g_debug) {
            printf("[sr_qnn] 使用 CPU EP: %s\n", lastErr.c_str());
        }
    }
    if (!ReadSessionInfo(holder.get())) {
        g_api->ReleaseSession(holder->session);
        err = "读取模型输入输出信息失败";
        return nullptr;
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
    OrtMemoryInfo* memInfo = nullptr;
    if (g_api->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &memInfo) != nullptr) {
        err = "CreateCpuMemoryInfo 失败";
        return false;
    }
    OrtValue* inputValue = nullptr;
    OrtStatus* status = nullptr;
    std::vector<uint16_t> halfInput;
    const void* inputPtr = input.data();
    size_t inputBytes = input.size() * sizeof(float);
    if (holder->inputType == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16) {
        halfInput.resize(input.size());
        for (size_t i = 0; i < input.size(); ++i) {
            halfInput[i] = FloatToHalf(input[i]);
        }
        inputPtr = halfInput.data();
        inputBytes = halfInput.size() * sizeof(uint16_t);
    }
    status = g_api->CreateTensorWithDataAsOrtValue(memInfo, const_cast<void*>(inputPtr), inputBytes,
                                                   dims, 4, holder->inputType, &inputValue);
    if (status != nullptr) {
        err = "创建输入张量失败: " + OrtError(status);
        g_api->ReleaseMemoryInfo(memInfo);
        return false;
    }
    const char* inputNames[1] = {holder->inputName.c_str()};
    const char* outputNames[1] = {holder->outputName.c_str()};
    const OrtValue* inputValues[1] = {inputValue};
    OrtValue* outputValue = nullptr;
    status = g_api->Run(holder->session, nullptr, inputNames, inputValues, 1,
                        outputNames, 1, &outputValue);
    g_api->ReleaseValue(inputValue);
    g_api->ReleaseMemoryInfo(memInfo);
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
        const uint16_t* src = reinterpret_cast<const uint16_t*>(raw);
        for (size_t i = 0; i < count; ++i) {
            output[i] = HalfToFloat(src[i]);
        }
    } else if (holder->outputType == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) {
        memcpy(output.data(), raw, count * sizeof(float));
    } else if (holder->outputType == ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8) {
        const uint8_t* src = reinterpret_cast<const uint8_t*>(raw);
        for (size_t i = 0; i < count; ++i) {
            output[i] = src[i] / 255.0f;
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

/* 处理一个任务：分块推理 + 拼接 + 目标尺寸缩放 */
int ProcessTask(const std::shared_ptr<SrTask>& task, std::shared_ptr<SrOut>& result) {
    auto begin = std::chrono::steady_clock::now();
    result = std::make_shared<SrOut>();
    result->taskId = task->taskId;
    result->format = task->format;

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
        SetError("没有可用的 ONNX 模型，请把模型放到 " + g_modelDir);
        return -11;
    }
    if (!note.empty() && g_debug) {
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
            const size_t planeSize = static_cast<size_t>(tile) * tile;
            for (int y = 0; y < tile; ++y) {
                int sy = oy - pad + y;
                sy = sy < 0 ? 0 : (sy >= height ? height - 1 : sy);
                for (int x = 0; x < tile; ++x) {
                    int sx = ox - pad + x;
                    sx = sx < 0 ? 0 : (sx >= width ? width - 1 : sx);
                    const uint8_t* src = &task->rgb[(static_cast<size_t>(sy) * width + sx) * 3];
                    const size_t offset = static_cast<size_t>(y) * tile + x;
                    input[offset] = src[0] / 255.0f;                   // R
                    input[planeSize + offset] = src[1] / 255.0f;       // G
                    input[planeSize * 2 + offset] = src[2] / 255.0f;   // B
                }
            }
            int outW = static_cast<int>(tile) * nativeScale;
            int outH = static_cast<int>(tile) * nativeScale;
            if (!RunTile(holder, input, tile, output, outW, outH, err)) {
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
            for (int y = 0; y < rh * nativeScale; ++y) {
                int ty = readY + y;
                if (ty < 0 || ty >= outH) {
                    continue;
                }
                int dy = oy * nativeScale + y;
                if (dy >= srHeight) {
                    break;
                }
                for (int x = 0; x < rw * nativeScale; ++x) {
                    int tx = readX + x;
                    if (tx < 0 || tx >= outW) {
                        continue;
                    }
                    int dx = ox * nativeScale + x;
                    if (dx >= srWidth) {
                        break;
                    }
                    float r = output[(static_cast<size_t>(0) * outH + ty) * outW + tx];
                    float g = output[(static_cast<size_t>(1) * outH + ty) * outW + tx];
                    float b = output[(static_cast<size_t>(2) * outH + ty) * outW + tx];
                    uint8_t* dst = &srImage[(static_cast<size_t>(dy) * srWidth + dx) * 3];
                    dst[0] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, r * 255.0f + 0.5f)));
                    dst[1] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, g * 255.0f + 0.5f)));
                    dst[2] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, b * 255.0f + 0.5f)));
                }
            }
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
    if (g_htpEnabled) {
        buffer = "Qualcomm Hexagon NPU (QNN HTP, fp16)";
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

int srq_init(void) {
    if (g_inited) {
        return 0;
    }
    if (g_api == nullptr) {
        g_api = OrtGetApiBase()->GetApi(ORT_API_VERSION);
        if (g_api == nullptr) {
            SetError("ONNX Runtime API 版本不匹配");
            return -1;
        }
    }
    OrtStatus* status = g_api->CreateEnv(ORT_LOGGING_LEVEL_WARNING, "sr_qnn", &g_env);
    if (status != nullptr) {
        SetError("创建 ONNX Runtime 环境失败: " + OrtError(status));
        return -2;
    }
    if (g_api->GetAllocatorWithDefaultOptions(&g_allocator) != nullptr) {
        SetError("获取默认分配器失败");
        return -3;
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
    g_threads = std::max(1, std::min(4, srq_get_cpu_core_num() - 1));
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
        int workerNum = std::max(1, std::min(g_threads, 4));
        for (int i = 0; i < workerNum; ++i) {
            g_workers.emplace_back(WorkerLoop);
        }
    }
    return 0;
}

void srq_set_debug(int enable) {
    g_debug = enable != 0;
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
            for (int x = 0; x < width; ++x) {
                dst[x * 3 + 0] = src[x * channels + 0];
                dst[x * 3 + 1] = src[x * channels + 1];
                dst[x * 3 + 2] = src[x * channels + 2];
            }
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
