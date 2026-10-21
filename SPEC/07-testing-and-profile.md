# 07 候选、测试与 Profile

> 上层：[06-communication-and-orchestration.md](06-communication-and-orchestration.md)  
> 下层：[08-persistence-and-events.md](08-persistence-and-events.md)

---

## 1. 目标

- 每个候选算子都有不可变源码快照。
- 每次测试/profile 产出完整 TestRecord zip；未执行的候选在收敛前追加明确未执行的审计 zip。
- tester/profiler 的行为由用户 skill 定义；首版 tester 用 CANN 仿真。
- 硬件访问通过共享队列与独占租约。
- 最终只突出最优算子与探索报告，但所有候选记录保留。

---

## 2. 候选版本

```python
@dataclass(frozen=True)
class CandidateVersion:
    id: CandidateId
    cluster_id: ClusterId
    parent_id: CandidateId | None
    direction_id: DirectionId
    author_agent_id: AgentId | None # IMPORT 作者为 system
    author_principal: Principal
    task_id: TaskId | None
    import_id: str | None
    source: SourceRevision          # 不可变源码快照
    diff_artifact: ArtifactRef      # 与 parent 的 diff
    # 验证状态与 best 单独投影/存储，不作为源码实体状态
    created_at: Timestamp
```

规则：

- 候选源码不可变；optimizer 每次提交新 ID。
- `parent_id` 形成无环版本图；GENERATE/IMPORT 根候选 parent 为 null，修复产生后代；首个完整验证通过的 baseline 不一定是根。
- diff 必须对应 parent 与当前源码；根候选对空工程生成新增文件 diff，不伪造 parent。
- 候选必须记录方向、作者、任务来源。
- 修改候选 = 新候选；不允许原地更新。

---

## 3. TestRecord

### 3.1 索引字段

| 字段 | 说明 |
| --- | --- |
| `id` | TestRecordId |
| `cluster_id` / `candidate_id` / `task_id` | 执行关联；Control 未执行审计允许 task_id 为空并使用 audit_id |
| `kind` | TEST / PROFILE |
| `skill` | `SkillRef`（name/version/digest） |
| `backend` | `cann-simulation` / `npu` / 自定义 |
| `outcome` | PASS / FAIL / ERROR / CANCELLED / UNKNOWN |
| `metrics` | 粗结果/详细指标 |
| `environment` | 设备、CANN、Python、工具版本 |
| `artifact` | zip 的 ArtifactRef |
| `created_at` | |

### 3.2 zip 内容（必须尽量丰富）

```text
<record_id>.zip
├── manifest.json              # schema/id/关联/哈希/时间/角色/模型
├── README.md                  # 人类可读摘要
├── task.json                  # mentor 下发的原始任务
├── context.json               # TaskContext 快照/摘要及反馈引用
├── operator-spec.json         # 固定语义、reference、用例、评价策略引用
├── candidate/
│   ├── source/                # 候选完整源码
│   ├── diff.patch             # 相对 parent
│   └── source.sha256
├── skill/
│   ├── SKILL.md               # 使用的用户/内置 skill
│   ├── metadata.json          # name/version/backend/allowed_tools
│   └── scripts/               # 可选脚本原文
├── cases.json                 # 输入/用例定义
├── config.json                # backend/设备/超时/参数
├── environment.json           # OS/CANN/驱动/Python/PyTorch/工具/设备
├── commands.log               # 实际命令（脱敏）
├── stdout.log
├── stderr.log
├── results.json               # 逐 case 结果/精度/错误
├── metrics.json               # 性能/耗时/cycles
├── profile/                   # profiler 原始/汇总（可选）
├── checksums.sha256           # 每个文件哈希
└── provenance.json            # agent/task/mentor/skill/queue lease
```

`manifest.json` 至少包含：

```json
{
  "schema": "justkernel.test_record.v1",
  "record_id": "...",
  "cluster_id": "...",
  "candidate_id": "...",
  "parent_candidate_id": "...",
  "task_id": "...",
  "job_id": "...",
  "audit_id": null,
  "mentor_id": "...",
  "worker_id": "...",
  "kind": "TEST",
  "skill": {"name": "...", "version": "1", "digest": "..."},
  "backend": "cann-simulation",
  "outcome": "PASS",
  "executed": true,
  "coverage": "FULL",
  "operator_spec_digest": "...",
  "case_pack_digest": "...",
  "reference_digest": "...",
  "accuracy_policy_digest": "...",
  "evaluation_policy_digest": "...",
  "environment_fingerprint": "...",
  "measurement_protocol_digest": "...",
  "source_digest": "...",
  "created_at": 0,
  "environment": {"target_soc": "Ascend910B4", "cann": "9.0.0"},
  "files": {"candidate/source/...": "sha256"}
}
```

