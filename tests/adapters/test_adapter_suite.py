from __future__ import annotations

from pathlib import Path

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import AgentState, Role
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.platform.artifacts.store import ArtifactStore
from justkernel.platform.hardware.ledger import (
    HardwareLedger,
    LeaseConflictError,
    apply_hardware_schema,
)
from justkernel.platform.persistence.database import connect
from justkernel.platform.persistence.migrations import apply_migrations
from justkernel.platform.persistence.outbox import OutboxEntry
from justkernel.platform.persistence.projections import (
    ClusterGraphProjection,
    MentorBoardProjection,
    ProjectionRunner,
)
from justkernel.platform.persistence.recovery import recover
from justkernel.platform.persistence.registry import (
    OperatorActiveError,
    OperatorRegistry,
    apply_registry_schema,
)
from justkernel.platform.persistence.unit_of_work import UnitOfWork
from justkernel.shared.digest import Digest
from justkernel.shared.events import DomainEvent, EventType
from justkernel.shared.ids import AgentId, ClusterId, EventId
from justkernel.shared.principal import Principal


# ---- helpers ----------------------------------------------------------------
def _cluster() -> Cluster:
    cluster = Cluster(
        id=ClusterId.generate(),
        operator_id="op-1",
        supervisor_id=AgentId.generate(),
        operator_spec_ref=OperatorRef(
            operator_id="op-1",
            version="1",
            digest=Digest.from_text("spec"),
            artifact_ref="artifact://spec",
        ),
        start_mode=StartMode.GENERATE,
        created_at=0,
    )
    cluster.start()
    return cluster


def _skill() -> SkillRef:
    return SkillRef(
        name="optimizer",
        version="1",
        source_path="/skills/base/optimizer",
        digest=Digest.from_text("skill"),
    )


def _agent(
    cluster: Cluster,
    *,
    role: Role = Role.OPTIMIZER,
    mentor_id: AgentId | None = None,
) -> AgentInstance:
    return AgentInstance(
        id=AgentId.generate(),
        cluster_id=cluster.id,
        role=role,
        mentor_id=mentor_id,
        model_profile="model-1",
        skills=(_skill(),),
        created_at=0,
        state=AgentState.IDLE,
    )


def _event(
    cluster: Cluster,
    event_type: EventType,
    payload: dict[str, object],
) -> DomainEvent:
    return DomainEvent(
        id=EventId.generate(),
        cluster_id=cluster.id,
        type=event_type,
        event_version=1,
        aggregate_type="Test",
        aggregate_id="aggregate-1",
        aggregate_version=0,
        actor=Principal.system(),
        occurred_at=0,
        payload=payload,
    )


# ---- end-to-end adapter suite ----------------------------------------------
def test_adapter_stack_end_to_end(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    cluster_dir = data_root / "clusters" / "c1"
    cluster_dir.mkdir(parents=True)
    journal = connect(str(cluster_dir / "journal.db"))
    apply_migrations(journal)
    registry_connection = connect(str(data_root / "registry.db"))
    apply_registry_schema(registry_connection)
    hardware_connection = connect(str(data_root / "hardware.db"))
    apply_hardware_schema(hardware_connection)

    registry = OperatorRegistry(registry_connection)
    ledger = HardwareLedger(hardware_connection)
    artifacts = ArtifactStore(cluster_dir / "artifacts")
    cluster = _cluster()
    mentor = _agent(cluster, role=Role.MENTOR)
    worker = _agent(cluster, role=Role.OPTIMIZER, mentor_id=mentor.id)
    worker.start_turn()

    registry.reserve(
        operator_id=cluster.operator_id,
        cluster_id=cluster.id.value,
        journal_ref="clusters/c1/journal.db",
        reservation_key="reservation-1",
        now_ms=0,
    )
    with pytest.raises(OperatorActiveError):
        registry.reserve(
            operator_id=cluster.operator_id,
            cluster_id="cluster-2",
            journal_ref="clusters/c2/journal.db",
            reservation_key="reservation-2",
            now_ms=0,
        )

    events = (
        _event(
            cluster,
            EventType.AGENT_CREATED,
            {
                "agent_id": mentor.id.value,
                "role": "MENTOR",
                "mentor_id": None,
                "cluster_id": cluster.id.value,
            },
        ),
        _event(
            cluster,
            EventType.AGENT_CREATED,
            {
                "agent_id": worker.id.value,
                "role": "OPTIMIZER",
                "mentor_id": mentor.id.value,
                "cluster_id": cluster.id.value,
            },
        ),
        _event(
            cluster,
            EventType.BOARD_POSTED,
            {
                "post_id": "post-1",
                "board": "MENTOR",
                "topic": "direction",
                "author_agent_id": mentor.id.value,
                "payload": {"objective": "improve memory"},
            },
        ),
    )
    outbox = OutboxEntry(
        id="outbox-1",
        cluster_id=cluster.id,
        kind="message",
        payload={"subject": "wake"},
        idempotency_key="key-1",
        available_at=0,
    )

    with UnitOfWork(journal) as uow:
        uow.clusters.insert(cluster)
        uow.agents.insert(mentor)
        uow.agents.insert(worker)
        for event in events:
            uow.events.append(event)
        uow.outbox.enqueue(outbox)

    artifact = artifacts.put_bytes(b"candidate source")
    assert artifacts.get_bytes(artifact) == b"candidate source"
    assert artifacts.path_for(artifact).is_relative_to(artifacts.root)

    board = MentorBoardProjection()
    graph = ClusterGraphProjection()
    ProjectionRunner(journal, (board, graph)).rebuild()
    assert board.latest("direction").author_agent_id == mentor.id
    assert graph.nodes[worker.id].mentor_id == mentor.id

    first_lease = ledger.acquire(
        lease_id="lease-1",
        cluster_id=cluster.id.value,
        task_id="task-1",
        job_id="job-1",
        device_id="npu:0",
        ttl_ms=100,
        now_ms=0,
    )
    ledger.start_execution(first_lease.lease_id, first_lease.fencing_token)
    with pytest.raises(LeaseConflictError):
        ledger.acquire(
            lease_id="lease-2",
            cluster_id=cluster.id.value,
            task_id="task-2",
            job_id="job-2",
            device_id="npu:0",
            ttl_ms=100,
            now_ms=1,
        )
    ledger.release(first_lease.lease_id, first_lease.fencing_token)

    report = recover(journal, now_ms=100, ledger=ledger)
    assert report.clusters_paused == 1
    assert report.agents_interrupted == 1
    assert report.pending_outbox == 1
    assert (
        journal.execute("SELECT state FROM clusters WHERE id = ?", (cluster.id.value,)).fetchone()[
            0
        ]
        == "PAUSED"
    )
    assert (
        journal.execute("SELECT state FROM agents WHERE id = ?", (worker.id.value,)).fetchone()[0]
        == "INTERRUPTED"
    )

    assert registry.release(cluster.id.value, "STOPPED") is True
    new_cluster = registry.reserve(
        operator_id=cluster.operator_id,
        cluster_id="cluster-2",
        journal_ref="clusters/c2/journal.db",
        reservation_key="reservation-2",
        now_ms=200,
    )
    assert new_cluster.cluster_id == "cluster-2"
    journal.close()
    registry_connection.close()
    hardware_connection.close()
