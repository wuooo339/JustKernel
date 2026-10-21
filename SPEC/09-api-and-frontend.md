# 09 API、A2A 与前端

> 上层：[08-persistence-and-events.md](08-persistence-and-events.md)  
> 下层：[10-configuration-security-observability.md](10-configuration-security-observability.md)

---

## 1. API 原则

- `/api/v1/*`；本地优先、同源校验。
- 查询返回读模型 DTO；不返回 DB 行/文件路径。
- 写操作走应用用例；不提供“直接改 board/状态”的端点。
- `application/problem+json` + 稳定错误码。
- 列表游标分页；SSE 断线续传。
- 密钥/私有路径/模型私有推理不出现在响应。

---

## 2. 端点

### 2.1 Cluster

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/clusters` | `{operator_spec_ref, start_mode, baseline_source_ref?, skills, hardware, model_routing, budget, max_agents}`；GENERATE 不要求源码 |
| `GET` | `/clusters/{id}` | 状态、supervisor、best、report |
| `POST` | `/clusters/{id}/stop` | 停止 |
| `POST` | `/clusters/{id}/pause` | 暂停新探索、核对并处理在途任务 |
| `POST` | `/clusters/{id}/resume` | 显式核对结果/租约/预算后恢复 PAUSED 集群，幂等投递 RecoverySummary |
| `POST` | `/clusters/{id}/converge` | supervisor 收敛（受权限/门槛） |
| `GET` | `/clusters/{id}/graph` | 角色/父子/状态图 |

### 2.2 Agents

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/clusters/{id}/agents` | 角色、mentor、状态、模型 |
| `GET` | `/agents/{id}` | 详情/skills/最近任务 |
| `POST` | `/agents/{id}/close` | mentor 关闭 worker（管理/人工） |
| `GET` | `/agents/{id}/conversation` | 公开工作会话（脱敏） |

### 2.3 Board / Messages

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/clusters/{id}/board/mentor` | 方向/摘要/候选/失败 |
| `GET` | `/clusters/{id}/board/consultant` | consultant 汇总 |
| `GET` | `/clusters/{id}/messages?channel=` | 消息分页 |
| `POST` | `/clusters/{id}/messages` | 人工消息（审计） |

### 2.4 Directions / Tasks

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/clusters/{id}/directions` | 方向列表 |
| `GET` | `/tasks?cluster=&state=` | 任务列表 |
| `GET` | `/tasks/{id}` | 详情/context 摘要/结果/记录 |
| `GET` | `/tasks/{id}/context` | 任务上下文与授权反馈快照；按对象 ACL |
| `GET` | `/tool-jobs/{id}` | 异步作业状态、queue、record_id/error；按任务 ACL |
| `POST` | `/tasks/{id}/cancel` | 取消（mentor/管理） |

### 2.5 Candidates / Records

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/clusters/{id}/candidates` | 版本图/状态/指标 |
| `GET` | `/candidates/{id}` | 源码摘要/parent/记录 |
| `GET` | `/candidates/{id}/source` | 源码文本 |
| `GET` | `/candidates/{id}/records` | TestRecord 列表 |
| `GET` | `/records/{id}` | 摘要/manifest |
| `GET` | `/records/{id}/download` | zip 下载 |

### 2.6 Hardware

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/hardware/queue` | 设备队列/租约 |
| `GET` | `/hardware/devices` | 设备/能力 |
| `POST` | `/hardware/leases/{id}/release` | 管理释放 |

### 2.7 Report / Events

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/clusters/{id}/report` | 最新探索报告，可按 revision 查询历史；失败报告 best 可空 |
| `GET` | `/clusters/{id}/report/download` | Markdown/zip |
| `GET` | `/events?after=` | 事件分页 |
| `GET` | `/events/stream?after=` | SSE |
| `GET` | `/export` | 导出（脱敏） |

### 2.8 Admin

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/system/health` | 组件健康 |
| `GET` | `/system/config` | 脱敏配置 |
| `POST` | `/system/recover` | 核对存储/重建投影；不会自动 resume 或重跑任务 |
| `GET` | `/skills` | 已加载 base/builtin/user skills |
| `POST` | `/skills/reload` | 重新加载用户 skills |

---

## 3. A2A

### 3.1 Agent Card

- 一个集群暴露一个 A2A agent card（不是每团队）。
- skills：
  - `cluster-status`：查询集群/方向/候选摘要。
  - `cluster-message`：向 supervisor/board 投递受限消息。
- 不暴露 worker 私有 channel；不提供直接改 board/提交测试。

### 3.2 消息

```json
{"action":"status","cluster_id":"..."}
{"action":"message","cluster_id":"...","topic":"direction","message":"...","delivery_id":"..."}
```

规则：

- 外部消息进入 `external` channel，由 control 校验后转成 board post/人工消息。
- `delivery_id` 幂等。
- 外部客户端不能冒充 agent、不能写 worker channel、不能读私有会话。
- A2A 默认仅本机/受信网络。

---

## 4. DTO

