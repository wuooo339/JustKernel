from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from justkernel.platform.hardware.ledger import (
    DeviceQuarantinedError,
    FencingError,
    HardwareLedger,
    HardwareLedgerError,
    LeaseConflictError,
    apply_hardware_schema,
)
from justkernel.platform.persistence.database import connect


# ---- helpers ----------------------------------------------------------------
def _ledger(tmp_path: Path) -> tuple[sqlite3.Connection, HardwareLedger]:
    connection = connect(str(tmp_path / "hardware.db"))
    apply_hardware_schema(connection)
    return connection, HardwareLedger(connection)


def _acquire(
    ledger: HardwareLedger,
    *,
    lease_id: str = "lease-1",
    device_id: str = "npu:0",
    job_id: str = "job-1",
    now_ms: int = 0,
    ttl_ms: int = 100,
) -> object:
    return ledger.acquire(
        lease_id=lease_id,
        cluster_id="cluster-1",
        task_id="task-1",
        job_id=job_id,
        device_id=device_id,
        ttl_ms=ttl_ms,
        now_ms=now_ms,
    )


def _enqueue(ledger: HardwareLedger, *, dedupe_key: str = "dedupe-1") -> bool:
    return ledger.enqueue(
        cluster_id="cluster-1",
        task_id="task-1",
        job_id="job-1",
        device_id="npu:0",
        purpose="test",
        priority=1,
        dedupe_key=dedupe_key,
        now_ms=0,
    )


# ---- leases and fencing -----------------------------------------------------
def test_acquire_release_and_single_lease_per_device(tmp_path: Path) -> None:
    _, ledger = _ledger(tmp_path)
    lease = _acquire(ledger)

    assert lease.state == "LEASED"
    assert lease.execution_active == 0
    assert lease.fencing_token == 1
    assert lease.expires_at == 100
    assert ledger.active_lease("npu:0") == lease

    with pytest.raises(LeaseConflictError):
        _acquire(ledger, lease_id="lease-2", job_id="job-2")

    ledger.start_execution("lease-1", 1)
    assert ledger.active_lease("npu:0").execution_active == 1

    released = ledger.release("lease-1", 1)
    assert released.state == "RELEASED"
    assert released.execution_active == 0
    assert ledger.active_lease("npu:0") is None

    next_lease = _acquire(ledger, lease_id="lease-2", job_id="job-2")
    assert next_lease.fencing_token == 2


def test_old_fencing_token_is_rejected(tmp_path: Path) -> None:
    _, ledger = _ledger(tmp_path)
    _acquire(ledger, lease_id="lease-1", job_id="job-1")
    ledger.start_execution("lease-1", 1)
    ledger.release("lease-1", 1)
    _acquire(ledger, lease_id="lease-2", job_id="job-2")

    with pytest.raises(FencingError):
        ledger.start_execution("lease-2", 1)
    with pytest.raises(FencingError):
        ledger.release("lease-2", 1)
    with pytest.raises(FencingError):
        ledger.start_execution("lease-1", 1)


def test_expired_execution_blocks_until_confirmed(tmp_path: Path) -> None:
    _, ledger = _ledger(tmp_path)
    _acquire(ledger, lease_id="lease-1", ttl_ms=10)
    ledger.start_execution("lease-1", 1)
    expired = ledger.mark_expired("lease-1", 10)

    assert expired.state == "EXPIRED"
    assert expired.execution_active == 1
    with pytest.raises(LeaseConflictError):
        _acquire(ledger, lease_id="lease-2", job_id="job-2")

    confirmed = ledger.confirm_stopped("lease-1", 1)
    assert confirmed.execution_active == 0
    assert ledger.active_lease("npu:0") is None
    assert _acquire(ledger, lease_id="lease-2", job_id="job-2").fencing_token == 2


def test_expire_requires_ttl_reached(tmp_path: Path) -> None:
    _, ledger = _ledger(tmp_path)
    _acquire(ledger, ttl_ms=10)

    with pytest.raises(HardwareLedgerError):
        ledger.mark_expired("lease-1", 5)


# ---- quarantine -------------------------------------------------------------
def test_quarantine_blocks_and_clears(tmp_path: Path) -> None:
    _, ledger = _ledger(tmp_path)
    ledger.quarantine("npu:0", "unknown execution", 0)

    with pytest.raises(DeviceQuarantinedError):
        _acquire(ledger)

    ledger.clear_quarantine("npu:0", 1)
    assert _acquire(ledger).lease_id == "lease-1"


# ---- queue ------------------------------------------------------------------
def test_queue_deduplication_and_status(tmp_path: Path) -> None:
    _, ledger = _ledger(tmp_path)

    assert _enqueue(ledger) is True
    assert _enqueue(ledger) is False
    assert len(ledger.queue_status("npu:0")) == 1
    assert len(ledger.queue_status()) == 1


# ---- cross-connection and schema -------------------------------------------
def test_two_connections_share_the_device_lease(tmp_path: Path) -> None:
    connection_a, ledger_a = _ledger(tmp_path)
    connection_b = connect(str(tmp_path / "hardware.db"))
    ledger_b = HardwareLedger(connection_b)

    _acquire(ledger_a, lease_id="lease-1", job_id="job-1")
    with pytest.raises(LeaseConflictError):
        _acquire(ledger_b, lease_id="lease-2", job_id="job-2")

    connection_a.close()
    connection_b.close()


def test_job_id_is_globally_unique(tmp_path: Path) -> None:
    _, ledger = _ledger(tmp_path)
    _acquire(ledger, lease_id="lease-1", device_id="npu:0", job_id="job-1")

    with pytest.raises(LeaseConflictError):
        _acquire(ledger, lease_id="lease-2", device_id="npu:1", job_id="job-1")


def test_hardware_schema_is_idempotent(tmp_path: Path) -> None:
    connection = connect(str(tmp_path / "hardware.db"))
    apply_hardware_schema(connection)
    apply_hardware_schema(connection)

    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"device_leases", "device_queue", "device_quarantine"} <= tables
