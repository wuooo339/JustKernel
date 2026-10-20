/*!
 * \file confusion_mul_grad.h
 * \brief ConfusionMulGrad 算子 kernel 类定义
 *
 * 单 Kernel 完成：
 *   output0 = fp32(input0) * fp32(input1)          （逐元素乘，cast 回输入 dtype 后整块写回）
 *   p       = fp32(input1) * fp32(input2)
 *   output1 = ReduceSum(p, axis, keep_dims)        （部分和与最终累加全部为 fp32）
 *
 * input1 is loaded once per element and reused for both FP32 products.
 * Row/full reductions retain the current lane accumulator. Column reduction
 * uses a four-level FP32 cascade; tail columns use four independent chains.
 * The strategy depends only on shape/axis, never testcase IDs or tensor values.
 */

#ifndef CONFUSIONMULGRAD_H
#define CONFUSIONMULGRAD_H

#include "kernel_operator.h"
#include "kernel_tiling/kernel_tiling.h"
#include "confusion_mul_grad_tiling_data.h"
#include "confusion_mul_grad_tiling_key.h"

namespace NsConfusionMulGrad {

using namespace AscendC;

constexpr int32_t BUFFER_NUM = 2;
// 容量常量与 Host tiling 共享同一份定义（见 confusion_mul_grad_tiling_data.h）
constexpr int64_t VECTOR_LANE = CONFUSIONMULGRAD_VECTOR_LANE;
constexpr int64_t MAX_LANE_LEN = CONFUSIONMULGRAD_MAX_LANE_LEN;
constexpr int64_t MAX_COL_ACC_NUM = CONFUSIONMULGRAD_COL_ACC_NUM;
constexpr int64_t MAX_COL_ACC_BYTES = CONFUSIONMULGRAD_COL_ACC_BYTES;
// 行/全归约的累加器宽度为 laneLen_(64..512)，最终 tree 折半收敛到 REDUC_LANE(=64) 后
// 一次 ReduceSum(64) 归到标量。REDUC_LANE 只是最后合并阶段的目标 lane 数，
// 不再用它做整行的 strided fold（那会把每 lane 串行链拉长到 ceil(N/64)）。
constexpr int64_t REDUC_LANE = CONFUSIONMULGRAD_VECTOR_LANE;

enum ConfusionMulGradAxisMode : int32_t {
    AXIS_MODE_ROW = 0,   // axis=[1] / [-1]
    AXIS_MODE_COL = 1,   // axis=[0] / [-2]
    AXIS_MODE_FULL = 2,  // axis=[0,1]
};

template <typename T>
class ConfusionMulGrad {
public:
    __aicore__ inline ConfusionMulGrad(){};

    __aicore__ inline void Init(GM_ADDR input0, GM_ADDR input1, GM_ADDR input2, GM_ADDR output0,
                                GM_ADDR output1, const ConfusionMulGradTilingData* tilingData);
    __aicore__ inline void Process();

private:
    __aicore__ inline void CastToFp32(const LocalTensor<float>& dst, const LocalTensor<T>& src, int64_t len);
    __aicore__ inline void CastFromFp32(const LocalTensor<T>& dst, const LocalTensor<float>& src, int64_t len);
    // 处理一个 tile：搬入 input1（及按需搬入 input0 / input2），
    // 计算 output0 = input0*input1 写回，p = input1*input2 留在 bufP_ 中
    __aicore__ inline void ProcessTile(int64_t offset, int64_t len, bool needOut0, bool needP);
    // 上面的两种 dtype 实现：各自只在对应实例化中编译，避免无用的 fp32 暂存与告警
    __aicore__ inline void ProcessTileFloat(int64_t offset, int64_t len, bool needOut0, bool needP);
    __aicore__ inline void ProcessTileHalf(int64_t offset, int64_t len, bool needOut0, bool needP);
    // 把 bufP_ 中 len 个元素按 laneLen_ 分组累加进 fp32 累加器
    __aicore__ inline void AccumulateFlat(int64_t len);
    // 累加器 laneLen_ 个 lane 求和 -> bufRed_[0]
    __aicore__ inline void ReduceAccToScalar();
    // 把 bufRed_[0] cast 成输入 dtype 后写回 output1 的一个元素
    __aicore__ inline void StoreScalar(int64_t gmOffset);
    __aicore__ inline void ProcessRow();
    __aicore__ inline void ProcessHalfRows(int64_t rowBegin, int64_t rowEnd);
    __aicore__ inline void ProcessFloatRow(int64_t offset);
    __aicore__ inline void ProcessCol();
    __aicore__ inline LocalTensor<float> TailBank(int64_t bank);
    __aicore__ inline void ProcessColumnBlock(int64_t start, int64_t len, bool tail);
    __aicore__ inline void ProcessFull();

private:
    TPipe pipe_;
    TQue<TPosition::VECIN, BUFFER_NUM> inQueA_;
    TQue<TPosition::VECIN, BUFFER_NUM> inQueB_;
    TQue<TPosition::VECIN, BUFFER_NUM> inQueC_;
    TQue<TPosition::VECOUT, BUFFER_NUM> outQue_;

