"""Global hardware ledger with device leases and fencing."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from uuid import uuid4

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError

HARDWARE_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_leases (
  lease_id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  job_id TEXT NOT NULL UNIQUE,
  device_id TEXT NOT NULL,
  state TEXT NOT NULL,
  execution_active INTEGER NOT NULL DEFAULT 0,
  fencing_token INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  UNIQUE(device_id, fencing_token)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_lease_per_device
  ON device_leases(device_id)
  WHERE state = 'LEASED' OR execution_active = 1;

CREATE TABLE IF NOT EXISTS device_queue (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  job_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  purpose TEXT NOT NULL,
  priority INTEGER NOT NULL,
  enqueued_at INTEGER NOT NULL,
  dedupe_key TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS device_quarantine (
  device_id TEXT PRIMARY KEY,
  reason TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  cleared_at INTEGER
);
"""


# ---- errors -----------------------------------------------------------------
class HardwareLedgerError(JustKernelError):
    code = ErrorCode.HARDWARE_ERROR


class LeaseConflictError(HardwareLedgerError):
    code = ErrorCode.HARDWARE_LEASE_CONFLICT


class FencingError(HardwareLedgerError):
    code = ErrorCode.HARDWARE_FENCING_REJECTED


class DeviceQuarantinedError(HardwareLedgerError):
    code = ErrorCode.HARDWARE_QUARANTINED


# ---- DeviceLease ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DeviceLease:
    lease_id: str
    cluster_id: str
    task_id: str
    job_id: str
    device_id: str
    state: str
    execution_active: bool
    fencing_token: int
    expires_at: int


# ---- QueueEntry -------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class QueueEntry:
    queue_id: str
    cluster_id: str
    task_id: str
    job_id: str
    device_id: str
    purpose: str
    priority: int
    enqueued_at: int
    state: str


# ---- apply_hardware_schema --------------------------------------------------
def apply_hardware_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(HARDWARE_SCHEMA)


