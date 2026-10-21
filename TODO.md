# JustKernel v2 重构实施 TODO

> 依据：[SPEC v2.1](SPEC/README.md)（2026-10-21）  
> 目标：把旧“多队 lab + Judge/官测”实现替换为“单算子、单 supervisor、约 100 个动态角色的 Agent 集群”。  
> 状态：`P0` 待开始。所有任务只有在有测试/命令证据后才能勾选。  
> 维护规则：每完成一项，在文末“进度记录”登记日期、任务号、证据（命令输出、测试名、PR/commit）。

---

## 0. 总体策略

1. **新包并行，不做旧代码渐进改造**  
   新建 `src/justkernel/`，旧 `src/aworker/` 冻结。新代码禁止 import 旧包；P8 删除旧包并把发行物切换到 `justkernel`。
2. **只复用适配器和资源**  
   CANN simulator、模型 provider、A2A、skills/templates 先写 characterization tests 锁定行为，再复制/适配到新包。`LabService`、`ContinuousSwarm`、`IterationController`、`JudgeMonitor` 不迁移。
3. **先垂直闭环，再扩规模**  
   先跑通“1 supervisor + 1 mentor + optimizer/tester/profiler”的 fake 闭环，再加 consultant、多 mentor、约 100 agent、UI。
4. **fake-first，真实验收最后**  
   领域/应用测试不启动模型、设备、HTTP；fake 通过不算验收。P9 必须跑真实模型 + 实际 CANN。
5. **证据链先冻结**  
   候选、TestRecord zip、TaskContext、BestSelection、wake/budget 的契约先定，避免后期回填。
6. **每个里程碑单独写可执行 TDD plan**  
   本文件是路线图和检查清单；开始某个里程碑前，在 `docs/superpowers/plans/` 写该里程碑的详细 plan（文件级任务、失败测试、实现、验证、提交）。

---

## 1. 全局约束（每个任务都适用）

- Python `3.13+`；使用 `uv` 管理依赖；测试用 `pytest`；lint/format 用 `ruff`。
- 最终发行包和 CLI 只暴露 `justkernel`；不创建 `aworker` 模块。P0–P7 为过渡期，允许旧包暂时存在，但新包不得依赖旧包；P8 必须删除。
- 一个 Cluster 恰好一个 Operator、一个 supervisor；活动 agent 总数 ≤ `max_agents`（默认 100）。
- 角色固定：`SUPERVISOR` / `CONSULTANT` / `MENTOR` / `OPTIMIZER` / `TESTER` / `PROFILER`。
- ACL 必须同时在**工具层**和**应用层**强制；不能只靠 prompt。worker 工具集中不得存在任何 board 工具。
- 领域状态只写 SQLite/制品库；禁止用可变 JSON 文件保存 board/task/candidate 等状态。
- 消息/任务/租约/记录都有稳定 ID 和幂等键；至少一次投递，接收方按 ID 去重。
- 只有完整执行、`executed=true`、`coverage=FULL` 且 `outcome=PASS` 的 TEST 记录才能建立 baseline 或参与 best 最终验证。
- TestRecord zip 是必交付制品；未执行候选在收敛前必须有 `executed=false`、`coverage=NONE` 的审计记录。
- 设备租约跨集群全局唯一；TTL 过期不等于物理执行停止，无法确认停止则隔离设备。
- 密钥、私有推理、绝对私有路径不得进入 prompt/tool result/board/日志/导出。
- 领域文件 ≤ 300 行；应用服务 ≤ 400 行；adapter ≤ 600 行；前端模块 ≤ 400 行；单函数 ≤ 40 行。
- 默认只监听 `127.0.0.1:4173`；本地优先、受信环境，不提供恶意代码沙箱。
- 每项工作先写失败测试，再写最小实现；完成前运行对应层测试 + `ruff format --check` + `ruff check`。

---

## 2. 目录与测试分层目标

```text
src/justkernel/
├── shared/                  # ID、Digest、Clock、规范 JSON、错误、Principal、ProjectPath
├── cluster/                 # Cluster、OperatorSpec、Direction、budget、convergence
├── agent/                   # AgentInstance、Role、lifecycle、skills、tools、model binding
├── comm/                    # Board、Channel、Message、ACL、router、wake
├── task/                    # Task、TaskContext、assignment、worker lifecycle
├── candidate/               # CandidateVersion、版本图、BestSelection
├── testing/                 # TestRecord、ToolJob、HardwareQueue、skill contract
├── report/                  # ExplorationReport
├── platform/
│   ├── config.py
│   ├── persistence/         # SQLite、事件、投影、迁移、registry、recovery、legacy import
│   ├── artifacts/           # 内容寻址 zip/source
│   ├── runtime/             # Deep Agents runner、进程池、checkpoint
│   ├── bus/                 # 本地消息总线/A2A
│   ├── tools/               # 编译/测试/profile 后端
│   ├── hardware/            # 设备队列/租约
│   ├── models/              # 模型档案/provider/路由
│   ├── http/                # API/SSE
│   └── security/            # 脱敏
├── bootstrap/               # 组合根、CLI、迁移、恢复
├── resources/
│   ├── skills/              # base/builtin/user
│   └── templates/
└── web/                     # 原生 ES Modules 前端
```

```text
tests/
├── unit/                    # 纯领域
├── application/             # 用例 + fakes
├── adapters/                # SQLite/制品/总线/runtime/tool backend
├── integration/             # control + fake runtime + fake hardware + HTTP/SSE
├── architecture/            # 依赖、无副作用、文件规模
├── web/                     # reducer/selectors/format
├── e2e/                     # demo/回放/完整假集群
└── characterization/        # 旧实现行为锁定，P8 后可删除
```

