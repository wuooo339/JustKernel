# F00-02 Project Bootstrap Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Create an independent `justkernel` Python project with a minimal importable package, locked dev tooling, and a reproducible build.

**Architecture:** `src/justkernel/__init__.py` is the only production module in this feature. `pyproject.toml` defines the distribution, hatch wheel target, and dev tools. `uv.lock` pins the toolchain. No old code, no old tests, no runtime dependencies yet.

**Spec:** `SPEC/03-architecture.md` §2, `SPEC/12-migration-and-acceptance.md` §7.

## Global Constraints

- Python 3.13+; `uv`; `pytest`; `ruff`; `mypy` scoped to `src/justkernel`.
- Package only `justkernel`; no `aworker` import or compatibility layer.
- Domain state/behavior is not implemented in this feature.
- Every step must be verified by a command; no success claims without output.

## Files

- Create: `pyproject.toml`
- Create: `src/justkernel/__init__.py`
- Create: `tests/unit/test_package_identity.py`
- Create: `uv.lock` (generated)
- Modify: `TODO.md`
- Modify: `docs/refactor/feature-log.md`

## Steps

- [ ] **Step 1: Create the project scaffold (configuration only)**

`pyproject.toml`:

```toml
[project]
name = "justkernel"
version = "0.1.0"
description = "JustKernel v2 independent implementation."
readme = "README.md"
requires-python = ">=3.13"
license = "MIT"
dependencies = []

[dependency-groups]
dev = [
    "mypy>=1.15",
    "pytest>=8.0",
    "ruff>=0.9",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/justkernel"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.ruff.lint.isort]
known-first-party = ["justkernel"]

[tool.mypy]
python_version = "3.13"
files = ["src/justkernel"]
strict = true
warn_unused_ignores = true
```

Create an empty `src/justkernel/__init__.py` as scaffolding.

- [ ] **Step 2: Generate the lockfile and install the toolchain**

```bash
uv lock
uv sync --locked
```

Expected: both exit 0; `.venv` created with pytest, ruff, mypy, and editable `justkernel`.

- [ ] **Step 3: Write the failing identity test**

`tests/unit/test_package_identity.py`:

```python
from __future__ import annotations

import justkernel


def test_package_exposes_version() -> None:
    assert justkernel.__version__ == "0.1.0"
```

- [ ] **Step 4: Run the test and verify RED**

```bash
uv run pytest -q tests/unit/test_package_identity.py
```

Expected: FAIL with `AttributeError: module 'justkernel' has no attribute '__version__'`.

- [ ] **Step 5: Implement the version**

`src/justkernel/__init__.py`:

```python
"""JustKernel v2 independent implementation."""

__version__ = "0.1.0"
```

- [ ] **Step 6: Run the test and verify GREEN**

```bash
uv run pytest -q tests/unit/test_package_identity.py
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

Expected: test passes; mypy/ruff clean.

- [ ] **Step 7: Verify the build**

```bash
uv build
```

Expected: `dist/justkernel-0.1.0.tar.gz` and `dist/justkernel-0.1.0-py3-none-any.whl`; wheel contains only `justkernel`.

- [ ] **Step 8: Update TODO and feature log**

Mark `F00-02` done, record the test/build evidence, and append a feature-log row.

- [ ] **Step 9: Commit and push**

```bash
git add pyproject.toml uv.lock src/justkernel/__init__.py tests/unit/test_package_identity.py TODO.md docs/refactor/feature-log.md docs/superpowers/plans/2026-10-21-f00-02-project-bootstrap.md
git commit -m "feat(f00-02): bootstrap independent justkernel project"
scripts/push_refactor.sh
```
