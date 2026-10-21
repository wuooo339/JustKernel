from __future__ import annotations

import sqlite3

from justkernel.platform.hardware.ledger import DeviceLease, HardwareLedgerError
from justkernel.platform.persistence.database import connect
from justkernel.platform.persistence.migrations import apply_migrations
from justkernel.platform.persistence.recovery import recover


# ---- helpers ----------------------------------------------------------------
def _connection() -> sqlite3.Connection:
    connection = connect()
    apply_migrations(connection)
    return connection


def _cluster(
    connection: sqlite3.Connection,
    *,
    state: str = "RUNNING",
    phase: str = "OPTIMIZING",
) -> None:
    connection.execute(
        """
        INSERT INTO clusters (
            id, operator_id, supervisor_id, operator_spec_digest, start_mode,
            phase, state, max_agents, created_at, version
        ) VALUES ('c1', 'op', 's1', 'spec', 'GENERATE', ?, ?, 100, 0, 0)
        """,
        (phase, state),
    )


def _agent(
    connection: sqlite3.Connection,
    agent_id: str,
    state: str,
    *,
    mentor_id: str | None = "m1",
    role: str = "OPTIMIZER",
) -> None:
    connection.execute(
        """
        INSERT INTO agents (
            id, cluster_id, role, mentor_id, model_profile, skills_json,
            state, created_at, version
        ) VALUES (?, 'c1', ?, ?, 'model', '[]', ?, 0, 0)
        """,
        (agent_id, role, mentor_id, state),
    )


def _direction(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO directions (
            id, cluster_id, mentor_id, objective, constraints_json, state,
            created_at, version
        ) VALUES ('d1', 'c1', 'm1', 'objective', '[]', 'ACTIVE', 0, 0)
        """
    )


def _task(
    connection: sqlite3.Connection,
    task_id: str,
    state: str,
    *,
    worker_id: str = "w1",
    finished_at: int | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO tasks (
            id, cluster_id, mentor_id, worker_id, kind, direction_id,
            operator_spec_digest, context_artifact, context_digest, budget_ref,
            objective, constraints_json, state, created_at, finished_at, version
        ) VALUES (?, 'c1', 'm1', ?, 'GENERATE', 'd1', 'spec',
                  'artifact://context', 'context', 'budget', 'objective', '[]',
                  ?, 0, ?, 0)
        """,
        (task_id, worker_id, state, finished_at),
    )


def _lease(
    connection: sqlite3.Connection,
    lease_id: str,
    device_id: str,
    state: str,
    expires_at: int,
) -> None:
    connection.execute(
        """
        INSERT INTO hardware_leases (
            id, device_id, task_id, owner_agent_id, state, acquired_at,
            expires_at, version
        ) VALUES (?, ?, 't1', 'm1', ?, 0, ?, 0)
        """,
        (lease_id, device_id, state, expires_at),
    )


