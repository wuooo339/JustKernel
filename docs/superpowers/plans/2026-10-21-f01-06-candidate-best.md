# F01-06 Candidate DAG and BestSelection Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`) syntax.

**Goal:** Implement immutable candidate versions, a provenance-checked candidate DAG, and the independent BestSelection state machine.

**Architecture:** Pure domain modules under `src/justkernel/candidate/`. `SourceRevision` computes a canonical digest from files; `CandidateVersion` is frozen; `CandidateGraph` validates parent/cluster/cycle rules; `BestSelection` is a separate frozen state machine.

**Spec:** `SPEC/04-domain-model.md` §4.5; `SPEC/07-testing-and-profile.md` §2, §7.

## Global Constraints

- Candidate source is immutable; changes require a new CandidateId.
- Exactly one provenance source: task/optimizer or system import.
- Parent must belong to the same cluster; the DAG must be acyclic.
- BestSelection is independent of candidate source state; only VALIDATED can update cluster.best (application layer).
- BestSelection nomination requires evidence records; final validation requires final task/record IDs.
- No old-code imports or old tests.

## Files

- Create: `src/justkernel/candidate/source.py` — `SourceRevision`
- Create: `src/justkernel/candidate/state.py` — `SelectionState`
- Create: `src/justkernel/candidate/errors.py` — `CandidateError`, `BestSelectionError`
- Create: `src/justkernel/candidate/candidate.py` — `CandidateVersion`
- Create: `src/justkernel/candidate/graph.py` — `CandidateGraph`
- Create: `src/justkernel/candidate/best.py` — `BestSelection`
- Modify: `src/justkernel/shared/ids.py` — add `BestSelectionId`
- Modify: `src/justkernel/shared/__init__.py` — export it
- Create: `tests/unit/candidate/test_candidate.py`
- Create: `tests/unit/candidate/test_best.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Interfaces

```python
class SourceRevision:
    files: tuple[tuple[ProjectPath, str], ...]
    digest: Digest  # computed, canonical file map

class CandidateVersion:  # frozen
    id: CandidateId
    cluster_id: ClusterId
    direction_id: DirectionId
    parent_id: CandidateId | None
    author_agent_id: AgentId | None
    author_principal: Principal
    task_id: TaskId | None
    import_id: str | None
    source: SourceRevision
    diff_artifact: str
    created_at: int

class CandidateGraph:
    def add(self, candidate: CandidateVersion) -> None: ...
    def get(self, candidate_id: CandidateId) -> CandidateVersion: ...
    def children(self, candidate_id: CandidateId) -> tuple[CandidateVersion, ...]: ...
    def ancestors(self, candidate_id: CandidateId) -> tuple[CandidateVersion, ...]: ...
    def __len__(self) -> int: ...

class BestSelection:  # frozen
    id: BestSelectionId
    cluster_id: ClusterId
    candidate_id: CandidateId
    policy_digest: Digest
    nomination_record_ids: tuple[TestRecordId, ...]
    reason: str
    created_at: int
    final_task_ids: tuple[TaskId, ...] = ()
    final_record_ids: tuple[TestRecordId, ...] = ()
    state: SelectionState = PENDING

    def validated(self, final_task_ids, final_record_ids) -> Self: ...
    def failed(self, reason) -> Self: ...
```

## Steps

- [ ] **Step 1: Write failing tests**

`tests/unit/candidate/test_candidate.py`:
- SourceRevision digest stable across file order; duplicate/empty rejection;
- task-authored candidate and system import; exactly one source;
- frozen candidate;
- graph add/get/children/ancestors; duplicate/missing/cross-cluster parent rejection.

`tests/unit/candidate/test_best.py`:
- nomination evidence required;
- PENDING → VALIDATED with final task/record IDs;
- PENDING → FAILED with reason;
- invalid transitions, empty final evidence, duplicate IDs.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/unit/candidate
```

Expected: import failures for missing modules.

- [ ] **Step 3: Implement**

Add `BestSelectionId`, source digest, frozen candidate, graph, and best-selection state machine. Keep files ≤300 lines and functions ≤40 lines.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/unit/candidate
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

- [ ] **Step 5: Commit, record, push**

```bash
scripts/push_refactor.sh
```
