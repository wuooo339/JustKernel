# 13 从零生成与持续迭代执行契约

> 关联：[04 领域模型](04-domain-model.md)、[05 运行时](05-agent-runtime-and-skills.md)、[06 编排](06-communication-and-orchestration.md)、[07 测试](07-testing-and-profile.md)、[08 存储](08-persistence-and-events.md)。
> 本章定义输入、生成、反馈、唤醒和恢复的统一契约；其他章节引用这些类型，不得另建不兼容定义。

---

## 1. 启动输入与可信参考

启动必须提交不可变 `OperatorSpec`，按规范 JSON 计算摘要；`OperatorRef = {operator_id, version, digest, artifact_ref}`。

| 字段 | 必须定义的内容 |
| --- | --- |
| `semantics` | 数学语义、输入输出签名、标量参数、原地修改/别名约束、异常及边界行为 |
| `input_contract` | shape 取值范围/关系、dtype、布局/stride、动态维度、合法值域、空张量等边界 |
| `reference` | 用户提供或明确确认的可执行正确性参考及摘要；不可执行时须有可由后端校验的完整 oracle；记录来源与版本 |
| `accuracy_policy` | 逐输出 dtype 的 atol/rtol、NaN/Inf 处理、比较算法；禁止优化时放宽 |
| `case_pack` | 用例定义/生成器、随机种子、覆盖标签、完整用例集摘要；子集须引用完整集及选取规则 |
| `target` | SoC、语言/接口 ABI、CANN/编译器、构建/运行入口、内存及工程限制 |
| `engineering_policy` | 可修改路径、禁止行为、参考/测试文件只读、允许模板及模板摘要 |
| `evaluation_policy` | 正确性门槛、性能目标是否启用、比较环境、计时/聚合/回归规则，见第 7 节 |

启动请求另含 `start_mode: GENERATE | IMPORT`、`baseline_source_ref?`、tester skill、设备、模型路由、预算；启用性能目标时还必须提供 profiler skill。只有 IMPORT 必须提供源码。GENERATE 不要求用户提供 kernel 源码或初始工程。

- 缺少语义、合法输入范围、可校验 reference/oracle、精度策略或可运行后端时，启动前返回 `operator_spec.incomplete`；模型不得猜测这些事实。
- 参考实现与测试包由用户提供或确认，由 Control 固化为只读制品；optimizer 可按任务读取公开参考，但不能修改 oracle、测试或指标规则。
- GENERATE 可以从已注册模板构建，也可以按 `target` 创建工程；模板不是预先验证的 baseline。
- `OperatorSpec`、用例或精度策略变化必须新版本、新集群；禁止让不同验证契约的结果混入同一比较。

## 2. 从零生成与基线建立

Cluster `state` 仍为 INITIALIZING/RUNNING/PAUSED/CONVERGING/COMPLETED/STOPPED/FAILED；另设 `phase: BOOTSTRAPPING | OPTIMIZING | FINALIZING`，不把生成阶段混成新的运行状态。

```text
校验 OperatorSpec → 全局注册活动集群 → 创建 supervisor/mentor 等角色
→ RUNNING + BOOTSTRAPPING
→ supervisor 发布建立基线的 direction
→ mentor 下发 GENERATE（或 IMPORT 时由 Control 固化用户源码）
→ 初始候选 → tester 编译、执行完整正确性测试
→ 失败：反馈包 → optimizer 用 OPTIMIZE 修复 → 新候选 → 再测试
→ 首个完整正确性 PASS 的候选获认定为 baseline
→ OPTIMIZING → 多方向优化、测试、profile、反馈循环
```

