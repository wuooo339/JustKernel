from __future__ import annotations

import sqlite3

import pytest

from justkernel.platform.persistence.migrations import apply_migrations

CORE_TABLES = {
    "clusters",
    "agents",
    "directions",
    "tasks",
    "candidates",
    "test_records",
    "hardware_leases",
    "board_posts",
    "messages",
    "reports",
    "events",
    "outbox",
    "projections",
    "tool_jobs",
    "agent_inbox",
    "wake_requests",
    "best_selections",
    "task_artifact_grants",
    "budget_ledger",
    "schema_migrations",
}


# ---- helpers ----------------------------------------------------------------
def _connect(*, foreign_keys: bool = False) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys = ON")
    apply_migrations(connection)
    return connection


def _cluster(connection: sqlite3.Connection, cluster_id: str = "c1") -> None:
    connection.execute(
        """
        INSERT INTO clusters (
            id, operator_id, supervisor_id, operator_spec_digest, start_mode,
            phase, state, max_agents, created_at, version
        ) VALUES (?, 'op', 's1', 'spec', 'GENERATE', 'BOOTSTRAPPING',
                  'INITIALIZING', 100, 0, 0)
        """,
        (cluster_id,),
    )


def _agent(
    connection: sqlite3.Connection,
    agent_id: str,
    *,
    role: str = "OPTIMIZER",
    state: str = "IDLE",
    cluster_id: str = "c1",
    mentor_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO agents (
            id, cluster_id, role, mentor_id, model_profile, skills_json,
            state, created_at, version
        ) VALUES (?, ?, ?, ?, 'model', '[]', ?, 0, 0)
        """,
        (agent_id, cluster_id, role, mentor_id, state),
    )


def _direction(
    connection: sqlite3.Connection,
    direction_id: str,
    mentor_id: str,
    *,
    state: str = "ACTIVE",
) -> None:
    connection.execute(
        """
        INSERT INTO directions (
            id, cluster_id, mentor_id, objective, constraints_json, state,
            created_at, version
        ) VALUES (?, 'c1', ?, 'objective', '[]', ?, 0, 0)
        """,
        (direction_id, mentor_id, state),
    )


def _task(
    connection: sqlite3.Connection,
    task_id: str,
    worker_id: str,
    *,
    state: str = "ASSIGNED",
) -> None:
    connection.execute(
        """
        INSERT INTO tasks (
            id, cluster_id, mentor_id, worker_id, kind, direction_id,
            operator_spec_digest, context_artifact, context_digest, budget_ref,
            objective, constraints_json, state, created_at, version
        ) VALUES (?, 'c1', 'm1', ?, 'GENERATE', 'd1', 'spec',
                  'artifact://context', 'context', 'budget', 'objective', '[]',
                  ?, 0, 0)
        """,
        (task_id, worker_id, state),
    )


def _candidate(connection: sqlite3.Connection, candidate_id: str, task_id: str) -> None:
    connection.execute(
        """
        INSERT INTO candidates (
            id, cluster_id, parent_id, direction_id, author_agent_id,
            author_principal, task_id, import_id, source_digest,
            source_artifact, diff_artifact, created_at
        ) VALUES (?, 'c1', NULL, 'd1', 'o1', 'agent:o1', ?, NULL,
                  'source', 'artifact://source', 'artifact://diff', 0)
        """,
        (candidate_id, task_id),
    )


def _record(
    connection: sqlite3.Connection,
    record_id: str,
    candidate_id: str,
    *,
    task_id: str | None,
    audit_id: str | None = None,
    executed: int = 1,
    coverage: str = "FULL",
    outcome: str = "PASS",
) -> None:
    connection.execute(
        """
        INSERT INTO test_records (
            id, cluster_id, candidate_id, task_id, job_id, audit_id, executed,
            coverage, operator_spec_digest, case_pack_digest, reference_digest,
            accuracy_policy_digest, evaluation_policy_digest,
            environment_fingerprint, measurement_protocol_digest, kind,
            skill_json, backend, outcome, metrics_json, environment_json,
            artifact, artifact_digest, created_at
        ) VALUES (?, 'c1', ?, ?, ?, ?, ?, ?, 'spec', 'cases', 'ref',
                  'accuracy', 'evaluation', 'env', NULL, 'TEST', '{}',
                  'cann-simulation', ?, '{}', '{}', 'artifact://record',
                  'record', 0)
        """,
        (
            record_id,
            candidate_id,
            task_id,
            "job-1" if task_id else None,
            audit_id,
            executed,
            coverage,
            outcome,
        ),
    )


def _wake(
    connection: sqlite3.Connection, wake_id: str, agent_id: str, state: str = "CLAIMED"
) -> None:
    connection.execute(
        """
        INSERT INTO wake_requests (
            id, agent_id, reason, event_ids_json, expected_agent_version,
            not_before, state
        ) VALUES (?, ?, 'reason', '[]', 0, 0, ?)
        """,
        (wake_id, agent_id, state),
    )


def _event(connection: sqlite3.Connection, event_id: str) -> None:
    connection.execute(
        """
        INSERT INTO events (
            event_id, cluster_id, type, event_version, aggregate_type,
            aggregate_id, aggregate_version, actor, payload_json, occurred_at
        ) VALUES (?, 'c1', 'cluster.started', 1, 'Cluster', 'c1', 0,
                  'system', '{}', 0)
        """,
        (event_id,),
    )


# ---- migrations -------------------------------------------------------------
def test_migrations_create_core_tables_and_are_idempotent() -> None:
    connection = _connect()
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert tables >= CORE_TABLES

    assert apply_migrations(connection) == 0
    assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1


# ---- partial unique indexes -------------------------------------------------
def test_one_supervisor_per_cluster() -> None:
    connection = _connect()
    _cluster(connection)
    _agent(connection, "s1", role="SUPERVISOR")
    with pytest.raises(sqlite3.IntegrityError):
        _agent(connection, "s2", role="SUPERVISOR")

    connection.execute("UPDATE agents SET state = 'CLOSED' WHERE id = 's1'")
    _agent(connection, "s2", role="SUPERVISOR")


def test_one_open_direction_per_mentor() -> None:
    connection = _connect()
    _cluster(connection)
    _agent(connection, "m1", role="MENTOR")
    _direction(connection, "d1", "m1", state="ACTIVE")
    with pytest.raises(sqlite3.IntegrityError):
        _direction(connection, "d2", "m1", state="PROPOSED")

    connection.execute("UPDATE directions SET state = 'COMPLETED' WHERE id = 'd1'")
    _direction(connection, "d2", "m1", state="PROPOSED")


def test_one_running_task_per_worker() -> None:
    connection = _connect()
    _cluster(connection)
    _agent(connection, "m1", role="MENTOR")
    _agent(connection, "w1", role="OPTIMIZER", mentor_id="m1")
    _direction(connection, "d1", "m1")
    _task(connection, "t1", "w1", state="ASSIGNED")
    with pytest.raises(sqlite3.IntegrityError):
        _task(connection, "t2", "w1", state="RUNNING")

    connection.execute("UPDATE tasks SET state = 'SUCCEEDED' WHERE id = 't1'")
    _task(connection, "t2", "w1", state="RUNNING")


def test_one_record_per_task_and_audit_records() -> None:
    connection = _connect()
    _cluster(connection)
    _agent(connection, "m1", role="MENTOR")
    _agent(connection, "w1", role="OPTIMIZER", mentor_id="m1")
    _direction(connection, "d1", "m1")
    _task(connection, "t1", "w1")
    _candidate(connection, "cand1", "t1")

    _record(connection, "r1", "cand1", task_id="t1")
    with pytest.raises(sqlite3.IntegrityError):
        _record(connection, "r2", "cand1", task_id="t1")

    _record(
        connection,
        "r3",
        "cand1",
        task_id=None,
        audit_id="a1",
        executed=0,
        coverage="NONE",
        outcome="CANCELLED",
    )
    _record(
        connection,
        "r4",
        "cand1",
        task_id=None,
        audit_id="a2",
        executed=0,
        coverage="NONE",
        outcome="CANCELLED",
    )


def test_one_claimed_wake_per_agent() -> None:
    connection = _connect()
    _cluster(connection)
    _agent(connection, "m1", role="MENTOR")
    _wake(connection, "w1", "m1")
    with pytest.raises(sqlite3.IntegrityError):
        _wake(connection, "w2", "m1")

    connection.execute("UPDATE wake_requests SET state = 'COMPLETED' WHERE id = 'w1'")
    _wake(connection, "w2", "m1")


# ---- events and foreign keys ------------------------------------------------
def test_events_are_append_only() -> None:
    connection = _connect()
    _event(connection, "e1")

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE events SET type = 'changed'")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM events")


def test_foreign_keys_are_enforced_when_enabled() -> None:
    connection = _connect(foreign_keys=True)
    with pytest.raises(sqlite3.IntegrityError):
        _agent(connection, "s1", role="SUPERVISOR", cluster_id="missing")

    _cluster(connection)
    _agent(connection, "s1", role="SUPERVISOR")
