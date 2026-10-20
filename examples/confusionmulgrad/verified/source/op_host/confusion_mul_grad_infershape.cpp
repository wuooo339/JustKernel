/*!
 * \file confusion_mul_grad_infershape.cpp
 * \brief ConfusionMulGrad 算子形状推导实现
 *
 * output0 : 与输入同 shape，恒为 (M, N)
 * output1 : 由 axis / keep_dims 严格推导
 *           axis=[1]        -> keep_dims ? (M, 1) : (M)
 *           axis=[0]        -> keep_dims ? (1, N) : (N)
 *           axis=[0,1]/()   -> keep_dims ? (1, 1) : 0 维标量
 */

#include "register/op_impl_registry.h"
#include "exe_graph/runtime/infer_shape_context.h"

using namespace ge;

namespace ops {

namespace {
constexpr int64_t CONFUSION_MUL_GRAD_AXIS_NUM = 2;

// 读取 list_int 属性 axis，归一化到 2D 语义后得到是否含 0 轴 / 1 轴
void ParseAxisAttr(const gert::RuntimeAttrs* attrs, bool& hasAxis0, bool& hasAxis1)
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
        int64_t axisValue = axisData[i] % CONFUSION_MUL_GRAD_AXIS_NUM;
        if (axisValue < 0) {
            axisValue += CONFUSION_MUL_GRAD_AXIS_NUM;
        }
        if (axisValue == 0) {
            hasAxis0 = true;
        } else {
            hasAxis1 = true;
        }
    }
}
}  // namespace

static ge::graphStatus InferShapeConfusionMulGrad(gert::InferShapeContext* context)
{
    const gert::Shape* inputShape = context->GetInputShape(0);
    if (inputShape == nullptr) {
        return ge::GRAPH_FAILED;
    }
    gert::Shape* output0Shape = context->GetOutputShape(0);
    gert::Shape* output1Shape = context->GetOutputShape(1);
    if (output0Shape == nullptr || output1Shape == nullptr) {
        return ge::GRAPH_FAILED;
    }

    // output0 与输入完全同 shape
    *output0Shape = *inputShape;

    size_t rank = inputShape->GetDimNum();
    int64_t rows = 1;
    int64_t cols = 1;
    if (rank > 0) {
        cols = inputShape->GetDim(rank - 1);
        for (size_t i = 0; i + 1 < rank; i++) {
            rows *= inputShape->GetDim(i);
        }
    }

    const gert::RuntimeAttrs* attrs = context->GetAttrs();
    bool hasAxis0 = false;
    bool hasAxis1 = false;
    ParseAxisAttr(attrs, hasAxis0, hasAxis1);
    bool keepDims = false;
    if (attrs != nullptr && attrs->GetAttrNum() > 1) {
        const bool* keepDimsPtr = attrs->GetAttrPointer<bool>(1);
        if (keepDimsPtr != nullptr) {
            keepDims = *keepDimsPtr;
        }
    }

    gert::Shape reduceShape;  // 默认 0 维
    if (hasAxis0 && hasAxis1) {
        // 全归约
        if (keepDims) {
            reduceShape.AppendDim(1);
            reduceShape.AppendDim(1);
        }
    } else if (hasAxis1) {
        // 行内归约：归约最后一维
        reduceShape.AppendDim(rows);
        if (keepDims) {
            reduceShape.AppendDim(1);
        }
    } else if (hasAxis0) {
        // 跨行归约：归约第一维
        if (keepDims) {
            reduceShape.AppendDim(1);
        }
        reduceShape.AppendDim(cols);
    } else {
        // axis 为空等价于 [0,1]
        if (keepDims) {
            reduceShape.AppendDim(1);
            reduceShape.AppendDim(1);
        }
    }
    *output1Shape = reduceShape;
    return ge::GRAPH_SUCCESS;
}

IMPL_OP_INFERSHAPE(ConfusionMulGrad).InferShape(InferShapeConfusionMulGrad);

} // namespace ops