- `GENERATE` 由 optimizer 执行，`candidate_id = null`，输入 OperatorSpec、模板引用和工程约束；输出完整工程快照、构建入口与说明，生成候选 `parent_id = null`。
- `IMPORT` 由 Control 创建根候选，作者为 `system`，记录 import ID；绑定 supervisor 分配给 mentor 的基线建立 direction。不能因为用户提供就标记 PASS。
- 编译/测试始终由 tester 和工具服务执行；optimizer 不直接测试。修复任务必须引用失败候选作为 parent。
- `baseline_candidate_id` 初始为空；Control 只在当前完整 case pack、reference、精度策略下的有效 TEST PASS 后设置一次，发出 `baseline.established`，唤醒 supervisor 调度优化方向。
- 有性能目标时，还须采集同一比较环境下的 baseline PROFILE，才能比较加速或认定性能目标达成；正确性基线和性能参考分别留痕。
- `max_bootstrap_attempts` 计数 GENERATE/修复/导入候选的完整验证尝试；耗尽且无合格基线时 STOPPED，原因 `baseline_not_established`，生成失败报告，不伪造 baseline/best。
- 若生成任务在提交候选前失败，保存 Task 失败与日志即可；没有候选时不生成虚假 TestRecord。

## 3. 任务输入与反馈包

任务种类统一为 `GENERATE | OPTIMIZE | TEST | PROFILE`。所有 Task 固化 `operator_spec_ref`、`direction_id`、`context_ref`、`context_digest`、`retry_of_task_id?`、`budget_ref`；上下文快照不可修改。

`TaskContext` 必须包含以下字段；不适用的列表为空，并给出原因，不得填造数据：

| 字段 | 内容 |
| --- | --- |
| `operator_spec_ref` | 当前版本输入契约、参考和工程限制 |
| `base_candidate_ref` | 源码摘要/制品；仅 GENERATE 为空 |
| `objective` / `acceptance` | 方向、具体假设、通过条件与不得回归项 |
| `feedback` | TestRecord/失败任务引用、源码摘要、skill/用例/环境摘要、失败阶段、失败 case、期望/实际值或误差、脱敏日志、profile 热点 |
| `history` | 已尝试候选/源码摘要、假设、实际结果、否决原因、已知限制及避免重复事项 |
| `shared_evidence` | mentor 从 board 选择的可复用结论及原始证据引用；不包含他人私有通道 |
| `resource_grants` | 本任务获授权的源码、参考、记录/日志摘录制品、有效期和只读范围 |
| `budget` | 时长、token/费用、生成尝试、工具/设备配额及剩余额度 |

- mentor 负责选择反馈，应用层验证摘要、候选绑定与资源授权；大日志以授权制品/片段提供，截断须标记并保留原始引用。
- optimizer 可通过 `read_task_context`、`read_task_artifact` 读取被授权的反馈快照，不因此获得 `read_test_record` 或 board/他人 channel 权限。
- 任意 mentor 可只读同集群已发布到 MentorBoard 的候选和证据；它可以在自己 direction 中派生新候选，并给直属 worker 发放任务级只读授权。未发布的候选和私有数据不跨 mentor 开放。
- 关闭旧 worker 不会删除上下文/反馈；新 worker 必须能仅靠任务快照继续，禁止依赖旧会话记忆。
- 失败结果、未知指标和模型推测必须区分；每条测量结论引用有效记录。编译失败可以作为修复反馈，不能视为精度 FAIL 或性能测量。

## 4. 唤醒、消息消费与下一轮

Control 的持久化调度器负责唤醒；Agent 不通过无限轮询 board 驱动循环。唤醒是运行时调度，不改变分层通信 ACL。

| 触发 | 唤醒对象 | 输入与下一步 |
| --- | --- | --- |
| `cluster.started` | supervisor | 发布基线/探索 direction |
| `direction.assigned/updated` | 所属 mentor | 读取授权 direction，派发任务 |
| `task.assigned` | 直属 worker | 固化 TaskContext，执行本角色任务 |
| `candidate.committed`、任务终态 | 所属 mentor | 同因事件合并；决定测试、修复、profile 或分支淘汰 |
| `test_record.created` | 所属 mentor；对应 tester/profiler 的结果通知 | mentor 形成反馈包，正确性失败则修复，正确性通过且有性能目标则 profile |
| `baseline.established`、`consultant.brief`、有效阶段摘要 | supervisor | 分配/调整方向或收敛；不得直接派发 worker |
| 新的有效 MentorBoard 摘要/证据 | consultants；确有新增信息的 mentors | 汇总/学习；consultant brief 只投 supervisor |
| 汇总定时器 | 有未汇总增量的 consultants/supervisor | 按已消费 cursor 汇总；无增量不调用模型 |
| `budget.exhausted`、`direction.plateau` | supervisor 和受影响 mentor | 停止新探索，按剩余最终验证预算收敛或停止 |

