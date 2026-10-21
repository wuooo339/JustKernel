# F03-03 Agent/Worker Lifecycle and Task Dispatch Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`) syntax.

**Goal:** Implement application use cases for creating supervisor/consultant/mentor agents, opening/closing mentor-owned workers, dispatching tasks, and completing them.

**Architecture:** `application/agent_service.py` depends on cluster/agent/task repository ports and `IdFactoryPort`. It loads aggregates, validates mentor ownership/role/max_agents, calls aggregate commands, and persists with optimistic versions. Cross-aggregate rules use `cluster.invariants.validate_task_assignment`.

**Spec:** `SPEC/04-domain-model.md` §4.2; `SPEC/06-communication-and-orchestration.md` §6–7.

## Global Constraints

- Workers are created/closed only by their mentor.
- Worker has exactly one mentor; closed workers cannot receive tasks.
- Active agents ≤ cluster.max_agents.
- Only non-worker roles use `create_agent`; worker roles use `open_worker`.
- Task kind must match worker role; a worker has at most one running task.
- Closing a running worker is rejected; complete/cancel first.
- Application imports ports/domain only, never platform.
- No old-code imports or old tests.

## Files

- Modify: `src/justkernel/application/ports.py` — add `AgentRepositoryPort.list_by_cluster`
- Modify: `src/justkernel/application/fakes.py` — implement it
- Modify: `src/justkernel/platform/persistence/repositories.py` — implement it
- Create: `src/justkernel/application/agent_service.py` — `AgentService`
- Create: `tests/application/test_worker_lifecycle.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Interfaces

```python
class AgentService:
    def __init__(self, clusters, agents, tasks, ids) -> None: ...
    def create_agent(self, *, cluster_id, role, model_profile, skills,
                     agent_id=None, mentor_id=None) -> AgentInstance: ...
    def open_worker(self, *, mentor_id, role, model_profile, skills) -> AgentInstance: ...
    def close_worker(self, *, mentor_id, worker_id, now_ms) -> AgentInstance: ...
    def assign_task(self, *, mentor_id, worker_id, kind, direction_id,
                    operator_spec_ref, context_ref, context_digest,
                    budget_ref, objective, constraints=(), candidate_id=None,
                    skill_ref=None, retry_of_task_id=None,
                    created_at) -> Task: ...
    def complete_task(self, *, mentor_id, task_id, result_ref, now_ms) -> Task: ...
```

## Steps

- [ ] **Step 1: Write failing tests**

`tests/application/test_worker_lifecycle.py`:
- create supervisor/mentor; open worker; states and mentor binding;
- worker role cannot be created via `create_agent`;
- non-mentor cannot open/close or assign another mentor's worker;
- max_agents enforcement;
- task dispatch sets Task/Worker RUNNING and rejects a second task;
- close running worker rejected; complete task returns both to usable states;
- closed worker rejects tasks.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/application/test_worker_lifecycle.py
```

Expected: import failure for the missing service.

- [ ] **Step 3: Implement**

Keep the service thin; use aggregate commands and `validate_task_assignment`. Extend the agent repository port/fakes/SQL adapter with `list_by_cluster`.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/application/test_worker_lifecycle.py
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

- [ ] **Step 5: Commit, record, push**

```bash
scripts/push_refactor.sh
```
