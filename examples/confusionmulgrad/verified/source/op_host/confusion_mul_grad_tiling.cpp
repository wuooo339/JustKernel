/*!
 * \file confusion_mul_grad_tiling.cpp
 * \brief ConfusionMulGrad 算子 Tiling 实现
 *
 * Host 只做：参数校验、shape 提取、整数 tiling、tilingKey / BlockDim 配置。
 * 任何张量数值计算都不在 Host 完成。
 */

#include "register/op_def_registry.h"
#include "op_common/log/log.h"
#include "op_common/op_host/util/math_util.h"
#include "op_common/op_host/util/platform_util.h"
#include "../op_kernel/confusion_mul_grad_tiling_data.h"
#include "../op_kernel/confusion_mul_grad_tiling_key.h"

namespace optiling {

constexpr uint32_t WS_SYS_SIZE = 0U;
// 预留 UB（队列/临时 buffer 的对齐、reduce 工作区与运行时开销）
constexpr int64_t UB_RESERVED_SIZE = 16384;
constexpr int64_t UB_FIXED_RESERVE = 4096;
// 以下容量常量与 kernel 共享同一份定义（见 confusion_mul_grad_tiling_data.h）
constexpr int64_t VECTOR_LANE = CONFUSIONMULGRAD_VECTOR_LANE;
constexpr int64_t MAX_LANE_LEN = CONFUSIONMULGRAD_MAX_LANE_LEN;
constexpr int64_t MAX_TILE_LEN_F16 = CONFUSIONMULGRAD_MAX_TILE_LEN_F16;
constexpr int64_t MAX_TILE_LEN_F32 = CONFUSIONMULGRAD_MAX_TILE_LEN_F32;
constexpr int64_t COL_BLOCK_ALIGN = CONFUSIONMULGRAD_COL_BLOCK_ALIGN;
constexpr int64_t COL_ACC_NUM = CONFUSIONMULGRAD_COL_ACC_NUM;
constexpr int64_t COL_ACC_BUDGET = CONFUSIONMULGRAD_COL_ACC_BYTES;
// 列块长度上限（约束部分和累加器的 UB 占用）
constexpr int64_t MAX_COL_BLOCK = 2048;

static inline int64_t CeilDivI(int64_t a, int64_t b)
{
    if (b <= 0) {
        return 0;
    }
    return (a + b - 1) / b;
}

static inline int64_t AlignUpI(int64_t a, int64_t align)
{
    return CeilDivI(a, align) * align;
}

// 向下取 2 的幂，且不小于 VECTOR_LANE
static inline int64_t FloorPow2I(int64_t v)
{
    int64_t p = VECTOR_LANE;
    while ((p << 1) <= v) {
        p <<= 1;
    }
    return p;
}

// 向上取 2 的幂，且不超过 cap（cap 自身为 2 的幂，且 >= VECTOR_LANE）
static inline int64_t CeilPow2Capped(int64_t v, int64_t cap)
{
    int64_t p = VECTOR_LANE;
    while (p < v && p < cap) {
        p <<= 1;
    }
    if (p > cap) {
        p = cap;
    }
    return p;
}

static ge::graphStatus GetPlatformInfo(gert::TilingContext* context, uint64_t& ubSize, int64_t& coreNum)
{
    fe::PlatFormInfos* platformInfoPtr = context->GetPlatformInfo();
    OP_CHECK_NULL_WITH_CONTEXT(context, platformInfoPtr);
    auto ascendcPlatform = platform_ascendc::PlatformAscendC(platformInfoPtr);
    coreNum = ascendcPlatform.GetCoreNumAiv();
    OP_CHECK_IF(coreNum == 0, OP_LOGE(context, "coreNum is 0"), return ge::GRAPH_FAILED);
    ascendcPlatform.GetCoreMemSize(platform_ascendc::CoreMemType::UB, ubSize);
    OP_CHECK_IF(ubSize == 0, OP_LOGE(context, "ubSize is 0"), return ge::GRAPH_FAILED);
    return ge::GRAPH_SUCCESS;
}

static ge::graphStatus GetWorkspaceSize(gert::TilingContext* context)
{
    size_t* currentWorkspace = context->GetWorkspaceSizes(1);
    OP_CHECK_NULL_WITH_CONTEXT(context, currentWorkspace);
    currentWorkspace[0] = WS_SYS_SIZE;
    return ge::GRAPH_SUCCESS;
}

// 读取 list_int 属性 axis，归一化到 2D 语义后得到是否含 0 轴 / 1 轴
static void ParseAxis(const gert::RuntimeAttrs* attrs, bool& hasAxis0, bool& hasAxis1)
{
    hasAxis0 = false;
    hasAxis1 = false;
    if (attrs == nullptr || attrs->GetAttrNum() < 1) {
        return;
    }
    auto axisVec = attrs->GetAttrPointer<gert::ContinuousVector>(0);
    if (axisVec == nullptr) {
        return;
    }
    const int64_t* axisData = static_cast<const int64_t*>(axisVec->GetData());
    size_t axisSize = axisVec->GetSize();
    if (axisData == nullptr) {
        return;
    }
    for (size_t i = 0; i < axisSize; i++) {
        int64_t axisValue = axisData[i] % 2;
        if (axisValue < 0) {
            axisValue += 2;
        }
        if (axisValue == 0) {
            hasAxis0 = true;
        } else {
            hasAxis1 = true;
        }
    }
}

static ge::graphStatus ConfusionMulGradTilingFunc(gert::TilingContext* context)
{
    uint64_t ubSize = 0;
    int64_t coreNum = 0;
    OP_CHECK_IF(
        GetPlatformInfo(context, ubSize, coreNum) != ge::GRAPH_SUCCESS,
        OP_LOGE(context, "GetPlatformInfo error"),
        return ge::GRAPH_FAILED);

    OP_CHECK_IF(
        GetWorkspaceSize(context) != ge::GRAPH_SUCCESS,
        OP_LOGE(context, "GetWorkspaceSize error"),
        return ge::GRAPH_FAILED);

    ConfusionMulGradTilingData* tiling = context->GetTilingData<ConfusionMulGradTilingData>();
    OP_CHECK_NULL_WITH_CONTEXT(context, tiling);

    // ---- 输入 dtype ----
    auto inputDesc = context->GetInputDesc(0);
    OP_CHECK_NULL_WITH_CONTEXT(context, inputDesc);
    ge::DataType dtype = inputDesc->GetDataType();
    int64_t typeSize = (dtype == ge::DT_FLOAT16) ? 2 : 4;

    // ---- 输入 shape（本题固定二维 ND，按尾部两维归一化）----
    auto inputShapePtr = context->GetInputShape(0);
    OP_CHECK_NULL_WITH_CONTEXT(context, inputShapePtr);
    const gert::Shape& inputShape = inputShapePtr->GetStorageShape();
    size_t rank = inputShape.GetDimNum();
    int64_t rows = 1;
    int64_t cols = 1;
    if (rank > 0) {
        cols = inputShape.GetDim(rank - 1);
        for (size_t i = 0; i + 1 < rank; i++) {
            rows *= inputShape.GetDim(i);
        }
    }
    OP_CHECK_IF(
        rows <= 0 || cols <= 0,
        OP_LOGE(context, "invalid input shape, rows=%ld cols=%ld", rows, cols),
        return ge::GRAPH_FAILED);

    // ---- 属性：axis / keep_dims ----
    const gert::RuntimeAttrs* attrs = context->GetAttrs();
    OP_CHECK_NULL_WITH_CONTEXT(context, attrs);
    bool hasAxis0 = false;
    bool hasAxis1 = false;
    ParseAxis(attrs, hasAxis0, hasAxis1);
    bool keepDims = false;
    if (attrs->GetAttrNum() > 1) {
        const bool* keepDimsPtr = attrs->GetAttrPointer<bool>(1);
        if (keepDimsPtr != nullptr) {
            keepDims = *keepDimsPtr;
        }
    }

    // axis=[0,1] 或 axis=() 均为全归约；只含 1 轴为行内归约；只含 0 轴为跨行归约
    int64_t axisMode = 2;  // AXIS_MODE_FULL
    if (hasAxis0 && !hasAxis1) {
        axisMode = 1;  // AXIS_MODE_COL
    } else if (hasAxis1 && !hasAxis0) {
        axisMode = 0;  // AXIS_MODE_ROW
    }

    // ---- UB 元素预算 ----
    // 3 路输入队列(双缓冲) + 1 路输出队列(双缓冲) = 8*typeSize 字节/元素
    // 5 个 tile 大小的 fp32 临时(fa/fb/fc/fo/p) = 20 字节/元素（fp32 实际只用 1 个，按最坏估算）
    int64_t perElemBytes = 8 * typeSize + 20;
    int64_t usableUb = static_cast<int64_t>(ubSize) - UB_RESERVED_SIZE;
    if (usableUb < 8192) {
        usableUb = 8192;
    }
    // 列模式需要 colAccNum 路列方向部分和累加器 + 等长的 Kahan 补偿向量 + Kahan 临时量；
    // 行/全模式需要 laneLen 个 lane 的累加器（补偿/临时仅列路径占用，按上界预留）。
    int64_t accOne = (axisMode == 1) ? COL_ACC_BUDGET
                                     : (MAX_LANE_LEN * static_cast<int64_t>(sizeof(float)));
    // acc + 等长补偿(Kahan) + 2 个 lane 宽临时(bufWork/bufTmp) + reduce 工作区
    int64_t accBudget = 2 * accOne + 2 * MAX_LANE_LEN * static_cast<int64_t>(sizeof(float)) + 128;
    int64_t elemBudget = usableUb - UB_FIXED_RESERVE - accBudget;
    if (elemBudget < perElemBytes * VECTOR_LANE) {
        elemBudget = perElemBytes * VECTOR_LANE;
    }
    int64_t maxTileLen = (typeSize == 2) ? MAX_TILE_LEN_F16 : MAX_TILE_LEN_F32;
    int64_t maxElem = elemBudget / perElemBytes;
    if (maxElem > maxTileLen) {
        maxElem = maxTileLen;
    }
    int64_t tileLen = FloorPow2I(maxElem);

    // 行/全归约的累加器 lane 数：覆盖单块最小需求，2 的幂，上限 MAX_LANE_LEN
    int64_t laneNeed = (cols < tileLen) ? cols : tileLen;
    int64_t laneLen = CeilPow2Capped(laneNeed, tileLen);
    if (laneLen > MAX_LANE_LEN) {
        laneLen = MAX_LANE_LEN;
    }

    // ---- 按归约模式的并行切分 ----
    int64_t rowsPerCore = 0;
    int64_t colBlockLen = 0;
    int64_t colBlockNum = 0;
    int64_t colAccNum = 0;
    int64_t flatPerCore = 0;
    int64_t totalNum = rows * cols;
    if (axisMode == 0) {
        // 行内归约：按行切核，单核内按列块累加
        rowsPerCore = CeilDivI(rows, coreNum);
    } else if (axisMode == 1) {
        // 跨行归约：按列块切核，每核遍历全部行（无需跨核二次归约）
        colBlockLen = AlignUpI(CeilDivI(cols, coreNum), COL_BLOCK_ALIGN);
        if (colBlockLen > MAX_COL_BLOCK) {
            colBlockLen = MAX_COL_BLOCK;
        }
        if (colBlockLen > tileLen) {
            colBlockLen = tileLen;
        }
        if (colBlockLen > cols) {
            colBlockLen = cols;
        }
        if (colBlockLen < 1) {
            colBlockLen = 1;
        }
        colBlockNum = CeilDivI(cols, colBlockLen);
        // 分段偏移必须是 64 元素对齐，否则 kernel 退化为单链。
        // 8 路部分和用于窄列块（累加器 8*1024*4B <= 32KB），更宽的列块退回 4 路以守住同一预算。
        if ((colBlockLen % COL_BLOCK_ALIGN) != 0) {
            colAccNum = 1;
        } else if (colBlockLen <= (COL_ACC_BUDGET / (COL_ACC_NUM * static_cast<int64_t>(sizeof(float))))) {
            colAccNum = COL_ACC_NUM;
        } else {
            colAccNum = COL_ACC_NUM / 2;
        }
    } else {
        // 全归约：最终标量只能由同一个核汇总，kernel 侧由 0 号核在单遍扫描内完成
        // 两路乘法（保证 input1 只搬入一次），此处只记录每核平坦元素数上界
        flatPerCore = CeilDivI(totalNum, coreNum);
    }

    tiling->totalNum = totalNum;
    tiling->blockFactor = (axisMode == 0) ? rowsPerCore : ((axisMode == 1) ? colBlockLen : flatPerCore);
    tiling->ubFactor = tileLen;
    tiling->rows = rows;
    tiling->cols = cols;
    tiling->axisMode = axisMode;
    tiling->keepDims = keepDims ? 1 : 0;
    tiling->tileLen = tileLen;
    tiling->laneLen = laneLen;
    tiling->rowsPerCore = rowsPerCore;
    tiling->colBlockLen = colBlockLen;
    tiling->colBlockNum = colBlockNum;
    tiling->colAccNum = colAccNum;
    tiling->flatPerCore = flatPerCore;
    tiling->coreNum = coreNum;

    context->SetBlockDim(static_cast<uint32_t>(coreNum));

    // 根据输入 dtype 选择 tilingKey（0: float16, 1: float32）
    uint64_t tilingKey = GET_TPL_TILING_KEY(CONFUSIONMULGRAD_TPL_SCH_MODE_1);
    if (dtype == ge::DT_FLOAT16) {
        tilingKey = GET_TPL_TILING_KEY(CONFUSIONMULGRAD_TPL_SCH_MODE_0);
    }
    context->SetTilingKey(tilingKey);
    return ge::GRAPH_SUCCESS;
}

static ge::graphStatus TilingParseForConfusionMulGrad([[maybe_unused]] gert::TilingParseContext* context)
{
    return ge::GRAPH_SUCCESS;
}

struct ConfusionMulGradCompileInfo {};

IMPL_OP_OPTILING(ConfusionMulGrad).Tiling(ConfusionMulGradTilingFunc).TilingParse<ConfusionMulGradCompileInfo>(TilingParseForConfusionMulGrad);

} // namespace optiling
