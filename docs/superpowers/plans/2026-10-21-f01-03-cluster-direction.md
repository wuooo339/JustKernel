# F01-03 Cluster and Direction Aggregates Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`) syntax.

**Goal:** Implement the mutable Cluster and Direction aggregates with explicit state machines, transition guards, and terminal invariants.

**Architecture:** Pure domain modules under `src/justkernel/cluster/`. They depend on `shared` and `cluster.operator_spec` only. No I/O, platform, or application services.

**Spec:** `SPEC/04-domain-model.md` §4.1, §4.3.

## Global Constraints

- One Cluster has one operator and one supervisor.
- `max_agents` default 100; minimum 6.
- `COMPLETED` requires a best candidate and a report; `STOPPED` may have neither.
- Terminal states have `closed_at`; non-terminal states do not.
- A mentor has at most one open direction (application-level invariant; aggregate enforces its own transitions).
- Only supervisor commands activate/close directions; methods model that transition.
- No old-code imports or old tests.

## Files

- Create: `src/justkernel/cluster/state.py` — `ClusterState`, `ClusterPhase`, `StartMode`, `DirectionState`
- Create: `src/justkernel/cluster/errors.py` — `ClusterError`, `DirectionError`
- Create: `src/justkernel/cluster/cluster.py` — `Cluster`
- Create: `src/justkernel/cluster/direction.py` — `Direction`
- Create: `tests/unit/cluster/test_cluster.py`
- Create: `tests/unit/cluster/test_direction.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Interfaces

```python
class ClusterState(StrEnum):
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    CONVERGING = "CONVERGING"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"

class ClusterPhase(StrEnum):
    BOOTSTRAPPING = "BOOTSTRAPPING"
    OPTIMIZING = "OPTIMIZING"
    FINALIZING = "FINALIZING"

class StartMode(StrEnum):
    GENERATE = "GENERATE"
    IMPORT = "IMPORT"

class DirectionState(StrEnum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"

class Cluster:
    # fields from SPEC 04 §4.1
    def start(self) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def establish_baseline(self, candidate_id: CandidateId) -> None: ...
    def converge(self) -> None: ...
    def set_best_candidate(self, candidate_id: CandidateId) -> None: ...
    def attach_report(self, report_id: str) -> None: ...
    def complete(self, now_ms: int) -> None: ...
    def stop(self, reason: str, now_ms: int) -> None: ...
    def fail(self, reason: str, now_ms: int) -> None: ...
    def set_max_agents(self, max_agents: int) -> None: ...

class Direction:
    def activate(self) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def set_summary(self, summary: str) -> None: ...
    def complete(self, reason: str, now_ms: int) -> None: ...
    def abandon(self, reason: str, now_ms: int) -> None: ...
```

## Steps

- [ ] **Step 1: Write failing tests**

`tests/unit/cluster/test_cluster.py`:
- valid lifecycle INITIALIZING → RUNNING → BOOTSTRAPPING → baseline → OPTIMIZING → CONVERGING/FINALIZING → best + report → COMPLETED;
- pause/resume;
- stop/fail terminal reasons and `closed_at`;
- invalid transitions (start twice, complete without best/report, resume while running);
- `max_agents` minimum and setter;
- terminal-state invariants.

`tests/unit/cluster/test_direction.py`:
- PROPOSED → ACTIVE → PAUSED → ACTIVE → COMPLETED;
- ABANDONED from PROPOSED/ACTIVE/PAUSED;
- invalid transitions and empty close reason;
- summary update and terminal `closed_at`.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/unit/cluster
```

Expected: import failures for the missing modules.

- [ ] **Step 3: Implement**

Implement enums, errors, and the two aggregates with guards. Keep each file ≤300 lines and each function ≤40 lines.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/unit/cluster
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

- [ ] **Step 5: Commit, record, push**

```bash
scripts/push_refactor.sh
```
