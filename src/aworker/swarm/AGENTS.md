# AGENTS.md

## 目录说明

`swarm/` 描述蜂群本体：内部的成员 agent，以及对外表现为单个 agent 的协调者。

## 文件职责

- `member.py`：`MemberAgent`，单个 `deepagents` 智能体，编译后的图只构建一次并复用。
- `swarm.py`：`Swarm`，动态维护成员注册表；成员变化时惰性重建协调者。

## 约定

- 成员数量与身份在运行时可变；任何增删成员都要使协调者缓存失效。
- 每个智能体使用 `deepagents.create_deep_agent` 构建。
- `MemberAgent.endpoint` 保留成员自身的 A2A 端点；跨进程成员间通信走 `aworker.client`。
- 对外只暴露 `Swarm.respond()`，不要在协调者之外泄露内部委派细节。
- 成员上限由 `Settings.max_members` 控制，超限抛出 `ValueError`。
