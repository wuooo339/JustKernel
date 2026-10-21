# F01-07 TestRecord, HardwareLease, and ExplorationReport Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`) syntax.

**Goal:** Implement the immutable TestRecord, the hardware lease state machine, and the immutable exploration report.

**Architecture:** Pure domain modules under `testing/` and `report/`. TestRecord is frozen and distinguishes executed evidence from unexecuted audit records. HardwareLease is a mutable state machine. ExplorationReport is frozen and only references existing candidate/record IDs (existence checked by repositories).

**Spec:** `SPEC/04-domain-model.md` §4.6–4.8; `SPEC/07-testing-and-profile.md` §3.

## Global Constraints

- TestRecord is immutable; a new execution creates a new record.
- Executed records require task + job; audit records require audit_id and no task/job.
- PASS requires execution and coverage FULL or SUBSET; only FULL PASS can establish baseline/best (application layer).
- Audit outcome is CANCELLED or UNKNOWN, coverage NONE, executed false.
- Hardware lease states: QUEUED → LEASED → RELEASED / EXPIRED.
- Report is append-only by revision; best candidate must be one of its candidates when present.
- No old-code imports or old tests.

## Files

- Create: `src/justkernel/testing/state.py` — `TestRecordKind`, `TestOutcome`, `TestCoverage`, `LeaseState`
- Create: `src/justkernel/testing/errors.py` — `TestRecordError`, `LeaseError`
- Create: `src/justkernel/testing/record.py` — `ArtifactRef`, `Environment`, `TestRecord`
- Create: `src/justkernel/testing/lease.py` — `DeviceId`, `HardwareLease`
- Create: `src/justkernel/report/errors.py` — `ReportError`
- Create: `src/justkernel/report/report.py` — `ReportDirection`, `ExplorationReport`
- Create: `tests/unit/testing/test_record.py`
- Create: `tests/unit/testing/test_lease.py`
- Create: `tests/unit/report/test_report.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Interfaces

```python
class TestRecordKind(StrEnum): TEST; PROFILE
class TestOutcome(StrEnum): PASS; FAIL; ERROR; CANCELLED; UNKNOWN
class TestCoverage(StrEnum): FULL; SUBSET; NONE
class LeaseState(StrEnum): QUEUED; LEASED; RELEASED; EXPIRED

class ArtifactRef: ref: str; digest: Digest
class Environment: values: tuple[tuple[str, str], ...]; digest() -> Digest
class TestRecord:  # frozen
    id, candidate_id, kind, skill_ref, backend, outcome, coverage, executed,
    artifact, environment, created_at, task_id=None, job_id=None, audit_id=None, summary=""
    @property is_full_pass -> bool
    @property is_audit -> bool

class HardwareLease:
    id, device_id, task_id, owner_agent_id, state=QUEUED,
    acquired_at=None, expires_at=None, released_at=None
    def acquire(self, now_ms: int, ttl_ms: int) -> None
    def release(self, now_ms: int) -> None
    def expire(self, now_ms: int) -> None

class ExplorationReport:  # frozen
    id: str
    cluster_id: ClusterId
    best_candidate_id: CandidateId | None
    revision: int
    directions: tuple[ReportDirection, ...]
    candidates: tuple[CandidateId, ...]
    records: tuple[TestRecordId, ...]
    failures: tuple[str, ...]
    decision: str
    created_at: int
```

## Steps

- [ ] **Step 1: Write failing tests**

`test_record.py`: executed PASS FULL; audit CANCELLED/NONE; PASS without execution; coverage/outcome/job/task/audit contradictions; frozen record.

`test_lease.py`: QUEUED → LEASED → RELEASED; LEASED → EXPIRED; invalid transitions/TTL/time.

`test_report.py`: valid report with best in candidates; no best for stopped/failed; best not in candidates rejected; revision/duplicates/decision/failures validation.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/unit/testing tests/unit/report
```

Expected: import failures for missing modules.

- [ ] **Step 3: Implement**

Keep files ≤300 lines and functions ≤40 lines.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/unit/testing tests/unit/report
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

- [ ] **Step 5: Commit, record, push**

```bash
scripts/push_refactor.sh
```
