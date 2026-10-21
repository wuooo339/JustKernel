from __future__ import annotations

import re

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import AgentState, Role
from justkernel.application.fakes import (
    FakeAgentRuntime,
    FakeArtifactStore,
    FakeHardwareQueue,
    FakeIds,
    FakeMessageBus,
    FakeToolBackend,
    InMemoryAgentRepository,
    InMemoryClusterRepository,
    InMemoryRepositories,
    InMemoryTaskRepository,
)
from justkernel.application.ports import (
    AgentRepositoryPort,
    AgentRuntimePort,
    ArtifactStorePort,
    ClusterRepositoryPort,
    HardwareQueuePort,
    IdFactoryPort,
    MessageBusPort,
    TaskRepositoryPort,
    ToolBackendPort,
)
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.comm.channels import Channel
from justkernel.comm.message import Message, MessageType
from justkernel.shared.digest import Digest
from justkernel.shared.ids import (
    AgentId,
    CandidateId,
    ClusterId,
    DirectionId,
    TaskId,
)
from justkernel.shared.principal import Principal
from justkernel.task.state import TaskKind
from justkernel.task.task import Task


# ---- helpers ----------------------------------------------------------------
def _operator_ref() -> OperatorRef:
    return OperatorRef(
        operator_id="op-1",
        version="1",
        digest=Digest.from_text("spec"),
        artifact_ref="artifact://spec",
    )


def _cluster() -> Cluster:
    return Cluster(
        id=ClusterId.generate(),
        operator_id="op-1",
        supervisor_id=AgentId.generate(),
        operator_spec_ref=_operator_ref(),
        start_mode=StartMode.GENERATE,
        created_at=0,
    )


def _agent(cluster: Cluster) -> AgentInstance:
    return AgentInstance(
        id=AgentId.generate(),
        cluster_id=cluster.id,
        role=Role.MENTOR,
        mentor_id=None,
        model_profile="model-1",
        skills=(),
        created_at=0,
        state=AgentState.IDLE,
    )


def _task(cluster: Cluster) -> Task:
    return Task(
        id=TaskId.generate(),
        cluster_id=cluster.id,
        mentor_id=AgentId.generate(),
        worker_id=AgentId.generate(),
        kind=TaskKind.GENERATE,
        direction_id=DirectionId.generate(),
        operator_spec_ref=_operator_ref(),
        context_ref="artifact://context",
        context_digest=Digest.from_text("context"),
        budget_ref="budget-1",
        objective="generate",
        created_at=0,
    )


def _message() -> Message:
    return Message(
        id=FakeIds().message_id(),
        cluster_id=ClusterId.generate(),
        seq=1,
        channel=Channel.mentor_board(),
        type=MessageType.DIRECTION_ASSIGNED,
        sender=Principal.agent(AgentId.generate()),
        created_at=0,
    )


# ---- protocols --------------------------------------------------------------
def test_fakes_satisfy_ports() -> None:
    assert isinstance(FakeIds(), IdFactoryPort)
    assert isinstance(InMemoryClusterRepository(), ClusterRepositoryPort)
    assert isinstance(InMemoryAgentRepository(), AgentRepositoryPort)
    assert isinstance(InMemoryTaskRepository(), TaskRepositoryPort)
    assert isinstance(FakeMessageBus(), MessageBusPort)
    assert isinstance(FakeAgentRuntime(), AgentRuntimePort)
    assert isinstance(FakeToolBackend(), ToolBackendPort)
    assert isinstance(FakeHardwareQueue(), HardwareQueuePort)
    assert isinstance(FakeArtifactStore(), ArtifactStorePort)


# ---- deterministic IDs ------------------------------------------------------
def test_fake_ids_are_deterministic_and_valid() -> None:
    first = FakeIds()
    second = FakeIds()

    assert first.cluster_id() == second.cluster_id()
    values = [
        first.agent_id(),
        first.direction_id(),
        first.task_id(),
        first.candidate_id(),
        first.test_record_id(),
        first.message_id(),
        first.lease_id(),
        first.best_selection_id(),
        first.event_id(),
    ]
    assert len(set(values)) == len(values)
    assert all(re.fullmatch(r"[0-9a-f]{32}", value.value) for value in values)


# ---- repositories -----------------------------------------------------------
def test_cluster_repository_round_trip_and_conflict() -> None:
    repository = InMemoryClusterRepository()
    cluster = _cluster()

    repository.insert(cluster)
    assert repository.get(cluster.id) == cluster
    assert repository.version(cluster.id) == 0
    assert repository.update(cluster, expected_version=0) == 1

    with pytest.raises(ValueError):
        repository.update(cluster, expected_version=0)


def test_agent_and_task_repositories() -> None:
    cluster = _cluster()
    agent = _agent(cluster)
    task = _task(cluster)
    repositories = InMemoryRepositories()

    repositories.agents.insert(agent)
    repositories.tasks.insert(task)

    assert repositories.agents.get(agent.id) == agent
    assert repositories.tasks.get(task.id) == task
    assert repositories.agents.version(agent.id) == 0
    assert repositories.tasks.version(task.id) == 0


# ---- message bus ------------------------------------------------------------
def test_message_bus_deduplicates() -> None:
    bus = FakeMessageBus()
    message = _message()

    assert bus.publish(message) is True
    assert bus.publish(message) is False
    assert bus.messages() == (message,)
    assert bus.messages(Channel.mentor_board()) == (message,)


# ---- artifacts --------------------------------------------------------------
def test_fake_artifact_store_round_trip() -> None:
    store = FakeArtifactStore()
    digest = store.put_bytes(b"artifact")

    assert store.get_bytes(digest) == b"artifact"
    assert store.verify(digest) is True
    assert store.ref_for(digest) == f"mem/{digest.value}"


# ---- runtime, tools, hardware ----------------------------------------------
def test_fake_runtime_tools_and_hardware() -> None:
    ids = FakeIds()
    runtime = FakeAgentRuntime(ids)
    tool = FakeToolBackend()
    queue = FakeHardwareQueue(ids)
    agent_id = runtime.create_agent(Role.MENTOR, "model-1", ())
    turn = runtime.start_turn(agent_id, "work")
    runtime.send_message(agent_id, "hello")
    runtime.close_agent(agent_id)

    assert turn == "turn-1"
    assert runtime.created == [(agent_id, Role.MENTOR, "model-1", ())]
    assert runtime.messages == [(agent_id, "hello")]
    assert runtime.closed == [agent_id]

    skill = SkillRef("tester", "1", "/skills/tester", Digest.from_text("skill"))
    job = tool.submit_test(
        task_id=TaskId.generate(),
        candidate_id=CandidateId.generate(),
        skill_ref=skill,
        case_selection=("case-1",),
        timeout_s=30,
        device="npu:0",
    )
    assert job == "job-1"

    lease = queue.acquire(TaskId.generate(), "npu:0", 100, 0)
    assert queue.status("npu:0") == (lease,)
    queue.release(lease, 10)
    assert queue.status("npu:0") == ()
