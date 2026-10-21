# JustKernel v2 P0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the legacy baseline, create the `justkernel` package skeleton, and install architecture/characterization gates so implementation can start on a clean, evidence-backed foundation.

**Architecture:** New `src/justkernel/` package lives beside the frozen `src/aworker/` implementation. New code may not import legacy code. Architecture tests enforce import direction, file-size budgets, and import-time side-effect freedom. Characterization tests pin the legacy contracts we intend to reuse: simulator request, skills frontmatter, A2A card, and verified fixture.

**Tech Stack:** Python 3.13, uv, pytest, ruff, mypy, argparse.

> **Relocation (2026-10-21):** P0 was executed in the legacy `JustKernel/` worktree, then the project moved to the `Refactor/` worktree. Paths below are relative to `Refactor/`; legacy paths are under `../JustKernel/`. See "Relocation amendment" at the end.

**Spec:** `SPEC/README.md` and the P0 section of `TODO.md`.

## Global Constraints

- Python `3.13+`; use `uv`; tests with `pytest`; lint/format with `ruff`.
- Final distribution/CLI only exposes `justkernel`; no `aworker` module. P0–P7 are transitional: old package may exist, but new package must not import it. P8 deletes it.
- One Cluster has exactly one Operator and one supervisor; active agents ≤ `max_agents` (default 100).
- Roles are fixed: `SUPERVISOR`, `CONSULTANT`, `MENTOR`, `OPTIMIZER`, `TESTER`, `PROFILER`.
- ACL is enforced in the tool layer and application layer; worker tool sets contain no board tools.
- Domain state only in SQLite/artifact store; no mutable JSON domain state.
- Every message/task/lease/record has a stable ID and idempotency key; at-least-once delivery with receiver deduplication.
- Only a full executed TEST record (`executed=true`, `coverage=FULL`, `outcome=PASS`) can establish baseline or participate in final best validation.
- TestRecord zip is mandatory; untested candidates need an audit record with `executed=false`, `coverage=NONE`.
- Device leases are globally unique; TTL expiry does not prove the physical execution stopped.
- Secrets, private reasoning, and absolute private paths never enter prompts, tool results, boards, logs, or exports.
- Domain files ≤ 300 lines; application services ≤ 400; adapters ≤ 600; web modules ≤ 400; functions ≤ 40.
- Default bind `127.0.0.1:4173`; local/trusted environment, no malicious-code sandbox.
- Every task starts with a failing test where production code is involved; run the layer checks and `ruff format --check` + `ruff check` before finishing.

## Review Focus

- **Baseline prerequisite:** the full legacy suite fails with 117 errors if `tools/import_official_template.py` has not run. The report must name this prerequisite so a clean baseline is not misread as a regression.
- **Architecture gate honesty:** gates must actually scan `src/justkernel` and fail when the package is absent. A gate that skips because a path is missing gives false confidence.
- **Characterization scope:** tests must not require CANN, torch, model credentials, network, or a device; they lock request/skill/card/fixture contracts only.
- **CLI placeholder:** the scaffold may only report version/placeholder text; it must not imply cluster functionality exists.
- **CI compatibility:** adding `mypy` and new gates must keep the legacy 229-test suite green and must not make the old code a typing target.

---

### Task 1: Legacy baseline and P0 plan

**Files:**
- Create: `docs/refactor/baseline-test-report.txt`
- Create: `docs/superpowers/plans/2026-10-21-p0-foundation.md`

**Interfaces:**
- Consumes: current `main` at `2fa044f5197a2feecd1982f80db18823bd93f445`.
- Produces: branch `refactor/justkernel-v2`, tag `legacy-baseline`, baseline report, this plan.

- [x] **Step 1: Create the branch and tag**

```bash
git switch -c refactor/justkernel-v2
git tag -a legacy-baseline -m "Legacy aworker baseline before justkernel v2 refactor"
```

- [x] **Step 2: Record the baseline prerequisite and result**

Run:

```bash
uv sync --locked
uv run python tools/import_official_template.py
uv run pytest -q
```

Expected: `229 passed, 2 skipped, 1 warning` and exit 0. Save the command, commit SHA, prerequisite, and full output to `docs/refactor/baseline-test-report.txt`.

- [x] **Step 3: Commit the baseline and plan**

```bash
git add docs/refactor/baseline-test-report.txt docs/superpowers/plans/2026-10-21-p0-foundation.md
git commit -m "chore(refactor): record legacy baseline and P0 plan"
```

---

### Task 2: Package skeleton behind architecture gates

**Files:**
- Create: `tests/architecture/test_import_boundaries.py`
- Create: `tests/architecture/test_file_sizes.py`
- Create: `tests/architecture/test_import_has_no_side_effects.py`
- Create: `tests/architecture/test_package_exports.py`
- Create: `tests/unit/test_cli_scaffold.py`
- Create: `src/justkernel/__init__.py`
- Create: `src/justkernel/{shared,cluster,agent,comm,task,candidate,testing,report,platform,bootstrap}/__init__.py`
- Create: `src/justkernel/platform/{persistence,artifacts,runtime,bus,tools,hardware,models,http,security}/__init__.py`
- Create: `src/justkernel/bootstrap/cli.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: nothing from earlier tasks except the branch.
- Produces: `justkernel` importable package; `justkernel.bootstrap.cli.main(argv: Sequence[str] | None = None) -> int`; architecture tests that later tasks must keep green.

- [x] **Step 1: Write the failing architecture tests**

Create `tests/architecture/test_import_boundaries.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "justkernel"
DOMAIN_PACKAGES = ("shared", "cluster", "agent", "comm", "task", "candidate", "testing", "report")
FORBIDDEN_DOMAIN_IMPORTS = {
    "sqlite3",
    "subprocess",
    "http",
    "deepagents",
    "fastapi",
    "starlette",
    "uvicorn",
}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_package_skeleton_exists() -> None:
    assert (PACKAGE / "__init__.py").is_file()


def test_new_package_never_imports_legacy_aworker() -> None:
    for path in PACKAGE.rglob("*.py"):
        imports = _imported_modules(path)
        assert not any(
            name == "aworker" or name.startswith("aworker.") for name in imports
        ), path


def test_domain_packages_do_not_import_adapters_or_io() -> None:
    for package in DOMAIN_PACKAGES:
        for path in (PACKAGE / package).rglob("*.py"):
            for name in _imported_modules(path):
                assert name not in FORBIDDEN_DOMAIN_IMPORTS, (path, name)
                assert not name.startswith("justkernel.platform"), (path, name)
