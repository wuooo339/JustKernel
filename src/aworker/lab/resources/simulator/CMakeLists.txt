cmake_minimum_required(VERSION 3.19)
project(justkernel_simulation)
set(CMAKE_CXX_STANDARD 17)
find_package(ASC REQUIRED HINTS ${ASCEND_CANN_PACKAGE_PATH}/compiler/tikcpp/ascendc_kernel_cmake)
set(package_name justkernel)
include_directories(${ASCEND_CANN_PACKAGE_PATH}/include ${ASCEND_CANN_PACKAGE_PATH}/pkg_inc
    ${ASCEND_CANN_PACKAGE_PATH}/pkg_inc/base)
npu_op_package(${package_name} TYPE RUN CONFIG INSTALL_PATH ${CMAKE_BINARY_DIR})
file(GLOB ops_srcs ${CANDIDATE_ROOT}/op_host/*.cpp)
npu_op_code_gen(SRC ${ops_srcs} PACKAGE ${package_name} OUT_DIR ${ASCEND_AUTOGEN_PATH}
    COMPILE_OPTIONS -I${ASCEND_CANN_PACKAGE_PATH}/pkg_inc
    -I${ASCEND_CANN_PACKAGE_PATH}/pkg_inc/base -std=c++17)
file(GLOB api_src ${ASCEND_AUTOGEN_PATH}/aclnn_*.cpp)
file(GLOB proto_src ${ASCEND_AUTOGEN_PATH}/op_proto.cc ${ASCEND_AUTOGEN_PATH}/group_op_proto/*.cc)
file(GLOB fallback_src ${ASCEND_AUTOGEN_PATH}/fallback_*.cpp)
set_source_files_properties(${api_src} ${proto_src} ${fallback_src} PROPERTIES GENERATED TRUE)
npu_op_library(cust_opapi ACLNN ${api_src})
npu_op_library(cust_op_proto GRAPH ${ops_srcs} ${proto_src})
npu_op_library(cust_optiling TILING ${ops_srcs} ${fallback_src})
npu_op_package_add(${package_name} LIBRARY cust_opapi cust_op_proto cust_optiling)
npu_op_kernel_sources(ascendc_kernels OP_TYPE ConfusionMulGrad
    KERNEL_DIR . KERNEL_FILE confusion_mul_grad.cpp)
npu_op_kernel_options(ascendc_kernels ALL OPTIONS -g)
npu_op_kernel_library(ascendc_kernels SRC_BASE ${CANDIDATE_ROOT}/op_kernel
    TILING_LIBRARY cust_optiling)
npu_op_package_add(${package_name} LIBRARY ascendc_kernels)