常用验证命令：

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest tests/unit tests/architecture -q
uv run pytest tests/application -q
uv run pytest tests/adapters tests/integration -q
uv run pytest tests/web -q
uv run pytest tests/e2e -q
uv run pytest -q
```

---

## P0 基线与工程骨架

> 参考工期：约 1 周。前置：无。  
> 目标：冻结旧行为、建立迁移边界、让新包可 import 且架构门禁可运行。  
> SPEC：[12 §1–3](SPEC/12-migration-and-acceptance.md)、[03 §2–3](SPEC/03-architecture.md)、[11 §9](SPEC/11-testing-and-quality.md)。  
> 路径约定：除特别说明外，代码/文档路径相对 `Refactor/`；旧实现位于同级 `../JustKernel/`，只读参考。

- [x] **P0-01 建立基线与分支**
  - 创建 `refactor/justkernel-v2` 分支（或 worktree），给当前 HEAD 打 `legacy-baseline` tag。
  - 运行 `uv sync` 与 `uv run pytest -q`，把完整输出保存到 `docs/refactor/baseline-test-report.txt`。
  - 在进度记录登记 commit SHA、测试通过/失败数、已知 flaky。
  - 不修改旧业务代码。

- [x] **P0-02 旧实现清单与数据映射**
  - 新建 `docs/refactor/legacy-inventory.md`，逐项列出旧路径、职责、决策（复用/适配/删除）、新位置、验证测试。
  - 至少覆盖旧仓库 `../JustKernel/src/aworker/` 中的：`cli.py`、`lab/cli.py`、`lab/api.py`、`lab/service.py`、`lab/continuous.py`、`lab/store.py`、`lab/simulation.py`、`lab/deepagent.py`、`lab/iteration.py`、`lab/judger.py`、`lab/judge_*`、`server/*`、`swarm/*`、`lab/resources/*`。
  - 标注可复用：CANN simulator、模型 provider/凭证、A2A 信封、skills/templates、旧算子工程样本。
  - 标注旧数据目录、`work-items`/judge 状态文件、旧环境变量 `AWORKER_*` 的只读导入范围。

- [x] **P0-03 旧行为 characterization tests**
  - 在 `tests/characterization/` 新增（实际文件名）：
    - `test_simulation_request_contract.py`：旧 simulator 请求 schema、默认值、别名字段。
    - `test_skills_contract.py`：当前 skill 目录、`SKILL.md` frontmatter、名称。
    - `test_agent_card_contract.py`：agent card 默认值、传输协议。
    - `test_verified_fixture_contract.py`：已验证 fixture 的身份与哈希格式。
  - 测试只读 `../JustKernel` 旧实现，不改旧代码；干净 checkout 中通过 `conftest.py` 自动忽略。P8 切换后可删除，但删除前必须确认新适配器有等价合同测试。

- [x] **P0-04 新包骨架**
  - 创建 `src/justkernel/` 及第 2 节目的目录，包内先放空 `__init__.py`，不写业务逻辑。
  - 更新 `pyproject.toml`：新项目只打包 `src/justkernel`，`justkernel` 入口指向 `justkernel.bootstrap.cli:main`；旧实现与旧 CLI 留在 `../JustKernel/`。
  - 更新 `[tool.ruff.lint.isort] known-first-party = ["justkernel"]`。
  - 不在新项目引入 `src/aworker`；旧测试留在旧仓库。

- [x] **P0-05 架构门禁**
  - `tests/architecture/test_import_boundaries.py`：AST 检查 `justkernel` 不得 import `aworker`；`shared`/领域模块不得 import `platform`、`http`、`sqlite3`、`subprocess`、`deepagents`。
  - `tests/architecture/test_file_sizes.py`：领域 300、应用 400、adapter 600、前端模块 400、函数 40 行。
  - `tests/architecture/test_import_has_no_side_effects.py`：在临时目录/临时 HOME 下 import 全部 `justkernel` 模块，断言没有创建目录、数据库、文件。
  - `tests/architecture/test_package_exports.py`：最终只暴露 `justkernel` 公共入口（P8 前允许旧包存在，但新包不得 re-export）。

- [x] **P0-06 CI 与类型检查**
  - 更新 `.github/workflows/ci.yml`：运行 `ruff format --check`、`ruff check`、`mypy`、`pytest`、`uv build`；characterization 在干净 checkout 中 skip。
  - 类型检查先只覆盖 `src/justkernel`：在 `pyproject.toml` 增加 `mypy` 配置并加入 dev 依赖；不要求旧 `aworker` 通过。
  - 在现有 CI 矩阵中增加 `tests/characterization` 的独立 step；P8 前必须保持通过。

- [x] **P0-07 基础决策记录**
  - 新建 `docs/refactor/decision-log.md`，记录并定稿：
    - SQLite 访问方式：推荐标准库 `sqlite3` + 显式 SQL（schema/触发器/部分唯一索引是规范的一部分），不引入 ORM。
    - ID：UUID4 的 32 位小写十六进制；Digest：SHA-256 的 64 位小写十六进制。
    - 规范 JSON：键排序、UTF-8、无空白差异、浮点/NaN 规则。
    - 配置只由 `platform/config.py` 读环境变量；优先级 CLI > env > `.env` > 默认。
    - 过渡期双包规则；P8 切换清单。
    - 错误码/`application/problem+json` 命名规则。
    - 前端测试运行方式（Node 内置 test runner 或现有 `.cjs` 方式）。

**P0 出口**

- [x] 旧测试基线有记录，旧实现未被修改。
- [x] `uv run python -c "import justkernel"` 成功。
- [x] 架构门禁可运行且针对空骨架通过。
- [x] 旧实现保留/删除清单完成，可复用资源有合同测试。
- [x] 基础决策记录完成，无 TBD。

---

## P1 领域模型与执行契约

> 参考工期：约 1.5–2 周。前置：P0。  
> 目标：纯领域层完整表达 SPEC 04、13 的类型、状态机、ACL 和不变量；无 I/O。  
> SPEC：[04](SPEC/04-domain-model.md)、[13 §1–3](SPEC/13-generation-and-iteration-contract.md)、[06 §2–3](SPEC/06-communication-and-orchestration.md)、[11 §4](SPEC/11-testing-and-quality.md)。

- [ ] **P1-01 `shared` 基础类型**
  - `shared/ids.py`：`ClusterId`/`AgentId`/`DirectionId`/`TaskId`/`CandidateId`/`TestRecordId`/`MessageId`/`LeaseId` 生成与校验。
  - `shared/digest.py`：`Digest` 计算/校验；`shared/canonical_json.py`：规范 JSON。
  - `shared/clock.py`：`Clock` 协议；`shared/errors.py`：稳定错误码与领域异常。
  - `shared/principal.py`：`agent:<id>` / `human` / `system`；`shared/paths.py`：`ProjectPath` 安全校验。
  - 测试：`tests/unit/shared/`，覆盖非法 ID、非法摘要、绝对路径、`..`、反斜杠、NUL、非规范 JSON。

- [ ] **P1-02 执行契约类型**
  - `cluster/operator_spec.py`：`OperatorSpec`、`OperatorRef`、字段校验、规范摘要、`operator_spec.incomplete` 原因码。
  - `task/context.py`：`TaskContext`、`TaskContextRef`、`ArtifactGrant`；不适用列表为空并给原因。
  - `testing/policy.py`：`BudgetPolicy`、`EvaluationPolicy`、`WakePolicy`、`ModelRouting`。
  - 测试：13 §1 的必填字段；缺 oracle/输入约束/精度/后端被拒；策略必须有至少一个全局硬上限；`final_validation_reserve` 不得被探索占用。

- [ ] **P1-03 Cluster / Agent / Direction 聚合**
  - `cluster/domain.py`：`Cluster`（state、phase、baseline、best、report、continued_from）、不变量、命令/事件。
  - `cluster/direction.py`：`Direction`；一个 mentor 同时最多一个未关闭 direction。
  - `agent/domain.py`：`AgentInstance`、`Role`、`mentor_id` 规则、生命周期状态机。
  - 测试：唯一 supervisor；RUNNING 条件；COMPLETED 必须有 best+report；worker 必有 mentor 且不能有下级；关闭后不能接 task；`max_agents`。

- [ ] **P1-04 Task / Candidate / BestSelection 聚合**
  - `task/domain.py`：`Task`、四种 kind、candidate/skill/context 约束、状态机。
  - `candidate/domain.py`：`CandidateVersion` 不可变、来源唯一性（task 或 import）、parent 同 cluster、无环。
  - `candidate/graph.py`：DAG 校验、后代查询。
  - `candidate/best.py`：`BestSelection` 字段与 `PENDING → VALIDATED | FAILED`。
  - 测试：GENERATE 的 `candidate_id=null`；OPTIMIZE/TEST/PROFILE 必须有 candidate；TEST/PROFILE 必须有 skill；候选修改必须新 ID；成环拒绝；重新提名用新 selection。

- [ ] **P1-05 TestRecord / HardwareLease / Report 聚合**
  - `testing/domain.py`：`TestRecord`、`TestOutcome`、`executed`、`coverage`、skill/backend/environment。
  - `testing/lease.py`：`HardwareLease`、状态、TTL、fencing token 语义（领域侧）。
  - `report/domain.py`：`ExplorationReport`、revision、失败路径必填。
  - 测试：PASS 必须 `executed=1` 且 `coverage ∈ {FULL,SUBSET}`；baseline/best 只认 `FULL`；未执行记录必须 `task_id=null`+`audit_id`+`coverage=NONE`；同一 task 最多一个终态记录；报告只引用已存在候选/记录；COMPLETED 报告 best 必填。

- [ ] **P1-06 通信 ACL 与消息**
  - `comm/domain.py`：`MentorBoard`、`ConsultantBoard`、`WorkerChannel`、`HardwareQueue`。
  - `comm/message.py`：`Message` 信封（id、cluster_id、seq、channel、type、sender、recipient、correlation/causation、payload）。
  - `comm/acl.py`：SPEC 04 §2.2 的完整读/写矩阵；`comm/capabilities.py`：SPEC 05 §5 的角色×工具矩阵。
  - `comm/router.py`：纯函数路由/越权判断；board post 不可修改；worker 无 board。
  - 测试：`tests/unit/comm/test_acl_matrix.py` 表驱动覆盖每个角色×资源×读/写；consultant 只读；mentor 只能给直属 worker 派任务；worker 不能进其他 channel。

- [ ] **P1-07 跨聚合并发不变量**
  - 实现 I1–I12 的纯领域校验：唯一 supervisor/operator、worker 单 mentor、活动 agent 上限、task 归属、候选不可变、baseline/best 证据、消息幂等、领域无 JSON、模型输出不是指令。
  - `tests/unit/test_invariants.py` 为每条不变量写正例和反例。
  - `tests/unit/test_qa_matrix.py` 映射 QA-1–QA-20，每条至少一个领域/应用测试或注明由后续适配器/集成测试覆盖。

- [ ] **P1-08 事件、命令与错误码**
  - `shared/events.py`：SPEC 06 §11 的事件类型常量与版本。
  - 每个聚合定义命令/事件；错误码覆盖 `operator_spec.incomplete`、`cluster.operator_active`、ACL 拒绝、状态冲突、证据不足、租约冲突、预算耗尽。
  - 测试：事件名/字段稳定；错误码可被 API 映射。

**P1 出口**

- [ ] `uv run pytest tests/unit tests/architecture -q` 全绿。
- [ ] 领域层不 import 数据库/HTTP/模型/文件系统/进程库。
- [ ] SPEC 04 的所有状态机、ACL、I1–I12 有测试。
- [ ] 13 §1–3 的类型在不依赖 platform 的情况下可构造、校验、计算摘要。

---

## P2 持久化、事件、制品与全局服务

> 参考工期：约 2 周。前置：P1。  
> 目标：把领域状态可靠落盘；事件只追加；制品内容寻址；全局 registry/设备账本可仲裁。  
> SPEC：[08](SPEC/08-persistence-and-events.md)、[03 §4.2](SPEC/03-architecture.md)、[11 §6](SPEC/11-testing-and-quality.md)。

- [ ] **P2-01 journal schema 与迁移**
  - `platform/persistence/migrations/001_initial.sql`：SPEC 08 §3 的 clusters/agents/directions/tasks/candidates/test_records/hardware_leases/board_posts/messages/reports/events/outbox/projections。
  - 追加 SPEC 08 §12：`tool_jobs`、`agent_inbox`、`wake_requests`、`best_selections`、`task_artifact_grants`、`budget_ledger`。
  - 实现全部部分唯一索引：one_supervisor、one_active_direction、one_running_task_per_agent、one_record_per_task、one_claimed_wake_per_agent；事件 no_update/no_delete 触发器。
  - `platform/persistence/migrations.py`：版本表、顺序执行、幂等/失败回滚；测试重复执行不重复建表。

- [ ] **P2-02 仓储、UnitOfWork、事件与 outbox**
  - `platform/persistence/sqlite.py`：连接、WAL、`foreign_keys=ON`、`busy_timeout`、事务上下文。
  - `platform/persistence/repositories.py`：每个聚合的仓储；版本号乐观并发。
  - `platform/persistence/unit_of_work.py`：一次事务内提交聚合变更 + 事件 + outbox。
  - `platform/persistence/events.py`：append-only、seq、event_id 唯一；`outbox.py`：幂等键、available_at、attempts。
  - 测试：事务回滚、版本冲突、事件 append-only 触发器、outbox 重复投递不产生重复副作用。

- [ ] **P2-03 内容寻址制品库**
  - `platform/artifacts/store.py`：`artifacts/sha256/<ab>/<cd>/<digest>`；临时文件 → fsync → replace；目录 0700/文件 0600；读取校验大小/哈希；内容去重。
  - 拒绝路径逃逸、绝对路径、符号链接；DB 只存摘要/引用。
  - `tests/adapters/test_artifact_store.py`：哈希/大小校验、路径安全、并发写、孤立制品回收、软删除审计。

- [ ] **P2-04 投影与回放**
  - `platform/persistence/projections.py`：`mentor_board_view`、`consultant_board_view`、`cluster_graph`、`candidate_graph`、`queue_view`、`agent_inbox` 读模型。
  - 投影可从 `events` 重放；`projections.last_seq` 游标；重建不触发任务/测试/消息重发。
  - 测试：同一事件序列 live 与 replay 产生相同投影；未知事件忽略但记录游标。

- [ ] **P2-05 全局 operator registry**
  - `platform/persistence/registry.py` 或 `platform/registry/service.py`：`registry.db` 单写服务；`cluster_registry` + `one_active_cluster_per_operator`。
  - `reserve(operator_id, cluster_id, reservation_key)` 原子占位；`release` 幂等；初始化失败/崩溃遗留占位由恢复器核对。
  - 测试：同 operator 第二个活动集群被拒；终态后释放；并发 reserve 只成功一个；不得因锁超时另起同算子集群。

- [ ] **P2-06 全局设备账本**
  - `platform/hardware/ledger.py`：`hardware.db` `device_leases`、`one_lease_per_device`、`fencing_token`、`execution_active`。
  - `acquire/release/expire/isolate`；每 device 单调 fencing；TTL 过期保留 `execution_active` 直到确认停止。
  - 测试：跨集群同设备只一个有效租约；旧 token 不能启动新执行/覆盖新结果；无法确认停止则隔离。

- [ ] **P2-07 启动恢复**
  - `platform/persistence/recovery.py`：实现 SPEC 08 §7 表格：Agent RUNNING→INTERRUPTED；Task 未封存→INTERRUPTED；Lease 核对/EXPIRED/隔离；Cluster RUNNING/CONVERGING→PAUSED；Report 草稿重建；outbox 重试。
  - 不自动重放模型 Turn、不自动重试外部测试；所有恢复动作写事件。
  - 测试：`tests/adapters/test_recovery.py` 用临时 SQLite + fake 故障注入逐项验证。

- [ ] **P2-08 适配器门禁**
  - 覆盖：部分唯一索引、事件触发器、事务边界、重复消息、跨集群 registry/设备争抢、崩溃中断、镜像租约不能授予执行权。
  - `uv run pytest tests/adapters -q` 全绿。

**P2 出口**

- [ ] 所有领域状态有 SQLite 仓储；没有可变 JSON 领域状态。
- [ ] 事件只追加；投影可重建；outbox 至少一次 + 幂等。
- [ ] 制品内容寻址、哈希校验、权限正确。
- [ ] registry/hardware 全局唯一性由单写服务保证，不依赖每个集群的 SQLite。
- [ ] 重启后不产生重复 task/record/lease；恢复矩阵逐项有测试。

---

## P3 应用用例、端口与 Fakes

> 参考工期：约 1–1.5 周。前置：P2。  
> 目标：不启动模型/设备/HTTP，也能用 fakes 跑出完整用例；事务边界和幂等键固定。  
> SPEC：[03 §3.1](SPEC/03-architecture.md)、[11 §5](SPEC/11-testing-and-quality.md)、[08 §6](SPEC/08-persistence-and-events.md)。

- [ ] **P3-01 端口定义**
  - `*/ports.py`：仓储、消息总线、Agent runtime、工具后端、硬件队列、Clock/Ids、制品、模型注册表、脱敏器。
  - Control↔Runtime 协议按 SPEC 03 §4.2：`CreateAgent`、`StartTurn`、`SendMessage`、`CloseAgent`、`CancelTurn`、事件。
  - Control↔Tool/Hardware：`SubmitTest`、`SubmitProfile`、`ReadToolJob`、`QueueStatus`、`AcquireLease`、`ReleaseLease`。
  - 测试：端口协议可被 fake 实现；应用服务只依赖端口。

- [ ] **P3-02 Cluster / Agent 用例**
  - `cluster/service.py`：CreateCluster、StartCluster、PauseCluster、ResumeCluster、StopCluster、SetMaxAgents、Converge。
  - `agent/service.py`：CreateAgent、OpenWorker、CloseWorker、AssignTask 的归属校验、CompleteTask。
  - 校验：唯一 supervisor、worker 只能由 mentor 创建/关闭、max_agents、关闭前取消/等待 task+租约。
  - 测试：`tests/application/test_cluster_lifecycle.py`、`test_worker_lifecycle.py`。

- [ ] **P3-03 Task / Candidate 用例**
  - `task/service.py`：AssignTask、StartTask、CompleteTask、FailTask、CancelTask、RetryTask（新 TaskId）。
  - `candidate/service.py`：CommitCandidate、ImportCandidate、发布引用；diff/source 摘要校验；parent 同 cluster/无环。
  - 测试：越权派单拒绝；worker 同时一个 task；GENERATE/OPTIMIZE/TEST/PROFILE 参数约束；候选不可变。

- [ ] **P3-04 Testing / ToolJob / Record 用例**
  - `testing/service.py`：SubmitTest、SubmitProfile、ReadToolJob、SealTestRecord、CreateAuditRecord。
  - 幂等：同 task 同参数返回同一 job；冲突参数拒绝；一 task 一 job/终态记录。
  - 记录封存：先落盘 zip/校验，再同事务封存 record/job/Task/事件/wake。
  - 测试：`tests/application/test_testing_flow.py`。

- [ ] **P3-05 Best / Report / Budget 用例**
  - `candidate/best.py` + `cluster/service.py`：SelectBest、FinalValidate、FailSelection；只更新 VALIDATED。
  - `report/service.py`：CreateReport、AppendRevision；引用候选/记录哈希；失败路径必填。
  - `cluster/budget.py`：预留、结算、硬上限、最终验证预留、bootstrap/plateau/连续失败。
  - 测试：无完整 PASS 拒绝提名；最终验证失败不覆盖旧 best；预算不足 STOPPED 且可生成无 best 报告。

- [ ] **P3-06 Fakes**
  - `tests/application/fakes/`：InMemoryRepos、FakeBus、FakeClock、FakeIds、FakeAgentRuntime、FakeToolBackend、FakeHardwareQueue、FakeArtifactStore、FakeRedactor。
  - 所有 fake 确定性；禁止 `sleep`；可注入重复/乱序/失败。
  - 测试：fake 与端口协议一致；重复事件/重复提交幂等。

- [ ] **P3-07 应用测试**
  - 覆盖 SPEC 11 §5：CreateCluster、Open/CloseWorker、AssignTask、SubmitTest/Profile、CommitCandidate、SelectBest、Converge、模型/工具/设备/消息失败。
  - 覆盖反例：越权、超额、关闭后接任务、无候选测试、无记录 best、重复 task/record。

**P3 出口**

- [ ] 无模型/设备/HTTP 时，脚本化 fake 集群可完成启动→方向→开 worker→任务→候选→测试→记录→收敛。
- [ ] 所有写用例有事务边界和幂等键。
- [ ] `uv run pytest tests/application -q` 全绿。

---

## P4 Agent 运行时、Skills 与工具权限

> 参考工期：约 2–3 周。前置：P3 端口冻结。  
> 目标：六角色可运行；worker 工具集无 board；用户 tester/profiler skill 可加载/替换。  
> SPEC：[05](SPEC/05-agent-runtime-and-skills.md)、[10 §7](SPEC/10-configuration-security-observability.md)、[11 §8](SPEC/11-testing-and-quality.md)。

- [ ] **P4-01 模型档案与路由**
  - `platform/models/profiles.py`：`ModelProfile`（provider、model、base_url、secret ref、effort、max_tokens、extra_body、streaming）。
  - `platform/models/registry.py`：provider 适配器、密钥只留在 adapter、能力校验。
  - `platform/models/routing.py`：优先级 `实例显式 > direction/任务 > RoleConfig > 系统默认`；fallback 仅限已配置兼容模型；换模新建 session 并留审计。
  - 测试：优先级、缺能力拒绝、provider 限流/配额独立、fallback 证据、换模不丢 TaskContext 摘要。

- [ ] **P4-02 Deep Agents runner 与检查点**
  - `platform/runtime/runner.py`：CreateAgent、StartTurn、SendMessage、CloseAgent、CancelTurn、事件输出。
  - `platform/runtime/checkpoint.py`：键 `(cluster_id, agent_id, session_id)`；检查点不是证据；恢复需新 Turn，不自动重放工具副作用。
  - `platform/runtime/fake.py`：确定性 fake runner，支持排队/失败/中断。
  - 测试：创建/关闭/取消；同 agent 单 Turn；崩溃后 RUNNING→INTERRUPTED；不自动重跑。

- [ ] **P4-03 Skill 加载与校验**
  - `agent/skills.py`：解析 `SKILL.md` frontmatter；校验 `name`/`description`/`metadata.role`/`metadata.backend`/`metadata.version`/`allowed_tools`。
  - 加载顺序：tester `base → builtin → user`；profiler 同理；后者覆盖同名。
  - 安全：路径不得逃逸 skills 根；`SKILL.md` ≤ 10MB；`allowed_tools` 必须是角色矩阵子集；用户脚本受 `allow_user_scripts` 控制；扫描/拒绝 `.env`/密钥文件。
  - 测试：非法 frontmatter、越权工具、路径逃逸、超大文件、脚本开关、版本变化生成新 SkillRef。

- [ ] **P4-04 六角色基础 skills 与内置 tester/profiler**
  - `resources/skills/base/{supervisor,consultant,mentor,optimizer,tester,profiler}/SKILL.md`：职责、禁止事项、数据不是指令、无记录不能声称通过/最优。
  - `resources/skills/builtin/tester-cann-simulation/SKILL.md`、`profiler-cann/SKILL.md`：输入、工作流、输出、失败处理、限制；先骨架，P5 接后端。
  - 测试：六个 skill 可解析；prompt 版本可记录；内置 skill 的 `metadata.role/backend` 正确。

- [ ] **P4-05 工具注册表与对象级 ACL**
  - `agent/tools.py`：按角色注册工具；实现 SPEC 05 §5 矩阵。
  - worker 工具集**静态不包含** `read_mentor_board`/`post_mentor_board`/`read_consultant_board`/`post_consultant_board`/`send_brief`。
  - 对象级 ACL：`read_candidate`/`read_test_record`/`read_task_context`/`read_task_artifact` 必须校验 task 授权、candidate 发布状态、记录所属。
  - 测试：`tests/unit/agent/test_tool_matrix.py` 静态断言；`tests/application/test_object_acl.py` 越权反例。

- [ ] **P4-06 Agent 池与生命周期**
  - `platform/runtime/pool.py`：逻辑 agent 与进程解耦；`runtime_processes`、`model_concurrency`、`max_agents`。
  - 同一 agent 只在一个进程运行；崩溃后新 Turn 恢复；关闭 worker 取消/等待 task、核对工具执行、释放租约、归档 channel。
  - 测试：100 逻辑 agent/8 进程可创建；超限拒绝；关闭无孤儿 session/租约；idle worker 复用。

- [ ] **P4-07 运行时测试**
  - `tests/adapters/test_runtime_fake.py`、`tests/integration/test_agent_lifecycle.py`。
  - 覆盖：六角色创建；worker 无 board；consultant 只读；mentor 跨 worker 派单拒绝；skill 替换；模型 401/429/超时；agent 崩溃。

**P4 出口**

- [ ] 六角色可在 fake 模型下创建/运行/关闭。
- [ ] worker 工具集静态无 board；对象级 ACL 有反例测试。
- [ ] 用户 tester/profiler skill 可加载/替换；内置 CANN skill 骨架可用。
- [ ] 约 100 逻辑 agent 的上限、并发、检查点可验证。

---

## P5 证据链：候选、TestRecord、ToolJob、硬件队列

> 参考工期：约 2–3 周。前置：P4 工具端口。  
> 目标：候选→测试→zip→记录→租约证据链完整；fake 后端可确定性运行。  
> SPEC：[07](SPEC/07-testing-and-profile.md)、[13 §3/§5/§6](SPEC/13-generation-and-iteration-contract.md)、[08 §12](SPEC/08-persistence-and-events.md)。

- [ ] **P5-01 ToolJob 服务**
  - `testing/job.py`：`ToolJobRef`、`ToolJobView`、状态 `QUEUED → RUNNING → SUCCEEDED | FAILED | CANCELLED | INTERRUPTED`。
  - 幂等键 `task_id`：重复提交返回同一 job；参数冲突拒绝；每 Task 至多一个 job/终态记录。
  - 排队超时与执行超时分离；执行 timeout 从取得租约后开始；submit 立即返回，worker 进入 WAIT。
  - 测试：重复提交、冲突参数、排队超时、执行超时、取消/中断、迟到结果。

- [ ] **P5-02 硬件队列与租约**
  - `testing/queue.py` + `platform/hardware/service.py`：enqueue/acquire/release/status；FIFO/优先级；queue timeout。
  - 租约 TTL、fencing token、`execution_active`；job 完成立即释放设备，不等待模型解读。
  - 关闭/崩溃时由工具服务核对实际执行；无法确认则隔离并告警；重排必须新 Task。
  - 测试：跨集群独占、TTL 过期、旧 token 拒绝、排队可见性、tester/profiler 看不到彼此 task 内容。

- [ ] **P5-03 TestRecord zip 构建与校验**
  - `testing/record.py`、`testing/zip.py`：按 SPEC 07 §3.2 生成完整目录（manifest、README、task、context、operator-spec、candidate source/diff/sha256、skill、cases、config、environment、commands/stdout/stderr、results、metrics、profile、checksums、provenance）。
  - `manifest.json` 使用 `justkernel.test_record.v1`；包含 13 §5 的 `executed/coverage/job_id/audit_id` 与各摘要。
  - `checksums.sha256` 排除自身；zip 创建后不可修改；缺失必需文件→无效。
  - 未执行审计 zip：`task_id/job_id=null`、`audit_id`、`executed=false`、`coverage=NONE`、`outcome=CANCELLED/UNKNOWN`、`author=system`，不伪造命令/环境。
  - 测试：完整/缺文件/哈希不符/zip 中断/重复记录幂等/审计记录字段。

- [ ] **P5-04 CANN 仿真后端与 fake 后端**
  - `platform/tools/fake.py`：确定性编译/测试/profile、可注入 FAIL/ERROR/超时。
  - `platform/tools/cann_simulation.py`：包装旧 simulator，输出 case 结果、粗性能、日志、环境指纹；命令脱敏。
  - 后端解析 skill 的 `metadata.backend`；未注册后端拒绝。
  - 测试：fake 与真实 adapter 合同测试；环境指纹；指标不补 0；仿真/真机指标分字段。

- [ ] **P5-05 TaskContext 与只读授权**
  - `task/context.py` + `platform/persistence`：`task_artifact_grants` 保存 task_id、artifact_digest、只读范围、有效期。
  - `TaskContext` 生成：base candidate、objective/acceptance、feedback（记录/失败阶段/case/日志/profile）、history、shared_evidence、resource_grants、budget。
  - optimizer 只能通过 `read_task_context`/`read_task_artifact` 读取授权快照；不能因此获得 board/其他 channel/未发布候选。
  - 测试：grant 过期/越权拒绝；大日志截断标记；反馈摘要与原始记录一致；关闭旧 worker 后新 worker 仅凭快照可读。

- [ ] **P5-06 证据链测试**
  - `tests/application/test_evidence_chain.py`：候选→测试 job→zip→记录→mentor 通知。
  - 覆盖：无有效记录不得 PASS；子集 PASS 不升级 FULL；同一候选多次测试追加；租约唯一；submit 幂等；Task SUCCEEDED 但 record FAIL 不误报通过。

**P5 出口**

- [ ] 候选→测试→TestRecord zip→索引完整走通。
- [ ] zip 必需文件/哈希/不可变/审计记录有测试。
- [ ] 硬件队列独占、TTL、fencing、隔离有测试。
- [ ] 不存在“fake PASS”；所有 PASS 都有 `executed=true` 与有效记录。

---

## P6 生成/导入、反馈与闭环编排

> 参考工期：约 2–3 周。前置：P5。  
> 目标：完成 SPEC 13 §10 的 fake 闭环：无源码 GENERATE→失败→反馈修复→baseline→再优化→最终验证→best+report。  
> SPEC：[13](SPEC/13-generation-and-iteration-contract.md)、[06](SPEC/06-communication-and-orchestration.md)、[07 §7](SPEC/07-testing-and-profile.md)、[12 §8](SPEC/12-migration-and-acceptance.md)。

- [ ] **P6-01 OperatorSpec 启动校验**
  - 校验 semantics、input_contract、reference/oracle、accuracy_policy、case_pack、target、engineering_policy、evaluation_policy。
  - 缺字段返回稳定原因码 `operator_spec.incomplete`；模型不得猜测/补齐。
  - 测试：每种缺失/非法字段；GENERATE 无源码可过；IMPORT 缺源码拒绝；两模式缺 oracle/输入约束拒绝。

- [ ] **P6-02 全局注册与集群启动**
  - `bootstrap`/`cluster/service.py`：校验输入 → 原子占位 registry → 创建 Cluster（INITIALIZING，phase=BOOTSTRAPPING）→ 创建 supervisor/consultants/mentors → RUNNING。
  - 启动失败清理已建 agent/session、取消待投递 wake、幂等释放占位。
  - 测试：同 operator 冲突 409；启动失败无孤儿；registry 占位崩溃恢复；初始角色不超 `max_agents`。

- [ ] **P6-03 GENERATE / IMPORT 与根候选**
  - GENERATE：supervisor 发布基线 direction → mentor 派发 GENERATE（candidate_id=null）→ optimizer 建工程 → 候选 parent=null。
  - IMPORT：Control 固化用户源码为根候选，`author_principal=system`、`import_id`，不因用户提供就标记 PASS。
  - 测试：GENERATE 任务参数；IMPORT 根候选来源唯一；diff/源码快照；导入后仍须完整验证。

- [ ] **P6-04 baseline 建立**
  - `cluster/baseline.py` 或 `cluster/service.py`：只在当前完整 case pack/reference/accuracy 下完整 TEST PASS 后设置 `baseline_candidate_id`，发 `baseline.established`。
  - `max_bootstrap_attempts` 计数 GENERATE/修复/导入候选完整验证；耗尽无 baseline → STOPPED，原因 `baseline_not_established`，生成失败报告。
  - 有性能目标时，同一比较环境采集 baseline PROFILE；正确性基线/性能参考分别留痕。
  - 测试：子集/未执行/FAIL 不建 baseline；只有首个完整 PASS；attempts 耗尽 STOPPED；无候选不伪造记录。

- [ ] **P6-05 反馈包与换 worker 续接**
  - mentor 选择证据生成 TaskContext：失败记录、失败阶段、case、期望/实际、脱敏日志、profile 热点、历史尝试、避免重复事项。
  - 关闭旧 optimizer；新 optimizer 仅凭 TaskContext 修复；reference/case pack/skill 摘要不变；修复候选 parent=失败候选。
  - 测试：QA-17；旧会话删除/不可用后仍可修复；反馈越权/缺授权拒绝；历史尝试不重复。

- [ ] **P6-06 唤醒、消息消费与单 Turn**
  - `comm/inbox.py`、`comm/wake.py`、`platform/runtime/scheduler.py`：`(agent_id,event_id)` 去重；`WakeRequest` 固化；debounce（默认 500ms）；RUNNING 期间 pending；Turn 完成按 seq 合并领取。
  - 触发矩阵按 13 §4：cluster.started→supervisor；direction→mentor；task.assigned→worker；candidate/task 终态→mentor；record→mentor；baseline/brief→supervisor；summary timer 仅处理增量。
  - 每次 mentor Turn 必须 `ASSIGN|WAIT|COMPLETE_DIRECTION|REQUEST_PIVOT|STOP`；每次 supervisor Turn 必须 `CONTINUE|PIVOT|CONVERGE|PAUSE|STOP`；WAIT 必须有 deadline。
  - 测试：重复 event 不重复任务；RUNNING 时多事件合并；同 Agent 不并发 Turn；无增量不调模型；自发帖/回声不唤醒；WAIT 到期一次。

- [ ] **P6-07 watchdog、停滞与暂停**
  - `platform/runtime/watchdog.py`：RUNNING 集群无运行/排队任务、无 pending wake、无有效 WAIT → `cluster.stalled`，一次性唤醒 supervisor；重复无动作 → PAUSED。
  - PAUSED/CONVERGING/终态拒绝普通探索 wake；PAUSED 保留通知；CONVERGING 只接最终验证/报告。
  - 测试：合法 WAIT 不误报；无任务检测；重复停滞转 PAUSED；暂停期间事件保留。

- [ ] **P6-08 预算、plateau 与重复候选**
  - `cluster/budget.py`：预留/结算、token/费用、工具/设备时间、max_rounds、max_bootstrap_attempts、plateau_rounds、max_consecutive_failures、final_validation_reserve。
  - 至少一个可执行全局硬上限；调用前按最坏消耗预留；未知费用按配置价格保守结算并标注估算。
  - plateau：连续 `plateau_rounds` 个有可比测量且无超过 `min_improvement` 的完整周期；工具故障不算无收益。
  - 相同源码提交 → `candidate.duplicate`，默认不再自动实验；跨契约/环境不得复用通过结论。
  - 测试：预算耗尽停止新探索；最终验证预留不被占用；plateau；连续失败；重复候选；未知费用不当 0。

- [ ] **P6-09 收敛、BestSelection 与报告**
  - supervisor `select_best` 创建 PENDING；校验完整 TEST PASS；性能目标启用时校验可比 PROFILE；子集/未执行拒绝。
  - 指定 mentor 派发最终完整 TEST/必要 PROFILE；通过→VALIDATED 更新 best，phase=FINALIZING；失败→FAILED 保留旧 best，回 RUNNING 或 STOPPED。
  - 收敛前为未执行候选生成审计记录；关闭角色前排空/取消 pending 任务；报告含方向、分支、候选、失败路径、记录哈希、选择理由。
  - STOPPED/FAILED 可无 best；COMPLETED 必须有 VALIDATED best + report。
  - 测试：QA-13/14；最终验证失败不覆盖旧 best；报告 revision；未执行审计；COMPLETED 门槛。

- [ ] **P6-10 暂停/恢复与迟到结果**
  - `/clusters/{id}/resume` 语义在应用层：核对结果/租约/预算 → 封存/中断任务 → supervisor 新 session → RUNNING → 一次 `RecoverySummary` 唤醒。
  - Control 崩溃后 PAUSED；未封存 Task INTERRUPTED；不自动重跑；迟到结果追加绑定原 task/job 并标 `late_completion`，不自动建 baseline/best。
  - 测试：QA-20；旧执行未确认停止前不发新租约；resume 后新 Task 引用旧失败任务；迟到结果只归档一次；终态集群不回 RUNNING。

- [ ] **P6-11 fake 闭环验收**
  - `tests/e2e/test_fake_closed_loop.py`：用 FakeRuntime/FakeToolBackend/FakeClock/Ids 跑：
    `GENERATE 无源码 → 首个候选编译/精度失败 → 关闭旧 optimizer → 新 optimizer 仅凭 TaskContext 修复 → 完整 TEST PASS 建 baseline → PROFILE 反馈 → 再优化 → 最终验证 → best + report`。
  - 断言：无重复任务/记录/租约；reference/case pack 摘要不变；子集/未执行不能成为 best；预算/最终验证预留正确；所有事件可回放。

**P6 出口**

- [ ] SPEC 13 §10 的 1–9 在 fake 环境确定性通过。
- [ ] 无源码 GENERATE 可建立真实（fake 后端）TEST PASS baseline。
- [ ] 反馈修复不依赖旧会话记忆。
- [ ] 唤醒/预算/收敛无重复副作用、无回声循环。

---

## P7 API、SSE、A2A 与前端

> 参考工期：约 2–3 周。前置：P6。  
> 目标：人类可观察、可回放、可导出；API 只返回 DTO，不泄露内部行/路径/密钥。  
> SPEC：[09](SPEC/09-api-and-frontend.md)、[06 §11](SPEC/06-communication-and-orchestration.md)、[11 §8](SPEC/11-testing-and-quality.md)。

- [ ] **P7-01 API 骨架与通用规则**
  - `platform/http/app.py`、`dto.py`、`errors.py`、`pagination.py`、`idempotency.py`。
  - `/api/v1/*`；`application/problem+json` + 稳定错误码；列表游标分页；写操作幂等键；未知值 `null` 不补 0。
  - 测试：DTO 字段；错误映射；重复 POST 不创建第二集群/第二次 resume；不返回 DB 行/绝对路径/密钥。

- [ ] **P7-02 路由**
  - Cluster：`POST /clusters`、GET 详情/graph、stop/pause/resume/converge。
  - Agents：列表/详情/close/conversation（脱敏）。
  - Board/Messages：mentor/consultant board、messages 分页、人工消息（审计）。
  - Directions/Tasks：列表/详情/context/tool-jobs/cancel。
  - Candidates/Records：列表/详情/source/records/download。
  - Hardware、Report、Events、Export、Admin、Skills。
  - 测试：每条路由的权限/对象级 ACL；GENERATE/IMPORT 422/409；下载哈希校验。

- [ ] **P7-03 SSE**
  - `/events/stream?after=`；`Last-Event-ID` 续传；seq 幂等/去重；心跳 20s；批量 ≤200；实时/回放共用 reducer。
  - 测试：断线续传、重复 seq、乱序、心跳、未知事件。

- [ ] **P7-04 A2A**
  - 一个集群一个 agent card；skills `cluster-status`、`cluster-message`；不暴露 worker channel/直接改 board/提交测试。
  - 外部消息进 `external` channel，Control 校验后转 board post/人工消息；`delivery_id` 幂等；不能冒充 agent。
  - 测试：status/message；重复 delivery；越权 channel；本机/受信网络限制。

- [ ] **P7-05 脱敏、导出与下载**
  - `platform/security/redactor.py`：注册密钥值（≥8）→ `[redacted]`；日志/事件/错误/tool result/导出统一处理。
  - `justkernel export`/`GET /export`：事件、cluster 图、board、任务、候选、记录索引、报告；不含密钥/私有路径/私有推理。
  - source/record/context 下载执行对象级 ACL，不能复用人类全量权限给 Agent。
  - 测试：密钥扫描、导出脱敏、路径泄露、下载越权。

- [ ] **P7-06 前端状态层**
  - `web/state/{store,reducer,selectors,sources}.js`；事件 reducer 支持 live/replay/demo；实体合并、候选 DAG、记录关联、角色树、队列。
  - 测试：`tests/web/reducer.test.js` 幂等/乱序/未知事件；`selectors.test.js` 合并/图/记录；`format.test.js` 时间/指标/未知值。

- [ ] **P7-07 前端视图**
  - `views/{cluster,agents,board,tasks,candidates,records,hardware,report,replay}.js`。
  - Best 显示 VALIDATED selection/policy/最终验证记录；PENDING 不标最终 best；失败候选可见；指标标注 simulation/npu/profile，不换算。
  - 可访问性：键盘/焦点/aria-live/reduced motion/对比度；大列表虚拟化；事件保留最近 160 条。
  - 测试：关键 DOM/键盘（可选）；无 live 数据伪造。

- [ ] **P7-08 回放与 demo**
  - `web/demo/fixture.js`；`demo` 模式无模型/设备可运行；实时/回放一致；标注来源。
  - 测试：`tests/e2e/test_demo_mode.py` 或 web 测试；demo 不写真实数据目录。

**P7 出口**

- [ ] fake 集群可通过 HTTP/SSE/UI 完整观察/操作/回放。
- [ ] DTO 不泄露内部行/路径/密钥/私有推理。
- [ ] A2A 不暴露 worker 私有通道。
- [ ] live/replay/demo 共用 reducer，测试一致。

---

## P8 迁移、切换与清理

> 参考工期：约 1–2 周。前置：P7。  
> 目标：单一 `justkernel` 包；旧数据只读导入；旧 lab/Judge/swarm 下线。  
> SPEC：[12 §1–5](SPEC/12-migration-and-acceptance.md)、[08 §9](SPEC/08-persistence-and-events.md)、[03 §2](SPEC/03-architecture.md)。

- [ ] **P8-01 旧数据只读导入**
  - `platform/persistence/legacy_import.py` + `bootstrap/migrate.py`：只读旧目录；幂等；不修改旧数据。
  - 旧 teams/work-items/candidates/judge 记录导入为 `LEGACY`，只读展示；不进入新 board/candidate/best。
  - 测试：样本导入两次结果一致；旧数据哈希不变；LEGACY 不参与 best；缺文件/损坏可报告。

- [ ] **P8-02 CLI 与运行模式**
  - `bootstrap/cli.py`：`justkernel cluster|demo|worker|migrate`。
  - `platform/config.py`：`AppConfig`/`ClusterConfig`/`RoleConfig`/`LimitsConfig`/`SkillsConfig`/`HardwareConfig`/`StorageConfig`；只这里读 `JUSTKERNEL_*`。
  - 启动校验：路径可写、模型档案存在、skills 目录、设备合法、agent 上限 ≥ 6；构造函数不建目录，`bootstrap.initialize()` 显式初始化。
  - 测试：模式启动/拒绝；配置优先级；`GENERATE` 允许空 baseline_source，`IMPORT` 必填；旧 `AWORKER_*` 只有 migrate 读取。

- [ ] **P8-03 数据目录与权限**
  - `<data_root>/{registry.db,hardware.db,clusters/<id>/{journal.db,artifacts,checkpoints,workspaces,exports,logs},private,service.lock}`。
  - 私有目录 0700/文件 0600；单数据根单控制服务锁；一个集群一个目录；不同算子不共享 board/候选。
  - 测试：权限；重复启动锁；路径布局；导出/回放只读。

- [ ] **P8-04 删除旧实现并切换发行物**
  - 删除 `src/aworker/`（旧 lab/judge/swarm/server/CLI）；
  - `pyproject.toml`：`name = "justkernel"`；`[project.scripts] justkernel = "justkernel.bootstrap.cli:main"`；删除 `aworker`/`aworker-lab`；hatch 只打包 `src/justkernel`；isort 只保留 `justkernel`。
  - 更新 README/CONTRIBUTING/docs/start 脚本/`.env.example`；删除旧 `aworker` 环境变量分支。
  - `tests/architecture/test_no_aworker.py`：全仓库不得 import `aworker`；构建产物不含旧模块。
  - 测试：`uv run python -m justkernel --help`；旧测试删除/归档；新测试全绿。

- [ ] **P8-05 打包与供应链检查**
  - `uv build`；wheel/sdist 只含 `justkernel`；排除受限模板/密钥/旧 lab 资源。
  - 依赖固定；`uv.lock` 更新；不新增不必要的 Node/Python 依赖。
  - 测试：安装后 `justkernel demo` 可启动；构建包扫描无密钥/绝对路径。

**P8 出口**

- [ ] 仓库与发行物只暴露 `justkernel`；无 `aworker` 模块/脚本/环境变量分支。
- [ ] 旧数据只读导入可查，不参与新 best。
- [ ] `justkernel cluster/demo/worker/migrate` 可用。
- [ ] `uv build` 成功且产物无密钥/受限文件。

---

## P9 加固、规模与真实验收

> 参考工期：约 3–5 周。前置：P8。  
> 目标：真实模型 + 实际 CANN 闭环；崩溃/规模/安全验收；可交付报告。  
> SPEC：[11 §7/§12](SPEC/11-testing-and-quality.md)、[12 §4](SPEC/12-migration-and-acceptance.md)、[13 §10](SPEC/13-generation-and-iteration-contract.md)、[10 §3–5](SPEC/10-configuration-security-observability.md)。

- [ ] **P9-01 混沌与恢复演练**
  - control `kill -9`、agent 崩溃、tool 崩溃、关闭 worker 时崩溃、设备断开、磁盘满、zip 写入中断、消息重复。
  - 断言：不自动重跑；未封存 Task INTERRUPTED；租约未确认停止则隔离；无重复 task/record/lease；迟到结果只归档一次。
  - 记录到 `docs/refactor/chaos-report.md`。

- [ ] **P9-02 规模与长跑**
  - 约 100 逻辑 agent（进程池 `runtime_processes`、`model_concurrency`）；多 mentor/多 worker；长跑无孤儿 agent/session/租约。
  - 监控：`agents.active/by_role`、`tasks.running/queued/failed`、`hardware.leased/queued`、`wakes.pending/failed`、`budget.reserved/consumed`、`recovery.applied_total`。
  - 记录资源/成本/稳定性到 `docs/refactor/scale-report.md`。

- [ ] **P9-03 多模型路由验收**
  - 不同角色/同角色不同实例绑定不同 profile；优先级、能力拒绝、provider 限流/配额、显式 fallback 留证据。
  - 换模新建 session，TaskContext 可续接；模型差异不改变 ACL/测试标准。
  - 测试/报告：路由审计、用量/错误、fallback 证据。

- [ ] **P9-04 真实 CANN + 真实模型闭环**
  - 用真实后端跑：无源码 GENERATE → 首次编译/精度失败 → 新 optimizer 仅凭 TaskContext 修复 → 完整 TEST PASS 建 baseline → PROFILE 反馈再优化 → 最终验证 → best + report。
  - 记录真实 TestRecord zip、环境指纹、profile 原始/汇总、最终验证证据。
  - 若性能未改善，按 plateau/预算停止，不承诺每轮变快；无收益必须留报告。
  - 产物：`docs/refactor/real-acceptance-report.md` + 记录 zip 索引。

- [ ] **P9-05 安全、可观测性与运行手册**
  - 威胁模型落地检查：worker 越权、consultant 写 board、跨 worker 派单、提示注入、用户 skill 越权、设备滥用、消息伪造、供应链。
  - 日志/指标/审计覆盖角色/任务/候选/记录/租约；运行手册覆盖 agent/worker/队列/记录/收敛/崩溃。
  - 导出/下载/回放脱敏审查；明确无恶意代码沙箱的限制。

- [ ] **P9-06 验收报告**
  - 逐项勾选 SPEC 12 §4 的 15 个验收场景。
  - 逐项勾选 SPEC 13 §10 的 10 条闭环验收。
  - 逐项核对 SPEC 11 §3 的 12 个高风险失败模式测试。
  - 记录未通过项、已知限制、后续项；不得把 fake 结果写成真实生成成功证据。

**P9 出口**

- [ ] 真实模型 + 实际 CANN 的 GENERATE→失败修复→baseline→再优化→最终验证通过。
- [ ] 100 agent 规模/长跑/混沌无孤儿、无重复证据。
- [ ] 验收报告完成，证据可复核。
- [ ] 文档/CI/打包/运行手册同步。

---

## 3. 关键路径与并行

```text
P0 → P1 → P2 → P3 → P5 → P6 → P7 → P8 → P9
                 ↘ P4 ↗
```

- **串行主干**：P0 → P1 → P2 → P3 → P5 → P6 → P7 → P8 → P9。
- **可并行**：P4 在 P3 端口冻结后开始；P8-01 旧数据导入器可在 P2 后开始，但 P8-04 切换必须等 P7。
- **不可并行**：P1–P2 的 schema/领域类型只能有一个所有者；任何跨里程碑的接口变更先改 P1 类型和测试。
- **建议团队规模**：1 名领域/存储负责人 + 1 名运行时/工具负责人 + 1 名 API/前端负责人；共享接口由领域负责人合并。

---

## 4. 里程碑门禁

| 门禁 | 时点 | 必须证明 |
| --- | --- | --- |
| G1 | P3 后 | 纯领域/应用/fake 可确定性运行；无 I/O 违规；所有用例有幂等键 |
| G2 | P5 后 | 候选→测试→zip→记录→租约证据链完整；缺失/伪造记录被拒 |
| G3 | P6 后 | fake 闭环 + 唤醒/预算/恢复无重复副作用；GENERATE 无源码可建 baseline |
| G4 | P7 后 | API/SSE/UI 可观察、可回放；DTO 不泄露；A2A 不暴露 worker 通道 |
| G5 | P8 后 | 单包 `justkernel`；旧数据只读；无 `aworker`；构建干净 |
| G6 | P9 后 | 真实模型 + CANN 闭环；100 agent/混沌/安全验收通过 |

---

## 5. 验收场景映射

### 5.1 SPEC 12 §4 的 15 个验收场景

| # | 场景 | 主要覆盖 |
| --- | --- | --- |
| 1 | 单算子集群、唯一 supervisor、启动/停止 | P1/P3/P6 |
| 2 | 六角色运行；同角色不同模型；路由/换模可追踪 | P4/P9 |
| 3 | ACL：worker 不能读 board；consultant 只读；mentor 不能跨 worker | P1/P4/P5 |
| 4 | 约 100 逻辑 agent；开关 worker；无孤儿/租约泄漏 | P4/P9 |
| 5 | 方向内探索；board 共享；consultant 汇总；supervisor 调整 | P6/P7 |
| 6 | 候选→tester→TestRecord zip；profiler→详细记录 | P5/P6 |
| 7 | tester/profiler 共享队列；设备独占；超时释放 | P2/P5 |
| 8 | best 有记录/最终验证；报告含方向/分支/失败/理由 | P6 |
| 9 | 所有候选记录保留；best+report 可下载 | P6/P7 |
| 10 | 崩溃后不重复 task/record/lease；显式 resume 新 session/Task | P6/P9 |
| 11 | 无源码 GENERATE 建 baseline；IMPORT 也须验证；缺输入拒绝 | P6/P9 |
| 12 | 反馈经 TaskContext 给新 worker；失败修复+再优化 | P6/P9 |
| 13 | 重复/并发通知不重复实验；无增量不调模型；停滞检测 | P6 |
| 14 | 无性能目标不强制 PROFILE；性能目标按冻结策略；子集/未执行不可 best | P5/P6 |
| 15 | 跨目录同算子注册冲突、跨集群同设备争抢被拦截；预算不足正确停止 | P2/P6/P9 |

### 5.2 SPEC 13 §10 的 10 条闭环验收

| # | 验收 | 主要覆盖 |
| --- | --- | --- |
| 1 | 无源码 GENERATE + 完整 TEST PASS baseline | P6/P9 |
| 2 | 首次失败→关闭旧 optimizer→新 worker 仅凭 TaskContext 修复 | P6/P9 |
| 3 | PROFILE 反馈→新 worker 改进→可比测量超阈值 | P6/P9 |
| 4 | 重复投递/RUNNING 多事件只产生一次后续任务 | P6 |
| 5 | watchdog 发现停滞；合法 WAIT 不误报；无增量不调模型 | P6 |
| 6 | 无性能目标仅完整 TEST；有性能目标缺 PROFILE 拒绝 | P6 |
| 7 | 崩溃时 job 占设备；未确认停止不发新租约；resume 新 Task | P6/P9 |
| 8 | 同算子跨目录重复启动被拒；跨集群设备只一个租约 | P2/P9 |
| 9 | bootstrap 预算耗尽输出无 best 失败报告；最终验证预算独立 | P6 |
| 10 | 不同角色/实例不同模型；路由可追踪；换模不丢反馈 | P4/P9 |

### 5.3 SPEC 11 §3 的 12 个高风险失败模式

| # | 失败模式 | 主要测试 |
| --- | --- | --- |
| 1 | worker 读 board | P1 ACL/P4 工具矩阵 |
| 2 | consultant 写 mentor board | P1 ACL |
| 3 | mentor 给别人的 worker 下 task | P1/P3/P4 |
| 4 | 关闭 worker 后仍接 task/租约未释放 | P3/P4/P5 |
| 5 | 同一设备两个 lease | P2/P5 |
| 6 | 无 TestRecord 成为 best | P3/P5/P6 |
| 7 | zip 缺文件/哈希不匹配 | P5 |
| 8 | agent 数量超过 100 | P4/P9 |
| 9 | control 崩溃后重复 task/测试/消息 | P2/P6/P9 |
| 10 | 用户 skill 越权工具 | P4 |
| 11 | mentor 跨 direction 抢占 | P1/P3 |
| 12 | best 引用旧候选/旧 skill 记录 | P1/P6 |

---

## 6. 风险与既定决策

| 风险/决策 | 处理 |
| --- | --- |
| 旧 `LabService` 渐进改造会拖死新架构 | 新包并行；旧代码冻结；只复用适配器/资源 |
| 双包过渡导致新代码依赖旧包 | `tests/architecture/test_import_boundaries.py` 硬门禁；P8 删除 |
| ACL 只写在 prompt | 工具层不存在 board 工具 + 应用层对象级校验 + 审计 |
| 先做 UI/多 mentor 导致返工 | 先 P6 单算子 fake 闭环，再 P7 UI、P9 规模 |
| 跨库共享事务 | registry/journal/hardware 用幂等命令 + outbox/补偿；不承诺跨库原子 |
| fake 通过被当真实验收 | P9 必须真实模型 + 实际 CANN；fake 结果只证明契约 |
| TestRecord zip 后补 | P5 先冻结 manifest/checksums/审计记录 schema |
| 旧 simulator 行为漂移 | P0 characterization tests + P5 合同测试 |
| 预算/最终验证预留最后补 | P1 类型、P2 ledger、P6 强制预留与结算 |
| 恢复时自动重跑 | 所有 Task/Agent 中断为终态；只允许新 Task/新 session 显式恢复 |

---

## 7. 进度记录

| 日期 | 任务号/里程碑 | 状态 | 证据（命令/测试/commit） | 阻塞 |
| --- | --- | --- | --- | --- |
| 2026-10-21 | P0-01..P0-07 | 完成并迁移到 `Refactor/` | 旧基线 229 passed / 2 skipped；新项目本地 18 passed（含 `../JustKernel` characterization）；干净 checkout 模拟 14 passed；relocation `b60e6e4`；mypy success；ruff check/format clean；证据见 `docs/refactor/p0-exit-report.txt`、`docs/refactor/relocation-report.md` | 无 |

---

## 8. 下一步

P0 已完成。下一步：写 `plan-01-foundation`（P1 的详细 TDD plan），然后进入 P1 领域模型与执行契约。
