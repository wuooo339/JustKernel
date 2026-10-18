# 配置与认证

所有环境变量通过 `aworker.config.Settings` 读取，前缀为 `AWORKER_`。本机 `.env`、`models.local.toml` 和 `.justkernel*/` 均不提交。

## 标准模型 API

优先使用面板「模型」→ 添加连接 → 保存 → 测试连接。默认档案保留 GPT 和 DeepSeek，可添加 Qwen 或其他兼容 API；不再预置 GLM。连接列表只展示已配置连接，默认模板通过「添加连接」使用，避免同一模型同时出现待配置和已配置两项。填写账号真实可用的模型 ID；保存代表配置完成，测试成功才代表已连通。已保存连接会立即出现在组建团队和成员模型列表，无需重启。

面板密钥加密保存在 系统本机应用数据目录的 `JustKernel/workbench/<workspace-id>/models.json`，加密密钥为同目录 `vault.key`。服务器密码同样加密。二者应一起作为本机私有数据保管；这不是防御本机管理员或任意主机代码的隔离。Windows 默认 `%LOCALAPPDATA%/JustKernel/workbench`，macOS 为 `~/Library/Application Support/JustKernel/workbench`，Linux 为 `$XDG_DATA_HOME/JustKernel/workbench`（默认 `~/.local/share`）。可用 `AWORKER_LAB_PRIVATE_ROOT` 更换私有目录。不会将密钥复制到 OneDrive 项目、浏览器存储、团队文件或源代码包。

文件配置仍可用。`.env` 示例（值替换为本机密钥）：

```dotenv
AWORKER_LAB_PROVIDER_KEYS={"openai":"YOUR_KEY","deepseek":"YOUR_KEY"}
```

`models.toml` 定义公开的模型档案：provider、model、base_url、secret、effort、max_tokens 和可选 extra_body。`secret` 引用上述字典的键名。`models.local.toml` 使用同样结构，按档案 ID **整项替换**；它用于私有 endpoint、模型别名与 OAuth 文件路径。更改配置后正常重启服务。

`max_tokens` 是可选的单次输出上限，不是上下文窗口或整次优化的累计额度。默认留空（文件中省略此项），不向标准 API 发送 `max_tokens` / `max_completion_tokens`，由模型服务使用自己的默认值；不再统一设置 8192。服务默认值可能小于该模型的最大输出能力，留空不代表无限。若接口要求显式传入或需要调整输出预算，可填写该模型支持的正整数，工作台不再统一限制为 65536。已有明确保存的数值继续生效，清空并保存即可取消。GPT 登录适配器由登录服务控制，不使用此参数。团队仍通过多轮模型与工具调用读取代码、修改、评测、再改进；运行超时与图执行步数是独立配置，不受此字段控制。

