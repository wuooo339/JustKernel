# F06-01 OperatorSpec Startup Validation and Cluster Start

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`).

**Goal:** Validate a complete startup request, reserve the global operator, create the initial supervisor/consultants/mentors, and transition the cluster to RUNNING; reject invalid input and duplicate active operators.

**Architecture:** `ClusterStartService` composes `OperatorSpec`, `ClusterService`, `AgentService`, and an `OperatorRegistryPort`. Validation happens before registry reservation. A failed startup releases the registry reservation.

**Spec:** `SPEC/13-generation-and-iteration-contract.md` §1; `SPEC/06-communication-and-orchestration.md` §5.

## Global Constraints

- GENERATE requires a tester skill but no baseline source; IMPORT requires a baseline source.
- Profiler skill is required when performance target is enabled.
- Backend must be in the frozen evaluation policy allow-list.
- Initial roles must fit within `max_agents`; supervisor is unique.
- Duplicate active operator reservation is a conflict.
- No old-code imports/tests.

## Files

- Create: `src/justkernel/application/start_cluster_service.py`
- Modify: `src/justkernel/application/ports.py` — registry port
- Modify: `src/justkernel/application/cluster_service.py` — optional preallocated cluster id
- Create: `tests/application/test_start_cluster.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Steps

- [ ] **Step 1: Write failing startup tests**

Cover valid GENERATE, invalid IMPORT, missing profiler for performance target, backend mismatch, capacity, duplicate operator, and no reservation after validation failure.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/application/test_start_cluster.py
```

Expected: missing service.

- [ ] **Step 3: Implement**

Validate first; reserve second; create roles and start third. On failure, release the reservation.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/application/test_start_cluster.py
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

- [ ] **Step 5: Commit, record, push**
