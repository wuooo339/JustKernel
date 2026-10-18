# 验证范围

本页描述可重复检查和当前能力边界，不发布维护者的账号、私有日志或机器配置。

## 自动检查

```sh
uv sync --locked
uv run python tools/import_official_template.py
uv run pytest -q
uv run ruff check src tests tools
uv run ruff format --check src tests tools
node --test tests/web_visualization.test.cjs tests/web_activity.test.cjs
uv build
uv run python tools/package_source.py
```

测试使用明确的脚本模型、测量夹具和协议回执。它们验证调度、冻结身份、提交门槛、每日预算、A2A 去重、流式事件和回放时序，不冒充真实模型、硬件测量或官网成绩。CI 在 Windows / macOS / Linux 执行上述检查；跨平台 CI 成功不表示各平台都能本机运行 CANN。

## 已完成的环境验证

- GPT 和 DeepSeek 的真实模型请求、工具循环、技能、成员委派与独立检查点。
- 8 队持续调度、独立冻结候选、公开代码学习及实际 A2A 投递确认。
- Ubuntu 22.04 / WSL2、CANN 9.0.0、Ascend910B4 CPU 仿真，保存真实编译日志、逐点校验和 trace。
- 独立官方浏览器人工登录，精选候选真实提交、读取失败回执并广播。曾取得部分测试点通过，**尚无 ConfusionMulGrad 官方全点通过成绩或有效 SOTA**。
- 面板预演、事件投影、可见模型输出、工具活动与离线回放的源代码及行为检查。未完成所有浏览器 / 屏幕尺寸的人工视觉验收。

## 仍需验收

- 默认 15 个暂拟本地点全通过后，对应新版本的完整官测闭环；旧 9 点记录不能充当新门槛证据。
- ConfusionMulGrad 的真实 NPU Profiler、更多设备型号、多卡并发与多机设备池。
- 百队长时间运行的资源消耗、收敛性和相对单队收益。
- 跨算子经验迁移收益、稀疏结构感知算法的实际加速。
- 公网部署的认证、容器隔离、凭据代理与恶意候选防护。

官方 15 个测试 ID 可见，但隐藏输入未确认。本地 15 组输入为暂拟定义，不能宣称逐点等价。仿真指标不换算为官测分数；失败和无结果不画成零耗时。
