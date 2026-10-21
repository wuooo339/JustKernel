# 10 配置、安全与可观测性

> 上层：[09-api-and-frontend.md](09-api-and-frontend.md)  
> 下层：[11-testing-and-quality.md](11-testing-and-quality.md)

---

## 1. 配置模型

```python
@dataclass(frozen=True)
class AppConfig:
    mode: Literal["cluster", "demo", "worker", "migrate"]
    data_root: Path
    private_root: Path
    host: str
    port: int
    log_level: str

@dataclass(frozen=True)
class ClusterConfig:
    operator: OperatorRef          # 包含 OperatorSpec 版本/摘要
    start_mode: Literal["GENERATE", "IMPORT"]
    baseline_source: Path | None    # 仅 IMPORT 必填
    continued_from_cluster_id: str | None
    budget: BudgetPolicy
    evaluation_policy: EvaluationPolicy
    wake_policy: WakePolicy
    max_agents: int                 # 默认 100
    max_workers_per_mentor: int
    initial_mentors: int
    initial_consultants: int
    # 轮次/时长上限统一读取 budget，不维护第二份同名限额

@dataclass(frozen=True)
class RoleConfig:
    model_profile: str
    skills: list[str]               # skill source paths
    prompt_version: int
    max_turns: int | None

@dataclass(frozen=True)
class LimitsConfig:
    model_concurrency: int
    runtime_processes: int
    max_agents: int
    max_workers_per_mentor: int
    max_task_duration_s: int
    max_turn_duration_s: int
    max_message_attempts: int
    queue_timeout_s: int

@dataclass(frozen=True)
class SkillsConfig:
    base_dir: Path
    builtin_dir: Path
    user_dir: Path
    allow_user_scripts: bool

@dataclass(frozen=True)
class HardwareConfig:
    devices: list[DeviceProfile]
    queue_policy: Literal["fifo", "priority"]
    default_lease_ttl_s: int
    max_test_duration_s: int
    max_profile_duration_s: int

@dataclass(frozen=True)
class StorageConfig:
    database: Path
    artifacts: Path
    checkpoints: Path
    retention_days: int
```

规则：

- 配置对象不可变；只有 `platform/config.py` 读环境变量。
- 优先级：CLI > 环境变量 > `.env` > 默认值。
- `start_mode=GENERATE` 允许 baseline_source 为空；IMPORT 必填。两模式都必须校验 OperatorSpec/reference/用例/目标后端，不能用模型猜测补齐。
- `ClusterConfig.max_agents` 是单集群上限，不得超过 `LimitsConfig.max_agents`（全局上限）；两者都校验。
- 启动时校验：路径可写、模型档案存在、skills 目录存在、设备配置合法、agent 上限 ≥ 6（可容纳六角色）；初始角色和按需 worker 总量不得超限。
- 构造函数不建目录；`bootstrap.initialize()` 显式执行。

### 1.1 环境变量

前缀 `JUSTKERNEL_`：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `JUSTKERNEL_MODE` | `cluster` | `cluster/demo/worker/migrate` |
| `JUSTKERNEL_DATA_ROOT` | `.justkernel` | 数据目录 |
| `JUSTKERNEL_PRIVATE_ROOT` | 系统应用数据目录 | 密钥/浏览器临时目录 |
| `JUSTKERNEL_HOST` / `PORT` | `127.0.0.1` / `4173` | 监听 |
| `JUSTKERNEL_MAX_AGENTS` | `100` | 逻辑 agent 上限 |
| `JUSTKERNEL_MAX_WORKERS_PER_MENTOR` | `8` | |
| `JUSTKERNEL_INITIAL_MENTORS` | `4` | |
| `JUSTKERNEL_INITIAL_CONSULTANTS` | `2` | |
| `JUSTKERNEL_MODEL_CONCURRENCY` | `8` | 全局模型并发 |
| `JUSTKERNEL_RUNTIME_PROCESSES` | `8` | Agent 运行时进程池 |
| `JUSTKERNEL_MODELS_FILE` | `models.toml` | 模型档案 |
| `JUSTKERNEL_PROVIDER_KEYS` | `{}` | JSON 密钥引用 |
| `JUSTKERNEL_SKILLS_BASE` | `resources/skills/base` | |
| `JUSTKERNEL_SKILLS_USER` | `resources/skills/user` | |
| `JUSTKERNEL_ALLOW_USER_SCRIPTS` | `false` | 用户 skill 脚本开关 |
| `JUSTKERNEL_DEVICES` | `[]` | JSON 设备列表 |
| `JUSTKERNEL_LEASE_TTL_S` | `600` | 设备租约 TTL |
| `JUSTKERNEL_MAX_TEST_S` | `1800` | |
| `JUSTKERNEL_MAX_PROFILE_S` | `1800` | |

