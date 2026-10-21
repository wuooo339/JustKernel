# JustKernel v2 独立重构实施 TODO

> 依据：[SPEC v2.1](SPEC/README.md)（2026-10-21）  
> 工作区：`Refactor/` 是**独立新项目**，与旧实现并列。  
> 状态：P7 进行中；F07-01～F07-05 已完成，下一个 feature：F07-06。所有 feature 只有在测试通过、提交并推送后才能标为 `done`。  
> 唯一架构事实来源：`SPEC/`。不使用旧实现的标准、旧测试或旧兼容结论。

---

## 0. 工作区边界

1. **独立实现**  
   `Refactor/` 从零建立 `justkernel` 项目；不复制、不 import 旧 `aworker` 代码，不运行旧测试，不以旧实现行为作为验收标准。
2. **并列关系**  
   同级 `../JustKernel/` 是旧项目，仅作为外部参考；新项目对它的存在不敏感，删除它也不影响新项目构建/测试。
3. **SPEC 驱动**  
   所有领域规则、角色、ACL、状态机、存储、测试记录、预算与验收都以 `SPEC/` 为准；SPEC 未规定的实现细节由 plan 决策并记录。
4. **先测试后实现**  
   每个 feature 先写失败测试，再写最小实现；没有观察过失败的功能代码不算完成。
5. **每个 feature 推送**  
   完成一个 feature 后：目标测试 + 全量测试 + mypy + ruff → commit → push 到 `origin/refactor` → 更新 feature log。

---

## 1. 每个 feature 的固定流程

1. 选择依赖已全部 `done` 的 `todo` feature，把状态改为 `in_progress`。
2. 在 `docs/superpowers/plans/` 写该 feature 的可执行 plan：文件、接口、失败测试、实现步骤、验证命令、提交点。
3. **RED**：写失败测试，运行并确认失败原因是功能缺失，而不是拼写/导入/环境错误。
4. **GREEN**：写最小实现，只让目标测试通过。
5. **REFACTOR**：保持测试绿，清理重复与命名，不扩大行为范围。
6. **验证**：
   ```bash
   uv run pytest -q <target tests>
   uv run pytest -q
   uv run mypy src/justkernel
   uv run ruff check src tests
   uv run ruff format --check src tests
   ```
7. **提交**：`feat(<feature-id>): <summary>`；同一提交把 TODO 状态改为 `done`，写明测试命令/结果。
8. **推送**：`scripts/push_refactor.sh`，并确认 `origin/refactor` 包含该 commit。
9. **记录**：在 `docs/refactor/feature-log.md` 追加 feature、commit、测试结果、远端 commit。

状态：`todo` / `in_progress` / `done` / `blocked`。同一时间只允许一个 `in_progress`。

---

## 2. 全局约束

- Python `3.13+`；`uv` 管理依赖；`pytest` 测试；`ruff` lint/format；`mypy` 检查 `src/justkernel`。
- 最终发行包、CLI、模块只暴露 `justkernel`；不创建 `aworker` 兼容层。
- 一个 Cluster 恰好一个 Operator、一个 supervisor；活动 agent 总数 ≤ `max_agents`（默认 100）。
- 角色固定：`SUPERVISOR` / `CONSULTANT` / `MENTOR` / `OPTIMIZER` / `TESTER` / `PROFILER`。
- ACL 在工具层和应用层同时强制；worker 工具集中不得存在任何 board 工具。
- 领域状态只写 SQLite/制品库；禁止用可变 JSON 文件保存 board/task/candidate 等领域状态。
- 消息/任务/租约/记录都有稳定 ID 和幂等键；至少一次投递 + 接收方去重。
- 只有完整执行、`executed=true`、`coverage=FULL`、`outcome=PASS` 的 TEST 记录才能建立 baseline 或参与 best 最终验证。
- TestRecord zip 是必交付制品；未执行候选在收敛前必须有 `executed=false`、`coverage=NONE` 的审计记录。
- 设备租约跨集群全局唯一；TTL 过期不等于物理执行停止，无法确认则隔离设备。
- 密钥、私有推理、绝对私有路径不得进入 prompt/tool result/board/日志/导出。
- 领域文件 ≤ 300 行；应用服务 ≤ 400 行；adapter ≤ 600 行；前端模块 ≤ 400 行；单函数 ≤ 40 行。
- 默认只监听 `127.0.0.1:4173`；本地优先、受信环境，不提供恶意代码沙箱。

---