执行规则：

1. 每个事件到目标 Agent 的 inbox 行唯一键为 `(agent_id, event_id)`；不可通过构造新 delivery ID 绕过去重。Worker 仅接收自己的任务通知。
2. `WakeRequest` 固化 `wake_id, agent_id, reason, event_ids, expected_agent_version, not_before`；消息及 wake 通过同一领域事务的 outbox 派送。
3. 同一 Agent 只运行一个 Turn。RUNNING 时新增通知持久化 pending；Turn 完成后按事件序号合并，原子领取下一批，禁止并发唤醒。
4. `wake_debounce_ms` 合并短期通知；已消费 cursor 与 Turn 完成结果事务提交。模型内部 HTTP 重试不新建业务任务；失败 Turn 的唤醒标记失败并通知负责人，不能无限重跑。
5. board 摘要必须包含新增证据/假设或明确决策及其引用；相同摘要摘要值去重。自发帖、已见引用、无增量摘要不得形成自唤醒或 consultant↔supervisor 回声循环。
6. 每次 mentor Turn 必须提交下一步 `ASSIGN | WAIT | COMPLETE_DIRECTION | REQUEST_PIVOT | STOP` 之一。WAIT 必须有等待事件/资源和 deadline；到期唤醒一次并记录原因。
7. 每次 supervisor Turn 必须提交 `CONTINUE | PIVOT | CONVERGE | PAUSE | STOP` 之一，并声明待处理方向/等待条件。不得仅输出文字而丢失后续调度。
8. watchdog 检查 RUNNING 集群：无运行/排队任务、无 pending wake、无有效 WAIT 时，发出 `cluster.stalled`，一次性唤醒 supervisor；重复无有效动作则 PAUSED 并提示人工处理。
9. PAUSED/CONVERGING/终态集群拒绝普通探索 wake；CONVERGING 仅接纳已登记的最终验证/报告工作；PAUSED 保留待处理通知，恢复后再领取。停止前排空或取消通知与任务。

## 5. 异步测试与任务终态

```python
submit_test(task_id, candidate_id, skill_ref, case_selection, timeout_s, device=None) -> ToolJobRef
submit_profile(task_id, candidate_id, skill_ref, case_selection, timeout_s, device=None) -> ToolJobRef
read_tool_job(job_id) -> ToolJobView
read_test_record(record_id) -> TestRecordView
```

- `ToolJobRef = {job_id, task_id, state}`；`ToolJobView` 另含 `record_id?, error?, queue_position?`。调用方必须为该 Task 的直属 tester/profiler，参数必须匹配任务，skill 用版本和摘要固定。
- `ToolJob` 是 TEST/PROFILE Task 的执行作业，不是另一个领域 Task；每 Task 至多一个 job 和一个终态记录。提交幂等键为 task_id，重复提交返回同一 job；参数冲突拒绝。
- job 状态为 `QUEUED → RUNNING → SUCCEEDED | FAILED | CANCELLED | INTERRUPTED`；排队有 queue timeout，执行 timeout 从取得租约后开始。
- submit 立即返回；排队/执行期间 worker 进入 WAIT，不持续消耗模型调用。结果由系统事件通知，按需唤醒新的结果整理 Turn，不重跑 submit。
- 有效 TestRecord 持久化后，Control 在同一集群事务封存 job、Task 结果并创建 mentor 通知。Task `SUCCEEDED` 表示记录执行与交付完成，记录 `outcome=FAIL/ERROR` 仍表示候选未通过；不把二者混用。
- 无有效记录的执行故障使 job/Task FAILED；取消和中断按各自状态封存。工具能正常归档失败日志时仍产出 FAIL/ERROR/CANCELLED/UNKNOWN 记录；无法归档必须保留可追踪故障，不能伪造 zip。
- 已封存的 Task/job 终态不可覆盖；恢复后收到旧执行的迟到结果可追加绑定原 task/job 的记录，并标记 late_completion，保留 INTERRUPTED 终态；不得自动用它建立基线或选 best，须由恢复后的 mentor 核对后重新安排验证。
- job 完成即释放设备资源，不等待模型解读；结果整理 Turn 不得改变已封存 Task。Agent Turn 晚到失败不覆盖已经完成的 job/Task。
- 重测或重试执行必须新 TaskId 和新 JobId，关联 retry_of；旧 Task/记录不覆盖。

