# F02-06 Global Hardware Ledger and Fencing Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`) syntax.

**Goal:** Implement the shared hardware ledger with one active lease per device, monotonic fencing tokens, TTL expiry, execution confirmation, quarantine, and a persistent queue.

**Architecture:** `platform/hardware/ledger.py` owns `hardware.db`. A partial unique index enforces one active lease per device; fencing tokens are issued per device and checked on execution/release. Expired leases keep `execution_active` until `confirm_stopped`, so a new lease cannot be granted early.

**Spec:** `SPEC/08-persistence-and-events.md` §11.

## Global Constraints

- One active lease (`state='LEASED'` or `execution_active=1`) per device across clusters.
- Fencing tokens are monotonic per device; old tokens cannot start/release/replace execution.
- TTL expiry does not clear `execution_active`; explicit confirmation is required.
- Quarantined devices reject new leases until cleared.
- Queue entries persist cluster/task/job/purpose/priority and dedupe key.
- No old-code imports or old tests.

## Files

- Create: `src/justkernel/platform/hardware/ledger.py` — schema, `HardwareLedger`, `DeviceLease`, `QueueEntry`, errors
- Modify: `src/justkernel/shared/error_codes.py` — hardware codes
- Create: `tests/adapters/test_hardware_ledger.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Interfaces

```python
def apply_hardware_schema(connection) -> None: ...

class DeviceLease:
    lease_id, cluster_id, task_id, job_id, device_id, state,
    execution_active, fencing_token, expires_at

class HardwareLedger:
    def acquire(self, *, lease_id, cluster_id, task_id, job_id, device_id,
                ttl_ms, now_ms) -> DeviceLease: ...
    def start_execution(self, lease_id, fencing_token) -> DeviceLease: ...
    def release(self, lease_id, fencing_token) -> DeviceLease: ...
    def mark_expired(self, lease_id, now_ms) -> DeviceLease: ...
    def confirm_stopped(self, lease_id, fencing_token) -> DeviceLease: ...
    def get_lease(self, lease_id) -> DeviceLease: ...
    def active_lease(self, device_id) -> DeviceLease | None: ...
    def quarantine(self, device_id, reason, now_ms) -> None: ...
    def clear_quarantine(self, device_id) -> None: ...
    def enqueue(self, *, cluster_id, task_id, job_id, device_id, purpose,
                priority, dedupe_key, now_ms) -> bool: ...
    def queue_status(self, device_id=None) -> tuple[QueueEntry, ...]: ...
```

## Steps

- [ ] **Step 1: Write failing tests**

`tests/adapters/test_hardware_ledger.py`:
- acquire/release and one lease per device;
- monotonic fencing and old-token rejection;
- expired execution blocks new lease until confirmed;
- quarantine blocks/clears;
- queue dedupe and status;
- cross-connection conflict;
- schema idempotency.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/adapters/test_hardware_ledger.py
```

Expected: import failure for missing module.

- [ ] **Step 3: Implement**

Use the SPEC 08 §11 schema and explicit SQL. Keep files ≤600 lines and functions ≤40 lines.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/adapters/test_hardware_ledger.py
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

- [ ] **Step 5: Commit, record, push**

```bash
scripts/push_refactor.sh
```
