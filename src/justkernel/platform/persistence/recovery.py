"""Startup recovery matrix."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Protocol

from justkernel.platform.hardware.ledger import DeviceLease, HardwareLedgerError


# ---- RecoveryReport ---------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RecoveryReport:
    agents_interrupted: int
    tasks_interrupted: int
    clusters_paused: int
    leases_expired: int
    devices_quarantined: int
    pending_outbox: int


# ---- LeaseLedger ------------------------------------------------------------
class LeaseLedger(Protocol):
    def get_lease(self, lease_id: str) -> DeviceLease: ...

    def mark_expired(self, lease_id: str, now_ms: int) -> DeviceLease: ...

    def quarantine(self, device_id: str, reason: str, now_ms: int) -> None: ...


# ---- recover ----------------------------------------------------------------
def recover(
    connection: sqlite3.Connection,
    now_ms: int,
    ledger: LeaseLedger | None = None,
) -> RecoveryReport:
    connection.execute("BEGIN IMMEDIATE")
    try:
        agents = _interrupt_agents(connection)
        tasks = _interrupt_tasks(connection, now_ms)
        clusters = _pause_clusters(connection)
        leases_expired, quarantined = _recover_leases(connection, now_ms, ledger)
        pending = _pending_outbox(connection, now_ms)
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    return RecoveryReport(
        agents_interrupted=agents,
        tasks_interrupted=tasks,
        clusters_paused=clusters,
        leases_expired=leases_expired,
        devices_quarantined=quarantined,
        pending_outbox=pending,
    )


# ---- _interrupt_agents ------------------------------------------------------
def _interrupt_agents(connection: sqlite3.Connection) -> int:
    cursor = connection.execute("UPDATE agents SET state = 'INTERRUPTED' WHERE state = 'RUNNING'")
    return cursor.rowcount


# ---- _interrupt_tasks -------------------------------------------------------
def _interrupt_tasks(connection: sqlite3.Connection, now_ms: int) -> int:
    cursor = connection.execute(
        """
        UPDATE tasks
        SET state = 'INTERRUPTED', finished_at = ?
        WHERE state IN ('ASSIGNED','RUNNING')
        """,
        (now_ms,),
    )
    return cursor.rowcount


# ---- _pause_clusters --------------------------------------------------------
def _pause_clusters(connection: sqlite3.Connection) -> int:
    cursor = connection.execute(
        "UPDATE clusters SET state = 'PAUSED' WHERE state IN ('RUNNING','CONVERGING')"
    )
    return cursor.rowcount


# ---- _pending_outbox --------------------------------------------------------
def _pending_outbox(connection: sqlite3.Connection, now_ms: int) -> int:
    row = connection.execute(
        "SELECT COUNT(*) FROM outbox WHERE available_at <= ?", (now_ms,)
    ).fetchone()
    return int(row[0])


# ---- _recover_leases --------------------------------------------------------
def _recover_leases(
    connection: sqlite3.Connection,
    now_ms: int,
    ledger: LeaseLedger | None,
) -> tuple[int, int]:
    rows = connection.execute("SELECT * FROM hardware_leases WHERE state = 'LEASED'").fetchall()
    expired = 0
    quarantined = 0
    for row in rows:
        lease_expired, device_quarantined = _recover_lease(connection, row, now_ms, ledger)
        expired += int(lease_expired)
        quarantined += int(device_quarantined)
    return expired, quarantined


def _recover_lease(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    now_ms: int,
    ledger: LeaseLedger | None,
) -> tuple[bool, bool]:
    lease_id = row["id"]
    device_id = row["device_id"]
    if ledger is None:
        if row["expires_at"] is not None and now_ms >= row["expires_at"]:
            _set_lease_state(connection, lease_id, "EXPIRED")
            return True, False
        return False, False

    try:
        global_lease = ledger.get_lease(lease_id)
    except HardwareLedgerError:
        ledger.quarantine(device_id, "journal lease missing in global ledger", now_ms)
        _set_lease_state(connection, lease_id, "EXPIRED")
        return True, True

    if global_lease.state == "RELEASED":
        _set_lease_state(connection, lease_id, "RELEASED")
        return False, False
    if global_lease.state == "EXPIRED":
        _set_lease_state(connection, lease_id, "EXPIRED")
        return True, False
    expires_at = row["expires_at"]
    if expires_at is not None and now_ms >= expires_at:
        try:
            ledger.mark_expired(lease_id, now_ms)
        except HardwareLedgerError:
            ledger.quarantine(device_id, "could not confirm lease expiry", now_ms)
            _set_lease_state(connection, lease_id, "EXPIRED")
            return True, True
        _set_lease_state(connection, lease_id, "EXPIRED")
        return True, False
    return False, False


def _set_lease_state(connection: sqlite3.Connection, lease_id: str, state: str) -> None:
    connection.execute(
        "UPDATE hardware_leases SET state = ?, version = version + 1 WHERE id = ?",
        (state, lease_id),
    )
