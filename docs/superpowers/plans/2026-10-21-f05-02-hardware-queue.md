# F05-02 Hardware Queue, Lease, TTL, Fencing

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`).

**Goal:** Add a queue adapter over the global hardware ledger: prioritized FIFO enqueue, device-exclusive claim, release, queue status, TTL expiry, quarantine until confirmed stopped, and stale-fencing rejection.

**Architecture:** `HardwareLedger` remains the lease/fencing store. A new `HardwareQueue` in `platform/hardware/queue.py` selects queued rows and atomically acquires the ledger lease. Queue rows move `QUEUED → LEASED → DONE/EXPIRED/CANCELLED`; expired active executions quarantine the device until `confirm_stopped`.

**Spec:** `SPEC/07-testing-and-profile.md` §6; `SPEC/08-persistence-and-events.md` §11.

## Global Constraints

- One `LEASED` lease per device across clusters.
- Queue order: priority ascending, then enqueue time/id.
- Dedupe key is idempotent.
- TTL expiry never silently reassigns a device with active execution.
- A quarantined device cannot be leased; confirmation clears the quarantine.
- Stale fencing tokens cannot release or start an execution.
- No old-code imports/tests.

## Files

- Create: `src/justkernel/platform/hardware/queue.py` — `HardwareQueue`, `HardwareQueueStatus`
- Create: `tests/adapters/test_hardware_queue.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Interfaces

```python
class HardwareQueue:
    def enqueue(...) -> int                  # 1-based queue position
    def claim_next(lease_id, device_id, ttl_ms, now_ms) -> DeviceLease | None
    def release(lease_id, fencing_token, now_ms) -> DeviceLease
    def expire(now_ms) -> tuple[DeviceLease, ...]
    def confirm_stopped(lease_id, fencing_token, now_ms) -> DeviceLease
    def cancel(queue_id) -> None
    def status(device_id=None) -> HardwareQueueStatus
```

## Steps

- [ ] **Step 1: Write failing adapter tests**

Cover priority/FIFO/dedupe, exclusive claim, release to next, TTL expiry, quarantine until confirmation, and stale fencing.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/adapters/test_hardware_queue.py
```

Expected: missing `HardwareQueue`.

- [ ] **Step 3: Implement queue over ledger**

Keep SQL/queue state transitions explicit; no sleeps, no real devices.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/adapters/test_hardware_queue.py
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

- [ ] **Step 5: Commit, record, push**
