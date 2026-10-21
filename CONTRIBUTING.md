# 参与 JustKernel v2

本目录是重构后的新项目。旧 `aworker` 实现位于同级 `../JustKernel/`，只读保留，供迁移对照和 characterization 测试使用。

## 工作方式

- 先读 `SPEC/` 和 `TODO.md`，确认当前阶段与退出条件。
- 从 `main` 的 `JustKernel/` 旧仓库之外，本目录位于分支 `refactor/justkernel-v2` 的 worktree；不要在新项目里修改旧仓库。
- 每个行为变更先写失败测试，再写最小实现；提交前运行：
  ```bash
  uv run ruff format .
  uv run ruff check src tests
  uv run mypy src/justkernel
  uv run pytest -q
  ```
- 不把 `src/aworker` 重新引入新项目；新代码只依赖 `justkernel`。
- 不伪造测试记录、性能、官方成绩或设备执行；没有记录就写“未执行”。

## 目录

```text
src/justkernel/   # 新实现
tests/unit        # 纯单元
tests/architecture# 依赖、规模、无副作用门禁
tests/characterization # 旧实现合同，干净 checkout 中 skip
SPEC/             # 重构规范
docs/             # 迁移、决策、计划
```

## 依赖与配置

- Python 3.13+，使用 `uv` 管理依赖；新增依赖用 `uv add` / `uv add --dev`，提交 `uv.lock`。
- 配置未来只由 `justkernel.platform.config` 读取 `JUSTKERNEL_*`；当前 P0 还没有配置模块。
- 不提交密钥、`.env`、私有路径、设备凭据或真实成绩。

## 提交

提交信息使用 `feat:` / `test:` / `fix:` / `docs:` / `chore:` 前缀。PR 描述说明行为、测试证据和未验证项。
