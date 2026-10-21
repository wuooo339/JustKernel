# 08 持久化、事件与制品

> 上层：[07-testing-and-profile.md](07-testing-and-profile.md)  
> 下层：[09-api-and-frontend.md](09-api-and-frontend.md)

---

## 1. 原则

- SQLite 保存领域状态与事件；制品库存源码/zip/profile。
- 事件只追加；读模型可重建。
- 消息、任务、租约、记录都有幂等键。
- 禁止用可变 JSON 文件保存 board/task/candidate 等领域状态。
- 多进程共享存储，但只有一个控制面写集群领域事务；全局活动集群注册及设备账本独立仲裁，不能用每集群索引替代。

---

## 2. 数据目录

```text
<data_root>/
├── registry.db                 # Control 全局活动集群注册
├── hardware.db                 # 设备服务全局队列/租约（只允许该服务写）
├── clusters/
│   └── <cluster_id>/
│       ├── journal.db              # SQLite
│       ├── artifacts/              # 内容寻址
│       │   └── sha256/<ab>/<cd>/<digest>
│       ├── checkpoints/            # agent 会话
│       ├── workspaces/             # 候选/工作区快照（只读/临时）
│       ├── exports/                # 报告/导出
│       └── logs/
├── private/                        # 密钥（0700）
└── service.lock
```

- 一个集群一个目录；不同算子不共享 board/候选。
- 工作区可编辑，但候选/记录以快照/制品为准。
- 检查点不是证据，可删/压缩。

---

## 3. SQLite schema（核心）

