# 12 迁移与验收

> 上层：[11-testing-and-quality.md](11-testing-and-quality.md)  
> 附录：[appendix-a-current-state-audit.md](appendix-a-current-state-audit.md)

---

## 1. 迁移策略

从旧的“多队 lab + Judge/官测”实现，迁移到“单算子角色化 Agent 集群”。

采用**新目录、新包、旧数据只读**：

```text
旧 JustKernel/lab 数据（只读）
        │ 导入
        ▼
新 justkernel 集群数据（独立目录）
```

原则：

- 旧数据不修改；新集群不读取旧 board/队列作为活动状态。
- 旧候选/记录标记 `LEGACY`，只读展示；不参与新 best。
- `aworker` 模块删除；包名/CLI 统一 `justkernel`。
- 每个阶段可运行、可测试；不合并“大爆炸”分支。
- 旧 API 不保证兼容；只保证数据可导入。

---

## 2. 必须保留的能力

| 能力 | 处理 |
| --- | --- |
| Deep Agents 角色/技能 | 保留并扩展 |
| A2A 传输 | 收敛为 cluster 外部接口/内部消息信封 |
| CANN 编译/仿真/ndjson | 保留为 tester/profiler 后端 |
| 源码/回执哈希 | 保留，绑定候选/记录 |
| 事件流/UI 观察 | 保留，改为集群视图 |
| 旧数据 | 只读导入 |

删除：

- 多队 team/work-item 模型。
- 独立 Judge/官测预算/浏览器主线。
- `LabService`、`ContinuousSwarm`、`IterationController`、`JudgeMonitor`。
- 通用 `aworker` server/swarm。
- 可变 JSON 状态文件。

---

## 3. 阶段

### Phase 0：基线与确认（1 周）

- 确认角色/ACL/测试记录/硬件队列需求，以及第 13 章 OperatorSpec、GENERATE/IMPORT、可信参考、反馈/唤醒及预算契约。
- 用当前代码写 characterization tests（哪些行为保留/删除）。
- 旧数据样本与导入夹具。
- 确定 `justkernel` 包结构、无 `aworker` 模块。

退出：需求/非目标/数据映射签字。

### Phase 1：领域与通信基座（2 周）

- `shared`、`cluster`、`agent`、`comm`、`task`、`candidate`、`testing` 领域模型。
- SQLite/事件/制品/消息 outbox；全局 registry/设备账本与集群 journal 分工；TaskContext 授权、inbox/wake/job/BestSelection。
- ACL 表/状态机/唯一索引测试。
- 架构测试。

退出：纯领域 + fake 消息/仓储测试通过；无 I/O 违规。

### Phase 2：Agent 运行时与 Skills（2–3 周）

- Deep Agents 六角色；工具矩阵；worker 无 board。
- 角色 skills；tester/profiler skill 加载；内置 CANN 测试 skill 骨架。
- Agent 池/检查点/开关 worker。
- Fake model/runtime 测试。

退出：可启动 supervisor/consultant/mentor/worker；worker 越权测试失败；skill 可替换。

### Phase 3：任务、测试与硬件（2–3 周）

- GENERATE/OPTIMIZE/TEST/PROFILE 的下发/归属/状态；异步 ToolJob、反馈快照、生成/导入后完整 TEST 建基线。
- TestRecord zip/制品/索引。
- HardwareQueue/lease/TTL。
- CANN 仿真 backend（先 fake，再接真实）。
- 每个候选生成记录。

退出：完整候选→测试→记录→board 流程；zip 完整；lease 唯一。

### Phase 4：编排与 UI（2–3 周）

- 方向/探索/consultant brief/supervisor 决策/收敛；持久化唤醒、单 Agent 串行、WAIT/deadline、停滞检测与无回声调度。
- 集群图/board/任务树/候选图/记录/队列/报告。
- HTTP/SSE/A2A；回放/demo。

退出：单算子集群端到端（fake 工具）可运行；报告含失败路径。

### Phase 5：切换与清理（1 周）

- 导入旧数据（只读 legacy）。
- 新集群默认入口；旧 lab API/服务下线。
- 删除 `aworker` 模块/通用 swarm。
- 文档/CI/打包更新。

退出：无旧模块导入；旧数据可查；构建不含旧模板/密钥。

### Phase 6：加固与验收（2–4 周）

- 真实 CANN 仿真 tester/profiler；真实模型完成无 baseline 生成、失败反馈修复和至少一次再优化。
- 约 100 agent 规模/长跑。
- 崩溃/租约/消息/记录演练。
- 安全/脱敏/导出审查。
- 验收报告。