```

Create `tests/architecture/test_file_sizes.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "justkernel"
DOMAIN_PACKAGES = ("shared", "cluster", "agent", "comm", "task", "candidate", "testing", "report")
DOMAIN_LIMIT = 300
BOOTSTRAP_LIMIT = 400
PLATFORM_LIMIT = 600
WEB_LIMIT = 400
FUNCTION_LIMIT = 40


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _function_lengths(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lengths: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = node.end_lineno or node.lineno
            lengths.append((node.name, end - node.lineno + 1))
    return lengths


def test_domain_files_are_small() -> None:
    for package in DOMAIN_PACKAGES:
        for path in (PACKAGE / package).rglob("*.py"):
            assert _line_count(path) <= DOMAIN_LIMIT, path


def test_bootstrap_and_platform_files_are_small() -> None:
    for package, limit in (("bootstrap", BOOTSTRAP_LIMIT), ("platform", PLATFORM_LIMIT)):
        for path in (PACKAGE / package).rglob("*.py"):
            assert _line_count(path) <= limit, path


def test_functions_are_small() -> None:
    for path in PACKAGE.rglob("*.py"):
        for name, length in _function_lengths(path):
            assert length <= FUNCTION_LIMIT, (path, name, length)


def test_web_modules_are_small() -> None:
    for path in (PACKAGE / "web").rglob("*.js"):
        assert _line_count(path) <= WEB_LIMIT, path
```

Create `tests/architecture/test_import_has_no_side_effects.py`:

```python
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_importing_all_justkernel_modules_creates_no_files(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["HOME"] = str(tmp_path)
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg")
    script = """
import importlib
import pkgutil

import justkernel

for module in pkgutil.walk_packages(justkernel.__path__, justkernel.__name__ + "."):
    importlib.import_module(module.name)
"""
    before = {path for path in tmp_path.rglob("*")}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    after = {path for path in tmp_path.rglob("*")}
    assert after == before
```

Create `tests/architecture/test_package_exports.py`:

```python
from __future__ import annotations

import justkernel


def test_package_does_not_reexport_legacy_stack() -> None:
    assert not hasattr(justkernel, "aworker")
```

Create `tests/unit/test_cli_scaffold.py`:

```python
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from justkernel.bootstrap.cli import main


def test_cli_reports_version(capsys) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out == "justkernel 0.1.0\n"


def test_cli_default_message(capsys) -> None:
    assert main([]) == 0
    assert capsys.readouterr().out == "justkernel: P0 scaffold\n"


def test_cli_reads_process_arguments(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["justkernel", "--version"])

    assert main() == 0
    assert capsys.readouterr().out == "justkernel 0.1.0\n"


def test_transitional_entry_points_preserve_legacy_justkernel() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    scripts = pyproject["project"]["scripts"]

    assert scripts["justkernel"] == "aworker.lab.cli:main"
    assert scripts["justkernel-next"] == "justkernel.bootstrap.cli:main"
```

- [x] **Step 2: Run the tests and verify RED**

Run:

```bash
uv run pytest -q tests/unit tests/architecture
```

Expected: FAIL because `src/justkernel` / `justkernel.bootstrap.cli` does not exist. Record the failure text.

- [x] **Step 3: Create the package skeleton**

Create `src/justkernel/__init__.py`:

```python
"""JustKernel v2 package."""
```

Create empty `__init__.py` files for:

```text
src/justkernel/shared/
src/justkernel/cluster/
src/justkernel/agent/
src/justkernel/comm/
src/justkernel/task/
src/justkernel/candidate/
src/justkernel/testing/
src/justkernel/report/
src/justkernel/platform/
src/justkernel/platform/persistence/
src/justkernel/platform/artifacts/
src/justkernel/platform/runtime/
src/justkernel/platform/bus/
src/justkernel/platform/tools/
src/justkernel/platform/hardware/
src/justkernel/platform/models/
src/justkernel/platform/http/
src/justkernel/platform/security/
src/justkernel/bootstrap/
```

Create `src/justkernel/bootstrap/cli.py`:

```python
"""Command-line entry point scaffold for JustKernel v2."""

from __future__ import annotations

from collections.abc import Sequence

VERSION = "0.1.0"


def main(argv: Sequence[str] | None = None) -> int:
    """Print the scaffold version or a placeholder message."""
    arguments = list(argv) if argv is not None else []
    if arguments == ["--version"]:
        print(f"justkernel {VERSION}")
    else:
        print("justkernel: P0 scaffold")
    return 0
```

- [x] **Step 4: Update `pyproject.toml` for the transitional package**

Make these exact changes:

```toml
[project.scripts]
justkernel = "aworker.lab.cli:main"
justkernel-next = "justkernel.bootstrap.cli:main"
aworker = "aworker.cli:main"
aworker-lab = "aworker.lab.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/justkernel", "src/aworker"]

[tool.ruff.lint.isort]
known-first-party = ["justkernel", "aworker"]
```

Do not rename the distribution yet; P8 performs the final rename and removes `aworker`.

- [x] **Step 5: Run the tests and verify GREEN**

Run:

```bash
uv run pytest -q tests/unit tests/architecture
uv run ruff check src/justkernel tests/unit tests/architecture
uv run ruff format --check src/justkernel tests/unit tests/architecture
```

Expected: all architecture tests pass; ruff clean.

- [x] **Step 6: Commit**

```bash
git add pyproject.toml src/justkernel tests/architecture
git commit -m "test(architecture): add package boundaries and justkernel skeleton"
```

---

### Task 3: Characterization contracts for reusable legacy behavior

**Files:**
- Create: `tests/characterization/test_simulation_request_contract.py`
- Create: `tests/characterization/test_skills_contract.py`
- Create: `tests/characterization/test_agent_card_contract.py`
- Create: `tests/characterization/test_verified_fixture_contract.py`

**Interfaces:**
- Consumes: legacy `aworker` modules and resources; no new package APIs.
- Produces: four contract tests that must stay green until P8 replaces the legacy adapters.

- [x] **Step 1: Write the simulator request contract test**

Create `tests/characterization/test_simulation_request_contract.py`:

```python
from __future__ import annotations

from aworker.lab.simulation import SimulationRequest


def test_simulation_request_defaults_and_alias() -> None:
    request = SimulationRequest(
        id="a" * 32,
        workspace_id="workspace",
        team="team-1",
        operator="ConfusionMulGrad",
        files={"op_kernel/kernel.cpp": "// source"},
        source_sha256="b" * 64,
        cases_json="[]",
        case_pack_sha256="c" * 64,
        case_ids=["case-1"],
        worker_sha256="d" * 64,
        hypothesis="lock the legacy request contract",
        created_at=0.0,
    )

    payload = request.model_dump(by_alias=True)

    assert request.schema_version == "justkernel.simulation.request.v1"
    assert payload["schema"] == "justkernel.simulation.request.v1"
    assert request.target_soc == "Ascend910B4"
    assert request.evaluation_mode == "full-profile"
    assert request.timeout_seconds == 3600
    assert request.profile_case_ids == []
```

- [x] **Step 2: Write the skills contract test**

Create `tests/characterization/test_skills_contract.py`:

```python
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / "src" / "aworker" / "lab" / "resources" / "skills"
EXPECTED = {
    "compliance-review",
    "evidence-distillation",
    "kernel-engineering",
}


def _frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---", path
    end = lines.index("---", 1)
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def test_legacy_skills_have_stable_frontmatter() -> None:
    discovered = {path.parent.name for path in SKILLS_ROOT.glob("*/SKILL.md")}
    assert discovered == EXPECTED

    for name in EXPECTED:
        fields = _frontmatter(SKILLS_ROOT / name / "SKILL.md")
        assert fields["name"] == name
        assert fields["description"]
```

- [x] **Step 3: Write the A2A card contract test**

Create `tests/characterization/test_agent_card_contract.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from aworker.config import Settings
from aworker.server.card import build_agent_card


def test_agent_card_defaults_and_transport() -> None:
    settings = Settings(_env_file=None)
    card = build_agent_card(settings, SimpleNamespace(members=[]))

    assert card.name == "JustKernel"
    assert card.version == "0.2.0"
    assert card.capabilities.streaming is True
    assert card.supported_interfaces[0].protocol_binding == "JSONRPC"
    assert card.supported_interfaces[0].protocol_version == "1.0"
    assert card.skills == []
```

- [x] **Step 4: Write the verified fixture contract test**

Create `tests/characterization/test_verified_fixture_contract.py`:

```python
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "examples" / "confusionmulgrad" / "verified" / "baseline.json"
DIGEST = re.compile(r"^[a-f0-9]{64}$")


def test_verified_fixture_identity_and_hashes() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert data["schema"] == "justkernel.verified-solution.v1"
    assert data["operator"] == "ConfusionMulGrad"
    assert data["official"]["status"] == "Pass"
    assert len(data["template_files"]) == 34

    digests = [
        data["source_sha256"],
        data["template_sha256"],
        *data["template_files"].values(),
        *data["overlays"].values(),
    ]
    assert all(DIGEST.fullmatch(digest) for digest in digests)
```

- [x] **Step 5: Run the characterization tests**

Run:

```bash
uv run pytest -q tests/characterization
```

Expected: PASS (these tests lock existing behavior; they must not require CANN, torch, models, or network). If a test fails, fix the test's assumptions against the current contract, not the legacy code.

- [x] **Step 6: Commit**

```bash
git add tests/characterization
git commit -m "test(characterization): lock reusable legacy contracts"
```

---

### Task 4: Legacy inventory and foundation decisions

**Files:**
- Create: `docs/refactor/legacy-inventory.md`
- Create: `docs/refactor/decision-log.md`

**Interfaces:**
- Consumes: P0 baseline, SPEC Appendix A, and current source tree.
- Produces: one-way mapping from legacy modules/resources to reuse/adapt/delete decisions; accepted foundation decisions.

- [x] **Step 1: Write `docs/refactor/legacy-inventory.md`**

Include a table with these columns: `Legacy path`, `Responsibility`, `Decision`, `New location`, `Evidence test`. Cover at least:

```text
src/aworker/cli.py
src/aworker/config.py
src/aworker/messages.py
src/aworker/models.py
src/aworker/server/app.py
src/aworker/server/card.py
src/aworker/server/client.py
src/aworker/server/credentials.py
src/aworker/server/executor.py
src/aworker/server/workspace.py
src/aworker/swarm/member.py
src/aworker/swarm/swarm.py
src/aworker/lab/api.py
src/aworker/lab/bridge.py
src/aworker/lab/cli.py
src/aworker/lab/continuous.py
src/aworker/lab/deepagent.py
src/aworker/lab/domain.py
src/aworker/lab/export.py
src/aworker/lab/filesystem.py
src/aworker/lab/inputs.py
src/aworker/lab/iteration.py
src/aworker/lab/judge_automation.py
src/aworker/lab/judge_bridge.py
src/aworker/lab/judge_browser.py
src/aworker/lab/judge_browser_worker.py
src/aworker/lab/judger.py
src/aworker/lab/lifecycle.py
src/aworker/lab/model_settings.py
src/aworker/lab/notices.py
src/aworker/lab/operators.py
src/aworker/lab/persistence.py
src/aworker/lab/policy.py
src/aworker/lab/prepare.py
src/aworker/lab/probes.py
src/aworker/lab/progress.py
src/aworker/lab/project.py
src/aworker/lab/providers.py
src/aworker/lab/public_session.py
src/aworker/lab/receipts.py
src/aworker/lab/runner.py
src/aworker/lab/selection.py
src/aworker/lab/service.py
src/aworker/lab/setup_agent.py
src/aworker/lab/simulation.py
src/aworker/lab/store.py
src/aworker/lab/supervisor.py
src/aworker/lab/tool_arguments.py
src/aworker/lab/tools.py
src/aworker/lab/workbench_api.py
src/aworker/lab/resources/simulator/worker.py
src/aworker/lab/resources/skills/*
src/aworker/lab/resources/web/*
```

Mark decisions:

- `reuse`: CANN simulator worker/protocol, model provider/credential adapters, A2A envelope/card ideas, skills/templates, example fixture.
- `adapt`: request/response contracts, artifact hashing, event/SSE ideas, runner pieces that can sit behind new ports.
- `delete`: `LabService`, `ContinuousSwarm`, `IterationController`, `JudgeMonitor`, `JudgeAutomation`, team/work-item candidate queue, mutable JSON domain state, per-team inbox, browser/judge mainline.
- `legacy-only`: old data importer inputs, `AWORKER_*` env mapping.
- `new`: all domain/application modules listed in SPEC 03.

At the end, add a “Reuse evidence” section naming the P0 characterization tests.

- [x] **Step 2: Write `docs/refactor/decision-log.md`**

Record these decisions as accepted for P0:

```text
D-001 SQLite access: standard-library sqlite3 with explicit SQL, no ORM.
D-002 IDs: UUID4 rendered as 32 lowercase hex; Digest: SHA-256 rendered as 64 lowercase hex.
D-003 Canonical JSON: UTF-8, sorted keys, compact separators; NaN/Inf rejected in persisted payloads.
D-004 Config: only platform/config.py reads environment variables; precedence CLI > env > .env > defaults.
D-005 Transitional packages: src/justkernel and src/aworker coexist until P8; new code may not import old code.
D-006 CLI: justkernel is the only future CLI; aworker/aworker-lab are transitional aliases removed in P8.
D-007 Type checking: mypy scoped to src/justkernel; legacy code is not a typing target.
D-008 Web tests: Node built-in test runner for plain ES modules; existing .cjs tests remain until P7.
```

For each decision, add one line: why, and what it costs if wrong.

- [x] **Step 3: Verify links and required rows**

Run:

```bash
rg -n "LabService|ContinuousSwarm|IterationController|JudgeMonitor|aworker" docs/refactor/legacy-inventory.md
rg -n "D-00[1-8]" docs/refactor/decision-log.md
```

Expected: all critical legacy modules and all eight decisions are present.

- [x] **Step 4: Commit**

```bash
git add docs/refactor/legacy-inventory.md docs/refactor/decision-log.md
git commit -m "docs(refactor): inventory legacy modules and record foundation decisions"
```

---

### Task 5: CI, type checking, and layer gates

**Files:**
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: architecture and characterization tests from Tasks 2–3.
- Produces: CI commands that run `mypy`, architecture tests, characterization tests, and the legacy suite.

- [x] **Step 1: Add mypy and configuration**

Run:

```bash
uv add --dev "mypy>=1.15"
```

Append to `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.13"
files = ["src/justkernel"]
strict = true
warn_unused_ignores = true
```

- [x] **Step 2: Add CI steps**

In `.github/workflows/ci.yml`, after the existing ruff steps, add:

```yaml
      - run: uv run mypy src/justkernel
      - name: New package architecture gates
        run: uv run pytest -q tests/unit tests/architecture
      - name: Legacy characterization contracts
        run: uv run pytest -q tests/characterization
```

Keep the existing `uv run pytest -q` step and all legacy checks. Do not add `src/aworker` to the mypy target.

- [x] **Step 3: Verify locally**

Run:

```bash
uv run mypy src/justkernel
uv run pytest -q tests/architecture tests/characterization
uv run ruff check src/justkernel tests/architecture tests/characterization
uv run ruff format --check src/justkernel tests/architecture tests/characterization
```

Expected: mypy success, all selected tests pass, ruff clean.

- [x] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock .github/workflows/ci.yml
git commit -m "chore(ci): gate justkernel types, architecture, and legacy contracts"
```

---

### Task 6: P0 exit verification and checklist update

**Files:**
- Modify: `Refactor/TODO.md`
- Modify: `docs/superpowers/plans/2026-10-21-p0-foundation.md` (mark this plan complete only after evidence)

**Interfaces:**
- Consumes: all P0 deliverables.
- Produces: green P0 evidence and updated roadmap status.

- [x] **Step 1: Run the complete P0 verification**

Run:

```bash
uv run python tools/import_official_template.py
uv run pytest -q
uv run pytest -q tests/architecture tests/characterization
uv run mypy src/justkernel
uv run ruff check src tests tools
uv run ruff format --check src tests tools
```

Expected:

```text
- full suite: legacy 229 passed + new architecture/characterization tests, 0 failed
- architecture/characterization: all pass
- mypy: success
- ruff check/format: clean
```

Record exact counts and commands in the progress log.

- [x] **Step 2: Update `Refactor/TODO.md`**

Check off `P0-01` through `P0-07` and every P0 exit item only if Step 1 passed. Add a progress row with date, commit range, commands, and result. Leave P1 unchecked.

- [x] **Step 3: Commit the P0 closeout**

```bash
git add Refactor/TODO.md docs/superpowers/plans/2026-10-21-p0-foundation.md
git commit -m "docs(refactor): close P0 foundation checklist"
```

Note: `TODO.md` is in the same `Refactor/` worktree; commit it with the plan.

---

## Self-Review

- **Spec coverage:** P0 covers baseline, package skeleton, architecture gates, characterization contracts, legacy inventory, decisions, CI/type checks, and exit evidence. It does not implement P1 domain types; that is intentional.
- **No placeholder steps:** every step names an exact file, command, or expected result.
- **Type consistency:** `main(argv: Sequence[str] | None = None) -> int` is used by the scaffold test and the pyproject entry point.
- **Review focus ownership:** each of the five review-focus items maps to Task 1 (baseline prerequisite), Task 2 (gate honesty), Task 3 (characterization scope), Task 2 (CLI placeholder), and Task 5 (CI compatibility).
- **Proportion:** P0 is scaffolding and guards; no production domain logic is written before P1.

---

## Execution Record

- Task 1: complete (commits `2fa044f..a1a4a22`; baseline 229 passed, 2 skipped).
- Task 2: complete (commits `a1a4a22..87ce206`; current `uv run pytest -q tests/unit tests/architecture` → 14 passed after the final-review gate fixes). Ruling: CLI scaffold tests live in `tests/unit` instead of `tests/architecture`.
- Task 3: complete (commits `87ce206..bccff05`; `uv run pytest -q tests/characterization` → 4 passed).
- Task 4: complete (commits `bccff05..519ed67`; current `uv run pytest -q tests/unit tests/architecture tests/characterization` → 18 passed).
- Task 5: complete (commits `519ed67..66524f9`; current `uv run pytest -q tests/unit tests/architecture tests/characterization` → 18 passed; mypy success).
- Task 6: complete (closeout commit plus final-review fix commit; `uv run pytest -q` → 247 passed, 2 skipped; mypy success; ruff check/format clean).

Rulings:
- Branch in the existing checkout, no separate worktree: the TODO allowed branch or worktree and the legacy tree is frozen. Cost if wrong: the checkout stays on `refactor/justkernel-v2`.
- CLI scaffold tests in `tests/unit`: keeps the P0 CI unit path non-empty and matches the test's unit scope. Cost if wrong: one path differs from the original plan text.
- `justkernel` keeps the legacy CLI until P8; `justkernel-next` is the new scaffold: reassigning `justkernel` in P0 would break the README/start scripts. Cost if wrong: two CLI names temporarily, and P8 must complete the switch.
- Architecture gate rejects cross-package relative imports (`level >= 2`), not only absolute `justkernel.platform` imports: prevents bypassing the dependency rule. Cost if wrong: a legitimate cross-package relative import must be written as an absolute import.
- P0 exit evidence stored in `docs/refactor/p0-exit-report.txt`: durable verification record. Cost if wrong: one extra documentation file.

---

## Relocation Amendment (2026-10-21)

The P0 work was relocated from the legacy `JustKernel/` worktree into a new
`Refactor/` worktree of the same git repository.

Current layout:

- `JustKernel/` — `main` worktree, legacy `aworker` implementation, read-only reference.
- `Refactor/` — `refactor/justkernel-v2` worktree, new `justkernel` project root.

Superseding decisions:

- `Refactor/pyproject.toml` names the project `justkernel`, packages only `src/justkernel`,
  and maps `justkernel` to `justkernel.bootstrap.cli:main`. No `justkernel-next` alias.
- `src/aworker` is not present in the new project; the old package stays in `JustKernel/`.
- `tests/characterization/conftest.py` adds `../JustKernel/src` locally and skips the
  legacy contracts when that tree is absent (CI).
- The P0 exit evidence after relocation is in `docs/refactor/p0-exit-report.txt`.
- Local full suite: 18 passed (including characterization with the legacy sibling tree).
- Clean-checkout CI: 14 passed, 4 skipped (characterization), plus mypy, ruff, and build.
