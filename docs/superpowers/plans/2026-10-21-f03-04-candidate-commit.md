# F03-04 Candidate Commit and Import Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`) syntax.

**Goal:** Implement application use cases for importing a root candidate and committing GENERATE/OPTIMIZE candidates from an optimizer task.

**Architecture:** `application/candidate_service.py` depends on candidate/task/agent repository ports and `IdFactoryPort`. It validates task kind/state/worker ownership and parent provenance before creating an immutable `CandidateVersion`.

**Spec:** `SPEC/04-domain-model.md` §4.5; `SPEC/13-generation-and-iteration-contract.md` §2.

## Global Constraints

- IMPORT creates a root candidate authored by `system`; task_id/author_agent_id are null.
- GENERATE creates a root candidate authored by the optimizer task worker.
- OPTIMIZE creates a child whose parent is the task's base candidate.
- Only a RUNNING GENERATE/OPTIMIZE task with an OPTIMIZER worker may commit.
- Parent must exist in the same cluster; source files must be non-empty.
- Candidate source remains immutable; a new commit is a new CandidateId.
- Application imports ports/domain only, never platform.
- No old-code imports or old tests.

## Files

- Modify: `src/justkernel/application/ports.py` — add `CandidateRepositoryPort`
- Modify: `src/justkernel/application/fakes.py` — add `InMemoryCandidateRepository` + bundle field
- Create: `src/justkernel/application/candidate_service.py` — `CandidateService`
- Create: `tests/application/test_candidate_commit.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Interfaces

```python
class CandidateRepositoryPort(Protocol):
    def insert(self, candidate: CandidateVersion) -> None: ...
    def get(self, candidate_id: CandidateId) -> CandidateVersion: ...
    def list_by_cluster(self, cluster_id: ClusterId) -> tuple[CandidateVersion, ...]: ...

class CandidateService:
    def import_candidate(self, *, cluster_id, direction_id, source_files,
                         diff_artifact, import_id, created_at) -> CandidateVersion: ...
    def commit_candidate(self, *, task_id, author_agent_id, source_files,
                         diff_artifact, created_at) -> CandidateVersion: ...
```

## Steps

- [ ] **Step 1: Write failing tests**

`tests/application/test_candidate_commit.py`:
- IMPORT root candidate with system provenance;
- GENERATE commit with parent null;
- OPTIMIZE commit with parent equal to the task base candidate;
- reject non-GENERATE/OPTIMIZE task, non-RUNNING task, non-optimizer author, wrong parent;
- reject empty source files.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/application/test_candidate_commit.py
```

Expected: import failure for the missing service.

- [ ] **Step 3: Implement**

Add the candidate repository port/fake, then the thin service. Keep files ≤400 lines and functions ≤40 lines.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/application/test_candidate_commit.py
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

- [ ] **Step 5: Commit, record, push**

```bash
scripts/push_refactor.sh
```
