# F01-09 Invariants, Events, and Stable Error Codes Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`) syntax.

**Goal:** Centralize stable error codes, define the domain event envelope, and enforce the key cross-aggregate invariants.

**Architecture:** `shared/error_codes.py` is the code registry; `shared/events.py` defines event types/envelopes; `cluster/invariants.py` checks cluster/agent/task/candidate/lease combinations; `comm/inbox.py` implements MessageId deduplication.

**Spec:** `SPEC/04-domain-model.md` §5; `SPEC/06-communication-and-orchestration.md` §11.

## Global Constraints

- Error codes are unique, stable strings; existing codes do not change.
- Events are immutable and carry cluster/aggregate/actor/correlation metadata.
- One cluster has exactly one supervisor; active agents ≤ max_agents.
- Worker mentor must exist, be a mentor, and be in the same cluster.
- Task kind must match worker role; closed workers cannot receive tasks.
- Every submitted candidate has at least one TestRecord; baseline/best requires a FULL PASS.
- BestSelection references existing candidates/records; VALIDATED final records must be full passes.
- At most one LEASED hardware lease per device.
- Message duplicates are rejected by MessageId.
- No old-code imports or old tests.

## Files

- Create: `src/justkernel/shared/error_codes.py` — `ErrorCode`
- Modify: error classes in `shared`, `testing`, `cluster`, `agent`, `task`, `candidate`, `report`, `comm`
- Create: `src/justkernel/shared/events.py` — `EventType`, `DomainEvent`
- Modify: `src/justkernel/shared/ids.py` — add `EventId`
- Modify: `src/justkernel/shared/__init__.py` — export `EventId`
- Create: `src/justkernel/comm/inbox.py` — `MessageInbox`
- Create: `src/justkernel/cluster/invariants.py` — `InvariantError`, validators
- Create: `tests/unit/test_error_codes.py`
- Create: `tests/unit/test_events.py`
- Create: `tests/unit/test_invariants.py`
- Create: `tests/unit/comm/test_inbox.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Interfaces

```python
class ErrorCode(StrEnum): ...  # all existing codes + invalid_event + invariant.violation
class EventType(StrEnum): ...  # SPEC 06 §11
class DomainEvent:
    id: EventId
    cluster_id: ClusterId
    type: EventType
    event_version: int
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    actor: Principal
    occurred_at: int
    correlation_id: str | None = None
    causation_id: str | None = None
    payload: Mapping[str, object] = ...

class MessageInbox:
    def accept(self, message: Message) -> bool: ...
    def __len__(self) -> int: ...

class InvariantError(JustKernelError): code = ErrorCode.INVARIANT_VIOLATION
def validate_cluster_agents(cluster, agents) -> None: ...
def validate_task_assignment(task, worker, mentor) -> None: ...
def validate_candidate_evidence(candidate, records) -> None: ...
def require_full_pass(records) -> None: ...
def validate_best_selection(selection, candidate_ids, records) -> None: ...
def validate_lease_uniqueness(leases) -> None: ...
```

## Steps

- [ ] **Step 1: Write failing tests**

`test_error_codes.py`: all error classes use `ErrorCode`; values unique.
`test_events.py`: valid event, immutable payload, invalid versions/time/aggregate.
`test_inbox.py`: duplicate MessageId returns False.
`test_invariants.py`: supervisor/agent limits; worker mentor; task ownership/kind; candidate evidence/full pass; best selection final evidence; lease uniqueness.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/unit/test_error_codes.py tests/unit/test_events.py tests/unit/comm/test_inbox.py tests/unit/test_invariants.py
```

Expected: import failures for missing modules.

- [ ] **Step 3: Implement**

Centralize error codes; add EventId/events; add inbox; add validators. Keep files ≤300 lines and functions ≤40 lines.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

- [ ] **Step 5: Commit, record, push**

```bash
scripts/push_refactor.sh
```