旧 `AWORKER_*` 只允许迁移工具读取，不进入新运行时；不在新代码中保留兼容分支。

---

## 2. 密钥与脱敏

| 密钥 | 可见位置 | 禁止 |
| --- | --- | --- |
| 模型 API Key | provider adapter | prompt/tool result/board/日志/导出 |
| 设备/SSH 密码 | tool adapter | agent/board/日志 |
| 用户 skill 脚本中的密钥 | 不允许 | skill 不应包含密钥 |

- 私有目录 0700，文件 0600；Fernet 加密。
- `Redactor` 统一处理日志、事件、错误、tool result、导出。
- 注册密钥值（长度 ≥8）；替换为 `[redacted]`。
- 不脱敏短字符串/常见词；可疑密钥记录告警但不回显。
- 用户 skill 目录禁止 `.env`/密钥文件；加载时扫描/拒绝。

---

## 3. 威胁模型

| 威胁 | 场景 | 控制 | 残余风险 |
| --- | --- | --- | --- |
| worker 越权读 board | worker prompt 要求读 board | 工具层无 board 工具；ACL 拒绝；事件审计 | 模型可能尝试，但无法成功 |
| consultant 写 board | consultant 试图指挥 | 只读接口；无 post 工具；应用层校验 | 无 |
| mentor 跨 worker 下任务 | 给别的 worker 发 task | 校验 worker.mentor == caller | 无 |
| 提示注入 | board/消息/测试日志含指令 | 数据/指令分离；ACL；supervisor 决策 | 模型可能误判，需审计/报告 |
| 候选代码执行 | optimizer 生成恶意代码 | 受信 Worker；无沙箱；记录/策略 | **无恶意代码隔离**；只支持可信环境 |
| 用户 skill 注入 | skill 指示越权/泄密 | allowed_tools 子集；路径扫描；审计 | 用户自定义 skill 风险自担 |
| 设备滥用 | tester/profiler 绕过队列 | 全局设备服务队列/租约/fencing token；过期须核对物理执行 | 本机管理员可绕过 |
| 重复测试/记录 | 消息重投/重试 | 幂等键；task/record 唯一 | 需正确实现 |
| agent 数量失控 | mentor 无限开 worker | max_agents；open_worker 校验；清理 | 需监控 |
| 数据泄露 | board/导出含私有数据 | ACL/脱敏/导出审批 | 本机管理员可见 |
| 消息伪造 | 外部 A2A 冒充 agent | 网关校验 principal；worker channel 不可外部访问 | 需认证 |
| 供应链 | skill 脚本/依赖 | 固定依赖；脚本开关；审计 | 上游风险 |

**明确限制**：没有容器级恶意代码沙箱；仅支持可信本机/受信集群。公网部署需额外认证/隔离。

---

## 4. 可观测性

### 4.1 日志

```json
{
  "ts": "...",
  "level": "INFO",
  "logger": "orchestration.task",
  "cluster_id": "...",
  "agent_id": "...",
  "mentor_id": "...",
  "task_id": "...",
  "candidate_id": "...",
  "message": "task succeeded",
  "code": "task.succeeded",
  "data": {"kind": "TEST", "outcome": "PASS"}
}
```

- 结构化；带 cluster/agent/task/candidate/record 关联 ID。
- 不记录密钥、私有推理、未脱敏源码/日志。
- 日志轮转；单文件上限/保留数可配置。

### 4.2 指标

`GET /api/v1/system/health` / UI：

| 指标 | 说明 |
| --- | --- |
| `cluster.state` | |
| `agents.active` / `agents.by_role` | 角色数量 |
| `agents.failed_total` | |
| `tasks.running/queued/failed` | |
| `model.calls_active` | |
| `hardware.leased/queued` | 设备 |
| `records.created_total` | |
| `messages.duplicate_total` | |
| `recovery.applied_total` | |

### 4.3 审计事件

