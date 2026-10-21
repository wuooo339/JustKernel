# JustKernel v2 独立重构

本目录是 JustKernel v2 的**独立新项目**。它只依据 [`SPEC/`](SPEC/README.md) 实现，不从旧 `aworker` 实现复制代码，不运行旧测试，也不以旧实现行为作为兼容标准。

- 架构事实来源：[`SPEC/README.md`](SPEC/README.md)
- 实施路线图：[`TODO.md`](TODO.md)
- 当前状态：P6 进行中；F06-01～F06-02 已完成，下一步 F06-03（见 TODO §8）

同级的 `../JustKernel/` 是旧项目，仅作为外部参考；新项目构建、测试和运行都不依赖它。

## 开发命令

项目初始化（F00-02/F00-03）完成后：

```bash
uv sync
uv run ruff format .
uv run ruff check src tests
uv run mypy src/justkernel
uv run pytest -q
uv run justkernel --version
```

## Feature 工作流

每个 feature 按 `TODO.md` §1 执行：写失败测试 → 最小实现 → 全量验证 → commit → `scripts/push_refactor.sh` → 更新 feature log。
