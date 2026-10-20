/*!
 * \file confusion_mul_grad_tiling_data.h
 * \brief tiling data struct
 *
 * ConfusionMulGrad = (output0 = input0 * input1, output1 = ReduceSum(input1 * input2, axis, keep_dims))
 * 所有字段均由 Host 通过整数 tiling 计算得到，不含任何张量数值。
 */

#ifndef _CONFUSIONMULGRAD_TILING_DATA_H_
#define _CONFUSIONMULGRAD_TILING_DATA_H_

// ---- Host(tiling) 与 Device(kernel) 必须一致共享的容量常量 ----
// 放在同一个头文件里，避免两侧各写一份导致 UB 预算漂移（危险方向是 Host 调小预算）。
constexpr int64_t CONFUSIONMULGRAD_VECTOR_LANE = 64;      // fp32 单 repeat lane 数（256B）
constexpr int64_t CONFUSIONMULGRAD_MAX_LANE_LEN = 512;    // 行/全归约累加器 lane 上限
constexpr int64_t CONFUSIONMULGRAD_MAX_TILE_LEN_F16 = 4096;
constexpr int64_t CONFUSIONMULGRAD_MAX_TILE_LEN_F32 = 2048;
constexpr int64_t CONFUSIONMULGRAD_COL_BLOCK_ALIGN = 64;  // 列块/分段对齐元素数
constexpr int64_t CONFUSIONMULGRAD_COL_ACC_NUM = 8;       // 列方向部分和路数上限
constexpr int64_t CONFUSIONMULGRAD_COL_ACC_BYTES = 32768; // 列方向部分和累加器 UB 预算

struct ConfusionMulGradTilingData {
    // ---- 兼容官方模板字段（保留语义：总元素数 / 单核元素数 / 单次 UB 元素数）----
    int64_t totalNum = 0;     // M * N 总元素数
    int64_t blockFactor = 1;  // 每个核处理的元素数量
    int64_t ubFactor = 0;     // 每次 UB 循环处理的元素数量

    // ---- 形状与归约模式 ----
    int64_t rows = 1;         // M
    int64_t cols = 1;         // N
    int64_t axisMode = 0;     // 0: axis=[1] 行内归约; 1: axis=[0] 跨行归约; 2: axis=[0,1] 全归约
    int64_t keepDims = 0;     // 属性 keep_dims（仅用于记录，写回布局由 shape 决定）

    // ---- UB tiling ----
    int64_t tileLen = 64;     // 单次搬入 UB 的元素数（2 的幂，>= 64）
    int64_t laneLen = 64;     // 行/全归约的 fp32 累加器 lane 数（2 的幂，64..512，<= tileLen）

    // ---- 三种归约模式的并行切分 ----
    // 说明：kernel 侧统一使用均衡切分公式（begin = n*blockIdx/coreNum，
    //       end = n*(blockIdx+1)/coreNum）切分行/列块，下列字段是 Host 侧
    //       计算出的同量级上界，用于核对与调试。
    int64_t rowsPerCore = 0;  // axis=[1]：每核处理的行数上界
    int64_t colBlockLen = 0;  // axis=[0]：单次处理的列块长度（元素），kernel 直接使用
    int64_t colBlockNum = 0;  // axis=[0]：列块总数，kernel 直接使用（按 blockIdx 轮转）
    int64_t colAccNum = 0;    // axis=[0]：列方向部分和路数（kernel 直接用，取值 1/4/8）
    int64_t flatPerCore = 0;  // axis=[0,1]：每核处理的平坦元素数上界（全归约由 0 号核完成）
    int64_t coreNum = 1;      // 实际启动的 AI Vector 核数（= BlockDim），kernel 直接使用
};
#endif
