"""Prioritized hardware queue over the global device ledger."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.platform.hardware.ledger import (
    DeviceLease,
    DeviceQuarantinedError,
    HardwareLedger,
    HardwareLedgerError,
    LeaseConflictError,
    QueueEntry,
)

QUEUE_QUEUED = "QUEUED"
QUEUE_LEASED = "LEASED"
QUEUE_DONE = "DONE"
QUEUE_EXPIRED = "EXPIRED"
QUEUE_CANCELLED = "CANCELLED"


# ---- HardwareQueueStatus ----------------------------------------------------
@dataclass(frozen=True, slots=True)
class HardwareQueueStatus:
    device_id: str | None
    queued: tuple[QueueEntry, ...]
    active_lease: DeviceLease | None
    quarantined: bool


# ---- HardwareQueue ----------------------------------------------------------
class HardwareQueue:
    def __init__(self, ledger: HardwareLedger) -> None:
        self.ledger = ledger
        self.connection = ledger.connection

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
    ) -> int:
        if priority < 0:
            raise HardwareLedgerError("queue priority must be non-negative")
        self.ledger.enqueue(
            cluster_id=cluster_id,
            task_id=task_id,
            job_id=job_id,
            device_id=device_id,
            purpose=purpose,
            priority=priority,
            dedupe_key=dedupe_key,
            now_ms=now_ms,
        )
        return self._position_for_job(job_id, device_id)

    def claim_next(
        self,
        *,
        lease_id: str,
        device_id: str,
        ttl_ms: int,
        now_ms: int,
    ) -> DeviceLease | None:
        if self.ledger.is_quarantined(device_id):
            raise DeviceQuarantinedError(f"device is quarantined: {device_id}")
        if self.ledger.active_lease(device_id) is not None:
            return None
        entries = self._queued(device_id)
        if not entries:
            return None
        entry = entries[0]
        try:
            lease = self.ledger.acquire(
                lease_id=lease_id,
                cluster_id=entry.cluster_id,
                task_id=entry.task_id,
                job_id=entry.job_id,
                device_id=device_id,
                ttl_ms=ttl_ms,
                now_ms=now_ms,
            )
        except LeaseConflictError:
            return None
        self._set_state(entry.queue_id, QUEUE_LEASED)
        return lease

    def release(self, lease_id: str, fencing_token: int, now_ms: int) -> DeviceLease:
        lease = self.ledger.get_lease(lease_id)
        released = self.ledger.release(lease_id, fencing_token)
        self._set_state_by_job(lease.job_id, QUEUE_DONE)
        return released

    def expire(self, now_ms: int) -> tuple[DeviceLease, ...]:
        rows = self.connection.execute(
            """
            SELECT * FROM device_leases
            WHERE state = 'LEASED' AND expires_at <= ?
            ORDER BY expires_at, lease_id
            """,
            (now_ms,),
        ).fetchall()
        expired: list[DeviceLease] = []
        for row in rows:
            lease = self.ledger.mark_expired(row["lease_id"], now_ms)
            self._set_state_by_job(lease.job_id, QUEUE_EXPIRED)
            if lease.execution_active:
                self.ledger.quarantine(lease.device_id, "lease expired during execution", now_ms)
            expired.append(lease)
        return tuple(expired)

    def confirm_stopped(self, lease_id: str, fencing_token: int, now_ms: int) -> DeviceLease:
        lease = self.ledger.confirm_stopped(lease_id, fencing_token)
        self.ledger.clear_quarantine(lease.device_id, now_ms)
        return lease

    def cancel(self, queue_id: str) -> None:
        cursor = self.connection.execute(
            "UPDATE device_queue SET state = ? WHERE id = ? AND state = ?",
            (QUEUE_CANCELLED, queue_id, QUEUE_QUEUED),
        )
        if cursor.rowcount != 1:
            raise HardwareLedgerError(f"queued entry is not cancellable: {queue_id}")

    def status(self, device_id: str | None = None) -> HardwareQueueStatus:
        return HardwareQueueStatus(
            device_id=device_id,
            queued=self._queued(device_id),
            active_lease=self.ledger.active_lease(device_id) if device_id else None,
            quarantined=self.ledger.is_quarantined(device_id) if device_id else False,
        )

    def _queued(self, device_id: str | None) -> tuple[QueueEntry, ...]:
        entries = self.ledger.queue_status(device_id)
        return tuple(entry for entry in entries if entry.state == QUEUE_QUEUED)

    def _position_for_job(self, job_id: str, device_id: str) -> int:
        for index, entry in enumerate(self._queued(device_id), start=1):
            if entry.job_id == job_id:
                return index
        raise HardwareLedgerError(f"job is not queued: {job_id}")

    def _set_state(self, queue_id: str, state: str) -> None:
        self.connection.execute(
            "UPDATE device_queue SET state = ? WHERE id = ?",
            (state, queue_id),
        )

    def _set_state_by_job(self, job_id: str, state: str) -> None:
        self.connection.execute(
            "UPDATE device_queue SET state = ? WHERE job_id = ?",
            (state, job_id),
        )
