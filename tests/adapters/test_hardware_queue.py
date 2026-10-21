from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from justkernel.platform.hardware.ledger import (
    DeviceLease,
    DeviceQuarantinedError,
    FencingError,
    HardwareLedger,
    HardwareLedgerError,
    apply_hardware_schema,
)
from justkernel.platform.hardware.queue import HardwareQueue
from justkernel.platform.persistence.database import connect


# ---- helpers ----------------------------------------------------------------
def _queue(tmp_path: Path) -> tuple[sqlite3.Connection, HardwareQueue]:
    connection = connect(str(tmp_path / "hardware.db"))
    apply_hardware_schema(connection)
    return connection, HardwareQueue(HardwareLedger(connection))


def _enqueue(
    queue: HardwareQueue,
    *,
    job_id: str = "job-1",
    device_id: str = "npu:0",
    cluster_id: str = "cluster-1",
    priority: int = 1,
    dedupe_key: str | None = None,
    now_ms: int = 0,
) -> int:
    return queue.enqueue(
        cluster_id=cluster_id,
        task_id=f"task-{job_id}",
        job_id=job_id,
        device_id=device_id,
        purpose="test",
        priority=priority,
        dedupe_key=dedupe_key or f"dedupe-{job_id}",
        now_ms=now_ms,
    )


def _claim(
    queue: HardwareQueue,
    *,
    lease_id: str = "lease-1",
    device_id: str = "npu:0",
    ttl_ms: int = 100,
    now_ms: int = 0,
) -> DeviceLease | None:
    return queue.claim_next(
        lease_id=lease_id,
        device_id=device_id,
        ttl_ms=ttl_ms,
        now_ms=now_ms,
    )


# ---- ordering and dedupe ----------------------------------------------------
def test_priority_fifo_and_dedupe(tmp_path: Path) -> None:
    _, queue = _queue(tmp_path)

    assert _enqueue(queue, job_id="job-1", priority=1) == 1
    assert _enqueue(queue, job_id="job-2", priority=0) == 1
    assert _enqueue(queue, job_id="job-1", priority=1) == 2
    status = queue.status("npu:0")
    assert [entry.job_id for entry in status.queued] == ["job-2", "job-1"]


def test_claim_is_device_exclusive_across_clusters(tmp_path: Path) -> None:
    _, queue = _queue(tmp_path)
    _enqueue(queue, job_id="job-a", cluster_id="cluster-a")
    _enqueue(queue, job_id="job-b", cluster_id="cluster-b", priority=2)

    first = _claim(queue)
    assert first is not None
    assert first.job_id == "job-a"
    assert first.fencing_token == 1
    assert queue.status("npu:0").active_lease == first
    assert _claim(queue, lease_id="lease-2") is None

    released = queue.release("lease-1", 1, 10)
    assert released.state == "RELEASED"
    assert queue.status("npu:0").active_lease is None
    second = _claim(queue, lease_id="lease-2", now_ms=11)
    assert second is not None
    assert second.job_id == "job-b"
    assert second.fencing_token == 2


def test_stale_fencing_token_cannot_release(tmp_path: Path) -> None:
    _, queue = _queue(tmp_path)
    _enqueue(queue)
    lease = _claim(queue)

    with pytest.raises(FencingError):
        queue.release(lease.lease_id, 999, 10)
    assert queue.status("npu:0").active_lease is not None

    queue.release(lease.lease_id, lease.fencing_token, 10)
    assert queue.status("npu:0").active_lease is None


# ---- TTL and quarantine -----------------------------------------------------
def test_expired_execution_quarantines_until_confirmed(tmp_path: Path) -> None:
    _, queue = _queue(tmp_path)
    _enqueue(queue, job_id="job-1")
    _enqueue(queue, job_id="job-2")
    lease = _claim(queue, ttl_ms=10)
    queue.ledger.start_execution(lease.lease_id, lease.fencing_token)

    expired = queue.expire(10)
    assert [item.lease_id for item in expired] == [lease.lease_id]
    assert queue.status("npu:0").quarantined is True
    assert queue.status("npu:0").active_lease is not None
    with pytest.raises(DeviceQuarantinedError):
        _claim(queue, lease_id="lease-2")

    queue.confirm_stopped(lease.lease_id, lease.fencing_token, 11)
    assert queue.status("npu:0").quarantined is False
    assert queue.status("npu:0").active_lease is None
    assert _claim(queue, lease_id="lease-2", now_ms=12) is not None


def test_expired_without_execution_can_be_reclaimed(tmp_path: Path) -> None:
    _, queue = _queue(tmp_path)
    _enqueue(queue, job_id="job-1")
    _enqueue(queue, job_id="job-2")
    _claim(queue, ttl_ms=10)

    expired = queue.expire(10)
    assert expired
    assert queue.status("npu:0").quarantined is False
    assert _claim(queue, lease_id="lease-2", now_ms=11) is not None


# ---- cancellation and invalid state ----------------------------------------
def test_cancel_queued_entry_and_terminal_release(tmp_path: Path) -> None:
    _, queue = _queue(tmp_path)
    _enqueue(queue, job_id="job-1")
    entry = queue.status("npu:0").queued[0]

    queue.cancel(entry.queue_id)
    assert queue.status("npu:0").queued == ()
    with pytest.raises(HardwareLedgerError):
        queue.cancel(entry.queue_id)
    assert _claim(queue) is None