规则：

- zip 创建后不可修改；重复执行产生新 record，不覆盖旧 zip。
- `checksums.sha256` 覆盖 zip 内除它自身以外的全部文件（避免自引用哈希）；zip 本身摘要存入制品库/DB。manifest.files 不包含 manifest 自身和 checksums 文件，由 checksums 覆盖 manifest。
- 缺失必需文件 → 记录无效，不得成为测试通过证据。未执行记录仍保留必需文件，命令/结果明确为未执行，outcome=CANCELLED/UNKNOWN、executed=false，指标为空且注明原因。
- 日志/命令脱敏；不包含密钥、绝对私有路径。
- 大文件（profile/trace）可外部引用，但 manifest 记录哈希/引用。
- 未执行审计的 task.json/context.json/config/environment 文件必须标注未派任务、未执行及已知的计划配置，未知值为空；不编造命令或实际环境。

---

## 4. Tester / Profiler Skills

### 4.1 加载

- Deep Agents `skills` 参数加载目录中的 `SKILL.md`。
- tester：基础 skill + 内置 CANN simulation + 用户 skill；后者覆盖同名。
- profiler：基础 skill + 内置 CANN profiler + 用户 skill。
- 用户 skill 放在 `skills/user/tester/`、`skills/user/profiler/`；每个 skill 一个目录。

### 4.2 最小接口

每个 tester/profiler skill 必须声明：

| 项 | 示例 |
| --- | --- |
| `name` | `my-npu-tester` |
| `description` | 何时使用、测什么 |
| `metadata.role` | `tester` / `profiler` |
| `metadata.backend` | `npu` / `cann-simulation` / 已注册后端 |
| `metadata.version` | 版本号 |
| `allowed_tools` | `read_candidate`, `submit_test`, `read_tool_job`, `read_test_record` |
| 输入 | task_id、candidate_id、skill_ref、case_selection、budget、device |
| 工作流 | 调哪些工具、顺序、重试 |
| 输出 | outcome/metrics/zip |
| 失败 | 编译/精度/设备/超时如何报告 |
| 限制 | 覆盖/仿真 vs 真机/未知项 |

平台不要求用户写 Python；skill 是 Markdown 指令 + 可选脚本。实际执行由 `submit_test`/`submit_profile` 后端完成。

### 4.3 首版内置

| Skill | 后端 | 说明 |
| --- | --- | --- |
| `tester-cann-simulation` | `cann-simulation` | 编译 + 功能仿真，返回粗性能 |
| `profiler-cann` | `cann-profiler` | 代表点详细采集 |

后续接真机：新增 `tester-npu`/`profiler-npu` skill 与后端，规则不变。

---

## 5. 测试结果

### 5.1 TEST（tester）

- 目标：快速判断候选是否正确、是否值得继续。
- 输出：
  - `outcome`：PASS/FAIL/ERROR/CANCELLED；
  - 逐 case 正确性/误差；
  - 粗略耗时/cycles；
  - 编译/运行日志；
  - 失败阶段。
- 结果不宣称最终性能；tester 是筛选器。

### 5.2 PROFILE（profiler）

- 目标：对代表 case 做详细性能分析。
- 输出：
  - 逐 case 详细耗时/cycles/热点；
  - 原始/汇总 profile 文件；
  - 与同一 EvaluationPolicy 和环境下的父候选/基线比较；
  - 环境/版本。
- profile 结果绑定候选；不能复用旧候选数据。

### 5.3 指标

```python
Metric = {"name": str, "value": float, "unit": str, "direction": "min"|"max"}
```

- `value` 必须有限；缺失为 null，不补 0。
- 本地仿真/真机/官方指标分开命名，不换算。
- 最优比较先校验完整正确性/约束，再按启动时冻结的 EvaluationPolicy 确定性聚合与回归阈值比较；supervisor 不得事后更改计时/评分规则。

---

## 6. 硬件队列与租约

```text
enqueue(task_id, device?, purpose) -> queue_position
acquire(task_id, device, ttl_s) -> lease_id
release(lease_id)
status(device?) -> {queued, leased, owner, expires_at}
```

规则：

