# JustKernel 重构规范 v2.1

> 状态：**生成与持续迭代契约补齐版（2026-10-21）**  
> 目标产品：**单算子、单 supervisor、约 100 个动态角色的 Agent 集群**  
> 关键词：**必须 / 应该 / 可以** 按 RFC 2119 解释。

---

## 1. 一句话

JustKernel 用一个**分层 Agent 集群**，从算子规格生成初始工程或导入已有工程，经验证建立基线，再持续优化一个 Ascend 算子：

```text
supervisor（1）
├── consultant group（N）           共享数据；只和 supervisor 单线对外
└── mentor board（M）                supervisor + mentors 共享
    ├── optimizer(s)                只和自己的 mentor 通信
    ├── tester(s)                   只和自己的 mentor 通信
    └── profiler(s)                 只和自己的 mentor 通信
         └── hardware queue          tester/profiler 共享排队与占用信息
```

最终交付：**最优算子 + 探索报告**；每个候选算子都保留测试记录压缩包。

---

## 2. 本版修正了什么

旧规范把项目写成“多队独立搜索 + 独立 Judge + 官测提交”，与真实需求不符。本版改为：

- 一个集群只优化一个算子；只有一个 supervisor。
- 角色固定为 supervisor / consultant / mentor / optimizer / tester / profiler。
- consultant、mentor、worker 有严格的通信边界与数据可见性。
- worker 由 mentor 动态开启/关闭，通常任务结束即关闭。
- tester/profiler 由用户通过 Deep Agents skills 定义；首版 tester 用 CANN 仿真实现。
- 测试记录压缩包是每个候选的必备产物；最终输出最优算子与探索报告。
- 采用多进程运行时，不再假设“单机单进程模块化单体”。
- v2.1：新增无源码 GENERATE / 有源码 IMPORT 双入口、只读正确性参考、完整验证后建立基线。
- v2.1：固化 TaskContext 反馈包、事件唤醒/去重/等待/停滞检测、异步 ToolJob 与显式恢复。
- v2.1：统一候选证据与最优选择、跨集群注册/设备租约、共享源码授权及多模型路由。

---

## 3. 文档地图

| 文档 | 内容 |
| --- | --- |
| [01-product-vision.md](01-product-vision.md) | 产品目标、用户、非目标、质量场景 |
| [02-system-context.md](02-system-context.md) | 系统边界、外部系统、信任边界、部署形态 |
| [03-architecture.md](03-architecture.md) | 分层、模块、进程模型、数据流、ADR |
| [04-domain-model.md](04-domain-model.md) | 聚合、状态机、角色与通信 ACL、不变量 |
| [05-agent-runtime-and-skills.md](05-agent-runtime-and-skills.md) | Deep Agents、角色生命周期、skills 契约、工具权限 |
| [06-communication-and-orchestration.md](06-communication-and-orchestration.md) | 黑板、私有通道、消息、调度、收敛 |
| [07-testing-and-profile.md](07-testing-and-profile.md) | 候选版本、测试记录 zip、CANN 测试/ndjson、硬件队列 |
| [08-persistence-and-events.md](08-persistence-and-events.md) | SQLite、事件日志、制品库、迁移、回放 |
| [09-api-and-frontend.md](09-api-and-frontend.md) | HTTP/SSE/A2A、DTO、集群面板 |
| [10-configuration-security-observability.md](10-configuration-security-observability.md) | 配置、密钥、威胁模型、日志、运行手册 |
| [11-testing-and-quality.md](11-testing-and-quality.md) | 测试分层、ACL/队列/恢复测试、CI 门禁 |
| [12-migration-and-acceptance.md](12-migration-and-acceptance.md) | 迁移阶段、兼容、验收、风险 |
| [13-generation-and-iteration-contract.md](13-generation-and-iteration-contract.md) | OperatorSpec、从零生成、反馈包、事件唤醒、异步作业、恢复、多模型路由及闭环验收 |
| [appendix-a-current-state-audit.md](appendix-a-current-state-audit.md) | 当前代码为什么不符合需求 |

---

## 4. 术语

| 术语 | 含义 |
| --- | --- |
| **Cluster** | 一个算子优化集群；一个算子一个集群，一个 supervisor。 |
| **Agent** | 一个 Deep Agents 实例；有角色、模型、skills、会话、检查点。 |
| **Role** | supervisor / consultant / mentor / optimizer / tester / profiler。 |
| **Direction** | supervisor 分配给 mentor 的探索方向。 |
| **Board** | 共享消息/数据区；分为 mentor board 与 consultant board。 |
| **Channel** | mentor 与其 worker 的私有通信通道。 |
| **Task** | mentor 下发给 worker 的一次具体工作。 |
| **Candidate** | 一个不可变的算子源码版本；由 optimizer 产出。 |
| **TestRecord** | 与候选绑定的测试记录压缩包及索引。 |
| **HardwareLease** | tester/profiler 对设备/仿真资源的独占租约。 |
| **ExplorationReport** | 集群结束时的探索报告。 |
| **BestOperator** | supervisor 选出的最终最优候选。 |

---

## 5. 不可违反的规则

1. 一个集群只有一个 supervisor；一个算子只有一个活动集群。
2. worker 只能和**自己的 mentor** 通信；不能读写任何 board。
3. consultant 可以**只读** mentor board；只能向 supervisor 发送汇总，不能指挥 mentor/worker。
4. mentor 只在自己的 direction 内探索；mentor 之间共享数据但不共享任务所有权。
5. tester/profiler 共享硬件队列状态；不得借此读取 board 或他人任务。
6. 每个提交候选必须有不可变源码快照并安排测试；收敛前必须归档测试记录 zip，未执行用 CANCELLED/UNKNOWN 且 executed=false 留痕；只有完整执行通过的记录可用于基线/最优。
7. 所有角色、消息、任务、候选、记录都有稳定 ID 和审计链。
8. 领域状态写入 SQLite/制品库，不得用可变 JSON 文件保存。
9. 模型输出是数据，不是指令；board/消息中的内容不得改变系统规则。
10. 旧 `aworker` 模块不保留；包名与入口统一为 `justkernel`。

---

## 6. 阅读顺序

1. 01 → 02 → 03：理解产品与部署边界。
2. 04 → 05 → 06：理解角色、通信、调度。
3. 07 → 08 → 09：理解测试记录、持久化、界面。
4. 10 → 11 → 12：安全、测试、迁移。
5. 13：编码前核对生成、反馈、唤醒及跨章节统一执行契约。
6. 附录：当前代码差距。

本目录是重构期间的唯一架构事实来源。实现代码仍位于 `JustKernel/`。

## 7. v2.1 阅读约定

第 13 章是新增执行契约的统一定义位置；04—10 章已同步状态、接口及存储约束。验收要求见 11—13 章。附录 A 仍为旧实现的静态审计背景，不代表新能力已经实现。