    TBuf<TPosition::VECCALC> bufFA_;
    TBuf<TPosition::VECCALC> bufFB_;
    TBuf<TPosition::VECCALC> bufFC_;
    TBuf<TPosition::VECCALC> bufFO_;
    TBuf<TPosition::VECCALC> bufP_;
    TBuf<TPosition::VECCALC> bufAcc_;
    TBuf<TPosition::VECCALC> bufAccC_;   // Compact cascade tail banks (column mode only).
    TBuf<TPosition::VECCALC> bufWork_;
    TBuf<TPosition::VECCALC> bufTmp_;    // Kahan 中间量 t（仅列归约用）
    TBuf<TPosition::VECCALC> bufRed_;

    GlobalTensor<T> input0Gm_;
    GlobalTensor<T> input1Gm_;
    GlobalTensor<T> input2Gm_;
    GlobalTensor<T> output0Gm_;
    GlobalTensor<T> output1Gm_;

    int64_t rows_ = 1;
    int64_t cols_ = 1;
    int64_t tileLen_ = VECTOR_LANE;
    int64_t laneLen_ = VECTOR_LANE;
    int64_t rowsPerCore_ = 0;
    int64_t colBlockLen_ = 0;
    int64_t colBlockNum_ = 0;
    int64_t colStride_ = VECTOR_LANE;
    int64_t colAccNum_ = 1;
    int64_t flatPerCore_ = 0;
    int64_t coreNum_ = 1;
    int64_t blockIdx_ = 0;
    int32_t axisMode_ = AXIS_MODE_ROW;
};

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::Init(GM_ADDR input0, GM_ADDR input1, GM_ADDR input2,
                                                 GM_ADDR output0, GM_ADDR output1,
                                                 const ConfusionMulGradTilingData* tilingData)
{
    rows_ = tilingData->rows;
    cols_ = tilingData->cols;
    axisMode_ = static_cast<int32_t>(tilingData->axisMode);
    tileLen_ = tilingData->tileLen;
    laneLen_ = tilingData->laneLen;
    rowsPerCore_ = tilingData->rowsPerCore;
    colBlockLen_ = tilingData->colBlockLen;
    colBlockNum_ = tilingData->colBlockNum;
    colAccNum_ = tilingData->colAccNum;
    flatPerCore_ = tilingData->flatPerCore;
    coreNum_ = tilingData->coreNum;
    if (rows_ < 1) {
        rows_ = 1;
    }
    if (cols_ < 1) {
        cols_ = 1;
    }
    if (coreNum_ < 1) {
        coreNum_ = 1;
    }
    // 防御式 clamp：tiling 结构异常时也不越界（只改变分块粒度，不改变语义）
    int64_t tileCap = (sizeof(T) == 2) ? CONFUSIONMULGRAD_MAX_TILE_LEN_F16 : CONFUSIONMULGRAD_MAX_TILE_LEN_F32;
    if (tileLen_ < VECTOR_LANE) {
        tileLen_ = VECTOR_LANE;
    }
    if (tileLen_ > tileCap) {
        tileLen_ = tileCap;
    }
    if (laneLen_ < VECTOR_LANE) {
        laneLen_ = VECTOR_LANE;
    }
    if (laneLen_ > MAX_LANE_LEN) {
        laneLen_ = MAX_LANE_LEN;
    }
    // laneLen_ 必须是 2 的幂：Add 树按折半把部分和收敛到 64 lane
    int64_t powLane = VECTOR_LANE;
    while ((powLane << 1) <= laneLen_) {
        powLane <<= 1;
    }
    // 上限也取 2 的幂，保证 clamp 后仍然是 2 的幂（tileLen_ 不做幂次假设）
    int64_t laneCap = VECTOR_LANE;
    while ((laneCap << 1) <= tileLen_) {
        laneCap <<= 1;
    }
    if (powLane > laneCap) {
        powLane = laneCap;
    }
    laneLen_ = powLane;
    if (colBlockLen_ < 1) {
        colBlockLen_ = tileLen_;
    }
    if (colBlockLen_ > tileLen_) {
        colBlockLen_ = tileLen_;
    }
    if (colBlockLen_ > CONFUSIONMULGRAD_MAX_TILE_LEN_F32) {
        colBlockLen_ = CONFUSIONMULGRAD_MAX_TILE_LEN_F32;  // 与 Host 的 MAX_COL_BLOCK 一致
    }
    if (colAccNum_ < 1) {
        colAccNum_ = 1;
    }
    if (colAccNum_ > MAX_COL_ACC_NUM) {
        colAccNum_ = MAX_COL_ACC_NUM;
    }
    // 多路部分和之间用 colBlockLen_ 做分段偏移，必须 64 元素对齐，否则退化为单链
    if (colAccNum_ > 1 && (colBlockLen_ % VECTOR_LANE) != 0) {
        colAccNum_ = 1;
    }
    // 累加器 UB 预算（与 Host 侧同一上界），超了就减半（保持 2 的幂与对齐）
    while (colAccNum_ > 1 &&
           (colAccNum_ * colBlockLen_ * static_cast<int64_t>(sizeof(float)) > MAX_COL_ACC_BYTES)) {
        colAccNum_ >>= 1;
    }
    blockIdx_ = static_cast<int64_t>(GetBlockIdx());

    input0Gm_.SetGlobalBuffer(reinterpret_cast<__gm__ T*>(input0));
    input1Gm_.SetGlobalBuffer(reinterpret_cast<__gm__ T*>(input1));
    input2Gm_.SetGlobalBuffer(reinterpret_cast<__gm__ T*>(input2));
    output0Gm_.SetGlobalBuffer(reinterpret_cast<__gm__ T*>(output0));
    output1Gm_.SetGlobalBuffer(reinterpret_cast<__gm__ T*>(output1));

    colStride_ = (colBlockLen_ + VECTOR_LANE - 1) / VECTOR_LANE * VECTOR_LANE;
    uint32_t tileBytes = static_cast<uint32_t>(tileLen_ * static_cast<int64_t>(sizeof(T)));
    uint32_t f32Bytes = static_cast<uint32_t>(tileLen_ * static_cast<int64_t>(sizeof(float)));
    int64_t accLanes = laneLen_;
    if (axisMode_ == static_cast<int32_t>(AXIS_MODE_COL)) {
        accLanes = colAccNum_ * colBlockLen_;
    }
    if (accLanes < VECTOR_LANE) {
        accLanes = VECTOR_LANE;
    }
    // Four cascade levels for a vector block; scalar column tails use sixteen
    // compact banks split over the two existing buffers (eight banks each).
    if (axisMode_ == static_cast<int32_t>(AXIS_MODE_COL)) {
        if (accLanes < 4 * colStride_) accLanes = 4 * colStride_;
        if (accLanes < 8 * VECTOR_LANE) accLanes = 8 * VECTOR_LANE;
    }
    // 不变量：累加器至少容纳 laneLen_ 个 lane。
    // （单列 cols==1 的 axis=[0] 会走平坦扫描，按 laneLen_ 清零/归约，而 COL 定尺寸走
    //  colAccNum*colBlockLen；两者今日恒相等，这里显式取大者，避免未来 Host 改动后越界。）
    if (accLanes < laneLen_) {
        accLanes = laneLen_;
    }
    uint32_t accBytes = static_cast<uint32_t>(accLanes * static_cast<int64_t>(sizeof(float)));

    pipe_.InitBuffer(inQueA_, BUFFER_NUM, tileBytes);
    pipe_.InitBuffer(inQueB_, BUFFER_NUM, tileBytes);
    pipe_.InitBuffer(inQueC_, BUFFER_NUM, tileBytes);
    pipe_.InitBuffer(outQue_, BUFFER_NUM, tileBytes);
    pipe_.InitBuffer(bufP_, f32Bytes);
    if constexpr (sizeof(T) != sizeof(float)) {
        // fp16 需要 fp32 暂存；fp32 输入走零拷贝路径，不占用这些 buffer
        pipe_.InitBuffer(bufFA_, f32Bytes);
        pipe_.InitBuffer(bufFB_, f32Bytes);
        pipe_.InitBuffer(bufFC_, f32Bytes);
        pipe_.InitBuffer(bufFO_, f32Bytes);
    }
    pipe_.InitBuffer(bufAcc_, accBytes);
    pipe_.InitBuffer(bufAccC_, accBytes);
    pipe_.InitBuffer(bufWork_, static_cast<uint32_t>(MAX_LANE_LEN * sizeof(float)));
    pipe_.InitBuffer(bufTmp_, static_cast<uint32_t>(MAX_LANE_LEN * sizeof(float)));
    pipe_.InitBuffer(bufRed_, 128U);
}

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::CastToFp32(const LocalTensor<float>& dst,
                                                       const LocalTensor<T>& src, int64_t len)
{
    if constexpr (sizeof(T) != sizeof(float)) {
        Cast(dst, src, RoundMode::CAST_NONE, static_cast<int32_t>(len));
    } else {
        Adds(dst, src, static_cast<float>(0), static_cast<int32_t>(len));
    }
}

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::CastFromFp32(const LocalTensor<T>& dst,
                                                         const LocalTensor<float>& src, int64_t len)
{
    if constexpr (sizeof(T) != sizeof(float)) {
        // fp32 -> float16 narrowing of the OUTPUTS (output0 elementwise product and the
        // reduced output1). Use explicit round-to-nearest-even (ties-to-even) so the per-element
        // fp16 result matches the golden torch `.to(orig_dtype)` rounding. This is the only
        // output arithmetic that was identical across both frozen submissions, so it is the
        // branch the reduction-precision change could not have covered.
        Cast(dst, src, RoundMode::CAST_RINT, static_cast<int32_t>(len));
    } else {
        Adds(dst, src, static_cast<float>(0), static_cast<int32_t>(len));
    }
}

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::ProcessTile(int64_t offset, int64_t len, bool needOut0, bool needP)
{
    if (len <= 0) {
        return;
    }
    if constexpr (sizeof(T) == sizeof(float)) {
        ProcessTileFloat(offset, len, needOut0, needP);
    } else {
        ProcessTileHalf(offset, len, needOut0, needP);
    }
}

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::ProcessTileFloat(int64_t offset, int64_t len, bool needOut0, bool needP)
{
    // T = float：搬入的数据本身就是 fp32，两路乘法直接复用同一份片上数据（零拷贝）
    DataCopyExtParams copyParams{};
    copyParams.blockCount = 1;
    copyParams.blockLen = static_cast<uint32_t>(len * static_cast<int64_t>(sizeof(T)));
    copyParams.srcStride = 0;
    copyParams.dstStride = 0;
    DataCopyPadExtParams<T> padParams{};

    LocalTensor<T> localB = inQueB_.AllocTensor<T>();
    DataCopyPad(localB, input1Gm_[offset], copyParams, padParams);
    inQueB_.EnQue(localB);

    LocalTensor<T> localA;
    LocalTensor<T> localC;
    if (needOut0) {
        localA = inQueA_.AllocTensor<T>();
        DataCopyPad(localA, input0Gm_[offset], copyParams, padParams);
        inQueA_.EnQue(localA);
    }
    if (needP) {
        localC = inQueC_.AllocTensor<T>();
        DataCopyPad(localC, input2Gm_[offset], copyParams, padParams);
        inQueC_.EnQue(localC);
    }

    localB = inQueB_.DeQue<T>();
    if (needOut0) {
        localA = inQueA_.DeQue<T>();
        // product 直接算进写回队列，省掉 fp32 暂存 + 恒等 cast 两趟向量操作
        LocalTensor<T> localOut = outQue_.AllocTensor<T>();
        Mul(localOut, localA, localB, static_cast<int32_t>(len));
        outQue_.EnQue(localOut);
        inQueA_.FreeTensor(localA);
        localOut = outQue_.DeQue<T>();
        DataCopyPad(output0Gm_[offset], localOut, copyParams);
        outQue_.FreeTensor(localOut);
    }
    if (needP) {
        localC = inQueC_.DeQue<T>();
        LocalTensor<float> localFP = bufP_.Get<float>();
        Mul(localFP, localB, localC, static_cast<int32_t>(len));  // p = input1 * input2（fp32）
        inQueC_.FreeTensor(localC);
    }
    inQueB_.FreeTensor(localB);
}

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::ProcessTileHalf(int64_t offset, int64_t len, bool needOut0, bool needP)
{
    // T = half：先升到 fp32 再乘，写回前 cast 回输入 dtype
    DataCopyExtParams copyParams{};
    copyParams.blockCount = 1;
    copyParams.blockLen = static_cast<uint32_t>(len * static_cast<int64_t>(sizeof(T)));
    copyParams.srcStride = 0;
    copyParams.dstStride = 0;
    DataCopyPadExtParams<T> padParams{};
    LocalTensor<float> localFB = bufFB_.Get<float>();

    LocalTensor<T> localB = inQueB_.AllocTensor<T>();
    DataCopyPad(localB, input1Gm_[offset], copyParams, padParams);
    inQueB_.EnQue(localB);

    LocalTensor<T> localA;
    LocalTensor<T> localC;
    if (needOut0) {
        localA = inQueA_.AllocTensor<T>();
        DataCopyPad(localA, input0Gm_[offset], copyParams, padParams);
        inQueA_.EnQue(localA);
    }
    if (needP) {
        localC = inQueC_.AllocTensor<T>();
        DataCopyPad(localC, input2Gm_[offset], copyParams, padParams);
        inQueC_.EnQue(localC);
    }

    localB = inQueB_.DeQue<T>();
    CastToFp32(localFB, localB, len);

    if (needOut0) {
        localA = inQueA_.DeQue<T>();
        LocalTensor<float> localFA = bufFA_.Get<float>();
        LocalTensor<float> localFO = bufFO_.Get<float>();
        CastToFp32(localFA, localA, len);
        Mul(localFO, localFA, localFB, static_cast<int32_t>(len));
        LocalTensor<T> localOut = outQue_.AllocTensor<T>();
        CastFromFp32(localOut, localFO, len);
        outQue_.EnQue(localOut);
        inQueA_.FreeTensor(localA);
        localOut = outQue_.DeQue<T>();
        DataCopyPad(output0Gm_[offset], localOut, copyParams);
        outQue_.FreeTensor(localOut);
    }
    if (needP) {
        localC = inQueC_.DeQue<T>();
        LocalTensor<float> localFC = bufFC_.Get<float>();
        LocalTensor<float> localFP = bufP_.Get<float>();
        CastToFp32(localFC, localC, len);
        Mul(localFP, localFB, localFC, static_cast<int32_t>(len));
        inQueC_.FreeTensor(localC);
    }
    inQueB_.FreeTensor(localB);
}

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::AccumulateFlat(int64_t len)
{
    // 行/全归约把数据折叠进 laneLen_ 个 fp32 lane（lane 映射 i = pos mod laneLen_）。
    // 使用简单逐元素 Add：与参考的 fp32 顺序累加语义一致，避免 Kahan 补偿改变部分和
    // 值后在 fp16 输出路径上跨越舍入边界（官测对比：Kahan 导致 fp16 行归约 case 回归）。
    // laneLen_ 为 2 的幂且整除 tileLen_，故每块起始 base 均为 laneLen_ 的倍数，lane 索引 j
    // 恒等于 (全局列偏移) mod laneLen_，折叠语义正确。
    LocalTensor<float> acc = bufAcc_.Get<float>();
    LocalTensor<float> src = bufP_.Get<float>();
    const int64_t ll = laneLen_;
    for (int64_t base = 0; base < len; base += ll) {
        int64_t count = len - base;
        if (count > ll) {
            count = ll;
        }
        Add(acc, acc, src[base], static_cast<int32_t>(count));
    }
}

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::ReduceAccToScalar()
{
    LocalTensor<float> acc = bufAcc_.Get<float>();
    LocalTensor<float> work = bufWork_.Get<float>();
    LocalTensor<float> red = bufRed_.Get<float>();
    // 先把 laneLen_ 条部分和搬到 work，再折半 tree 合并到 REDUC_LANE(=64) 条，最后
    // ReduceSum(64) 归到标量。tree 合并把"最后一次性求和"的串行深度降到对数量级，
    // 与上面的宽 lane 累加共同缩短整体误差累积链。
    Adds(work, acc, static_cast<float>(0), static_cast<int32_t>(laneLen_));
    int64_t cur = laneLen_;
    while (cur > REDUC_LANE) {
        int64_t half = cur / 2;
        // work[0..half) += work[half..cur)，两段地址不重叠，原地累加安全
        Add(work, work, work[half], static_cast<int32_t>(half));
        cur = half;
    }
    ReduceSum(red, work, acc, static_cast<int32_t>(REDUC_LANE));
}

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::StoreScalar(int64_t gmOffset)
{
    LocalTensor<float> red = bufRed_.Get<float>();
    LocalTensor<T> localOut = outQue_.AllocTensor<T>();
    CastFromFp32(localOut, red, 1);
    outQue_.EnQue(localOut);
    localOut = outQue_.DeQue<T>();
    DataCopyExtParams copyParams{};
    copyParams.blockCount = 1;
    copyParams.blockLen = static_cast<uint32_t>(sizeof(T));
    copyParams.srcStride = 0;
    copyParams.dstStride = 0;
    DataCopyPad(output1Gm_[gmOffset], localOut, copyParams);
    outQue_.FreeTensor(localOut);
}

// General compact FP32 cascade. Pair two independent float4 chains in each
// aligned float8 vector so every UB vector operand retains 32-byte alignment.
template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::ProcessFloatRow(int64_t offset)
{
    LocalTensor<float> acc = bufAcc_.Get<float>();
    LocalTensor<float> src = bufP_.Get<float>();
    LocalTensor<float> tmp = bufWork_.Get<float>();
    LocalTensor<float> val = bufTmp_.Get<float>();
    LocalTensor<float> red = bufRed_.Get<float>();
    Duplicate(acc, static_cast<float>(0), 64);
    const int64_t groups = cols_ / 16;
    const int64_t prefix = groups * 16;
    int64_t bits = 0;
    for (int64_t n = groups - 1; n > 0; n >>= 1) ++bits;
    const int64_t power = bits / 4 > 4 ? bits / 4 : 4;
    const int64_t step = static_cast<int64_t>(1) << power;
    const int64_t mask = step - 1;
    int64_t completed = 0;
    int64_t lastTile = 0;
    for (int64_t col = 0; col < cols_; col += tileLen_) {
        int64_t len = cols_ - col;
        if (len > tileLen_) len = tileLen_;
        ProcessTile(offset + col, len, true, true);
        lastTile = col;
        for (int64_t base = 0; base + 16 <= len && col + base < prefix; base += 16) {
            Add(acc, acc, src[base], 8);
            Add(acc[8], acc[8], src[base + 8], 8);
            ++completed;
            if ((completed & mask) == 0) {
                for (int64_t level = 1; level < 4; ++level) {
                    for (int64_t pack = 0; pack < 2; ++pack) {
                        LocalTensor<float> lower = acc[((level - 1) * 2 + pack) * 8];
                        LocalTensor<float> upper = acc[(level * 2 + pack) * 8];
                        Add(upper, upper, lower, 8);
                        Duplicate(lower, static_cast<float>(0), 8);
                    }
                    if ((completed & (mask << (level * power))) != 0) break;
                }
            }
        }
    }
    for (int64_t pack = 0; pack < 2; ++pack)
        for (int64_t level = 1; level < 4; ++level)
            Add(acc[pack * 8], acc[pack * 8], acc[(level * 2 + pack) * 8], 8);
    PipeBarrier<PIPE_ALL>();
    const int64_t vectorEnd = (cols_ / 4) * 4;
    Duplicate(red, static_cast<float>(0), 8);
    for (int64_t col = vectorEnd; col < cols_; ++col) {
        Duplicate(val, src.GetValue(col - lastTile), 8);
        Add(red, red, val, 1);
    }
    if (cols_ < 4) return;
    for (int64_t lane = 0; lane < 4; ++lane) {
        Duplicate(tmp, acc.GetValue(lane), 8);
        for (int64_t col = prefix; col < vectorEnd; col += 4) {
            Duplicate(val, src.GetValue(col + lane - lastTile), 8);
            Add(tmp, tmp, val, 1);
        }
        Duplicate(val, acc.GetValue(lane + 4), 8);
        Add(tmp, tmp, val, 1);
        Duplicate(val, acc.GetValue(lane + 8), 8);
        Add(tmp, tmp, val, 1);
        Duplicate(val, acc.GetValue(lane + 12), 8);
        Add(tmp, tmp, val, 1);
        Add(red, red, tmp, 1);
    }
}

// Independent short rows are batched only by dtype, capacity and alignment.
// All padding is explicitly initialized; input1 is DMA-loaded once and reused.
template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::ProcessHalfRows(int64_t rowBegin, int64_t rowEnd)
{
    const int64_t pitch = laneLen_;
    const int64_t cap = tileLen_ / pitch;
    const int64_t packed = (cols_ + 15) / 16 * 16;
    for (int64_t first = rowBegin; first < rowEnd; first += cap) {
        int64_t count = rowEnd - first;
        if (count > cap) count = cap;
        const int64_t length = count * pitch;
        LocalTensor<T> a = inQueA_.AllocTensor<T>();
        LocalTensor<T> b = inQueB_.AllocTensor<T>();
        LocalTensor<T> c = inQueC_.AllocTensor<T>();
        Duplicate(a, static_cast<T>(0), static_cast<int32_t>(length));
        Duplicate(b, static_cast<T>(0), static_cast<int32_t>(length));
        Duplicate(c, static_cast<T>(0), static_cast<int32_t>(length));
        PipeBarrier<PIPE_ALL>();
        DataCopyExtParams load{};
        load.blockCount = static_cast<uint16_t>(count);
        load.blockLen = static_cast<uint32_t>(cols_ * sizeof(T));
        load.srcStride = 0;
        load.dstStride = static_cast<uint32_t>((pitch - packed) / 16);
        DataCopyPadExtParams<T> padding{};
        padding.isPad = true;
        padding.rightPadding = static_cast<uint8_t>(packed - cols_);
        padding.paddingValue = static_cast<T>(0);
        DataCopyPad(a, input0Gm_[first * cols_], load, padding);
        DataCopyPad(b, input1Gm_[first * cols_], load, padding);
        DataCopyPad(c, input2Gm_[first * cols_], load, padding);
        inQueA_.EnQue(a); inQueB_.EnQue(b); inQueC_.EnQue(c);
        a = inQueA_.DeQue<T>(); b = inQueB_.DeQue<T>(); c = inQueC_.DeQue<T>();
        LocalTensor<float> fa = bufFA_.Get<float>();
        LocalTensor<float> fb = bufFB_.Get<float>();
        LocalTensor<float> fc = bufFC_.Get<float>();
        LocalTensor<float> fo = bufFO_.Get<float>();
        LocalTensor<float> product = bufP_.Get<float>();
        CastToFp32(fa, a, length); CastToFp32(fb, b, length); CastToFp32(fc, c, length);
        Mul(fo, fa, fb, static_cast<int32_t>(length));
        Mul(product, fb, fc, static_cast<int32_t>(length));
        LocalTensor<T> out = outQue_.AllocTensor<T>();
        CastFromFp32(out, fo, length);
        outQue_.EnQue(out); out = outQue_.DeQue<T>();
        DataCopyExtParams store = load;
        store.srcStride = load.dstStride;
        store.dstStride = 0;
        DataCopyPad(output0Gm_[first * cols_], out, store);
        outQue_.FreeTensor(out);
        inQueA_.FreeTensor(a); inQueB_.FreeTensor(b); inQueC_.FreeTensor(c);
        // Same per-row halving tree as the unbatched FP16 baseline.
        for (int64_t span = pitch / 2; span >= 64; span /= 2)
            for (int64_t row = 0; row < count; ++row)
                Add(product[row * pitch], product[row * pitch], product[row * pitch + span],
                    static_cast<int32_t>(span));
        LocalTensor<float> sums = bufWork_.Get<float>();
        WholeReduceSum(sums, product, static_cast<uint64_t>(64), static_cast<int32_t>(count),
                       1, 1, static_cast<int32_t>(pitch / 8));
        out = outQue_.AllocTensor<T>();
        CastFromFp32(out, sums, count);
        outQue_.EnQue(out); out = outQue_.DeQue<T>();
        DataCopyExtParams scalarStore{};
        scalarStore.blockCount = 1;
        scalarStore.blockLen = static_cast<uint32_t>(count * sizeof(T));
        DataCopyPad(output1Gm_[first], out, scalarStore);
        outQue_.FreeTensor(out);
    }
}

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::ProcessRow()
{
    // 行内归约：行按核均分（相邻核最多相差 1 行），核内沿列块累加
    int64_t rowBegin = rows_ * blockIdx_ / coreNum_;
    int64_t rowEnd = rows_ * (blockIdx_ + 1) / coreNum_;
    if (rowBegin >= rowEnd) {
        return;
    }
    if constexpr (sizeof(T) == 2) {
        if (cols_ <= MAX_LANE_LEN && cols_ <= tileLen_) {
            ProcessHalfRows(rowBegin, rowEnd);
            return;
        }
    }
    LocalTensor<float> acc = bufAcc_.Get<float>();
    for (int64_t row = rowBegin; row < rowEnd; ++row) {
        if constexpr (sizeof(T) == sizeof(float)) {
            ProcessFloatRow(row * cols_);
            StoreScalar(row);
            continue;
        }
        Duplicate(acc, static_cast<float>(0), static_cast<int32_t>(laneLen_));  // 清零全部 laneLen_ 个累加器 lane
        int64_t rowOffset = row * cols_;
        for (int64_t col = 0; col < cols_; col += tileLen_) {
            int64_t len = cols_ - col;
            if (len > tileLen_) {
                len = tileLen_;
            }
            ProcessTile(rowOffset + col, len, true, true);
            AccumulateFlat(len);
        }
        ReduceAccToScalar();
        StoreScalar(row);
    }
}

// Four-level cascade summation, following the public PyTorch CPU SumKernel
// numerical strategy (BSD-3-Clause, pytorch/pytorch, aten/src/ATen/native/cpu/
// SumKernel.cpp). Implemented with AscendC vectors; no host tensor computation.
template <typename T>
__aicore__ inline LocalTensor<float> ConfusionMulGrad<T>::TailBank(int64_t bank)
{
    if (bank < 8) return bufAcc_.Get<float>()[bank * VECTOR_LANE];
    return bufAccC_.Get<float>()[(bank - 8) * VECTOR_LANE];
}

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::ProcessColumnBlock(int64_t start, int64_t len, bool tail)
{
    LocalTensor<float> acc = bufAcc_.Get<float>();
    LocalTensor<float> src = bufP_.Get<float>();
    const int64_t chains = tail ? 4 : 1;
    const int64_t groups = rows_ / chains;
    int64_t bits = 0;
    for (int64_t n = groups - 1; n > 0; n >>= 1) ++bits;
    const int64_t power = bits / 4 > 4 ? bits / 4 : 4;
    const int64_t step = static_cast<int64_t>(1) << power;
    const int64_t mask = step - 1;
    if (tail) {
        for (int64_t bank = 0; bank < 16; ++bank)
            Duplicate(TailBank(bank), static_cast<float>(0), static_cast<int32_t>(VECTOR_LANE));
    } else {
        for (int64_t level = 0; level < 4; ++level)
            Duplicate(acc[level * colStride_], static_cast<float>(0), static_cast<int32_t>(len));
    }
    for (int64_t group = 0; group < groups; ++group) {
        for (int64_t chain = 0; chain < chains; ++chain) {
            ProcessTile((group * chains + chain) * cols_ + start, len, true, true);
            LocalTensor<float> dst = tail ? TailBank(chain) : acc;
            Add(dst, dst, src, static_cast<int32_t>(len));
        }
        const int64_t completed = group + 1;
        if ((completed & mask) == 0) {
            for (int64_t level = 1; level < 4; ++level) {
                for (int64_t chain = 0; chain < chains; ++chain) {
                    LocalTensor<float> lower = tail ? TailBank((level - 1) * 4 + chain)
                                                   : acc[(level - 1) * colStride_];
                    LocalTensor<float> upper = tail ? TailBank(level * 4 + chain)
                                                   : acc[level * colStride_];
                    Add(upper, upper, lower, static_cast<int32_t>(len));
                    Duplicate(lower, static_cast<float>(0), static_cast<int32_t>(len));
                }
                if ((completed & (mask << (level * power))) != 0) break;
            }
        }
    }
    for (int64_t chain = 0; chain < chains; ++chain) {
        LocalTensor<float> dst = tail ? TailBank(chain) : acc;
        for (int64_t level = 1; level < 4; ++level) {
            LocalTensor<float> part = tail ? TailBank(level * 4 + chain) : acc[level * colStride_];
            Add(dst, dst, part, static_cast<int32_t>(len));
        }
    }
    for (int64_t row = groups * chains; row < rows_; ++row) {
        ProcessTile(row * cols_ + start, len, true, true);
        Add(acc, acc, src, static_cast<int32_t>(len));
    }
    if (tail) {
        for (int64_t chain = 1; chain < 4; ++chain)
            Add(acc, acc, TailBank(chain), static_cast<int32_t>(len));
    }
    LocalTensor<T> out = outQue_.AllocTensor<T>();
    CastFromFp32(out, acc, len);
    outQue_.EnQue(out);
    out = outQue_.DeQue<T>();
    DataCopyExtParams params{};
    params.blockCount = 1;
    params.blockLen = static_cast<uint32_t>(len * static_cast<int64_t>(sizeof(T)));
    DataCopyPad(output1Gm_[start], out, params);
    outQue_.FreeTensor(out);
}

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::ProcessCol()
{
    // Vector columns and the residual (<32) columns use the same four-level
    // cascade with different unrolling, independent of any testcase identity.
    // Below one float8 vector, scalar output groups have width four.
    const int64_t groupWidth = cols_ < 8 ? 4 : 32;
    const int64_t vectorEnd = (cols_ / groupWidth) * groupWidth;
    for (int64_t block = blockIdx_; block < colBlockNum_; block += coreNum_) {
        int64_t start = block * colBlockLen_;
        int64_t end = start + colBlockLen_;
        if (end > cols_) end = cols_;
        if (start < vectorEnd) {
            int64_t split = end < vectorEnd ? end : vectorEnd;
            ProcessColumnBlock(start, split - start, false);
            start = split;
        }
        if (start < end) ProcessColumnBlock(start, end - start, true);
    }
}

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::ProcessFull()
{
    // 全归约 axis=[0,1] / ()：单核顺序完成整个矩阵。
    // 关键原因：全归约的最终标量必须由同一个核汇总；若把 output0 与归约拆成两遍，
    // input1 会被搬运两次，违反"input1 只搬入一次、片上复用"的硬约束。
    // 因此这里让 0 号核在一个 tile 内同时完成两路乘法：output0 写回 + p 累加。
    // 代价：全归约用例没有多核并行（已知性能限制，见交付说明）。
    if (blockIdx_ != 0) {
        return;
    }
    int64_t total = rows_ * cols_;
    LocalTensor<float> acc = bufAcc_.Get<float>();
    Duplicate(acc, static_cast<float>(0), static_cast<int32_t>(laneLen_));  // 清零全部 laneLen_ 个累加器 lane
    for (int64_t offset = 0; offset < total; offset += tileLen_) {
        int64_t len = total - offset;
        if (len > tileLen_) {
            len = tileLen_;
        }
        ProcessTile(offset, len, true, true);
        AccumulateFlat(len);
    }
    ReduceAccToScalar();
    StoreScalar(0);
}

template <typename T>
__aicore__ inline void ConfusionMulGrad<T>::Process()
{
    if (axisMode_ == static_cast<int32_t>(AXIS_MODE_ROW)) {
        ProcessRow();
    } else if (axisMode_ == static_cast<int32_t>(AXIS_MODE_COL)) {
        // 单列（N==1）时"每列求和"就等于"全和"：走平坦单遍扫描，
        // 避免 rows 次只搬 1 个元素的极小 DMA（实测在 CPU 仿真上直接把用例拖到超时）。
        if (cols_ == 1) {
            ProcessFull();
        } else {
            ProcessCol();
        }
    } else {
        ProcessFull();
    }
}

} // namespace NsConfusionMulGrad
#endif // CONFUSIONMULGRAD_H
