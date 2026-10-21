# F03-02 Cluster Lifecycle Use Cases Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`) syntax.

**Goal:** Implement application-level cluster create/start/pause/resume/converge/stop use cases over repository and ID ports.

**Architecture:** `application/cluster_service.py` orchestrates the Cluster aggregate and `ClusterRepositoryPort`/`IdFactoryPort`. It does not import platform adapters; versioned updates use the repository's current version.

**Spec:** `SPEC/04-domain-model.md` §4.1; `SPEC/06-communication-and-orchestration.md` §5, §8.

## Global Constraints

- Cluster creation persists INITIALIZING; start requires the aggregate transition.
- State changes reload, mutate the aggregate, and update with the current version.
- Invalid transitions raise the domain `ClusterError`; no silent correction.
- Application layer imports ports/domain only, never platform.
- No old-code imports or old tests.

## Files

- Create: `src/justkernel/application/cluster_service.py` — `ClusterService`
- Create: `tests/application/test_cluster_lifecycle.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Interfaces

```python
class ClusterService:
    def __init__(self, clusters: ClusterRepositoryPort, ids: IdFactoryPort) -> None: ...
    def create_cluster(self, *, operator_id, supervisor_id, operator_spec_ref,
                       start_mode, max_agents=100, created_at,
                       continued_from_cluster_id=None) -> Cluster: ...
    def get(self, cluster_id: ClusterId) -> Cluster: ...
    def start_cluster(self, cluster_id: ClusterId) -> Cluster: ...
    def pause_cluster(self, cluster_id: ClusterId) -> Cluster: ...
    def resume_cluster(self, cluster_id: ClusterId) -> Cluster: ...
    def converge_cluster(self, cluster_id: ClusterId) -> Cluster: ...
    def stop_cluster(self, cluster_id: ClusterId, reason: str, now_ms: int) -> Cluster: ...
    def set_max_agents(self, cluster_id: ClusterId, max_agents: int) -> Cluster: ...
```

## Steps

- [ ] **Step 1: Write failing tests**

`tests/application/test_cluster_lifecycle.py`:
- create persists INITIALIZING;
- start/pause/resume/converge transitions and version increments;
- stop records reason/closed_at;
- invalid transitions raise `ClusterError`;
- `set_max_agents` validation.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/application/test_cluster_lifecycle.py
```

Expected: import failure for the missing service.

- [ ] **Step 3: Implement**

Keep the service thin: load, call the aggregate command, update with the repository's current version.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/application/test_cluster_lifecycle.py
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

- [ ] **Step 5: Commit, record, push**

```bash
scripts/push_refactor.sh
```
