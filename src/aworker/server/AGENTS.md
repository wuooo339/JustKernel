# AGENTS.md

## 目录说明

`server/` 负责把蜂群通过 A2A 协议对外暴露为单个 agent。

## 文件职责

- `card.py`：`build_agent_card`，根据 `Settings` 与 `Swarm` 生成 `AgentCard`，每个成员对应一个 skill。
- `executor.py`：`SwarmAgentExecutor`，实现 `AgentExecutor`，把一次 A2A 请求转成一次蜂群运行，并负责全部 A2A 任务状态迁移。
- `app.py`：`create_app` / `run_server`，组装 FastAPI 与 a2a-sdk 路由。

## 约定

- 只使用 `a2a-sdk` 的公开 API；协议细节集中在 `executor.py`，蜂群保持传输无关。
- 请求文本通过 `RequestContext.get_user_input()` 获取，结果用 `TaskUpdater` 回写。
- `executor.execute` 是边界函数：捕获异常后必须记录日志并给出失败状态，不得让异常逃逸。
- 对外端点固定为：Agent Card `/.well-known/agent-card.json`，JSON-RPC `/`。
- 不在模块导入时创建应用或启动服务。
