# 参与 JustKernel

欢迎团队成员和外部贡献者共同开发。先创建 Issue 说明目标、涉及模块和可验证的结果，再从 `main` 建立功能分支并提交 PR；不要直接推送共享主分支。

## 建议分工

| 方向 | 主要位置 | 验收示例 |
| --- | --- | --- |
| Harness / 模型 | `lab/deepagent.py`、`providers.py`、`tools.py` | 新提供商完成工具调用，流式记录和错误能恢复 |
| 仿真 / 证据 | `lab/simulator.py`、`resources/simulator/` | 独立编译、逐点校验、源码和输入身份匹配 |
| Judger | `lab/judge*.py` | 冻结正确文件、预算不超限、不确定提交不重试 |
| A2A / 知识 | `server/`、团队消息与经验模块 | 实际投递确认、去重、引用可追溯证据 |
| 面板 / 回放 | `resources/web/` | 展示真实进度，回放不提前出现未来成绩 |
| 算子适配 | 新规格、暂拟输入、独立可信 evaluator | 描述来源、禁区、正确性与测量边界 |

## 开发环境

按 README 导入官方空工程；`uv sync --locked` 安装依赖。启动 `uv run justkernel serve --open`，默认仅监听本机。测试与构建命令见 README 和 CI。无模型、NPU 的贡献可使用明确的测试夹具，但必须说明没有进行真实硬件验收。

- 所有团队与成员统一使用 Deep Agents；模型适配集中在 `providers.py`。
- 环境读取只在 `config.Settings`；新增依赖通过 `uv add` / `uv add --dev`，提交锁文件。
- 遵循对应目录的 `AGENTS.md`；这些文件仅由人类维护，AI 不修改。
- 修改 Worker / evaluator 会影响证据身份。不要把旧证据绑定到新实现，不要伪造 SSE、Token 或性能。
- 为行为或安全边界变更补充有意义的测试；文档和纯视觉调整无需镜像实现的测试。
- 提交前检查 `git diff --cached`。不上传密钥、登录文件、SSH 配置、隐藏测试、私有轨迹或 CANN 二进制。
- 官方模板导入到本机的 `project/` 被忽略；不要强制加入 Git。新增第三方源码必须附带可核验来源与许可。

PR 描述应说明问题、最终行为、检查结果及未验证的真实环境。请不要将本地仿真通过写成官方 Pass，不要将模拟动画写成真实实验视频。
