# F02-08 Adapter Suite Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`) syntax.

**Goal:** Add an adapter-level end-to-end suite that exercises the journal, global operator registry, hardware ledger, artifact store, projections, events/outbox, and recovery together.

**Architecture:** Test-only integration feature. No new production module is expected; if the suite exposes an adapter defect, fix it under the owning adapter with a focused regression test.

**Spec:** `SPEC/11-testing-and-quality.md` §6; prior P2 adapters.

## Global Constraints

- Use temporary data roots/files; no real devices, models, or network.
- Exercise cross-adapter boundaries: registry/journal/hardware/artifacts/projections/recovery.
- Do not import old code or run old tests.
- Keep the suite deterministic (explicit `now_ms`, no sleeps).

## Files

- Create: `tests/adapters/test_adapter_suite.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Steps

- [ ] **Step 1: Write the integration suite**

`tests/adapters/test_adapter_suite.py`:
- create temp `journal.db`, `registry.db`, `hardware.db`, artifact root;
- reserve an operator and reject a second active cluster;
- write cluster/agent/event/outbox through `UnitOfWork`;
- persist/read an artifact;
- rebuild board/cluster projections;
- acquire/release a hardware lease and verify fencing;
- run startup recovery and verify paused/interrupted/pending outbox;
- release the registry and allow a new cluster.

- [ ] **Step 2: Run the suite**

```bash
uv run pytest -q tests/adapters/test_adapter_suite.py
```

Expected: pass once adapters are composed correctly. If it fails, fix the owning adapter and add a focused regression test.

- [ ] **Step 3: Run the full adapter suite**

```bash
uv run pytest -q tests/adapters
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

- [ ] **Step 4: Commit, record, push**

```bash
scripts/push_refactor.sh
```