```sql
CREATE TABLE clusters (
  id TEXT PRIMARY KEY,
  operator_id TEXT NOT NULL,
  supervisor_id TEXT NOT NULL,
  operator_spec_digest TEXT NOT NULL,
  start_mode TEXT NOT NULL CHECK (start_mode IN ('GENERATE','IMPORT')),
  phase TEXT NOT NULL CHECK (phase IN ('BOOTSTRAPPING','OPTIMIZING','FINALIZING')),
  baseline_candidate_id TEXT,
  continued_from_cluster_id TEXT,
  state TEXT NOT NULL,
  max_agents INTEGER NOT NULL,
  best_candidate_id TEXT,
  report_id TEXT,
  created_at INTEGER NOT NULL,
  closed_at INTEGER,
  version INTEGER NOT NULL DEFAULT 0
);

-- 此库只含本集群；跨目录 operator 唯一性由下文 registry.db 保证。
CREATE INDEX cluster_operator ON clusters(operator_id);

CREATE TABLE agents (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL REFERENCES clusters(id),
  role TEXT NOT NULL,
  mentor_id TEXT REFERENCES agents(id),
  model_profile TEXT NOT NULL,
  skills_json TEXT NOT NULL,
  state TEXT NOT NULL,
  session_id TEXT,
  created_at INTEGER NOT NULL,
  closed_at INTEGER,
  version INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX one_supervisor
  ON agents(cluster_id) WHERE role = 'SUPERVISOR' AND state != 'CLOSED';

CREATE TABLE directions (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL REFERENCES clusters(id),
  mentor_id TEXT NOT NULL REFERENCES agents(id),
  objective TEXT NOT NULL,
  constraints_json TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  closed_at INTEGER,
  version INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX one_active_direction
  ON directions(mentor_id) WHERE state IN ('PROPOSED','ACTIVE','PAUSED');

CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL REFERENCES clusters(id),
  mentor_id TEXT NOT NULL REFERENCES agents(id),
  worker_id TEXT NOT NULL REFERENCES agents(id),
  kind TEXT NOT NULL CHECK (kind IN ('GENERATE','OPTIMIZE','TEST','PROFILE')),
  direction_id TEXT NOT NULL REFERENCES directions(id),
  operator_spec_digest TEXT NOT NULL,
  context_artifact TEXT NOT NULL,
  context_digest TEXT NOT NULL,
  retry_of_task_id TEXT REFERENCES tasks(id),
  budget_ref TEXT NOT NULL,
  candidate_id TEXT,
  skill_json TEXT,
  objective TEXT NOT NULL,
  constraints_json TEXT NOT NULL,
  state TEXT NOT NULL,
  result_ref TEXT,
  created_at INTEGER NOT NULL,
  finished_at INTEGER,
  version INTEGER NOT NULL DEFAULT 0,
  CHECK ((kind = 'GENERATE' AND candidate_id IS NULL) OR
         (kind IN ('OPTIMIZE','TEST','PROFILE') AND candidate_id IS NOT NULL)),
  CHECK (kind NOT IN ('TEST','PROFILE') OR skill_json IS NOT NULL)
);

CREATE UNIQUE INDEX one_running_task_per_agent
  ON tasks(worker_id) WHERE state IN ('ASSIGNED','RUNNING');

CREATE TABLE candidates (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL REFERENCES clusters(id),
  parent_id TEXT REFERENCES candidates(id),
  direction_id TEXT NOT NULL REFERENCES directions(id),
  author_agent_id TEXT REFERENCES agents(id),
  author_principal TEXT NOT NULL,
  task_id TEXT REFERENCES tasks(id),
  import_id TEXT,
  source_digest TEXT NOT NULL,
  source_artifact TEXT NOT NULL,
  diff_artifact TEXT,
  evaluation_json TEXT,           -- 可重建投影；不是源码状态
  created_at INTEGER NOT NULL,
  CHECK ((task_id IS NOT NULL AND import_id IS NULL AND author_agent_id IS NOT NULL)
      OR (task_id IS NULL AND import_id IS NOT NULL AND author_agent_id IS NULL AND author_principal = 'system'))
);

CREATE TABLE test_records (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL REFERENCES clusters(id),
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  task_id TEXT REFERENCES tasks(id),
  job_id TEXT,
  audit_id TEXT UNIQUE,
  executed INTEGER NOT NULL CHECK (executed IN (0,1)),
  coverage TEXT NOT NULL CHECK (coverage IN ('FULL','SUBSET','NONE')),
  operator_spec_digest TEXT NOT NULL,
  case_pack_digest TEXT NOT NULL,
  reference_digest TEXT NOT NULL,
  accuracy_policy_digest TEXT NOT NULL,
  evaluation_policy_digest TEXT NOT NULL,
  environment_fingerprint TEXT NOT NULL,
  measurement_protocol_digest TEXT,
  kind TEXT NOT NULL,
  skill_json TEXT NOT NULL,
  backend TEXT NOT NULL,
  outcome TEXT NOT NULL,
  metrics_json TEXT,
  environment_json TEXT NOT NULL,
  artifact TEXT NOT NULL,
  artifact_digest TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  CHECK (outcome != 'PASS' OR (executed = 1 AND coverage IN ('FULL','SUBSET'))),
  CHECK ((task_id IS NOT NULL AND audit_id IS NULL) OR
         (task_id IS NULL AND audit_id IS NOT NULL AND executed = 0
          AND outcome IN ('CANCELLED','UNKNOWN') AND coverage = 'NONE'))
);

-- 集群内仅保存全局租约的投影，不授予执行权。
CREATE TABLE hardware_leases (
  id TEXT PRIMARY KEY,
  device_id TEXT NOT NULL,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  owner_agent_id TEXT NOT NULL REFERENCES agents(id),
  state TEXT NOT NULL,
  acquired_at INTEGER,            -- QUEUED 时未获取
  expires_at INTEGER,
  released_at INTEGER,
  version INTEGER NOT NULL DEFAULT 0
);

-- 本地 hardware_leases 是镜像；跨集群唯一索引在 hardware.db 的 device_leases。

CREATE TABLE board_posts (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  cluster_id TEXT NOT NULL,
  board TEXT NOT NULL,           -- MENTOR / CONSULTANT
  topic TEXT NOT NULL,
  author_agent_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  schema_version INTEGER NOT NULL
);

CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  seq INTEGER NOT NULL,
  type TEXT NOT NULL,
  sender TEXT NOT NULL,
  recipient TEXT,
  correlation_id TEXT,
  causation_id TEXT,
  payload_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  delivered_at INTEGER,
  schema_version INTEGER NOT NULL,
  UNIQUE(channel, seq)
);

CREATE TABLE reports (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  best_candidate_id TEXT,         -- STOPPED/FAILED 可空
  report_artifact TEXT NOT NULL,
  report_digest TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(cluster_id, revision)
);
```

事件/投影/outbox：

```sql
CREATE TABLE events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  cluster_id TEXT NOT NULL,
  type TEXT NOT NULL,
  event_version INTEGER NOT NULL,
  aggregate_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  aggregate_version INTEGER NOT NULL,
  actor TEXT NOT NULL,
  correlation_id TEXT,
  causation_id TEXT,
  payload_json TEXT NOT NULL,
  occurred_at INTEGER NOT NULL
);

CREATE TRIGGER events_no_update
BEFORE UPDATE ON events
BEGIN
  SELECT RAISE(ABORT, 'events are append-only');
END;

CREATE TRIGGER events_no_delete
BEFORE DELETE ON events
BEGIN
  SELECT RAISE(ABORT, 'events are append-only');
END;

CREATE UNIQUE INDEX one_record_per_task ON test_records(task_id) WHERE task_id IS NOT NULL;

CREATE TABLE outbox (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  available_at INTEGER NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE projections (
  name TEXT PRIMARY KEY,
  last_seq INTEGER NOT NULL,
  schema_version INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
```