## 3. 目标目录

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
│   ├── persistence/         # SQLite、事件、投影、迁移、registry、recovery
│   ├── artifacts/           # 内容寻址 zip/source
│   ├── runtime/             # Deep Agents runner、进程池、checkpoint
│   ├── bus/                 # 本地消息总线/A2A
│   ├── tools/               # 编译/测试/profile 后端
│   ├── hardware/            # 设备队列/租约
│   ├── models/              # 模型档案/provider/路由
│   ├── http/                # API/SSE
│   └── security/            # 脱敏
├── bootstrap/               # 组合根、CLI、迁移、恢复
├── resources/{skills,templates}/
└── web/                     # 原生 ES Modules 前端
```

```text
tests/
├── unit/            # 纯领域
├── application/     # 用例 + fakes
├── adapters/        # SQLite/制品/总线/runtime/tool backend
├── integration/     # control + fake runtime + fake hardware + HTTP/SSE
├── architecture/    # 依赖、无副作用、文件规模
├── web/             # reducer/selectors/format
└── e2e/             # demo/回放/完整假集群
```

---

## 4. Feature 路线图

### 4.1 P0 独立项目初始化

| ID | Feature | SPEC | 依赖 | 验收测试 | 状态 |
| --- | --- | --- | --- | --- | --- |
| F00-01 | 独立工作区边界：清理旧代码/旧测试/旧文档，README 声明独立实现 | 03 §2、12 §1 | — | `test ! -d src/aworker`；`test ! -d tests/characterization`；README 明确不依赖 `../JustKernel`；commit `df324b3` | done |
| F00-02 | `pyproject.toml`、最小 `justkernel` 包、依赖基线、`uv.lock` | 03 §2、12 §7 | F00-01 | `uv sync --locked`；`python -c "import justkernel"`；`uv build` 只产出 `justkernel`；commit `3e75f84` | done |
| F00-03 | 包骨架与 CLI scaffold | 03 §2 | F00-02 | `tests/unit/test_cli.py` 3 passed；`justkernel --version`；commit `4d9ef9e` | done |
| F00-04 | 架构门禁：import 边界、文件/函数规模、import 无副作用 | 03 §3、11 §8 | F00-03 | `tests/architecture` 11 passed；全量 15 passed；`rg "aworker" src tests` 为空；commit `f0b0cdc` | done |
| F00-05 | CI：ruff + mypy + pytest + build | 11 §9 | F00-04 | `.github/workflows/ci.yml`；本地等价命令全绿；commit `5998bf2` | done |
| F00-06 | 基础决策与 feature log 模板 | 03、12 | F00-05 | `docs/refactor/decision-log.md`、`feature-log.md`、`p0-exit-report.md`；无 TBD；commit `2888b3d` | done |

### 4.2 P1 领域模型与执行契约

| ID | Feature | SPEC | 依赖 | 验收测试 | 状态 |
| --- | --- | --- | --- | --- | --- |
| F01-01 | Shared primitives：ID/Digest/Clock/规范 JSON/错误/Principal/ProjectPath | 04 §3、13 §1 | F00-06 | `tests/unit/shared/` 19 passed；全量 34 passed；mypy/ruff clean；commit `7c6986c` | done |
| F01-02 | 执行契约：OperatorSpec、TaskContext、Budget/Evaluation/Wake/ModelRouting | 13 §1–3 | F01-01 | `tests/unit/test_contracts.py` 13 passed；全量 47 passed；mypy/ruff clean；commit `07549d4` | done |
| F01-03 | Cluster 与 Direction 聚合、phase/state | 04 §4.1、§4.3 | F01-02 | `tests/unit/cluster/` 11 passed；全量 58 passed；状态机/终态校验；commit `fa78426` | done |
| F01-04 | Agent/Role 聚合与生命周期 | 04 §4.2、05 §2 | F01-02 | `tests/unit/agent/` 10 passed；全量 68 passed；worker mentor/终态/恢复；commit `8854571` | done |
| F01-05 | Task 聚合与四种 kind | 04 §4.4、06 §7 | F01-03/04 | `tests/unit/task/` 10 passed；全量 78 passed；kind 约束/终态结果；commit `daed2a1` | done |
| F01-06 | Candidate DAG 与 BestSelection | 04 §4.5、07 §2/§7 | F01-03/05 | `tests/unit/candidate/` 13 passed；全量 91 passed；不可变/无环/PENDING→VALIDATED；commit `494046d` | done |
| F01-07 | TestRecord、HardwareLease、ExplorationReport 聚合 | 04 §4.6–4.8、07 §3 | F01-05 | `tests/unit/testing/`、`tests/unit/report/` 17 passed；全量 108 passed；commit `c78099c` | done |
| F01-08 | ACL、能力矩阵、Message 信封与路由 | 04 §2/§6、05 §5、06 §2–3 | F01-04/07 | `tests/unit/comm/` 23 passed；全量 131 passed；worker 无 board 工具；commit `b5b5bc4` | done |
| F01-09 | 跨聚合不变量、事件、稳定错误码 | 04 §5、06 §11 | F01-03..08 | `test_invariants.py`、`test_events.py`、`test_error_codes.py`、`test_inbox.py` 16 passed；全量 147 passed；commit `8c08d45` + error-code registry follow-up | done |

### 4.3 P2 持久化、事件、制品与全局服务

| ID | Feature | SPEC | 依赖 | 验收测试 | 状态 |
| --- | --- | --- | --- | --- | --- |
| F02-01 | journal schema、迁移器、部分唯一索引、事件触发器 | 08 §3/§12 | F01-09 | `tests/adapters/test_schema.py` 8 passed；全量 155 passed；commit `5ddaf51` | done |
| F02-02 | 仓储、UnitOfWork、事件 append、outbox | 08 §3/§6 | F02-01 | `tests/adapters/test_uow_events.py` 5 passed；全量 160 passed；commit `baeb079` | done |
| F02-03 | 内容寻址制品库 | 08 §4 | F02-01 | `tests/adapters/test_artifact_store.py` 7 passed；全量 168 passed；commit `fe99061` | done |
| F02-04 | 投影与回放 | 08 §5 | F02-02 | `tests/adapters/test_projections.py` 3 passed；全量 171 passed；live/replay 一致；commit `7843d76` | done |
| F02-05 | 全局 operator registry | 08 §11 | F02-01 | `tests/adapters/test_registry.py` 8 passed；全量 179 passed；commit `b044126` | done |
| F02-06 | 全局设备账本与 fencing | 08 §11 | F02-01 | `tests/adapters/test_hardware_ledger.py` 9 passed；全量 188 passed；commit `a8a88e5` | done |
| F02-07 | 启动恢复矩阵 | 08 §7 | F02-02..06 | `tests/adapters/test_recovery.py` 2 passed；全量 190 passed；Agent/Task/Lease/Cluster；commit `cc558e1` | done |
| F02-08 | SQLite/全局服务适配器套件 | 11 §6 | F02-01..07 | `tests/adapters` 43 passed；跨适配器套件 1 passed；全量 191 passed；commit `4c2818b` | done |

### 4.4 P3 应用用例、端口与 Fakes

| ID | Feature | SPEC | 依赖 | 验收测试 | 状态 |
| --- | --- | --- | --- | --- | --- |
| F03-01 | 端口定义与确定性 fakes | 03 §3.1、11 §5 | F02-08 | `tests/application/test_ports_fakes.py` 7 passed；全量 198 passed；commit `8ac9def` | done |
| F03-02 | Cluster 生命周期用例 | 04 §4.1、06 §5/§8 | F03-01 | `tests/application/test_cluster_lifecycle.py` 5 passed；全量 203 passed；commit `f7a04a0` | done |
| F03-03 | Agent/worker 生命周期与任务派发 | 04 §4.2、06 §6–7 | F03-01 | `tests/application/test_worker_lifecycle.py` 6 passed；全量 209 passed；commit `906390d` | done |
| F03-04 | Candidate 提交与导入用例 | 04 §4.5、13 §2 | F03-01 | `tests/application/test_candidate_commit.py` 7 passed；全量 216 passed；commit `538b247` | done |
| F03-05 | ToolJob/TestRecord 封存用例 | 13 §5、08 §6 | F03-01 | `tests/application/test_testing_flow.py` 5 passed；全量 221 passed；commit `cd11af8` | done |
| F03-06 | BestSelection/报告/预算用例 | 07 §7、13 §6–7 | F03-02/05 | `tests/application/test_best_report.py` 6 passed；全量 227 passed；commit `de3cf5d` | done |
| F03-07 | 应用层 ACL/归属/幂等测试 | 11 §5 | F03-02..06 | `tests/application/test_object_acl.py` 6 passed；全量 233 passed；commit `869f099` | done |

### 4.5 P4 Agent 运行时、Skills 与工具权限

| ID | Feature | SPEC | 依赖 | 验收测试 | 状态 |
| --- | --- | --- | --- | --- | --- |
| F04-01 | ModelProfile、provider 路由、fallback | 05 §7、13 §9 | F03-01 | `tests/application/test_model_routing.py` 6 passed；全量 239 passed；commit `704710c` | done |
| F04-02 | Deep Agents runner、检查点、Agent 池 | 05 §2–3 | F04-01 | `tests/adapters/test_runtime_pool.py` 7 passed；全量 246 passed；commit `a5df37f` | done |
| F04-03 | Skill 加载与安全校验 | 05 §6 | F04-01 | `tests/unit/agent/test_skills.py` 7 passed；全量 253 passed；commit `d999243` | done |
| F04-04 | 六角色 skills + 内置 tester/profiler | 05 §6.4 | F04-03 | `tests/unit/agent/test_role_skills.py` 3 passed；全量 256 passed；commit `0c30d71` | done |
| F04-05 | 工具注册表与对象级 ACL | 05 §5 | F04-03 | `tests/unit/agent/test_tool_matrix.py` 6 passed；全量 262 passed；commit `a2c50f4` | done |
| F04-06 | 运行时生命周期与 100 agent 上限 | 05 §2–3、11 §8 | F04-02/05 | `tests/integration/test_agent_lifecycle.py` 3 passed；无孤儿/租约；全量 265 passed；commit `4f002c7` | done |

### 4.6 P5 证据链：候选、TestRecord、ToolJob、硬件队列

| ID | Feature | SPEC | 依赖 | 验收测试 | 状态 |
| --- | --- | --- | --- | --- | --- |
| F05-01 | 异步 ToolJob 服务 | 13 §5 | F03-05、F04-05 | `tests/application/test_tool_job.py` 7 passed；幂等/冲突/超时；全量 272 passed；commit `92c8768` | done |
| F05-02 | 硬件队列、租约、TTL、fencing | 07 §6、08 §11 | F02-06、F05-01 | `tests/adapters/test_hardware_queue.py` 6 passed；独占/TTL/隔离；全量 278 passed；commit `dff7b7e` | done |
| F05-03 | TestRecord zip 构建/校验/审计记录 | 07 §3 | F05-01 | `tests/unit/testing/test_record_zip.py` 12 passed；缺文件/哈希/未执行；全量 290 passed；commit `dca59d4` | done |
| F05-04 | CANN simulation backend + fake | 07 §4、13 §5 | F05-01 | `tests/adapters/test_cann_backend.py` 7 passed；合同/环境指纹；全量 297 passed；commit `cdbe123` | done |
| F05-05 | TaskContext 与只读 artifact grants | 13 §3 | F05-01 | `tests/application/test_task_context.py` 7 passed；越权/过期；全量 304 passed；commit `9c83732` | done |
| F05-06 | 证据链测试：候选→job→zip→记录 | 07 §3、11 §3 | F05-01..05 | `tests/application/test_evidence_chain.py` 4 passed；无 fake PASS；全量 308 passed；commit `74b40ee` | done |

### 4.7 P6 生成/导入、反馈与闭环编排

| ID | Feature | SPEC | 依赖 | 验收测试 | 状态 |
| --- | --- | --- | --- | --- | --- |
| F06-01 | OperatorSpec 启动校验与集群启动 | 13 §1、06 §5 | F05-06 | `tests/application/test_start_cluster.py` 7 passed；422/409；全量 315 passed；commit `d5431f1` | done |
| F06-02 | GENERATE/IMPORT 与根候选 | 13 §2 | F06-01 | `tests/application/test_bootstrap_modes.py` 4 passed；根候选/system 作者；全量 319 passed；commit `3d81a00` | done |
| F06-03 | baseline 建立与 bootstrap 预算 | 13 §2/§7 | F06-02 | `tests/application/test_baseline.py` 6 passed；完整 PASS/预算耗尽；全量 325 passed；commit `5f806a9` | done |
| F06-04 | 反馈包与换 worker 续接 | 13 §3 | F06-03 | `tests/application/test_feedback_handoff.py` 4 passed；QA-17；全量 329 passed；commit `4e406cb` | done |
| F06-05 | Inbox/wake/单 Turn/WAIT/debounce | 13 §4 | F06-01 | `tests/application/test_wake_scheduler.py` 7 passed；重复事件/WAIT；全量 336 passed；commit `975ab81` | done |
| F06-06 | watchdog、停滞与暂停 | 13 §4 | F06-05 | `tests/application/test_watchdog.py` 6 passed；合法 WAIT 不误报；全量 342 passed；commit `388ee6d` | done |
| F06-07 | 预算、plateau、重复候选 | 13 §7 | F06-03 | `tests/application/test_budget.py` 6 passed；最终验证预留；全量 348 passed；commit `89a2861` | done |
| F06-08 | 收敛、BestSelection、报告 | 07 §7、13 §6 | F06-03/07 | `tests/application/test_convergence.py` 2 passed；失败提名不覆盖旧 best；全量 350 passed；commit `d3e12b5` | done |
| F06-09 | 暂停/恢复与迟到结果 | 13 §8 | F06-05 | `tests/application/test_resume.py` 5 passed；不自动重跑；全量 355 passed；commit `aedbbe7` | done |
| F06-10 | fake 闭环验收 | 13 §10 | F06-01..09 | `tests/e2e/test_fake_closed_loop.py` 8 passed；13 §10 1–9；全量 363 passed；commit `5b3e490` | done |

### 4.8 P7 API、SSE、A2A 与前端

| ID | Feature | SPEC | 依赖 | 验收测试 | 状态 |
| --- | --- | --- | --- | --- | --- |
| F07-01 | API 骨架、DTO、错误码、幂等键 | 09 §1/§4 | F06-10 | `tests/integration/test_api_contract.py` 6 passed；problem+json/幂等；全量 369 passed；commit `d396cfa` | done |
| F07-02 | Cluster/Agent/Board/Task/Candidate/Record/Hardware/Report 路由 | 09 §2 | F07-01 | `tests/integration/test_routes.py` 7 passed；对象级 ACL；全量 376 passed；commit `b95a7ee` | done |
| F07-03 | SSE 与回放 | 09 §5 | F07-01 | `tests/integration/test_sse.py` 4 passed；Last-Event-ID；全量 380 passed；commit `ef79b6f` | done |
| F07-04 | A2A cluster gateway | 09 §3 | F07-01 | `tests/integration/test_a2a.py` 4 passed；不能写 worker channel；全量 384 passed；commit `4ceb6bc` | done |
| F07-05 | 脱敏、导出、下载 ACL | 10 §2、09 §9 | F07-02 | `tests/integration/test_redaction.py` 3 passed；全量 387 passed；commit `3266ebd` | done |
| F07-06 | Web state/reducer/selectors | 09 §6/§7 | F07-01 | `tests/web/reducer.test.js`、`selectors.test.js` | todo |
| F07-07 | Web 视图与可访问性 | 09 §6 | F07-06 | `tests/web/views.test.js`；best/PENDING/失败可见 | todo |
| F07-08 | Demo/replay fixture | 09 §6 | F07-06 | `tests/e2e/test_demo_mode.py`；无模型/设备 | todo |

### 4.9 P8 迁移、配置与清理

| ID | Feature | SPEC | 依赖 | 验收测试 | 状态 |
| --- | --- | --- | --- | --- | --- |
| F08-01 | SPEC 要求的旧数据只读导入与 LEGACY 标记 | 08 §9、12 §1 | F02-08 | `tests/adapters/test_legacy_import.py`；合成 fixture，不依赖旧代码/旧测试 | todo |
| F08-02 | CLI 模式与配置 | 10 §1、12 §5 | F07-08 | `tests/integration/test_cli_modes.py` | todo |
| F08-03 | 数据目录、权限、单服务锁 | 08 §2、10 §2 | F02-03 | `tests/adapters/test_data_root.py` | todo |
| F08-04 | 新项目无旧引用：无 `aworker` import/CLI/env 分支 | 12 §5 | F08-01..03 | `tests/architecture/test_no_legacy.py`；`rg "aworker" src tests` 为空 | todo |
| F08-05 | 打包、依赖、供应链检查 | 12 §5、11 §9 | F08-04 | `uv build`；wheel/sdist 只含 justkernel | todo |
| F08-06 | 迁移/兼容验收 | 12 §4 | F08-01..05 | `tests/e2e/test_migration.py` | todo |

### 4.10 P9 加固、规模与真实验收

| ID | Feature | SPEC | 依赖 | 验收测试 | 状态 |
| --- | --- | --- | --- | --- | --- |
| F09-01 | 混沌/恢复演练 | 11 §7 | F08-06 | `tests/chaos/`；kill -9/设备断开/磁盘满 | todo |
| F09-02 | 约 100 agent 规模与长跑 | 01 §3、12 §4 | F08-06 | `tests/e2e/test_scale_100.py`；无孤儿/租约泄漏 | todo |
| F09-03 | 多模型路由验收 | 13 §9 | F08-06 | `tests/e2e/test_model_routing.py`；换模不丢反馈 | todo |
| F09-04 | 真实 CANN + 真实模型闭环 | 13 §10 | F09-01..03 | `tests/e2e/test_real_acceptance.py`；证据 zip | todo |
| F09-05 | 安全、可观测性、运行手册 | 10 §3–5 | F09-04 | 审计/脱敏/指标/手册检查 | todo |
| F09-06 | 最终验收报告 | 12 §4、13 §10 | F09-01..05 | `docs/refactor/final-acceptance.md`；15 场景 + 10 闭环 | todo |

---

## 5. 推送约定

- 远端：`origin` = `https://github.com/wuooo339/JustKernel.git`
- 目标分支：`refactor`
- 本地分支：`refactor/justkernel-v2`（`Refactor/` worktree）
- 每个 feature 完成后运行：
  ```bash
  scripts/push_refactor.sh
  ```
  脚本临时切换到有写权限的 GitHub 账号 `gresces`，推送后恢复默认账号 `secserg`；不输出 token。