# ---- HardwareLedger ---------------------------------------------------------
class HardwareLedger:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def acquire(
        self,
        *,
        lease_id: str,
        cluster_id: str,
        task_id: str,
        job_id: str,
        device_id: str,
        ttl_ms: int,
        now_ms: int,
    ) -> DeviceLease:
        self._validate_acquire(lease_id, cluster_id, task_id, job_id, device_id, ttl_ms, now_ms)
        if self.is_quarantined(device_id):
            raise DeviceQuarantinedError(f"device is quarantined: {device_id}")
        token = self._next_token(device_id)
        try:
            self.connection.execute(
                """
                INSERT INTO device_leases (
                    lease_id, cluster_id, task_id, job_id, device_id, state,
                    execution_active, fencing_token, expires_at
                ) VALUES (?, ?, ?, ?, ?, 'LEASED', 0, ?, ?)
                """,
                (lease_id, cluster_id, task_id, job_id, device_id, token, now_ms + ttl_ms),
            )
        except sqlite3.IntegrityError as error:
            raise LeaseConflictError(f"device/job already leased: {device_id}") from error
        return self.get_lease(lease_id)

    def start_execution(self, lease_id: str, fencing_token: int) -> DeviceLease:
        lease = self._lease_with_token(lease_id, fencing_token)
        if lease.state != "LEASED":
            raise FencingError(f"lease is not active: {lease_id}")
        self.connection.execute(
            "UPDATE device_leases SET execution_active = 1 WHERE lease_id = ?",
            (lease_id,),
        )
        return self.get_lease(lease_id)

    def release(self, lease_id: str, fencing_token: int) -> DeviceLease:
        lease = self._lease_with_token(lease_id, fencing_token)
        if lease.state != "LEASED":
            raise FencingError(f"lease is not active: {lease_id}")
        self.connection.execute(
            "UPDATE device_leases SET state = 'RELEASED', execution_active = 0 WHERE lease_id = ?",
            (lease_id,),
        )
        return self.get_lease(lease_id)

    def mark_expired(self, lease_id: str, now_ms: int) -> DeviceLease:
        lease = self.get_lease(lease_id)
        if lease.state != "LEASED":
            raise HardwareLedgerError(f"lease is not active: {lease_id}")
        if now_ms < lease.expires_at:
            raise HardwareLedgerError("lease has not reached its TTL")
        self.connection.execute(
            "UPDATE device_leases SET state = 'EXPIRED' WHERE lease_id = ?", (lease_id,)
        )
        return self.get_lease(lease_id)

    def confirm_stopped(self, lease_id: str, fencing_token: int) -> DeviceLease:
        lease = self._lease_with_token(lease_id, fencing_token)
        if lease.state != "EXPIRED":
            raise HardwareLedgerError(f"lease is not expired: {lease_id}")
        self.connection.execute(
            "UPDATE device_leases SET execution_active = 0 WHERE lease_id = ?",
            (lease_id,),
        )
        return self.get_lease(lease_id)

    def get_lease(self, lease_id: str) -> DeviceLease:
        row = self.connection.execute(
            "SELECT * FROM device_leases WHERE lease_id = ?", (lease_id,)
        ).fetchone()
        if row is None:
            raise HardwareLedgerError(f"lease not found: {lease_id}")
        return self._from_lease_row(row)

    def active_lease(self, device_id: str) -> DeviceLease | None:
        row = self.connection.execute(
            """
            SELECT * FROM device_leases
            WHERE device_id = ? AND (state = 'LEASED' OR execution_active = 1)
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()
        return self._from_lease_row(row) if row is not None else None

    def quarantine(self, device_id: str, reason: str, now_ms: int) -> None:
        if not device_id or not reason:
            raise HardwareLedgerError("device id and reason must be non-empty")
        self.connection.execute(
            """
            INSERT INTO device_quarantine (device_id, reason, created_at, cleared_at)
            VALUES (?, ?, ?, NULL)
            ON CONFLICT(device_id) DO UPDATE SET
                reason = excluded.reason,
                created_at = excluded.created_at,
                cleared_at = NULL
            """,
            (device_id, reason, now_ms),
        )

    def clear_quarantine(self, device_id: str, now_ms: int = 0) -> None:
        self.connection.execute(
            "UPDATE device_quarantine SET cleared_at = ? WHERE device_id = ?",
            (now_ms, device_id),
        )

    def is_quarantined(self, device_id: str) -> bool:
        row = self.connection.execute(
            """
            SELECT 1 FROM device_quarantine
            WHERE device_id = ? AND cleared_at IS NULL
            """,
            (device_id,),
        ).fetchone()
        return row is not None

    def enqueue(
        self,
        *,
        cluster_id: str,
        task_id: str,
        job_id: str,
        device_id: str,
        purpose: str,
        priority: int,
        dedupe_key: str,
        now_ms: int,
    ) -> bool:
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO device_queue (
                id, cluster_id, task_id, job_id, device_id, purpose, priority,
                enqueued_at, dedupe_key, state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'QUEUED')
            """,
            (
                uuid4().hex,
                cluster_id,
                task_id,
                job_id,
                device_id,
                purpose,
                priority,
                now_ms,
                dedupe_key,
            ),
        )
        return cursor.rowcount == 1

    def queue_status(self, device_id: str | None = None) -> tuple[QueueEntry, ...]:
        if device_id is None:
            rows = self.connection.execute(
                "SELECT * FROM device_queue ORDER BY priority, enqueued_at, id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM device_queue WHERE device_id = ?
                ORDER BY priority, enqueued_at, id
                """,
                (device_id,),
            ).fetchall()
        return tuple(self._from_queue_row(row) for row in rows)

    def _lease_with_token(self, lease_id: str, fencing_token: int) -> DeviceLease:
        lease = self.get_lease(lease_id)
        if lease.fencing_token != fencing_token:
            raise FencingError(f"stale fencing token for lease: {lease_id}")
        return lease

    def _next_token(self, device_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(fencing_token), 0) + 1 FROM device_leases WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        return int(row[0])

    def _validate_acquire(
        self,
        lease_id: str,
        cluster_id: str,
        task_id: str,
        job_id: str,
        device_id: str,
        ttl_ms: int,
        now_ms: int,
    ) -> None:
        if not all((lease_id, cluster_id, task_id, job_id, device_id)):
            raise HardwareLedgerError("lease fields must be non-empty")
        if ttl_ms <= 0 or now_ms < 0:
            raise HardwareLedgerError("ttl must be positive and time non-negative")

    def _from_lease_row(self, row: sqlite3.Row) -> DeviceLease:
        return DeviceLease(
            lease_id=row["lease_id"],
            cluster_id=row["cluster_id"],
            task_id=row["task_id"],
            job_id=row["job_id"],
            device_id=row["device_id"],
            state=row["state"],
            execution_active=bool(row["execution_active"]),
            fencing_token=row["fencing_token"],
            expires_at=row["expires_at"],
        )

    def _from_queue_row(self, row: sqlite3.Row) -> QueueEntry:
        return QueueEntry(
            queue_id=row["id"],
            cluster_id=row["cluster_id"],
            task_id=row["task_id"],
            job_id=row["job_id"],
            device_id=row["device_id"],
            purpose=row["purpose"],
            priority=row["priority"],
            enqueued_at=row["enqueued_at"],
            state=row["state"],
        )