- 集群启动/停止/收敛。
- agent 创建/关闭/失败。
- direction 变更。
- task 下发/失败/取消。
- 候选提交/测试/ profile/best。
- lease 获取/释放/过期。
- 用户人工操作（消息/停止/恢复/技能重载）。
- 安全事件（越权/脱敏告警/主机信任）。

---

## 5. 运行手册

### 5.1 Agent 不工作

1. 查看 agent 状态/模型错误。
2. 检查模型密钥/限流。
3. mentor 重开 worker 或重派 task。
4. 不自动重跑旧 Turn。

### 5.2 Worker 无法关闭

1. 查看是否有运行中 task/租约。
2. 取消 task → 等待 → 关闭。
3. 若进程无响应，标记中断并请设备服务核对/停止原 job；确认停止后才清理租约，否则隔离并告警。

### 5.3 设备队列卡住

1. 查看 lease/owner/expires_at。
2. 过期 lease 先标 EXPIRED；核对/停止原执行后才清理 execution_active，无法确认则隔离设备，不能仅按 TTL 重分配。
3. 检查工具服务心跳/设备可用性。

### 5.4 测试记录缺失

1. 查 task 状态/工具错误。
2. 重跑测试产生新记录；不伪造/补写旧记录。
3. 没有记录的候选不能成为 best。

### 5.5 集群收敛失败

1. 检查是否有满足条件的候选。
2. 查看报告草稿/失败路径。
3. supervisor 继续探索/停止；不能无记录选 best。

### 5.6 控制面崩溃

1. 重启；恢复 board/task/候选。
2. Cluster PAUSED；运行中 Agent/未封存 Task INTERRUPTED，不自动重跑。
3. 检查全局 job/实际执行/租约/落盘结果及消息去重，用户显式 resume 后创建 supervisor 新 session，以新 Task 续跑。

---

## 6. 完成定义

- [ ] 配置分层/校验/启动报告；无 `aworker` 运行时分支。
- [ ] 密钥不进入 agent 上下文/board/记录。
- [ ] ACL 在消息/工具/应用三层生效。
- [ ] 威胁模型与限制写入文档/启动提示。
- [ ] 日志/指标/审计覆盖角色/任务/候选/记录/租约。
- [ ] 运行手册覆盖 agent/worker/队列/记录/收敛/崩溃。

## 7. 新增策略配置与可观测性

以下配置作为 ClusterConfig 的版本化对象持久化，不只写在提示词中；字段语义见 [13 章](13-generation-and-iteration-contract.md)。

| 对象 | 字段与规则 |
| --- | --- |
| `BudgetPolicy` | max_bootstrap_attempts（默认 5）、max_rounds、max_duration_s、token/费用、工具/设备时间、plateau_rounds（默认 5）、max_consecutive_failures（默认 3）、final_validation_reserve；至少一个可执行全局硬上限非空 |
| `EvaluationPolicy` | 完整用例/reference/精度摘要、允许后端/环境、warmup/repeats、已注册聚合函数及参数、逐 case 回归上限、min_improvement；启动固定，修改须新集群 |
| `WakePolicy` | wake_debounce_ms（默认 500）、summary_interval_s（默认 30）、wait_deadline_s（默认 300）、stalled_timeout_s（默认 60）、max_stalled_wakes（默认 1）；运行/排队/有效 WAIT 不算停滞 |
| `ModelRouting` | 系统/角色默认、direction/任务覆盖、实例显式指定、允许的 fallback、provider 并发/配额及价格来源；显式值优先，换模新 session |
| `GlobalServices` | registry 服务及唯一数据根、hardware 服务及设备账本；独立本机实例不得管理同一 operator/设备，除非共用同一仲裁服务 |

- 上述默认值是实现缺省，允许用户在启动时覆盖；case 规模、计时次数和精度阈值没有安全通用默认，必须由 OperatorSpec/后端约定明确提供。
- 新增指标：baseline.attempts、directions.rounds/plateau、wakes.pending/failed、cluster.stalled_total、jobs.by_state、budget.reserved/consumed、final_validation.remaining；费用估算须标注来源。
- 新增审计：OperatorSpec 固化、模型路由/降级、TaskContext 授权、wake 合并/领取、baseline 认定、best 提名/最终验证、resume 与 continued_from 来源。
- 将参考、用例、测试脚本和凭据置于 optimizer 工程可写根之外；工具服务从只读快照执行，不从候选包接受 oracle 或评价规则替换。