DeepSeek 档案使用 `deepseek-flash`、`reasoning_effort=high` 和 `thinking.type=enabled`。专用适配器会回传所有 assistant 轮次的 reasoning_content，满足工具调用历史要求；面板记录工具与可见答复，不展示隐藏推理。账号实际可用模型不同，可在本机覆盖。GLM 使用标准 OpenAI 兼容 API。根据 [GLM Coding Plan 官方 FAQ](https://docs.bigmodel.cn/cn/coding-plan/faq)，套餐额度仅限指定工具，自建后端应使用标准 API；本项目拒绝把 Coding Plan endpoint 用作自建团队后端。Qwen 使用[百炼标准兼容端点](https://help.aliyun.com/en/model-studio/base-url)；Coding / Token Plan 的工具限制同样适用。

如果 Windows 进程以低完整性运行，写入普通 Local 目录会被系统拒绝，重复重启不会改变级别。可在本机 `.env` 明确设置 `AWORKER_LAB_PRIVATE_ROOT=C:/Users/<user>/AppData/LocalLow/JustKernel/workbench`，使用 Windows 为此类应用提供的[本地数据目录](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid)。不修改原目录权限或系统保护；已有配置需保留原文件，当前安装在首次成功保存前才切换目录。OAuth 登录文件路径保持不变。

## 复用 ChatGPT 登录

默认路径是 `~/.codex/auth.json`；可用本机覆盖文件指向已有独立目录。读取 access_token、refresh_token、account_id 等字段，仅发送给相应 ChatGPT 模型服务。不会将 OAuth token 作为 api.openai.com 的普通 API Key 使用，也不写回源登录文件。

当前固定 `langchain-openai==1.7.2` 的私有实验性 `_ChatOpenAICodex` 适配器。它是模型通信适配，不负责团队调度。过期会明确报错；通过原账号工具重新登录后再启动任务。发布长期服务可改用标准 API 或自行实现正式支持的授权流程。

## 团队自动分配

「组建团队」选择新增数量，默认按各个已配置模型的活动队数均衡分配，也可指定一个连接。名称由服务器统一编号（例如 `gpt-001`、`deepseek-001`）；即使旧队退出也不会复用其 ID 或覆写其源码。批量创建在数据库事务中预留名称和容量，并发创建不会重名，超出容量会整批拒绝。三名默认成员分别负责分析、实现和审查，与团队数量无关。

真实模式的 A2A、执行团队选择和榜单只展示对应已配置模型的活动团队；未使用节点与空模型分组隐藏。退出会保留源码、日志、会话和历史评测，可导出执行记录；导入的离线记录不要求当前仍保存相同凭据。模型列表只展示已配置连接，Key 输入框留空表示保留原密钥。

## NPU

```dotenv
AWORKER_LAB_SSH_HOST=ascend-lab
AWORKER_LAB_SSH_OPTIONS=["-F","C:/path/to/ssh/config"]
AWORKER_LAB_DEVICE=0
AWORKER_LAB_REMOTE_ROOT=/mnt/workspace/justkernel-lab
AWORKER_LAB_CANN_ENV=/home/developer/Ascend/cann-9.0.0/set_env.sh
```

以上文件配置仍可作为默认连接。面板「服务器」允许添加与更换连接：可粘贴 SSH 命令、完整 VS Code Host 块，或填写账号密码、私钥文件与口令。支持端口、现有 SSH config、代理跳转及 1–8 个不重复的 NPU 编号。首次连接须核对主机指纹，不能通过关闭验证解决。粘贴的 SSH 配置保存在私有目录，密码不回显、不传给配置助手。当前远程构建指定 `--npu-arch=dav-2201`，其他架构需要调整可信 evaluator。检测连接显示硬件和依赖；「检测并配置环境」的 Deep Agents 助手只能选择实际检测到的设备与 CANN 路径，不运行任意安装命令。「打开终端」通过 AsyncSSH PTY 连接所选服务器，使用 xterm.js；输入输出不发送模型、不写入优化轨迹。代理或连接失效时应先恢复原 SSH 会话。服务会检查所选卡的 npu-smi 运行进程，并以 flock 独占设备。编译上限默认 300 秒、整个作业默认 600 秒，评测进程有独立超时。

## 新增算子

「新增算子」接受题目文字、PNG / JPEG / WebP 图片，以及文本源码文件。每张图片上限 8 MB、最多 6 张；图片发给选定的模型，使用前应确认其内容适合该提供商。配置助手提交可检查的草稿，不自动开始 NPU 运行，也不能自行确认自己的评测器。

每个算子包包含描述、cases.json、默认约束加额外约束、kernel.asc，以及自己的 CMakeLists.txt、main.asc、evaluate.py 和可选 reference.py。必须遵循 runner 的构建和结果 JSON 契约；可参考内置 `resources/evaluator/`。case 支持自定义输入字段，但评测器需要解释这些字段，不能自动把任意形状当作 RotaryPosEmb。

规格不完整时可以保存草稿供模型分析；设备评测会说明缺少已审查的适配器。创建包之后不可原地覆写，补充评测器时使用新 ID 建立修订包，保持旧代码 / 回执不被改写。包位于 `.justkernel/operators/<id>/`，各自拥有团队、数据库、工作区和日志；切换时要求当前任务完成。当前公开工程样例为 ConfusionMulGrad；历史 RotaryPosEmb 仅保留记录兼容，私人优化基准不分发。

## LangSmith

默认关闭，SQLite / SSE 轨迹仍可用。开启后会将本轮图的输入输出、工具参数和源码片段发送至所配置的 LangSmith 项目；维护者应在自己的项目内启用。

```dotenv
AWORKER_LAB_LANGSMITH_ENABLED=true
AWORKER_LAB_LANGSMITH_API_KEY=YOUR_KEY
AWORKER_LAB_LANGSMITH_PROJECT=JustKernel
```

未启用时显式关闭继承的 LangSmith tracing。成功创建 trace 后面板展示真实链接；本轮没有 trace 链接时不会伪造。

## 参考

- [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview)
- [Skills](https://docs.langchain.com/oss/python/deepagents/skills)
- [LangSmith tracing](https://docs.langchain.com/langsmith/trace-with-langchain)
- [LangChain ChatGPT OAuth 模块](https://reference.langchain.com/python/langchain-openai/chatgpt_oauth)
- [OpenAI 的开源应用登录说明](https://developers.openai.com/siwc/token-sharing-open-source)
- [DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/)
