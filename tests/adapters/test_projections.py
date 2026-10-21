from __future__ import annotations

import sqlite3

from justkernel.platform.persistence.database import connect
from justkernel.platform.persistence.migrations import apply_migrations
from justkernel.platform.persistence.projections import (
    CandidateGraphProjection,
    ClusterGraphProjection,
    MentorBoardProjection,
    ProjectionRunner,
    QueueProjection,
)
from justkernel.platform.persistence.unit_of_work import UnitOfWork
from justkernel.shared.events import DomainEvent, EventType
from justkernel.shared.ids import (
    AgentId,
    CandidateId,
    ClusterId,
    DirectionId,
    EventId,
    LeaseId,
    TaskId,
)
from justkernel.shared.principal import Principal


# ---- helpers ----------------------------------------------------------------
def _connection() -> sqlite3.Connection:
    connection = connect()
    apply_migrations(connection)
    return connection


def _event(
    cluster_id: ClusterId,
    event_type: EventType,
    payload: dict[str, object],
) -> DomainEvent:
    return DomainEvent(
        id=EventId.generate(),
        cluster_id=cluster_id,
        type=event_type,
        event_version=1,
        aggregate_type="Test",
        aggregate_id="aggregate-1",
        aggregate_version=0,
        actor=Principal.system(),
        occurred_at=0,
        payload=payload,
    )


def _append(connection: sqlite3.Connection, *events: DomainEvent) -> None:
    with UnitOfWork(connection) as uow:
        for event in events:
            uow.events.append(event)


def _projections() -> list[object]:
    return [
        MentorBoardProjection(),
        ClusterGraphProjection(),
        CandidateGraphProjection(),
        QueueProjection(),
    ]


# ---- read models ------------------------------------------------------------
def test_projection_views_and_pending_cursor() -> None:
    connection = _connection()
    cluster = ClusterId.generate()
    supervisor = AgentId.generate()
    mentor = AgentId.generate()
    worker = AgentId.generate()
    candidate = CandidateId.generate()
    child = CandidateId.generate()
    direction = DirectionId.generate()
    lease = LeaseId.generate()
    task = TaskId.generate()

    _append(
        connection,
        _event(
            cluster,
            EventType.AGENT_CREATED,
            {
                "agent_id": supervisor.value,
                "role": "SUPERVISOR",
                "mentor_id": None,
                "cluster_id": cluster.value,
            },
        ),
        _event(
            cluster,
            EventType.AGENT_CREATED,
            {
                "agent_id": mentor.value,
                "role": "MENTOR",
                "mentor_id": None,
                "cluster_id": cluster.value,
            },
        ),
        _event(
            cluster,
            EventType.AGENT_CREATED,
            {
                "agent_id": worker.value,
                "role": "OPTIMIZER",
                "mentor_id": mentor.value,
                "cluster_id": cluster.value,
            },
        ),
        _event(
            cluster,
            EventType.BOARD_POSTED,
            {
                "post_id": "post-1",
                "board": "MENTOR",
                "topic": "direction",
                "author_agent_id": mentor.value,
                "payload": {"objective": "improve memory"},
            },
        ),
        _event(
            cluster,
            EventType.CANDIDATE_COMMITTED,
            {
                "candidate_id": candidate.value,
                "parent_id": None,
                "direction_id": direction.value,
                "author_agent_id": worker.value,
            },
        ),
        _event(
            cluster,
            EventType.HARDWARE_QUEUED,
            {
                "lease_id": lease.value,
                "device_id": "npu:0",
                "task_id": task.value,
                "owner_agent_id": worker.value,
            },
        ),
        _event(
            cluster,
            EventType.HARDWARE_LEASED,
            {
                "lease_id": lease.value,
                "device_id": "npu:0",
                "task_id": task.value,
                "owner_agent_id": worker.value,
            },
        ),
    )

    projections = _projections()
    board, graph, candidates, queue = projections
    runner = ProjectionRunner(connection, projections)
    runner.rebuild()

    assert board.latest("direction").author_agent_id == mentor
    assert graph.nodes[worker].mentor_id == mentor
    assert (mentor, worker) in graph.edges()
    assert candidates.nodes[candidate].parent_id is None
    assert queue.leased("npu:0").lease_id == lease.value
    assert runner.cursor("mentor_board") == 7

    _append(
        connection,
        _event(
            cluster,
            EventType.AGENT_CLOSED,
            {"agent_id": worker.value},
        ),
        _event(
            cluster,
            EventType.CANDIDATE_COMMITTED,
            {
                "candidate_id": child.value,
                "parent_id": candidate.value,
                "direction_id": direction.value,
                "author_agent_id": worker.value,
            },
        ),
        _event(
            cluster,
            EventType.HARDWARE_RELEASED,
            {
                "lease_id": lease.value,
                "device_id": "npu:0",
                "task_id": task.value,
                "owner_agent_id": worker.value,
            },
        ),
    )

    assert runner.apply_pending() > 0
    assert graph.nodes[worker].state == "CLOSED"
    assert candidates.nodes[child].parent_id == candidate
    assert queue.leased("npu:0") is None
    assert runner.apply_pending() == 0


def test_live_and_replay_snapshots_match() -> None:
    connection = _connection()
    cluster = ClusterId.generate()
    agent = AgentId.generate()
    candidate = CandidateId.generate()

    _append(
        connection,
        _event(
            cluster,
            EventType.AGENT_CREATED,
            {
                "agent_id": agent.value,
                "role": "MENTOR",
                "mentor_id": None,
                "cluster_id": cluster.value,
            },
        ),
        _event(
            cluster,
            EventType.CANDIDATE_COMMITTED,
            {
                "candidate_id": candidate.value,
                "parent_id": None,
                "direction_id": DirectionId.generate().value,
                "author_agent_id": agent.value,
            },
        ),
    )

    live = _projections()
    live_runner = ProjectionRunner(connection, live)
    live_runner.rebuild()
    live_snapshot = tuple(projection.snapshot() for projection in live)

    replay = _projections()
    replay_runner = ProjectionRunner(connection, replay)
    replay_runner.rebuild()
    replay_snapshot = tuple(projection.snapshot() for projection in replay)

    assert replay_snapshot == live_snapshot


def test_rebuild_does_not_write_events_or_outbox() -> None:
    connection = _connection()
    cluster = ClusterId.generate()
    _append(
        connection,
        _event(
            cluster,
            EventType.AGENT_CREATED,
            {
                "agent_id": AgentId.generate().value,
                "role": "MENTOR",
                "mentor_id": None,
                "cluster_id": cluster.value,
            },
        ),
    )
    events_before = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    outbox_before = connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]

    runner = ProjectionRunner(connection, _projections())
    runner.rebuild()

    assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == events_before
    assert connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == outbox_before
