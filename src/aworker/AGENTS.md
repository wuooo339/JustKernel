# src > aworker > AGENTS.md

## 包说明

`aworker` 是一个通过 A2A 协议对外提供蜂群 agent 服务的 Python 包。对外表现为单个 agent，内部由动态数量的 agent 协作。

## 文件职责

- `__init__.py`：包导出与版本号。
- `__main__.py`：`python -m aworker` 入口，仅调用 `cli.main`。
- `cli.py`：命令行解析、组装默认蜂群、启动服务。
- `config.py`：`Settings`，唯一读取环境变量的位置（前缀 `AWORKER_`）。
- `messages.py`：从 LangChain 消息/状态中提取纯文本。
- `client.py`：A2A 客户端，agent 之间通信的唯一入口。
- `swarm/`：成员与协调者，见 `swarm/AGENTS.md`。
- `server/`：A2A 服务端，见 `server/AGENTS.md`。

## 约定

- 业务逻辑不得直接读取环境变量，配置统一经由 `Settings` 传入。
- 外部输入、协议消息在边界处转换为明确类型，核心逻辑不使用裸 `dict`。
- 不在导入时执行副作用（不发网络请求、不启动后台任务）。
- 每个类、每个顶层函数、类内每组连续方法前必须有 `# ---- 名称 ----` 分隔注释。
- 新增依赖必须使用 `uv add` / `uv add --dev`，并提交 `pyproject.toml` 与 `uv.lock`。
- 智能体一律基于 `deepagents`（LangChain / LangGraph）实现。
