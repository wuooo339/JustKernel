from __future__ import annotations

from pathlib import Path

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.errors import AgentError
from justkernel.agent.state import AgentState, Role
from justkernel.application.agent_service import AgentService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import (
    FakeHardwareQueue,
    FakeIds,
    InMemoryAgentRepository,
    InMemoryClusterRepository,
    InMemoryTaskRepository,
)
from justkernel.application.lease_book import AgentLeaseBook
from justkernel.application.worker_lifecycle import WorkerLifecycle
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.platform.runtime.checkpoint import CheckpointStore
from justkernel.platform.runtime.errors import RuntimeLimitError
from justkernel.platform.runtime.pool import AgentRuntimePool
from justkernel.platform.runtime.runner import AgentRunRequest, RunnerResult
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, CandidateId, DirectionId, TaskId
from justkernel.task.state import TaskKind

MAX_AGENTS = 100
TURN_CYCLES = 3


class FakeRunner:
    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []

    def run(self, request: AgentRunRequest) -> RunnerResult:
        self.requests.append(request)
        return RunnerResult(output="ok", checkpoint={"tick": len(self.requests)})


def _operator_ref() -> OperatorRef:
    return OperatorRef(
        operator_id="op-1",
        version="1",
        digest=Digest.from_text("spec"),
        artifact_ref="artifact://spec",
    )


def _stack() -> tuple[object, AgentService, AgentInstance, AgentInstance, list[AgentInstance]]:
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
        max_agents=MAX_AGENTS,
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
    workers = [
        agent_service.open_worker(
            mentor_id=mentor.id,
            role=Role.OPTIMIZER,
            model_profile="model-1",
            skills=(),
        )
        for _ in range(98)
    ]
    return cluster, agent_service, supervisor, mentor, workers


def _runtime(tmp_path: Path) -> tuple[AgentRuntimePool, CheckpointStore]:
    pool = AgentRuntimePool(
        FakeRunner(),
        CheckpointStore(tmp_path / "checkpoints"),
        max_agents=MAX_AGENTS,
        runtime_processes=8,
        model_concurrency=32,
    )
    return pool, pool.checkpoints


def _attach(
    pool: AgentRuntimePool,
    cluster: object,
    supervisor: AgentInstance,
    mentor: AgentInstance,
    workers: list[AgentInstance],
) -> None:
    for agent in (supervisor, mentor, *workers):
        pool.create_agent(
            agent_id=agent.id,
            cluster_id=cluster.id,
            role=agent.role,
            model_profile=agent.model_profile,
            skills=agent.skills,
            mentor_id=agent.mentor_id,
        )


def test_100_agents_multiple_turns_and_clean_shutdown(tmp_path: Path) -> None:
    cluster, service, supervisor, mentor, workers = _stack()
    pool, checkpoints = _runtime(tmp_path)
    _attach(pool, cluster, supervisor, mentor, workers)
    runner = pool.runner
    assert isinstance(runner, FakeRunner)
    assert pool.active_count == MAX_AGENTS

    with pytest.raises(AgentError):
        service.open_worker(
            mentor_id=mentor.id,
            role=Role.OPTIMIZER,
            model_profile="model-1",
            skills=(),
        )
    with pytest.raises(RuntimeLimitError):
        pool.create_agent(
            agent_id=AgentId.generate(),
            cluster_id=cluster.id,
            role=Role.OPTIMIZER,
            model_profile="model-1",
            skills=(),
        )

    all_agents = [supervisor, mentor, *workers]
    for cycle in range(TURN_CYCLES):
        for agent in all_agents:
            pool.start_turn(agent.id, f"cycle-{cycle}")

    assert len(runner.requests) == MAX_AGENTS * TURN_CYCLES
    assert checkpoints.list_sessions(cluster.id, supervisor.id)
    assert len(list((tmp_path / "checkpoints").rglob("*.json"))) == MAX_AGENTS

    for worker in workers:
        service.assign_task(
            mentor_id=mentor.id,
            worker_id=worker.id,
            kind=TaskKind.OPTIMIZE,
            direction_id=DirectionId.generate(),
            operator_spec_ref=_operator_ref(),
            context_ref="artifact://context",
            context_digest=Digest.from_text("context"),
            budget_ref="budget-1",
            objective="scale task",
            candidate_id=CandidateId.generate(),
            created_at=0,
        )

    for worker in workers:
        task = worker.current_task_id
        assert task is not None
        service.complete_task(
            mentor_id=mentor.id,
            task_id=task,
            result_ref="artifact://result",
            now_ms=10,
        )

    book = AgentLeaseBook(FakeHardwareQueue(FakeIds()))
    lifecycle = WorkerLifecycle(service, book)
    for index, worker in enumerate(workers):
        book.acquire(
            agent_id=worker.id,
            task_id=TaskId.generate(),
            device=f"npu:{index}",
            ttl_ms=1_000,
            now_ms=0,
        )
        lifecycle.close_worker(mentor_id=mentor.id, worker_id=worker.id, now_ms=20)
        assert worker.state is AgentState.CLOSED
        assert book.leases_for(worker.id) == ()

    assert book.active_count == 0
    assert pool.close_all() == MAX_AGENTS
    assert pool.active_count == 0
