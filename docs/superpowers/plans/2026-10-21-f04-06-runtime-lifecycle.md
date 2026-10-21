# F04-06 Runtime Lifecycle and 100-agent Cap

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`).

**Goal:** Prove the 100-logical-agent cap, close workers with lease cleanup, and leave no runtime orphans after shutdown.

**Architecture:** The domain `AgentService` owns the cluster-wide active-agent cap. `AgentRuntimePool` owns logical sessions and process slots. `AgentLeaseBook` maps device leases to owners; `WorkerLifecycle` releases a worker's leases only after checking it is closable. `AgentRuntimePool.close_all()` closes every non-closed session after confirming no turn is active.

**Spec:** `SPEC/05-agent-runtime-and-skills.md` §2–3; `SPEC/11-testing-and-quality.md` §3.8.

## Global Constraints

- Active agents (not CLOSED) ≤ `max_agents` (default 100).
- Closing a worker with a running task fails and leaves leases intact.
- A successful worker close releases all leases owned by that worker.
- Shutdown closes all logical runtime sessions; no active sessions remain.
- Checkpoints are retained as recovery data, not evidence.
- No old-code imports/tests.

## Files

- Modify: `src/justkernel/application/agent_service.py` — `get_agent`
- Create: `src/justkernel/application/lease_book.py` — `AgentLeaseBook`
- Create: `src/justkernel/application/worker_lifecycle.py` — `WorkerLifecycle`
- Modify: `src/justkernel/platform/runtime/pool.py` — `close_all`
- Create: `tests/integration/test_agent_lifecycle.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`, create `p4-exit-report.md`

## Steps

- [ ] **Step 1: Write failing integration tests**

Cover:
- domain + runtime caps at 100;
- worker with running task cannot close and keeps its lease;
- completed worker close releases lease;
- 100 sessions shutdown to zero active;
- checkpoint survives shutdown.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/integration/test_agent_lifecycle.py
```

Expected: missing lease/lifecycle modules and `close_all`.

- [ ] **Step 3: Implement**

Keep validation fail-closed; a lease is released only after ownership/task checks pass.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/integration/test_agent_lifecycle.py
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

- [ ] **Step 5: P4 exit report, commit, push**

Write `docs/refactor/p4-exit-report.md`, then commit and push.
