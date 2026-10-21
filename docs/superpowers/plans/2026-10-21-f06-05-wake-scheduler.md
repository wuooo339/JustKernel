# F06-05 Inbox, Wake, Single Turn, WAIT and Debounce

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`).

**Goal:** Implement deterministic per-agent wake scheduling: `(agent_id,event_id)` dedupe, debounce merging, one running Turn per agent, pending events during RUNNING, and one-shot WAIT deadlines.

**Architecture:** Add immutable `WakeRequest`/`WakeWait` domain records to `comm/wake.py`; `WakeScheduler` in application owns in-memory inbox/wake state and atomically claims one PENDING wake per agent. It is driven by explicit `now_ms`, so no sleeps are needed.

**Spec:** `SPEC/13-generation-and-iteration-contract.md` §4.

## Global Constraints

- Duplicate `(agent_id,event_id)` is ignored.
- An agent never has two CLAIMED turns.
- Notifications during RUNNING remain pending and merge after completion.
- Debounce delays claim; events merge into one wake.
- WAIT requires a deadline and wakes exactly once; an arriving event satisfies it.
- Stale `expected_agent_version` cannot be claimed.
- No old-code imports/tests.

## Files

- Modify: `src/justkernel/shared/ids.py` — `WakeId`
- Modify: `src/justkernel/comm/wake.py` — `WakeState`, `WakeRequest`, `WakeWait`
- Modify: `src/justkernel/shared/error_codes.py` — wake error
- Create: `src/justkernel/application/wake_scheduler.py`
- Create: `tests/application/test_wake_scheduler.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Steps

- [ ] **Step 1: Write failing scheduler tests**

Cover dedupe, debounce merge, single running turn, pending events, WAIT deadline, event-satisfied WAIT, and stale version.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/application/test_wake_scheduler.py
```

- [ ] **Step 3: Implement**

Keep all transitions explicit and time-driven. Never claim while RUNNING or before `not_before`.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/application/test_wake_scheduler.py
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

- [ ] **Step 5: Commit, record, push**
