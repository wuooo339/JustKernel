# 附录 A 当前代码审计

> 性质：背景说明，不是目标规范。  
> 方法：静态阅读 `JustKernel/` 源码/测试/文档；未执行完整测试或真实设备。

---

## 1. 结论

当前代码实现的是：

> **多队独立优化 + 单 coder/复核 + 实验回执 + 官测提交**

而需求是：

> **单算子、单 supervisor、约 100 个动态角色的 Agent 集群；分层通信；worker 只对 mentor；tester/profiler 由 skills 定义；最终 best + 报告。**

因此不是“局部重构”，而是**产品模型替换**。

---

## 2. 主要差距

| 需求 | 当前代码 | 差距 |
| --- | --- | --- |
| 单算子单 supervisor | 多 team、每队独立运行 | 没有集群/supervisor 概念 |
| consultant | 不存在；有 reviewer/analyst | 没有只读汇总角色 |
| mentor | 不存在；`ContinuousSwarm` 是平级调度 | 没有方向/探索/worker 指挥 |
| optimizer | 每队一个 coder | 没有 mentor 直属 worker |
| tester/profiler | 仿真/评测是工具，不是独立角色 | 没有角色 skills/硬件队列 |
| worker 只对 mentor | 团队内成员/工具不隔离 | 没有私有 channel/ACL |
| supervisor+mentor board | `store.messages` 是团队 inbox | 没有 board/只读/共享语义 |
| consultant 只读 board | 无 | 无 |
| tester/profiler 共享硬件队列 | `runner`/`simulator` 各自队列 | 没有统一租约/可见性 |
| 每候选测试记录 zip | 回执 JSON/日志分散 | 没有 TestRecord zip |
| best+报告 | 候选/冠军/公开结果 | 没有探索报告/最优选择 |
| 约 100 agent 动态 | team/agent 数量有限、无开关 | 没有 agent 池/生命周期 |
| 多进程 | 单进程 `LabService` + 子进程工具 | 控制/运行时/工具未分离 |
| 包名 | `aworker` + `lab` + `justkernel` 入口 | 双栈/命名混乱 |

---

## 3. 具体证据

| 问题 | 位置 |
| --- | --- |
| `LabService` 是全局服务定位器，拥有团队/实验/Judge/调度/工具 | `src/aworker/lab/service.py:35` |
| 多队调度，不是 supervisor/mentor/worker | `lab/continuous.py:25` |
| 单 coder/复核/工具混合 | `lab/deepagent.py:81`, `lab/tools.py:45` |
| 团队 inbox，不是共享 board | `lab/store.py:403` |
| 仿真/Judge 各自循环、互相调用 | `lab/simulation.py`, `lab/judger.py`, `lab/judge_automation.py` |
| 可变 JSON 状态（work-items/judge/queue 等） | `lab/iteration.py`, `lab/judger.py`, `lab/continuous.py` |
| 官测浏览器/预算主线 | `lab/judge_browser.py`, `lab/judge_automation.py` |
| 通用 `aworker` swarm 与 lab 双栈 | `src/aworker/swarm/*`, `src/aworker/server/*`, `lab/bridge.py` |
| 前端按多队/官测组织 | `lab/resources/web/app.js`（1,126 行） |
| tester/profiler 不是独立角色/skills | 仅有 `simulator`/`runner` 工具 |
| 没有 TestRecord zip | 回执/日志分散在 spool/jobs |
| 没有 supervisor/consultant/mentor 角色 | 角色仅有 analyst/implementer/reviewer |

---

## 4. 可保留的部分

- Deep Agents / LangGraph 基础设施。
- A2A 作为消息传输（需收敛为集群协议）。
- CANN 编译/仿真/ndjson 工具（作为 tester/profiler 后端）。
- 源码/回执哈希、不可变快照、证据校验思路。
- 事件流/SSE/UI 观察与回放机制。
- 旧算子工程/模板/测试用例（作为 baseline/资源）。

---

## 5. 必须删除/替换

- 多队 team/work-item/candidate queue 模型。
- 独立 Judge/官测预算/浏览器自动化主线。
- `LabService`、`ContinuousSwarm`、`IterationController`、`JudgeMonitor`、`JudgeAutomation`。
- 通用 `aworker` swarm/server/CLI 双栈。
- 可变 JSON 领域状态与目录扫描查询。
- 团队 inbox 作为共享消息的替代。

---

## 6. 审计限制

- 未运行完整测试/真实设备；结论基于静态结构。
- 行号可能随代码变化。
- 未评估第三方库/官方平台行为。
- 本审计不构成安全认证；安全边界见 10。