规则：

- 事件只追加；禁止 UPDATE/DELETE（触发器）。
- `messages.id`/`tasks.id`/`test_records.task_id` 等用于幂等。
- 集群库部分唯一索引保证一个 supervisor、一个未关闭 direction、一个活动 task；跨目录活动集群、设备租约须由全局账本保证。
- 集群领域写事务只由 Control 执行；工具服务写制品并经 Control API 回报结果，禁止独立直接提交领域索引。

---

## 4. 制品库

```text
artifacts/sha256/<digest[0:2]>/<digest[2:4]>/<digest>
```

- 写入：临时文件 → fsync → replace；目录 0700，文件 0600。
- 读取校验 SHA-256/大小；不信任路径。
- 内容寻址去重；zip/source/diff/profile 都可存。
- DB 只存摘要/引用；不存绝对路径。
- 删除只允许未被候选/记录/报告引用的制品；软删除 + 审计。
- 测试记录 zip 默认永久保留；大 profile 可按策略裁剪但保留摘要。

---

## 5. 消息与 Board 持久化

- `messages` 表保存投递记录并新增 seq；Control 按 channel 事务分配，UNIQUE(channel, seq)。`board_posts` 保存 board 追加记录。
- `board_posts.seq` 提供 board 内顺序；`messages` 按 channel 查询。
- 读模型投影：
  - `mentor_board_view`：最新方向/摘要/候选/测试；
  - `cluster_graph`：角色/父子/状态；
  - `candidate_graph`：版本 DAG；
  - `queue_view`：设备队列/租约。
- 投影可从事件重放；重建不触发任务/测试/消息重发。
- 消息至少一次；消费者按 `messages.id` 去重。

---

## 6. 事务边界

| 操作 | 事务 |
| --- | --- |
| 创建 agent/worker | DB 事务 + max_agents 校验 |
| 下发 task | DB 事务 + worker 归属/状态校验 |
| 提交候选 | DB 事务 + 源码制品写 |
| 写 TestRecord | 先原子落盘并校验 zip；再同一集群 DB 事务封存 record、job/Task、事件和唤醒 outbox |
| 获取/释放 lease | DB 事务 + 唯一索引 |
| board post/message | DB 事务 + outbox |
| 收敛/报告 | DB 事务 + 状态/引用校验 |

外部副作用（启动 agent、测试执行、设备锁）及制品文件写入不放入 DB 事务；先落盘制品再事务关联，孤立制品可回收。跨 registry/journal/hardware 用幂等命令/补偿，不承诺跨库原子事务；重试投递不得自动重跑模型或已执行测试。

---

## 7. 恢复

启动时：

| 状态 | 动作 |
| --- | --- |
| Agent RUNNING | 标记 INTERRUPTED；显式恢复创建新 session，不自动重跑 |
| Task ASSIGNED/RUNNING | 先核对已经封存结果；其余 INTERRUPTED 终态；mentor 恢复后以新 Task 重派 |
| Lease LEASED | 核对全局设备账本/物理执行；过期只标 EXPIRED，确认原执行停止后才允许新租约，未知则设备隔离 |
| 消息未投递 | outbox 重试；幂等 |
| TestRecord 写入中 | 校验 zip/索引；不完整则标记失败，不伪造 |
| Cluster RUNNING/CONVERGING | 转 PAUSED、保留 phase；恢复 board/agents，等待用户显式 resume |
| Report 草稿 | 重新生成；不覆盖已终态报告 |

原则：不自动重放模型 Turn；不自动重试外部测试；所有恢复写事件。

---

## 8. 导出与回放

- `justkernel export`：事件、cluster 图、board、任务、候选、TestRecord 索引、报告；可选源码/zip。
- 不包含密钥、私有路径、模型私有推理。
- 回放只读；不启动 agent/测试/设备。
- 实时与回放使用同一读模型/reducer。

---

## 9. 旧数据迁移

- 旧 `JustKernel` lab 的 teams/work-items/candidates/judge 数据导入为 `LEGACY` 历史。
- 不作为新集群的 board/候选；只读展示。
- 旧证据/记录标记 legacy；不能成为新 best。
- 导入器只读旧目录，幂等；不修改旧数据。
- `aworker` 包不迁移；包名统一 `justkernel`。

---

## 10. 完成定义