## 6. 候选、证据与最终选择

- CandidateVersion 是提交即不可变的源码实体；不再把 TESTED/PROFILED/BEST 作为源码状态机。未提交编辑内容属于 workspace，不是候选。
- `CandidateEvaluationView` 是可重建读模型：当前契约下最新完整 TEST 的 `UNTESTED | TESTING | PASS | FAIL | ERROR | CANCELLED | UNKNOWN`，附 TEST/PROFILE 记录列表和正在进行的 job；子集 PASS 不升级为完整 PASS。
- 同一候选允许多次测试/profile；新记录追加，历史保留，按环境/skill/用例集分组。不能用其他环境下的新记录覆盖比较用记录。
- `BestSelection` 独立记录 `PENDING → VALIDATED | FAILED`，绑定候选、evaluation policy 摘要、提名证据和最终验证任务/记录。
- supervisor 通过 `select_best` 提名；Control 校验完整 TEST PASS，性能目标启用时还须有可比 PROFILE。最终验证由 supervisor 指定的 mentor 派发 tester/profiler，不允许越级指挥。
- 只有最终完整 TEST PASS、必要 PROFILE 合格且摘要一致，才把选择设为 VALIDATED 并更新 cluster.best_candidate_id；失败保留旧有效选择，返回 RUNNING 或 STOPPED。
- 没有性能目标时不要求 PROFILE；性能目标仅能使用 evaluation_policy 指定后端的证据，仿真指标不能证明真机加速。
- 每个已提交候选必须安排 TEST；在收敛前未执行的候选由 Control 生成 `kind=TEST, outcome=CANCELLED/UNKNOWN` 的未执行记录及 zip，明确 `executed=false` 和原因，不伪造命令/数值。这类记录只供审计，不能建立 baseline 或成为 best。未执行审计记录可不关联 Task：task_id/job_id=null，使用稳定 audit_id 去重，provenance.author=system，coverage=NONE，明确 planned_skill 与未执行原因；它不创建虚假 worker/任务。磁盘等故障导致记录不全时阻止 COMPLETED，恢复后追加审计记录，不能改写旧 Task。
- STOPPED/FAILED 没有 best 时仍可生成失败探索报告，best_candidate_id 允许为空；COMPLETED 必须有 VALIDATED best 和最终报告。

## 7. 可比较指标、重复搜索与预算

`EvaluationPolicy` 在启动时冻结：完整 case pack/reference/accuracy 摘要、允许后端与环境指纹、计时单位、warmup/repeats、聚合公式及参数、逐 case 回归上限、`min_improvement`、最终验证要求。聚合公式必须为已注册确定性函数；缺失指标为未知，不得补零。

- 比较前由程序校验候选正确性、用例覆盖、环境、skill 及测量协议；不满足则 `INCOMPARABLE`，触发补测。跨环境不计算加速比，不从仿真 cycles 换算真机时间。
- plateau 使用连续 `plateau_rounds` 个有可比测量且无超过 min_improvement 的完整探索周期；工具故障不当作性能无收益。`round` 指一个 direction 的优化任务产生候选并得到所需 TEST/PROFILE 后的决策周期，预算账本按已封存周期计数；集群 max_rounds 约束所有 direction 的周期总和，不是每个方向各自重新计额。
- 提交相同源码可保留不同候选的 provenance，但发出 `candidate.duplicate` 并默认不再自动实验；跨契约/环境不得复用通过结论。确需重测由 mentor 明确说明原因，新 Task/记录保留。
- `BudgetPolicy` 定义集群总时长、模型 token/费用、工具/设备执行时间、max_rounds、max_bootstrap_attempts、plateau_rounds、max_consecutive_failures；总时长、模型 token/费用、工具/设备时间或集群总轮次中至少一个可执行全局硬上限不得为空，仅 bootstrap/plateau 上限不算全局硬上限。
- 调用前按最坏允许消耗预留额度，调用后结算；无法获取模型实际费用时按配置价格保守结算并标注估算，不能把未知当零。达到限额后禁止新探索。
- 单列最终验证预算 `final_validation_reserve`，探索不能占用；不足以最终验证则 STOPPED，不能绕过验证直接 COMPLETED。