---

## 4. 验收场景

1. **单算子集群**：一个 operator，一个 supervisor；启动/停止。
2. **角色**：六角色均可运行；同角色不同实例可用不同模型；路由、换模及技能可追踪。
3. **ACL**：worker 无法读 board；consultant 只读 mentor board；mentor 不能跨 worker。
4. **动态规模**：约 100 逻辑 agent；mentor 开关 worker；无孤儿/租约泄漏。
5. **探索**：mentor 方向内探索；board 共享数据；consultant 汇总；supervisor 调整。
6. **测试**：候选→tester→TestRecord zip；profiler→详细记录；zip 完整/可校验。
7. **硬件**：tester/profiler 共享队列；设备独占租约；超时释放。
8. **收敛**：best 有记录/最终验证；报告含方向/分支/失败/理由。
9. **保留**：所有候选记录保留；最终 best+report 可下载。
10. **恢复**：control/agent/tool 崩溃后不重复 task/record/lease；显式 resume 新 session/Task，旧执行未确认停止前不重分配设备。
11. **从零生成**：无源码 GENERATE 建立完整 TEST PASS 基线；IMPORT 也须验证；缺输入/oracle 拒绝。
12. **反馈迭代**：失败与 profile 反馈经 TaskContext 给新 worker，至少完成一次失败修复和一次反馈后再优化。
13. **唤醒**：重复/并发通知不重复实验，无增量不调模型，无任务停滞可检测，合法 WAIT 不误报。
14. **证据比较**：无性能目标不强制 PROFILE；性能目标按冻结策略比较；子集/未执行记录不可成为 best。
15. **全局约束**：跨目录同算子注册冲突、跨集群同设备争抢均被全局服务拦截；预算不足正确停止并产出报告。

---

## 5. 兼容矩阵

| 项 | 处理 |
| --- | --- |
| 包名 | 只 `justkernel`；无 `aworker` 模块 |
| CLI | `justkernel cluster/demo/worker/migrate` |
| 旧环境变量 | 仅迁移工具读取；运行时不兼容 |
| 旧 HTTP API | 不保证；只提供新 `/api/v1` |
| 旧 A2A | 收敛为 cluster card；不保留 per-team skills |
| 旧数据 | 导入为 `LEGACY` 只读 |
| 旧模板/资源 | 可作为 operator baseline；不随包分发受限文件 |

---

## 6. 风险

| 风险 | 缓解 |
| --- | --- |
| 100 agent 资源/成本 | 逻辑 agent + 进程池；模型并发/预算；监控 |
| worker 越权 | 工具层无 board + ACL + 测试 |
| skill 质量/安全 | 用户 skill 审核；allowed_tools；脚本开关 |
| 测试记录膨胀 | 内容寻址/压缩/归档；大 profile 裁剪但留哈希 |
| 设备竞争 | 队列/租约/TTL/超时 |
| 消息重复/丢失 | 至少一次 + 幂等 + outbox |
| 旧数据误导 | `LEGACY` 标记；不参与 best |
| 多进程复杂度 | 明确协议/幂等/恢复；先单机多进程 |
| 模型成本失控 | 角色预算/轮次/并发/停止条件 |

---

## 7. 完成定义

- [ ] 新包/集群启动；旧 `aworker` 模块删除。
- [ ] 六角色/ACL/worker 隔离实现。
- [ ] tester/profiler skills + 内置 CANN 测试。
- [ ] 每个候选 TestRecord zip；best+report。
- [ ] 硬件队列/租约。
- [ ] 约 100 agent 动态规模。
- [ ] 崩溃/恢复/幂等测试。
- [ ] 旧数据只读导入。
- [ ] 验收场景 1–15 及第 13 章闭环验收通过。

## 8. v2.1 交付顺序补充

先交付一个 supervisor、一个 mentor、按需三类 worker 的真实闭环，再扩多方向和约 100 个逻辑 Agent；consultant 可按需参与。小规模验收仍遵守六角色权限和默认资源上限。

闭环必须包括：无 baseline 源码启动 → 初始候选失败 → 新 worker 根据反馈修复 → 完整验证建立基线 → profile/结果驱动再优化 → 最终验证 → 可复核 best 和报告。性能改善是测量结果，不能承诺每轮都变快；无收益必须按 plateau/预算停止。

迁移完成后的历史终态不重新开启；继续研究新建 Cluster 并记录 continued_from_cluster_id，导入旧 best 后重新验证。
