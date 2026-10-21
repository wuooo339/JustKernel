from __future__ import annotations

import sqlite3

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import AgentState, Role
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.platform.persistence.database import connect
from justkernel.platform.persistence.errors import ConcurrencyError
from justkernel.platform.persistence.events import EventStore
from justkernel.platform.persistence.migrations import apply_migrations
from justkernel.platform.persistence.outbox import OutboxEntry, OutboxRepository
from justkernel.platform.persistence.repositories import AgentRepository, ClusterRepository
from justkernel.platform.persistence.unit_of_work import UnitOfWork
from justkernel.shared.digest import Digest
from justkernel.shared.events import DomainEvent, EventError, EventType
from justkernel.shared.ids import AgentId, ClusterId, EventId
from justkernel.shared.principal import Principal


# ---- helpers ----------------------------------------------------------------
def _connection() -> sqlite3.Connection:
    connection = connect()
    apply_migrations(connection)
    return connection


def _cluster(**overrides: object) -> Cluster:
    values: dict[str, object] = {
        "id": ClusterId.generate(),
        "operator_id": "ConfusionMulGrad",
        "supervisor_id": AgentId.generate(),
        "operator_spec_ref": OperatorRef(
            operator_id="ConfusionMulGrad",
            version="1",
            digest=Digest.from_text("spec"),
            artifact_ref="artifact://spec",
        ),
        "start_mode": StartMode.GENERATE,
        "created_at": 0,
    }
    values.update(overrides)
    return Cluster(**values)


def _skill() -> SkillRef:
    return SkillRef(
        name="optimizer",
        version="1",
        source_path="/skills/base/optimizer",
        digest=Digest.from_text("skill"),
    )


def _agent(cluster: Cluster, **overrides: object) -> AgentInstance:
    values: dict[str, object] = {
        "id": AgentId.generate(),
        "cluster_id": cluster.id,
        "role": Role.OPTIMIZER,
        "mentor_id": AgentId.generate(),
        "model_profile": "model-1",
        "skills": (_skill(),),
        "created_at": 0,
        "state": AgentState.IDLE,
    }
    values.update(overrides)
    return AgentInstance(**values)


def _event(cluster: Cluster) -> DomainEvent:
    return DomainEvent(
        id=EventId.generate(),
        cluster_id=cluster.id,
        type=EventType.CLUSTER_STARTED,
        event_version=1,
        aggregate_type="Cluster",
        aggregate_id=str(cluster.id),
        aggregate_version=0,
        actor=Principal.system(),
        occurred_at=0,
        payload={"state": "RUNNING"},
    )


def _outbox(cluster: Cluster, **overrides: object) -> OutboxEntry:
    values: dict[str, object] = {
        "id": "outbox-1",
        "cluster_id": cluster.id,
        "kind": "message",
        "payload": {"subject": "wake"},
        "idempotency_key": "key-1",
        "available_at": 0,
    }
    values.update(overrides)
    return OutboxEntry(**values)


# ---- transactions -----------------------------------------------------------
def test_uow_commit_and_rollback() -> None:
    connection = _connection()
    cluster = _cluster()
    mentor = _agent(cluster, role=Role.MENTOR, mentor_id=None)
    agent = _agent(cluster, mentor_id=mentor.id)
    event = _event(cluster)
    entry = _outbox(cluster)

    with UnitOfWork(connection) as uow:
        uow.clusters.insert(cluster)
        uow.agents.insert(mentor)
        uow.agents.insert(agent)
        uow.events.append(event)
        uow.outbox.enqueue(entry)

    assert connection.execute("SELECT COUNT(*) FROM clusters").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1

    other = _cluster()
    with pytest.raises(RuntimeError), UnitOfWork(connection) as uow:
        uow.clusters.insert(other)
        uow.events.append(_event(other))
        uow.outbox.enqueue(_outbox(other, id="outbox-2", idempotency_key="key-2"))
        raise RuntimeError("rollback")

    assert connection.execute("SELECT COUNT(*) FROM clusters").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1


# ---- optimistic concurrency -------------------------------------------------
def test_cluster_update_rejects_stale_version() -> None:
    connection = _connection()
    cluster = _cluster()

    with UnitOfWork(connection) as uow:
        uow.clusters.insert(cluster)

    with UnitOfWork(connection) as uow:
        assert uow.clusters.update(cluster, expected_version=0) == 1

    with pytest.raises(ConcurrencyError), UnitOfWork(connection) as uow:
        uow.clusters.update(cluster, expected_version=0)

    assert ClusterRepository(connection).version(cluster.id) == 1


# ---- repositories -----------------------------------------------------------
def test_agent_round_trip() -> None:
    connection = _connection()
    cluster = _cluster()
    mentor = _agent(cluster, role=Role.MENTOR, mentor_id=None)
    agent = _agent(cluster, mentor_id=mentor.id)

    with UnitOfWork(connection) as uow:
        uow.clusters.insert(cluster)
        uow.agents.insert(mentor)
        uow.agents.insert(agent)

    loaded = AgentRepository(connection).get(agent.id)

    assert loaded.id == agent.id
    assert loaded.cluster_id == agent.cluster_id
    assert loaded.role is agent.role
    assert loaded.mentor_id == agent.mentor_id
    assert loaded.state is agent.state
    assert loaded.skills == agent.skills
    assert AgentRepository(connection).version(agent.id) == 0


# ---- events -----------------------------------------------------------------
def test_event_append_read_and_duplicate() -> None:
    connection = _connection()
    cluster = _cluster()
    first = _event(cluster)
    second = _event(cluster)

    with UnitOfWork(connection) as uow:
        uow.events.append(first)

    store = EventStore(connection)
    loaded = store.read_after()
    assert len(loaded) == 1
    assert loaded[0].id == first.id
    assert loaded[0].type is EventType.CLUSTER_STARTED
    assert loaded[0].payload["state"] == "RUNNING"

    with UnitOfWork(connection) as uow:
        uow.events.append(second)

    assert len(store.read_after(1)) == 1
    with pytest.raises(EventError), UnitOfWork(connection) as uow:
        uow.events.append(first)


# ---- outbox -----------------------------------------------------------------
def test_outbox_idempotency_and_attempts() -> None:
    connection = _connection()
    cluster = _cluster()
    entry = _outbox(cluster)

    with UnitOfWork(connection) as uow:
        assert uow.outbox.enqueue(entry) is True
        assert uow.outbox.enqueue(entry) is False

    outbox = OutboxRepository(connection)
    pending = outbox.pending(0)
    assert len(pending) == 1
    assert pending[0].attempts == 0

    outbox.mark_attempt(entry.id)
    assert outbox.pending(0)[0].attempts == 1