```python
@dataclass(frozen=True)
class ClusterView:
    id: str
    operator_id: str
    supervisor_id: str
    state: str
    phase: str
    start_mode: str
    operator_spec_digest: str
    baseline_candidate_id: str | None
    continued_from_cluster_id: str | None
    max_agents: int
    active_agents: int
    best_candidate_id: str | None
    report_id: str | None
    created_at: int
    closed_at: int | None

@dataclass(frozen=True)
class AgentView:
    id: str
    role: str
    mentor_id: str | None
    model_profile: str
    skills: list[SkillView]
    state: str
    current_task_id: str | None
    created_at: int
    closed_at: int | None

@dataclass(frozen=True)
class CandidateView:
    id: str
    parent_id: str | None
    direction_id: str
    author_agent_id: str | None
    author_principal: str
    evaluation: dict             # 完整 TEST 视图 + 分组证据，非源码状态
    source_digest: str
    metrics: dict
    record_count: int
    created_at: int

@dataclass(frozen=True)
class TestRecordView:
    id: str
    candidate_id: str
    kind: str
    skill: SkillView
    backend: str
    outcome: str
    executed: bool
    coverage: str
    operator_spec_digest: str
    case_pack_digest: str
    evaluation_policy_digest: str
    metrics: dict
    environment: dict
    artifact_digest: str
    created_at: int

@dataclass(frozen=True)
class BoardPostView:
    id: str
    seq: int
    board: str
    topic: str
    author_agent_id: str
    payload: dict
    created_at: int

@dataclass(frozen=True)
class QueueView:
    devices: list[dict]
    queued: list[dict]
    leased: list[dict]
```

规则：

- 未知值 null，不补 0。
- 本地/仿真/真机指标分字段。
- 列表只返回摘要；源码/zip 单独端点。
- 不返回密钥、绝对私有路径、模型私有推理。

---

## 5. SSE

```text
id: 123
event: message
data: {"seq":123,"type":"candidate.committed","occurred_at":...,"payload":{...}}
```

- `Last-Event-ID` 续传；按 seq 幂等/去重。
- 心跳 20s；批量 ≤200 条。
- 实时/回放共用 reducer。

---

## 6. 前端

### 6.1 目标

- 无构建依赖，原生 ES Modules。
- 读模型驱动；live/replay/demo 共用 reducer。
- 突出集群结构、board、任务树、候选图、测试记录、硬件队列、报告。
- 人类可看全部；UI 明确标注角色/通道/ACL，不把 worker 私有数据混入 board。

### 6.2 模块

```text
web/
├── main.js
├── api/client.js
├── api/sse.js
├── state/store.js
├── state/reducer.js
├── state/selectors.js
├── state/sources.js
├── views/cluster.js
├── views/agents.js
├── views/board.js
├── views/tasks.js
├── views/candidates.js
├── views/records.js
├── views/hardware.js
├── views/report.js
├── components/…
├── format.js
└── demo/fixture.js
```

### 6.3 视图

1. **集群图**：supervisor → consultants/mentors → 直属 workers；状态/模型/任务。
2. **Board**：MentorBoard/ConsultantBoard 分区；方向、摘要、候选、失败、decision；标记只读/可写。
3. **任务树**：mentor→worker、kind、候选、状态、耗时。
4. **候选图**：DAG、指标、记录数、best 标记。
5. **TestRecord**：zip manifest、结果、日志、profile 下载。
6. **硬件队列**：设备、排队、租约、过期。
7. **报告**：方向/分支/失败/最优理由。
8. **回放**：事件时间线，只读。

### 6.4 展示规则

- 角色色/图标；worker 私有 channel 不进入 board 视图。
- 测试结果标注 `simulation`/`npu`/`profile`，不换算。
- 缺失值 `—`；失败候选可见，不只显示成功。
- Best 必须显示 VALIDATED selection、policy 及最终验证记录；PENDING 提名不标为最终 best。
- 回放/演示标注来源；不伪造 live 数据。

### 6.5 可访问性

- 键盘/焦点/aria-live；reduced motion；对比度。
- 大列表虚拟化；事件保留最近 160 条，历史分页。

---

## 7. 前端测试

- reducer：幂等/乱序/未知事件；live/replay 一致。
- selectors：实体合并、候选图、记录关联。
- format：时间/指标/未知值。
- DOM（可选）：集群图、board、报告、键盘。

---

## 8. 完成定义

- [ ] API 只返回 DTO；无内部行/路径。
- [ ] A2A 只暴露 cluster 能力；不暴露 worker 私有通道。
- [ ] 前端展示角色/board/任务/候选/记录/队列/报告。
- [ ] live/replay/demo 共用 reducer。
- [ ] 测试记录可下载、哈希可校验。
- [ ] 无密钥/私有路径/模型私有推理。

## 9. 生成和持续迭代界面/API 契约

- 创建页先选择 GENERATE/IMPORT；GENERATE 无 baseline 上传必填项，必须填写/选择语义、输入约束、参考、精度、case pack 和目标平台。
- 创建 API 在输入不全时返回 422/operator_spec.incomplete；已占用 operator 返回 409/cluster.operator_active；缺完整测试或不可比性能证据返回稳定原因码，不能默默选 best。
- POST /clusters 与 pause/resume/stop/converge 必须带幂等键，重复请求不创建第二集群或第二次恢复。GENERATE/IMPORT 校验由后端执行，不依赖前端隐藏字段。
- 详情页显示 BOOTSTRAPPING/OPTIMIZING/FINALIZING、基线状态、生成/修复次数、预算及最终验证预留、等待原因/deadline、最新反馈摘要和下一动作。
- 任务视图区分 GENERATE、OPTIMIZE、TEST、PROFILE；结果区分任务交付成功与候选 PASS，作业排队不持续调用模型。
- 显示 pending wake、stalled/PAUSED 和显式 resume 入口；系统 recover 仅修复投影，不能当作 resume。
- source/record/TaskContext/artifact 下载必须执行对象级权限和脱敏；人类查看全量能力不能复用为 Agent 身份。
