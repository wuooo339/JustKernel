// Trusted local validation driver. Candidate mathematics stays in its AscendC kernel.
#include <acl/acl.h>
#include "aclnn_confusion_mul_grad.h"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static void Check(int code, const char* name) {
    if (code) throw std::runtime_error(std::string(name) + ": " + std::to_string(code));
}

static std::vector<int64_t> Strides(const std::vector<int64_t>& shape) {
    std::vector<int64_t> result(shape.size(), 1);
    for (int i = static_cast<int>(shape.size()) - 2; i >= 0; --i)
        result[i] = result[i + 1] * shape[i + 1];
    return result;
}

static size_t Elements(const std::vector<int64_t>& shape) {
    size_t size = 1;
    for (int64_t dim : shape) size *= dim;
    return size;
}

int main(int argc, char** argv) {
    if (argc != 8) return 64;
    try {
        const int64_t rows = std::stoll(argv[1]), cols = std::stoll(argv[2]);
        const bool fp16 = std::string(argv[3]) == "float16";
        const int mask = std::stoi(argv[4]);
        const bool keep = std::stoi(argv[5]) != 0;
        const std::string input = argv[6], output = argv[7];
        if (rows <= 0 || cols <= 0 || mask < 1 || mask > 3) return 64;
        const aclDataType dtype = fp16 ? ACL_FLOAT16 : ACL_FLOAT;
        const size_t width = fp16 ? 2 : 4;
        std::vector<int64_t> shape{rows, cols}, reduced;
        for (int axis = 0; axis < 2; ++axis) {
            if (!(mask & (1 << axis))) reduced.push_back(shape[axis]);
            else if (keep) reduced.push_back(1);
        }
        std::vector<int64_t> axes;
        for (int axis = 0; axis < 2; ++axis) if (mask & (1 << axis)) axes.push_back(axis);
        Check(aclInit(nullptr), "aclInit");
        Check(aclrtSetDevice(0), "aclrtSetDevice");
        aclrtStream stream = nullptr;
        Check(aclrtCreateStream(&stream), "aclrtCreateStream");
        void* address[5]{};
        aclTensor* tensor[5]{};
        size_t bytes[5]{};
        for (int i = 0; i < 5; ++i) {
            const auto& dims = i == 4 ? reduced : shape;
            bytes[i] = Elements(dims) * width;
            Check(aclrtMalloc(&address[i], bytes[i], ACL_MEM_MALLOC_HUGE_FIRST), "aclrtMalloc");
            std::vector<uint8_t> data(bytes[i], 0xa5);
            if (i < 3) {
                std::ifstream file(input + "/input" + std::to_string(i) + ".bin", std::ios::binary);
                if (!file.read(reinterpret_cast<char*>(data.data()), data.size()))
                    throw std::runtime_error("input file size mismatch");
            }
            Check(aclrtMemcpy(address[i], bytes[i], data.data(), bytes[i], ACL_MEMCPY_HOST_TO_DEVICE), "H2D");
            const auto strides = Strides(dims);
            tensor[i] = aclCreateTensor(dims.data(), dims.size(), dtype, strides.data(),
                                        0, ACL_FORMAT_ND, dims.data(), dims.size(), address[i]);
            if (!tensor[i]) throw std::runtime_error("aclCreateTensor");
        }
        aclIntArray* axis = aclCreateIntArray(axes.data(), axes.size());
        if (!axis) throw std::runtime_error("aclCreateIntArray");
        uint64_t workspace_size = 0;
        aclOpExecutor* executor = nullptr;
        Check(aclnnConfusionMulGradGetWorkspaceSize(tensor[0], tensor[1], tensor[2], axis,
              keep, tensor[3], tensor[4], &workspace_size, &executor), "GetWorkspaceSize");
        void* workspace = nullptr;
        if (workspace_size)
            Check(aclrtMalloc(&workspace, workspace_size, ACL_MEM_MALLOC_HUGE_FIRST), "workspace");
        Check(aclnnConfusionMulGrad(workspace, workspace_size, executor, stream), "kernel");
        Check(aclrtSynchronizeStream(stream), "synchronize");
        for (int i = 3; i < 5; ++i) {
            std::vector<uint8_t> data(bytes[i]);
            Check(aclrtMemcpy(data.data(), bytes[i], address[i], bytes[i], ACL_MEMCPY_DEVICE_TO_HOST), "D2H");
            std::ofstream file(output + "/output" + std::to_string(i - 3) + ".bin", std::ios::binary);
            if (!file.write(reinterpret_cast<const char*>(data.data()), data.size()))
                throw std::runtime_error("output file write failed");
        }
        for (int i = 0; i < 5; ++i) { aclDestroyTensor(tensor[i]); aclrtFree(address[i]); }
        aclDestroyIntArray(axis);
        if (workspace) aclrtFree(workspace);
        aclrtDestroyStream(stream);
        aclrtResetDevice(0);
        aclFinalize();
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << std::endl;
        return 1;
    }
}
