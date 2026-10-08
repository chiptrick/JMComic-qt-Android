/* sr_qnn.h —— Android 端 waifu2x 超分引擎(ONNX Runtime + 高通 QNN/HTP) C 接口
 *
 * 该接口与桌面端 sr_vulkan 的 Python 接口同构，由 sr_qnn/__init__.py 通过 ctypes 调用。
 */
#ifndef SR_QNN_H
#define SR_QNN_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct SrqResult {
    unsigned char* data;   /* RGB888 紧凑数据，stride = width*3，由 srq_free_result 释放 */
    int width;
    int height;
    int stride;
    int taskId;
    double tick;           /* 处理耗时(秒) */
    int status;            /* 0 成功，负数为错误码 */
    char format[16];
} SrqResult;

/* 初始化：加载模型表、创建 ONNX Runtime 环境。>=0 成功 */
int srq_init(void);
/* 设备/线程配置：device 为设备序号(getGpuInfo 顺序)，threads<=0 时自动 */
int srq_init_set(int device, int threads);
void srq_set_debug(int enable);

const char* srq_get_version(void);
const char* srq_get_backend_info(void);
int srq_has_htp(void);
int srq_get_cpu_core_num(void);
int srq_get_gpu_core_num(void);
const char* srq_get_last_error(void);

/* 模型目录(存放 models.txt 与 .onnx)，不设置则用 JM_SR_MODELS 环境变量 */
int srq_set_model_dir(const char* dir);
int srq_model_count(void);
const char* srq_model_name(int index);
const char* srq_model_info(int index);   /* "file|scale|denoise|tile" */
int srq_model_id(const char* name);

/* 添加超分任务：img 为 RGB888/RGBA8888 原始像素
 * scale > 0 时按倍数放大；scale <= 0 时使用 targetW/targetH(<=0 表示不缩放)
 * 返回 >0 成功(任务号)，<=0 失败 */
int srq_add(const unsigned char* img, int width, int height, int stride, int channels,
            int modelId, int taskId, double scale, int targetW, int targetH,
            const char* format, int tileSize);

/* 阻塞取结果：timeoutMs<=0 表示一直等待。返回 1 取到结果(含失败)，0 超时 */
int srq_load(int timeoutMs, SrqResult* out);
void srq_free_result(SrqResult* res);

void srq_stop(void);
/* 取消任务(含正在处理的) */
void srq_remove(const int* taskIds, int count);
/* 取消还没开始处理的任务 */
void srq_remove_wait(const int* taskIds, int count);

#ifdef __cplusplus
}
#endif

#endif /* SR_QNN_H */