def _outbox(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO outbox (
            id, cluster_id, kind, payload_json, idempotency_key,
            available_at, attempts
        ) VALUES ('o1', 'c1', 'message', '{}', 'key-1', 0, 0)
        """
    )


# ---- fake ledger ------------------------------------------------------------
class FakeLedger:
    def __init__(self, leases: dict[str, DeviceLease], missing: set[str]) -> None:
        self.leases = leases
        self.missing = missing
        self.expired: list[str] = []
        self.quarantined: list[tuple[str, str]] = []

    def get_lease(self, lease_id: str) -> DeviceLease:
        if lease_id in self.missing:
            raise HardwareLedgerError(f"missing: {lease_id}")
        return self.leases[lease_id]

    def mark_expired(self, lease_id: str, now_ms: int) -> DeviceLease:
        self.expired.append(lease_id)
        lease = self.leases[lease_id]
        return DeviceLease(
            lease_id=lease.lease_id,
            cluster_id=lease.cluster_id,
            task_id=lease.task_id,
            job_id=lease.job_id,
            device_id=lease.device_id,
            state="EXPIRED",
            execution_active=lease.execution_active,
            fencing_token=lease.fencing_token,
            expires_at=lease.expires_at,
        )

    def quarantine(self, device_id: str, reason: str, now_ms: int) -> None:
        self.quarantined.append((device_id, reason))


# ---- journal recovery -------------------------------------------------------
def test_recovery_matrix_and_idempotency() -> None:
    connection = _connection()
    _cluster(connection)
    _agent(connection, "m1", "IDLE", mentor_id=None, role="MENTOR")
    _agent(connection, "w1", "IDLE")
    _agent(connection, "w2", "IDLE")
    _agent(connection, "w3", "IDLE")
    _direction(connection)
    _agent(connection, "a1", "RUNNING")
    _agent(connection, "a2", "IDLE")
    _task(connection, "t1", "ASSIGNED", worker_id="w1")
    _task(connection, "t2", "RUNNING", worker_id="w2")
    _task(connection, "t3", "SUCCEEDED", worker_id="w3", finished_at=10)
    _lease(connection, "l1", "npu:0", "LEASED", 50)
    _lease(connection, "l2", "npu:1", "LEASED", 200)
    _outbox(connection)

    report = recover(connection, now_ms=100)

    assert report.agents_interrupted == 1
    assert report.tasks_interrupted == 2
    assert report.clusters_paused == 1
    assert report.leases_expired == 1
    assert report.devices_quarantined == 0
    assert report.pending_outbox == 1

    assert (
        connection.execute("SELECT state FROM agents WHERE id = 'a1'").fetchone()[0]
        == "INTERRUPTED"
    )
    assert connection.execute("SELECT state FROM agents WHERE id = 'a2'").fetchone()[0] == "IDLE"
    assert (
        connection.execute("SELECT state FROM tasks WHERE id = 't1'").fetchone()[0] == "INTERRUPTED"
    )
    assert connection.execute("SELECT finished_at FROM tasks WHERE id = 't2'").fetchone()[0] == 100
    assert (
        connection.execute("SELECT state FROM tasks WHERE id = 't3'").fetchone()[0] == "SUCCEEDED"
    )
    assert (
        connection.execute("SELECT state FROM clusters WHERE id = 'c1'").fetchone()[0] == "PAUSED"
    )
    assert (
        connection.execute("SELECT phase FROM clusters WHERE id = 'c1'").fetchone()[0]
        == "OPTIMIZING"
    )
    assert (
        connection.execute("SELECT state FROM hardware_leases WHERE id = 'l1'").fetchone()[0]
        == "EXPIRED"
    )
    assert (
        connection.execute("SELECT state FROM hardware_leases WHERE id = 'l2'").fetchone()[0]
        == "LEASED"
    )

    second = recover(connection, now_ms=100)
    assert second.agents_interrupted == 0
    assert second.tasks_interrupted == 0
    assert second.clusters_paused == 0
    assert second.leases_expired == 0
    assert second.pending_outbox == 1


def test_recovery_reconciles_global_ledger() -> None:
    connection = _connection()
    _cluster(connection)
    _agent(connection, "m1", "IDLE", mentor_id=None, role="MENTOR")
    _agent(connection, "w1", "IDLE")
    _direction(connection)
    _agent(connection, "a1", "RUNNING")
    _task(connection, "t1", "RUNNING")
    _lease(connection, "l1", "npu:0", "LEASED", 50)
    _lease(connection, "l2", "npu:1", "LEASED", 200)
    _lease(connection, "l3", "npu:2", "LEASED", 50)

    leases = {
        "l1": DeviceLease("l1", "c1", "t1", "j1", "npu:0", "LEASED", True, 1, 50),
        "l2": DeviceLease("l2", "c1", "t1", "j2", "npu:1", "LEASED", False, 1, 200),
        "l3": DeviceLease("l3", "c1", "t1", "j3", "npu:2", "LEASED", True, 1, 50),
    }
    ledger = FakeLedger(leases, missing={"l3"})

    report = recover(connection, now_ms=100, ledger=ledger)

    assert report.leases_expired == 2
    assert report.devices_quarantined == 1
    assert ledger.expired == ["l1"]
    assert ledger.quarantined[0][0] == "npu:2"
    assert (
        connection.execute("SELECT state FROM hardware_leases WHERE id = 'l1'").fetchone()[0]
        == "EXPIRED"
    )
    assert (
        connection.execute("SELECT state FROM hardware_leases WHERE id = 'l2'").fetchone()[0]
        == "LEASED"
    )
    assert (
        connection.execute("SELECT state FROM hardware_leases WHERE id = 'l3'").fetchone()[0]
        == "EXPIRED"
    )
