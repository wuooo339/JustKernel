# 11 测试与质量门禁

> 上层：[10-configuration-security-observability.md](10-configuration-security-observability.md)  
> 下层：[12-migration-and-acceptance.md](12-migration-and-acceptance.md)

---

## 1. 原则

- 领域/应用测试不启动真实模型、设备、HTTP。
- ACL、任务归属、租约、记录完整性必须自动化测试。
- 测试行为与不变量，不测试私有实现。
- 确定性：FakeClock/FakeIds；禁止 sleep 等待。
- 模型/skill/测试记录使用合成夹具，不包含真实密钥/成绩。

---

## 2. 测试分层

| 层 | 目录 | 目标 |
| --- | --- | --- |
| 领域 | `tests/unit` | 状态机、ACL、候选图、租约、记录不变量 |
| 应用 | `tests/application` | 用例：开/关 worker、task、测试、收敛 |
| 适配器 | `tests/adapters` | SQLite、制品、消息总线、agent runtime、tool backend |
| 集成 | `tests/integration` | control + fake runtime + fake hardware + HTTP/SSE |
| 架构 | `tests/architecture` | 依赖/无副作用/文件规模 |
| 前端 | `tests/web` | reducer/selectors/format |
| 端到端 | `tests/e2e` | demo/回放/一条完整假集群流程 |

---

## 3. 必须优先覆盖的失败模式

1. **worker 读到 board** → 工具不存在 + ACL 拒绝 + 审计。
2. **consultant 写 mentor board** → 只读接口 + 拒绝。
3. **mentor 给别人的 worker 下 task** → 归属校验失败。
4. **worker 关闭后仍接 task / 租约未释放** → 状态/租约测试。
5. **同一设备两个 lease** → 部分唯一索引/队列测试。
6. **候选没有 TestRecord 却成为 best** → 收敛门槛拒绝。
7. **测试记录 zip 缺文件/哈希不匹配** → 记录无效。
8. **agent 数量超过 100** → open_worker 拒绝；无孤儿。
9. **control 崩溃后重复 task/测试/消息** → 恢复 + 幂等。
10. **用户 skill 越权调用工具** → allowed_tools 子集 + 应用校验。
11. **mentor 跨 direction 抢占** → direction 所有权校验。
12. **best 引用旧候选/旧 skill 记录** → 绑定校验。

---

## 4. 领域测试

- Cluster：唯一 supervisor；RUNNING 条件；COMPLETED 需要 best+report。
- Agent：worker 必有 mentor；worker 不能有下级；关闭后不能接 task；总数上限。
- Direction：一个 mentor 一个 ACTIVE；只有 supervisor 能改。
- Task：只能直属 mentor 下发；worker 同时一个 task；终态不可变。
- Candidate：源码不可变、parent 图无环；完整验证读模型与 BestSelection 独立，允许同候选多次 TEST/PROFILE。
- TestRecord：必需字段/哈希；task 唯一终态；不可修改。
- HardwareLease：每设备一个 LEASED；TTL/释放。
- ACL：表驱动测试每个角色 × 每个资源 × 读/写。

---

## 5. 应用测试

- `CreateCluster`：supervisor/consultants/mentors；超限拒绝。
- `OpenWorker`/`CloseWorker`：归属、上限、任务/租约清理。
- `AssignTask`：kind/skill/candidate 校验；越权拒绝。
- `SubmitTest`/`SubmitProfile`：skill/backend/候选/队列；记录生成。
- `CommitCandidate`：源码不可变；parent/diff。
- `SelectBest`：记录/最终验证/理由。
- `Converge`：关闭 worker/租约/报告。
- 失败：模型错误、工具错误、设备超时、消息重复。

Fakes：InMemoryRepos、FakeMessageBus、FakeAgentRuntime、FakeToolBackend、FakeHardwareQueue、FakeClock/Ids。

---

## 6. 适配器/集成测试

- SQLite：部分唯一索引、事务、事件/投影、恢复。
- 制品库：zip/哈希/路径安全/去重。
- 消息总线：至少一次、重复幂等、ACL。
- Agent runtime：创建/关闭/取消/检查点；worker 工具集无 board。
- Tool backend：CANN 仿真 fake；超时/失败/租约释放。
- HTTP/SSE：DTO、错误码、游标、断线续传。
- A2A：cluster status/message；外部不能写 worker channel。
- 集成流程：

```text
启动集群 → supervisor 方向 → mentor 读 board → 开 optimizer
→ 候选 → 开 tester → fake 测试 → record zip → 发布 board
→ consultant brief → supervisor 收敛 → best + report
```

---

## 7. 崩溃/混沌

