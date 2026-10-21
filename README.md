# JustKernel v2

JustKernel 是一个单算子、单 supervisor、约 100 个动态角色的 Agent 集群，用于从算子规格生成工程、建立经过验证的基线，并持续优化 Ascend 算子。

本目录是重构后的新项目根目录；旧的 `aworker` 实现在同级 `../JustKernel/` 中只读保留，作为迁移参考和 characterization 测试来源。

## 文档

- [SPEC/README.md](SPEC/README.md)：唯一架构事实来源（v2.1）
- [TODO.md](TODO.md)：分阶段实施清单，当前 P0 已完成
- [docs/refactor/legacy-inventory.md](docs/refactor/legacy-inventory.md)：旧实现迁移映射
- [docs/refactor/decision-log.md](docs/refactor/decision-log.md)：基础决策
- [docs/refactor/p0-exit-report.txt](docs/refactor/p0-exit-report.txt)：P0 验证记录

## 当前状态

P0 已完成：

- `src/justkernel/` 包骨架（domain / platform / bootstrap）
- `justkernel` CLI scaffold（`--version` 与占位输出）
- 架构门禁：import 边界、相对 import、文件/函数规模、import 无文件副作用
- characterization tests：旧 simulator、skills、A2A card、verified fixture
- `mypy`、`ruff`、pytest 基础门禁

尚未实现领域模型、运行时、存储、测试/硬件服务、编排、API/UI；这些从 P1 开始。

## 开发命令

```bash
uv sync
uv run ruff format .
uv run ruff check src tests
uv run mypy src/justkernel
uv run pytest -q
uv run justkernel --version
```

Characterization tests 需要同级旧仓库 `../JustKernel/src`；在干净 checkout 中会自动 skip。

## 目录

```text
src/justkernel/   # 新实现
tests/            # unit / architecture / characterization
SPEC/             # 重构规范
docs/             # 迁移与计划文档
```
