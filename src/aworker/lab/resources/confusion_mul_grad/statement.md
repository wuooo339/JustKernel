# ConfusionMulGrad · JustKernel 工程规格摘要

本页为依据公开接口独立整理的实现摘要，不是官方题面副本。当前比赛要求、精度与可编辑范围以 [CANN Judge](https://cannjudge.cn/public/ladder_october/confusionmulgrad) 为准。官方原始工程需通过导入工具另行取得。

## 接口与语义

三路连续 ND 输入 `input0`、`input1`、`input2` 的 shape 均为 `(M, N)`，dtype 相同，为 float16 或 float32。输出为：

```text
output0 = cast_T(fp32(input0) * fp32(input1))
output1 = cast_T(sum(fp32(input1) * fp32(input2), axis, keep_dims))
```

`T` 是输入 dtype。两路乘法、归约部分和和最终累加均使用 FLOAT32；最后转换回 T，采用 round-to-nearest-even。不要在 float16 中提前乘法或累加。

属性 `axis` 为归约轴集合，二维归一化后支持 `[0]`、`[1]`、`[0, 1]`；负轴按二维规则归一化，空集合按全归约处理。非空轴不能重复。`keep_dims` 默认为 false。

| 归约轴 | output1，keep_dims=false | output1，keep_dims=true |
| --- | --- | --- |
| `[0]` | `(N,)` | `(1, N)` |
| `[1]` | `(M,)` | `(M, 1)` |
| `[0, 1]` | 标量 | `(1, 1)` |

output0 始终保持 `(M, N)`。两个输出均须完整写回，归约对象是 input1 与 input2 的乘积。

## 范围与数值

- `1 <= M, N <= 65536`，`M * N <= 2**27`；不支持广播、空张量和高于二维的输入。
- 合法输入保证输出有限，float16 输出不溢出。实现仍需避免低精度部分和溢出。
- 公开精度要求：float32 相对、绝对误差均小于 `1e-4`；float16 均小于 `1e-3`。实际判定以官网为准；本地校验不能证明隐藏测试通过。

## 实现边界

Host 仅处理元信息、shape、整数 tiling 和启动配置。完整双路乘法与归约在一次 Device Kernel 中完成；复用片上 input1，避免为两路乘法重复读取。不要以多个 Kernel 拆分一次调用。

只改 `input-source.json` / 工程 manifest 列出的 7 个允许文件。构建、测试、精度校验与计时文件受保护。通用禁区见 CONSTRAINTS.md；静态自查不等于完整合规认证。

`cases.json` 提供 **15 组暂拟本地输入**及确定性数据生成参数。官方同样有 15 个测试 ID，但隐藏 shape / 数值和逐点对应尚未确认。默认完整本队仿真必须覆盖全部本地点；子集探针不能替代。空工程不是正确基准，模板 UT 示例也不代表官方全点覆盖。

仿真原始诊断用于独立修正；学习其他队代码后再次验证。仿真 cycle、NPU 耗时和官方成绩分别记录，禁止换算或相互冒充。