| 故障 | 期望 |
| --- | --- |
| control `kill -9` | 重启；agent/task 中断；不自动重跑；board 恢复 |
| agent 崩溃 | task failed；mentor 可重开/重派；租约释放 |
| 关闭 worker 时崩溃 | 租约过期；无孤儿；记录保留 |
| 测试进程崩溃 | 封存失败/中断；不生成假 PASS；确认实际执行停止后再清理全局租约 |
| 设备断开 | lease 过期；设备隔离直到确认旧执行停止；如需重派则新 Task |
| 消息重复 | 幂等；不重复 task/record |
| 磁盘满 | 事务回滚；健康降级；停止新测试 |
| zip 写入中断 | 记录无效；重跑新记录 |

---

## 8. 前端/架构测试

- reducer：seq 幂等/乱序/未知事件；live/replay 一致。
- selectors：候选图、记录关联、角色树、队列。
- 架构：领域不导入 adapter/HTTP/DeepAgents；无模块级副作用；文件规模。
- 前端不直接消费 DB 行/内部路径。

---

## 9. CI 门禁

```text
1. ruff + format + type check
2. unit + application + architecture
3. adapters + integration（fake runtime/tool）
4. web tests
5. demo/e2e 离线
6. build/package（不含密钥/模板受限文件）
```

矩阵：Ubuntu/Windows/macOS；Linux 可选 CANN fake/real worker 测试。真实模型/设备不在 CI。

---

## 10. 覆盖率/门禁

| 范围 | 目标 |
| --- | --- |
| 领域 | 分支 ≥95% |
| 应用 | 分支 ≥90% |
| ACL/队列/记录 | 关键路径 100% |
| 前端 reducer | ≥90% |
| 全局 | ≥80% |

PR 必须：

- 新行为有失败测试；
- ACL/任务归属/记录/租约变更含反例；
- 架构测试通过；
- 无密钥/路径/私有推理泄漏；
- 文档同步。

---

## 11. 完成定义

- [ ] 12 个高风险失败模式全部有测试。
- [ ] ACL 表每个角色/资源组合有测试。
- [ ] worker 工具集静态断言无 board 工具。
- [ ] 测试记录 zip 完整/哈希/不可变。
- [ ] 设备租约唯一/超时/释放测试。
- [ ] 崩溃恢复无重复 task/record/lease。
- [ ] 约 100 agent 上限/关闭/孤儿测试。

## 12. 生成、反馈与调度的新增门禁

必须将 [13 章第 10 节](13-generation-and-iteration-contract.md#10-必须通过的闭环验收) 转成自动化验收，至少覆盖：

- 双入口：GENERATE 无源码创建成功，IMPORT 缺源码拒绝；两模式缺 oracle/输入约束均拒绝；导入源码不得跳过完整验证。
- 生成失败修复：第一次候选失败，关闭旧 optimizer，新 optimizer 读取固化反馈后修复；父子摘要与 readonly reference/case_pack 保持一致。
- 唤醒：重复 event、RUNNING 时新增通知、Turn 完成与消息同到、无增量 timer、WAIT deadline、停滞检测、PAUSED 通知保留；不得重复派实验。
- 异步作业：submit 立即返回 ToolJobRef，同 Task 同参数重复提交同 job、冲突参数拒绝；排队与执行分别超时；Task SUCCEEDED 配记录 FAIL 不误报通过。
- 最终选择：无性能目标允许仅完整 TEST；有性能目标缺 PROFILE/环境不符拒绝；子集 PASS/未执行记录不得建立 baseline/best；失败提名不覆盖旧有效 best。
- 存储：临时制品落盘后崩溃、记录与 job/Task/wake 事务失败、全局占位初始化中断、跨集群设备争抢；镜像不能独立发租约。
- 权限：已发布候选可被另一 mentor 在自己方向派生；worker 只能读取任务授权反馈，不能借 artifact_ref 访问其他通道或未发布源码。
- 恢复：Control 中断后 PAUSED，未封存 Task INTERRUPTED；过期 job 实际仍执行时禁止新租约；显式 resume 新 session/新 Task，旧结果只归档一次。
- 预算：bootstrap 耗尽、plateau、重复候选、硬限额与最终验证保留；无 best 时 STOPPED 报告允许空 best，不能 COMPLETED。
- 多模型：不同角色/同角色实例可选不同 profile，优先级、能力拒绝、provider 限流和显式 fallback 有证据，换模后反馈可续接。

先用 fake runtime/tool 完成确定性验证；上线能力还须至少一次真实模型 + 实际 CANN 后端的 GENERATE → 失败修复 → 基线 → 再优化 → 最终验证。Fake 流程通过不能作为真实算子生成成功的证据。
