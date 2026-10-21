from __future__ import annotations

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.errors import AgentError
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import AgentState, Role
from justkernel.application.agent_service import AgentService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import (
    FakeIds,
    InMemoryAgentRepository,
    InMemoryClusterRepository,
    InMemoryTaskRepository,
)
from justkernel.cluster.invariants import InvariantError
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.shared.digest import Digest
from justkernel.shared.ids import (
    AgentId,
    CandidateId,
    DirectionId,
)
from justkernel.task.state import TaskKind, TaskState
from justkernel.task.task import Task


# ---- helpers ----------------------------------------------------------------
def _operator_ref() -> OperatorRef:
    return OperatorRef(
        operator_id="op-1",
        version="1",
        digest=Digest.from_text("spec"),
        artifact_ref="artifact://spec",
    )


def _skill() -> SkillRef:
    return SkillRef(
        name="cann-simulation",
        version="1",
        source_path="/skills/tester",
        digest=Digest.from_text("skill"),
    )


def _stack(
    max_agents: int = 6,
) -> tuple[
    ClusterService,
    AgentService,
    InMemoryClusterRepository,
    InMemoryAgentRepository,
    InMemoryTaskRepository,
    object,
    AgentInstance,
]:
    clusters = InMemoryClusterRepository()
    agents = InMemoryAgentRepository()
    tasks = InMemoryTaskRepository()
    ids = FakeIds()
    cluster_service = ClusterService(clusters, ids)
    agent_service = AgentService(clusters, agents, tasks, ids)
    cluster = cluster_service.create_cluster(
        operator_id="op-1",
        supervisor_id=AgentId.generate(),
        operator_spec_ref=_operator_ref(),
        start_mode=StartMode.GENERATE,
        max_agents=max_agents,
        created_at=0,
    )
    cluster_service.start_cluster(cluster.id)
    supervisor = agent_service.create_agent(
        cluster_id=cluster.id,
        role=Role.SUPERVISOR,
        model_profile="model-1",
        skills=(),
        agent_id=cluster.supervisor_id,
    )
    mentor = agent_service.create_agent(
        cluster_id=cluster.id,
        role=Role.MENTOR,
        model_profile="model-1",
        skills=(),
    )
    return cluster_service, agent_service, clusters, agents, tasks, supervisor, mentor


def _open(
    service: AgentService,
    mentor: AgentInstance,
    role: Role = Role.OPTIMIZER,
) -> AgentInstance:
    return service.open_worker(
        mentor_id=mentor.id,
        role=role,
        model_profile="model-1",
        skills=(),
    )


def _assign(
    service: AgentService,
    mentor: AgentInstance,
    worker: AgentInstance,
    kind: TaskKind = TaskKind.OPTIMIZE,
    **overrides: object,
) -> Task:
    values: dict[str, object] = {
        "mentor_id": mentor.id,
        "worker_id": worker.id,
        "kind": kind,
        "direction_id": DirectionId.generate(),
        "operator_spec_ref": _operator_ref(),
        "context_ref": "artifact://context",
        "context_digest": Digest.from_text("context"),
        "budget_ref": "budget-1",
        "objective": "optimize",
        "created_at": 0,
    }
    if kind is not TaskKind.GENERATE:
        values["candidate_id"] = CandidateId.generate()
    if kind in (TaskKind.TEST, TaskKind.PROFILE):
        values["skill_ref"] = _skill()
    values.update(overrides)
    return service.assign_task(**values)


# ---- agent/worker lifecycle -------------------------------------------------
def test_create_agents_and_open_worker() -> None:
    _, service, _, agents, _, supervisor, mentor = _stack()
    worker = _open(service, mentor)

    assert supervisor.state is AgentState.IDLE
    assert mentor.state is AgentState.IDLE
    assert worker.state is AgentState.IDLE
    assert worker.mentor_id == mentor.id
    assert len(agents.list_by_cluster(worker.cluster_id)) == 3

    with pytest.raises(AgentError):
        service.create_agent(
            cluster_id=worker.cluster_id,
            role=Role.OPTIMIZER,
            model_profile="model-1",
            skills=(),
        )


def test_only_a_mentor_can_open_a_worker() -> None:
    _, service, _, _, _, supervisor, _ = _stack()

    with pytest.raises(AgentError):
        _open(service, supervisor)


def test_max_agents_is_enforced() -> None:
    _, service, _, _, _, _, mentor = _stack(max_agents=6)
    workers = [_open(service, mentor) for _ in range(4)]

    with pytest.raises(AgentError):
        _open(service, mentor)

    service.close_worker(mentor_id=mentor.id, worker_id=workers[0].id, now_ms=100)
    assert _open(service, mentor).state is AgentState.IDLE


# ---- task dispatch ----------------------------------------------------------
def test_assign_and_complete_task() -> None:
    _, service, _, _, _tasks, _, mentor = _stack()
    worker = _open(service, mentor)
    task = _assign(service, mentor, worker)

    assert task.state is TaskState.RUNNING
    assert worker.state is AgentState.RUNNING
    assert worker.current_task_id == task.id

    with pytest.raises(AgentError):
        service.close_worker(mentor_id=mentor.id, worker_id=worker.id, now_ms=100)
    with pytest.raises(InvariantError):
        _assign(service, mentor, worker)

    completed = service.complete_task(
        mentor_id=mentor.id,
        task_id=task.id,
        result_ref="artifact://result",
        now_ms=200,
    )
    assert completed.state is TaskState.SUCCEEDED
    assert worker.state is AgentState.IDLE
    assert worker.current_task_id is None

    closed = service.close_worker(mentor_id=mentor.id, worker_id=worker.id, now_ms=300)
    assert closed.state is AgentState.CLOSED


def test_mentor_ownership_and_task_kind_are_enforced() -> None:
    _, service, _, _, _, _, mentor = _stack()
    other_mentor = service.create_agent(
        cluster_id=mentor.cluster_id,
        role=Role.MENTOR,
        model_profile="model-1",
        skills=(),
    )
    worker = _open(service, mentor)

    with pytest.raises(InvariantError):
        _assign(service, other_mentor, worker)
    with pytest.raises(AgentError):
        service.close_worker(
            mentor_id=other_mentor.id,
            worker_id=worker.id,
            now_ms=100,
        )

    tester = _open(service, mentor, Role.TESTER)
    with pytest.raises(InvariantError):
        _assign(service, mentor, tester, TaskKind.OPTIMIZE)


def test_closed_worker_rejects_tasks() -> None:
    _, service, _, _, _, _, mentor = _stack()
    worker = _open(service, mentor)
    service.close_worker(mentor_id=mentor.id, worker_id=worker.id, now_ms=100)

    with pytest.raises(InvariantError):
        _assign(service, mentor, worker)