- 同一设备同时最多一个 `LEASED`。
- 租约 TTL；超时标记 EXPIRED，先核对/停止原执行；未确认停止前设备隔离，不能直接交给下一任务。重排须新 Task。
- tester/profiler 都可见队列状态；不能看到彼此 task 内容。
- worker 关闭/崩溃时由工具服务核对实际 job；确认执行已停止或服务接管后安全清理租约，不能只看 Agent 状态解锁设备。
- 等待队列时间不计入执行/测试指标。
- 设备 ID、CANN/Python/驱动版本写入 TestRecord environment。

---

## 7. 最优候选

Supervisor 选择 best 时：

1. 候选必须有当前完整用例集下实际执行 PASS 的 TEST TestRecord，且满足冻结的 reference/精度契约。
2. 若集群有性能目标，必须有对应 PROFILE TestRecord。
3. 满足约束（正确性/精度/内存/编译）。
4. 由 supervisor 显式 `select_best` 创建 PENDING BestSelection，记录理由和 policy/记录引用；尚不更新 cluster.best_candidate_id。
5. 通过指定 mentor 派发最终验证任务：
   - 完整测试（不是子集）；
   - 必要时最终 profile；
   - 重新确认源码摘要。
6. 最终验证通过 → selection=VALIDATED，更新 best；失败 → selection=FAILED，保留旧有效选择，继续探索或停止。

**禁止**：

- 用模型自述替代 TestRecord。
- 用子集测试冒充完整验证。
- 用旧候选/旧 skill 的记录证明新候选。
- 删除失败候选的记录。

---

## 8. 保留与交付

| 数据 | 保留 |
| --- | --- |
| 每个候选源码快照 | 保留 |
| 每个候选 TestRecord zip | 保留（默认永久/按策略归档） |
| 失败/取消任务记录 | 保留摘要与日志 |
| 最优算子 | 高亮交付 |
| 探索报告 | 最终交付 |
| 原始 trace/profile 大文件 | 可按策略裁剪，但保留摘要/哈希 |

最终交付：

```text
best/
├── source/                # 最优算子源码
├── manifest.json          # 源码/记录/哈希
├── final-test-record.zip  # 最终验证记录
└── README.md
report/
├── exploration-report.md  # 方向/分支/候选/失败/结论
├── candidates.json        # 版本图与指标
└── records.json           # 所有 TestRecord 索引/哈希
```

所有候选的 TestRecord 仍保留在制品库；报告引用它们。

---

## 9. 可选最终验收

如果用户配置了官方/外部评测，可作为**最终验收 skill/backend**，但：

- 不进入核心探索循环；
- 不改变 cluster supervision；
- 结果作为额外 TestRecord；
- 必须保留原始回执/错误，不伪造分数。

---

## 10. 完成定义

- [ ] 候选不可变、版本图无环。
- [ ] 每个候选至少一个 TestRecord；zip 含必需文件。
- [ ] tester/profiler skill 可加载/替换；内置 CANN 可用。
- [ ] 硬件队列独占租约/超时释放。
- [ ] best 选择有记录、最终验证、可追溯。
- [ ] 所有候选记录保留；最终输出 best + report。

## 11. 基线、异步作业与重复测量

- GENERATE 与 IMPORT 的源码均须完整 TEST；只有当前 OperatorSpec/用例/精度契约下实际执行 PASS 才建立 baseline。
- submit_test/submit_profile 统一异步返回 ToolJobRef；ToolJob 与领域 Task 分离，每 Task 一个作业/终态记录，见 [13 章第 5 节](13-generation-and-iteration-contract.md#5-异步测试与任务终态)。
- 记录新增 operator_spec_digest、case_pack_digest、reference_digest、accuracy_policy_digest、evaluation_policy_digest、coverage（FULL/SUBSET）、executed、job_id、environment_fingerprint、measurement_protocol_digest；TEST/PROFILE 指标保留逐 case 与聚合来源。
- 同一候选允许新 Task 重测；所有记录追加，不能用新环境结果覆盖旧环境。完整结果、子集筛选和未执行审计记录分别展示。
- 首轮编译/正确性错误和 profile 热点必须可摘录到下轮 TaskContext；反馈保留原始记录引用，optimizer 不能改变 oracle/测试包。
- 无性能目标可只做完整 TEST 最终验证；有性能目标必须有 policy 指定后端的可比 PROFILE。仿真结果不得证明真机加速。
- 未执行候选的审计 zip 由 Control 追加，task_id/job_id=null、audit_id 去重、author=system、coverage=NONE，skill 标注计划使用而未执行；不创建虚假 Task、不调用模型或申请设备，不能标记为 PASS。规则见 13 章第 6 节。