## 8. 中断恢复与新一轮研究

- Agent 新增 INTERRUPTED：RUNNING → INTERRUPTED；经显式恢复新 session 后 INTERRUPTED → IDLE，或关闭。Task 的 ASSIGNED/RUNNING → INTERRUPTED 为终态，只能用新 Task 重派。
- Control 崩溃后集群进入 PAUSED，保留原 phase；不得把 INTERRUPTED 当作 Cluster 状态。暂停期间到达的完整结果先幂等归档，不启动探索。
- 工具服务先核对 job、实际子进程、有效租约和已落盘制品；只有确认旧执行已停止或由服务接管后才能释放设备并重派。TTL 过期本身不能证明物理执行已经停止；无法确认则设备隔离。
- `/clusters/{id}/resume` 为人工显式恢复：核对结果/租约/预算 → 修复或封存中断任务 → supervisor 新 session → RUNNING → 投递一次 RecoverySummary 唤醒 supervisor；再由 supervisor 唤醒 mentor，新 Task 引用旧失败任务和反馈包。
- 消息/outbox 重投与 job 接收同一结果属于幂等投递，不等于自动重跑模型/外部测试。系统不得自行重放中断 Turn 或重新执行旧 Task。
- COMPLETED/STOPPED/FAILED 不回到 RUNNING；继续研究使用新 Cluster，`continued_from_cluster_id` 指向旧集群。旧 best 经授权只读导入为新根候选并重新验证；原始产物仍保留，跨集群不共享活动 board。

## 9. 多模型路由

- 每个 Agent 独立 ModelProfile；默认优先级为 `实例显式指定 > direction/任务策略 > RoleConfig > 系统默认`，最终选择在创建 Agent 时固化。
- task 策略与现有 worker 绑定模型不同时，mentor 新建 worker，不在进行中的 Turn 内静默换模型。supervisor/mentor 的换模由 Control 建新 session 并保留原历史。
- 启动/建 Agent 前验证所需工具调用、上下文和参数能力；不兼容返回明确错误。provider 级并发、限流、预算独立计算；降级只允许配置的 fallback，并留审计事件。
- 每 Turn 记录 provider、请求模型标识、可得的模型版本、profile/prompt/skill/context 摘要、用量和错误；不可得版本标为 unknown。模型差异不得改变 ACL 或测试标准。

## 10. 必须通过的闭环验收

1. 不提供 baseline 源码，仅提供完整 OperatorSpec，生成工程并建立真实 TEST PASS 基线。
2. 首候选编译/精度失败 → 关闭旧 optimizer → 新 optimizer 仅凭 TaskContext 修复 → 新候选通过；测试包/reference 摘要不变。
3. PROFILE 反馈 → 新 worker 改进 → 可比测量超过阈值；有逐 case 回归时按策略拒绝。
4. 同一结果重复投递/同一 Agent RUNNING 时收到多事件，只产生一次必要的后续任务，无重复副作用、无回声循环。
5. 无任务无 wake 时 watchdog 能发现停滞；合法 WAIT 不被误报；无增量定时器不调用模型。
6. 无性能目标时仅完整 TEST 即可最终验证；有性能目标而缺 PROFILE 时拒绝最终选择。
7. 崩溃时 job 仍可能占设备；未确认停止前不能发新租约；显式 resume 后用新 Task 续跑。
8. 同算子跨目录重复启动被全局注册拒绝；不同算子集群争同一设备仍仅一个有效执行租约。
9. bootstrap 预算耗尽输出无 best 的失败报告；已有合格候选时按独立预算完成最终验证。
10. 两个角色/同角色不同实例绑定不同模型，路由可追踪；换模不丢反馈，越权仍被拒绝。