- [ ] board/message/task/candidate/record 全部持久化，无领域 JSON 状态。
- [ ] 事件只追加；投影可重建。
- [ ] TestRecord zip 内容寻址/哈希校验。
- [ ] 部分唯一索引阻止重复 supervisor/lease/task。
- [ ] 崩溃恢复表逐项实现；无自动重跑。
- [ ] 旧 lab 数据只读导入。
- [ ] 导出/回放不含密钥/私有路径。

## 11. 全局注册与设备仲裁数据库

以下 schema 分别在共享服务唯一持有的数据库执行，不能复制到每个集群后宣称具备全局唯一性。

registry.db（Control 所有）：

```sql
CREATE TABLE cluster_registry (
  cluster_id TEXT PRIMARY KEY,
  operator_id TEXT NOT NULL,
  journal_ref TEXT NOT NULL,
  state TEXT NOT NULL,
  reservation_key TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX one_active_cluster_per_operator
  ON cluster_registry(operator_id)
  WHERE state NOT IN ('COMPLETED','STOPPED','FAILED');
```

- 先原子占位再创建 journal；崩溃遗留占位由恢复器核对初始化进度。不得因锁超时就另起同算子集群。
- journal 终态提交后，通过 outbox 幂等释放 registry；跨库失败可延迟释放但不得提前允许重复启动。

hardware.db（唯一 Tool/Hardware Service 所有）：

```sql
CREATE TABLE device_leases (
  lease_id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  job_id TEXT NOT NULL UNIQUE,
  device_id TEXT NOT NULL,
  state TEXT NOT NULL,
  execution_active INTEGER NOT NULL DEFAULT 0,
  fencing_token INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  UNIQUE(device_id, fencing_token)
);
CREATE UNIQUE INDEX one_lease_per_device
  ON device_leases(device_id)
  WHERE state = 'LEASED' OR execution_active = 1;
```

- 全局队列项还须持久化 cluster/task/job、purpose、排队时间、优先级与去重键；不能依赖任一 Agent 进程的内存队列。
- 设备服务对每 device 单调发放 fencing_token，执行入口核验当前 token；过期回调和旧 token 不得启动新进程或覆盖新结果。
- TTL 过期时仍保留 execution_active，直到确认旧执行停止。服务重启需核对 PID/执行标识，无法确认就隔离设备；只有 execution_active=0 且无有效租约才可重分配。

## 12. 反馈、唤醒、作业和选择的持久化

每集群 journal 追加以下表及约束；字段含义见 13 章：

```sql
CREATE TABLE tool_jobs (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id),
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  request_digest TEXT NOT NULL,
  state TEXT NOT NULL,
  record_id TEXT REFERENCES test_records(id),
  error_json TEXT,
  created_at INTEGER NOT NULL
);
CREATE TABLE agent_inbox (
  agent_id TEXT NOT NULL REFERENCES agents(id),
  event_id TEXT NOT NULL REFERENCES events(event_id),
  event_seq INTEGER NOT NULL,
  state TEXT NOT NULL,
  wake_id TEXT,
  PRIMARY KEY(agent_id, event_id)
);
CREATE TABLE wake_requests (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agents(id),
  reason TEXT NOT NULL,
  event_ids_json TEXT NOT NULL,
  expected_agent_version INTEGER NOT NULL,
  not_before INTEGER NOT NULL,
  state TEXT NOT NULL,
  turn_id TEXT UNIQUE,
  wait_json TEXT
);
CREATE UNIQUE INDEX one_claimed_wake_per_agent
  ON wake_requests(agent_id) WHERE state = 'CLAIMED';
CREATE TABLE best_selections (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL REFERENCES clusters(id),
  candidate_id TEXT NOT NULL REFERENCES candidates(id),
  policy_digest TEXT NOT NULL,
  nomination_record_ids_json TEXT NOT NULL,
  final_task_ids_json TEXT NOT NULL,
  final_record_ids_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('PENDING','VALIDATED','FAILED')),
  reason TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
```

- TaskContext 和 OperatorSpec 以摘要寻址的只读制品存储；对象级授权必须由 task_artifact_grants 保存 task_id、artifact_digest、只读范围及有效期，不能仅凭 Agent 声称拥有授权。
- budget_ledger 保存预留/实际消耗/估算、最终验证专用额度和幂等操作键；evaluation policy、baseline 认定与模型路由均保存摘要及事件。
- 唤醒领取与 Agent 版本比较、Turn 串行检查在事务中执行；完成后持久化消费 cursor，恢复不能丢 pending 通知或重复执行封存任务。
- test_records 的核心 schema 上列字段不可 UPDATE/DELETE；候选源码字段、最终报告与 BestSelection 终态同样通过仓储及触发器禁止改写。报告版本追加，以 UNIQUE(cluster_id, revision) 取代单集群仅一报告限制。
