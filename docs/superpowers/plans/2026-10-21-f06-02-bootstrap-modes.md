# F06-02 GENERATE/IMPORT and Root Candidate

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`).

**Goal:** After a validated cluster start, create an active baseline direction for GENERATE, or create a system-authored root candidate for IMPORT, without marking either as PASS.

**Architecture:** Add a `DirectionRepositoryPort` and in-memory adapter, then `BootstrapService` which validates the started cluster/mode/mentor and creates the direction/candidate. GENERATE creates no candidate; IMPORT uses `CandidateService.import_candidate` with the direction.

**Spec:** `SPEC/13-generation-and-iteration-contract.md` §2.

## Global Constraints

- GENERATE: baseline direction, no root candidate.
- IMPORT: baseline direction plus root candidate with `parent_id=None`, system author, import id.
- The imported root candidate is not PASS and does not establish a baseline.
- A direction is assigned to an existing mentor in the same cluster and is ACTIVE.
- Repeated/invalid modes fail closed.
- No old-code imports/tests.

## Files

- Modify: `src/justkernel/application/ports.py` — direction repository port
- Modify: `src/justkernel/application/fakes.py` — in-memory direction repository
- Create: `src/justkernel/application/bootstrap_service.py`
- Create: `tests/application/test_bootstrap_modes.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Steps

- [ ] **Step 1: Write failing bootstrap tests**

Cover GENERATE, IMPORT, mode mismatch, no mentor, and proof that the root candidate is not PASS.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/application/test_bootstrap_modes.py
```

Expected: missing bootstrap service/repository.

- [ ] **Step 3: Implement**

Create the direction/candidate only after validation. Do not mutate cluster baseline fields.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/application/test_bootstrap_modes.py
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

- [ ] **Step 5: Commit, record, push**