- 推送前必须满足：目标测试通过、全量测试通过、`mypy`/`ruff` 干净。
- 推送失败时不得把 TODO 标为 `done`；记录失败原因并重试。

---

## 6. Feature 完成定义

一个 feature 只有同时满足以下条件才算 `done`：

- [ ] 失败测试先存在，并确认失败原因正确。
- [ ] 目标测试通过。
- [ ] 全量 `uv run pytest -q` 通过。
- [ ] `uv run mypy src/justkernel` 通过。
- [ ] `uv run ruff check src tests` 与 `uv run ruff format --check src tests` 通过。
- [ ] TODO 中状态为 `done`，写明测试证据。
- [ ] commit 已创建。
- [ ] `origin/refactor` 已包含该 commit。
- [ ] `docs/refactor/feature-log.md` 已记录。

---

## 7. 进度记录

| 日期 | Feature | 状态 | 测试证据 | Commit / Push |
| --- | --- | --- | --- | --- |
| 2026-10-21 | F00-01 | done | 无旧 `src`/`tests`；README 声明独立；SPEC/TODO 保留 | `df324b3` / `origin/refactor` @ `df324b3` |
| 2026-10-21 | F00-02 | done | `uv sync --locked`；`pytest tests/unit/test_package_identity.py` 1 passed；mypy/ruff clean；`uv build` 产出 justkernel wheel | `3e75f84` / `origin/refactor` @ `0f3a4a9` |
| 2026-10-21 | F00-03 | done | `pytest tests/unit/test_cli.py` 3 passed；mypy/ruff clean；`justkernel --version`；`uv build` 成功 | `4d9ef9e` / `origin/refactor` @ `2f4a7cd` |
| 2026-10-21 | F00-04 | done | `tests/architecture` 11 passed；全量 15 passed；mypy/ruff clean；无 legacy 引用 | `f0b0cdc` / `origin/refactor` @ `840e852` |
| 2026-10-21 | F00-05 | done | CI 工作流；本地 ruff/mypy/pytest 15 passed/build 全绿 | `5998bf2` / `origin/refactor` @ `5f1d2db` |
| 2026-10-21 | F00-06 | done | 决策日志 D-001..D-010；feature log；P0 exit report；全量 15 passed | `2888b3d` / `origin/refactor` |
| 2026-10-21 | F01-01 | done | shared tests 19 passed；全量 34 passed；mypy/ruff clean；clock 决策 D-011 | `7c6986c` / `origin/refactor` @ `8b9f0f0` |
| 2026-10-21 | F01-02 | done | contract tests 13 passed；全量 47 passed；mypy/ruff clean；D-012 | `07549d4` / `origin/refactor` @ `2d0ed14` |
| 2026-10-21 | F01-03 | done | cluster tests 11 passed；全量 58 passed；mypy/ruff clean；D-013 | `fa78426` / `origin/refactor` @ `0f190c4` |
| 2026-10-21 | F01-04 | done | agent tests 10 passed；全量 68 passed；mypy/ruff clean；D-014 | `8854571` / `origin/refactor` @ `4a9486f` |
| 2026-10-21 | F01-05 | done | task tests 10 passed；全量 78 passed；mypy/ruff clean；D-015 | `daed2a1` / `origin/refactor` @ `e492c94` |
| 2026-10-21 | F01-06 | done | candidate tests 13 passed；全量 91 passed；mypy/ruff clean；D-016 | `494046d` / `origin/refactor` @ `96f3bbb` |
| 2026-10-21 | F01-07 | done | record/lease/report tests 17 passed；全量 108 passed；mypy/ruff clean；D-017 | `c78099c` / `origin/refactor` @ `0476eb4` |
| 2026-10-21 | F01-08 | done | comm tests 23 passed；全量 131 passed；mypy/ruff clean；D-018 | `b5b5bc4` / `origin/refactor` @ `468f3e5` |
| 2026-10-21 | F01-09 | done | invariants/events/error-codes/inbox 16 passed；全量 147 passed；mypy/ruff clean；D-019 | `8c08d45` (+ registry fix) / `origin/refactor` @ `b09ae4f` |
| 2026-10-21 | F02-01 | done | schema tests 8 passed；全量 155 passed；mypy/ruff clean；D-020 | `5ddaf51` / `origin/refactor` @ `6d75319` |
| 2026-10-21 | F02-02 | done | UoW/event/outbox tests 5 passed；全量 160 passed；mypy/ruff clean；D-021 | `baeb079` / `origin/refactor` @ `7c91cf9` |
| 2026-10-21 | F02-03 | done | artifact tests 7 passed + error test 1；全量 168 passed；mypy/ruff clean；D-022 | `fe99061` / `origin/refactor` @ `d0c8560` |
| 2026-10-21 | F02-04 | done | projection tests 3 passed；全量 171 passed；live/replay snapshot 一致；D-023 | `7843d76` / `origin/refactor` @ `25b7e93` |
| 2026-10-21 | F02-05 | done | registry tests 8 passed；全量 179 passed；mypy/ruff clean；D-024 | `b044126` / `origin/refactor` @ `d3e3303` |
| 2026-10-21 | F02-06 | done | hardware ledger tests 9 passed；全量 188 passed；mypy/ruff clean；D-025 | `a8a88e5` / `origin/refactor` @ `4e01e03` |
| 2026-10-21 | F02-07 | done | recovery tests 2 passed；全量 190 passed；mypy/ruff clean；D-026 | `cc558e1` / `origin/refactor` @ `8a065f9` |
| 2026-10-21 | F02-08 | done | adapters 43 passed；全量 191 passed；mypy/ruff clean；跨适配器 suite | `4c2818b` / `origin/refactor` @ `08a382d` |
| 2026-10-21 | F03-01 | done | ports/fakes tests 7 passed；全量 198 passed；mypy/ruff clean；D-027 | `8ac9def` / `origin/refactor` @ `d576d36` |
| 2026-10-21 | F03-02 | done | cluster lifecycle tests 5 passed；全量 203 passed；mypy/ruff clean；D-028 | `f7a04a0` / `origin/refactor` @ `bcc5acf` |
| 2026-10-21 | F03-03 | done | worker lifecycle tests 6 passed；全量 209 passed；mypy/ruff clean；D-029 | `906390d` / `origin/refactor` @ `d2b2652` |
| 2026-10-21 | F03-04 | done | candidate tests 7 passed；全量 216 passed；mypy/ruff clean；D-030 | `538b247` / `origin/refactor` @ `b371668` |
| 2026-10-21 | F03-05 | done | testing flow tests 5 passed；全量 221 passed；mypy/ruff clean；D-031 | `cd11af8` / `origin/refactor` @ `f0e33ce` |
| 2026-10-21 | F03-06 | done | best/report/budget tests 6 passed；全量 227 passed；mypy/ruff clean；D-032 | `de3cf5d` / `origin/refactor` @ `815293c` |
| 2026-10-21 | F03-07 | done | ACL/ownership/idempotency tests 6 passed；全量 233 passed；mypy/ruff clean | `869f099` / `origin/refactor` @ `41f14af` |
| 2026-10-21 | F04-01 | done | model routing tests 6 passed；全量 239 passed；mypy/ruff clean；D-033 | `704710c` / `origin/refactor` @ `76220a1` |
| 2026-10-21 | F04-02 | done | runtime pool tests 7 passed；全量 246 passed；mypy/ruff clean；D-034 | `a5df37f` / `origin/refactor` @ `e472e90` |
| 2026-10-21 | F04-03 | done | skill tests 7 passed；全量 253 passed；mypy/ruff clean；D-035 | `d999243` / `origin/refactor` @ `19c64c6` |
| 2026-10-21 | F04-04 | done | role-skills tests 3 passed；全量 256 passed；mypy/ruff clean；D-036 | `0c30d71` / `origin/refactor` @ `053f1d1` |
| 2026-10-21 | F04-05 | done | tool-registry tests 6 passed；全量 262 passed；mypy/ruff clean；D-037 | `a2c50f4` / `origin/refactor` |
| 2026-10-21 | F04-06 | done | lifecycle tests 3 passed；全量 265 passed；mypy/ruff clean；D-038；P4 exit report | `4f002c7` / `origin/refactor` |
| 2026-10-21 | F05-01 | done | tool-job tests 7 passed；全量 272 passed；mypy/ruff clean；D-039 | `92c8768` / `origin/refactor` |
| 2026-10-21 | F05-02 | done | hardware-queue tests 6 passed；全量 278 passed；mypy/ruff clean；D-040 | `dff7b7e` / `origin/refactor` |
| 2026-10-21 | F05-03 | done | record-zip tests 12 passed；全量 290 passed；mypy/ruff clean；D-041 | `dca59d4` / `origin/refactor` |
| 2026-10-21 | F05-04 | done | cann backend tests 7 passed；全量 297 passed；mypy/ruff clean；D-042 | `cdbe123` / `origin/refactor` |
| 2026-10-21 | F05-05 | done | task-context tests 7 passed；全量 304 passed；mypy/ruff clean；D-043 | `9c83732` / `origin/refactor` |
| 2026-10-21 | F05-06 | done | evidence-chain tests 4 passed；全量 308 passed；mypy/ruff clean；D-044；P5 exit report | `74b40ee` / `origin/refactor` |
| 2026-10-21 | F06-01 | done | startup tests 7 passed；全量 315 passed；mypy/ruff clean；D-045 | `d5431f1` / `origin/refactor` |
| 2026-10-21 | F06-02 | done | bootstrap tests 4 passed；全量 319 passed；mypy/ruff clean；D-046 | `3d81a00` / `origin/refactor` |
| 2026-10-21 | F06-03 | done | baseline tests 6 passed；全量 325 passed；mypy/ruff clean；D-047 | `5f806a9` / `origin/refactor` |
| 2026-10-21 | F06-04 | done | feedback-handoff tests 4 passed；全量 329 passed；mypy/ruff clean；D-048 | `4e406cb` / `origin/refactor` |
| 2026-10-21 | F06-05 | done | wake-scheduler tests 7 passed；全量 336 passed；mypy/ruff clean；D-049 | `975ab81` / `origin/refactor` |
| 2026-10-21 | F06-06 | done | watchdog tests 6 passed；全量 342 passed；mypy/ruff clean；D-050 | `388ee6d` / `origin/refactor` |
| 2026-10-21 | F06-07 | done | budget tests 6 passed；全量 348 passed；mypy/ruff clean；D-051 | `89a2861` / `origin/refactor` |
| 2026-10-21 | F06-08 | done | convergence tests 2 passed；全量 350 passed；mypy/ruff clean；D-052 | `d3e12b5` / `origin/refactor` |
| 2026-10-21 | F06-09 | done | resume tests 5 passed；全量 355 passed；mypy/ruff clean；D-053 | `aedbbe7` / `origin/refactor` |
| 2026-10-21 | F06-10 | done | e2e tests 8 passed；全量 363 passed；mypy/ruff clean；D-054；P6 exit report | `5b3e490` / `origin/refactor` |
| 2026-10-21 | F07-01 | done | API contract tests 6 passed；全量 369 passed；mypy/ruff clean；D-055 | `d396cfa` / `origin/refactor` |
| 2026-10-21 | F07-02 | done | route tests 7 passed；全量 376 passed；mypy/ruff clean；D-056 | `b95a7ee` / `origin/refactor` |
| 2026-10-21 | F07-03 | done | SSE/replay tests 4 passed；全量 380 passed；mypy/ruff clean；D-057 | `ef79b6f` / `origin/refactor` |
| 2026-10-21 | F07-04 | done | A2A tests 4 passed；全量 384 passed；mypy/ruff clean；D-058 | `4ceb6bc` / `origin/refactor` |
| 2026-10-21 | F07-05 | done | redaction tests 3 passed；全量 387 passed；mypy/ruff clean；D-059 | `3266ebd` / `origin/refactor` |

---

## 8. 下一步

从 **F07-06 Web state/reducer/selectors** 开始：

1. 写 `docs/superpowers/plans/2026-10-21-f07-06-web-state.md`。
2. 按 RED→GREEN→验证→commit→push 执行。
3. 更新本文件与 `docs/refactor/feature-log.md`。
