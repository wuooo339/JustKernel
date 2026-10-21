from __future__ import annotations

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import Role
from justkernel.application.agent_service import AgentService
from justkernel.application.candidate_service import CandidateService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import (
    FakeIds,
    InMemoryAgentRepository,
    InMemoryCandidateRepository,
    InMemoryClusterRepository,
    InMemoryTaskRepository,
)
from justkernel.candidate.candidate import CandidateVersion
from justkernel.candidate.errors import CandidateError
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, CandidateId, DirectionId
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


def _skill() -> SkillRef:
    return SkillRef(
        name="cann-simulation",
        version="1",
        source_path="/skills/tester",
        digest=Digest.from_text("skill"),
    )


def _stack() -> tuple[
    CandidateService,
    AgentService,
    AgentInstance,
    AgentInstance,
    AgentInstance,
    InMemoryCandidateRepository,
    object,
]:
    clusters = InMemoryClusterRepository()
    agents = InMemoryAgentRepository()
    tasks = InMemoryTaskRepository()
    candidates = InMemoryCandidateRepository()
    ids = FakeIds()
    cluster_service = ClusterService(clusters, ids)
    agent_service = AgentService(clusters, agents, tasks, ids)
    candidate_service = CandidateService(candidates, tasks, agents, ids)
    cluster = cluster_service.create_cluster(
        operator_id="op-1",
        supervisor_id=AgentId.generate(),
        operator_spec_ref=_operator_ref(),
        start_mode=StartMode.GENERATE,
        max_agents=6,
        created_at=0,
    )
    cluster_service.start_cluster(cluster.id)
    agent_service.create_agent(
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
    optimizer = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.OPTIMIZER,
        model_profile="model-1",
        skills=(),
    )
    tester = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.TESTER,
        model_profile="model-1",
        skills=(),
    )
    return candidate_service, agent_service, mentor, optimizer, tester, candidates, cluster


def _assign(
    service: AgentService,
    mentor: AgentInstance,
    worker: AgentInstance,
    kind: TaskKind,
    *,
    candidate_id: CandidateId | None = None,
) -> Task:
    return service.assign_task(
        mentor_id=mentor.id,
        worker_id=worker.id,
        kind=kind,
        direction_id=DirectionId.generate(),
        operator_spec_ref=_operator_ref(),
        context_ref="artifact://context",
        context_digest=Digest.from_text("context"),
        budget_ref="budget-1",
        objective="candidate work",
        candidate_id=candidate_id,
        skill_ref=_skill() if kind in (TaskKind.TEST, TaskKind.PROFILE) else None,
        created_at=0,
    )


def _import(service: CandidateService, cluster: object) -> CandidateVersion:
    return service.import_candidate(
        cluster_id=cluster.id,
        direction_id=DirectionId.generate(),
        source_files={"op_kernel/kernel.cpp": "// root"},
        diff_artifact="artifact://diff",
        import_id="import-1",
        created_at=0,
    )


def _commit(
    service: CandidateService,
    task: Task,
    author: AgentInstance,
) -> CandidateVersion:
    return service.commit_candidate(
        task_id=task.id,
        author_agent_id=author.id,
        source_files={"op_kernel/kernel.cpp": "// candidate"},
        diff_artifact="artifact://diff",
        created_at=0,
    )


# ---- import -----------------------------------------------------------------
def test_import_root_candidate() -> None:
    service, _, _, _, _, candidates, cluster = _stack()
    candidate = _import(service, cluster)

    assert candidate.parent_id is None
    assert candidate.task_id is None
    assert candidate.author_agent_id is None
    assert candidate.author_principal == Principal.system()
    assert candidate.import_id == "import-1"
    assert candidates.get(candidate.id) == candidate
    assert candidates.list_by_cluster(cluster.id) == (candidate,)


def test_import_rejects_empty_source() -> None:
    service, _, _, _, _, _, cluster = _stack()

    with pytest.raises(CandidateError):
        service.import_candidate(
            cluster_id=cluster.id,
            direction_id=DirectionId.generate(),
            source_files={},
            diff_artifact="artifact://diff",
            import_id="import-1",
            created_at=0,
        )


# ---- commit -----------------------------------------------------------------
def test_commit_generate_candidate() -> None:
    service, agents, mentor, optimizer, _, _, _ = _stack()
    task = _assign(agents, mentor, optimizer, TaskKind.GENERATE)
    candidate = _commit(service, task, optimizer)

    assert candidate.parent_id is None
    assert candidate.task_id == task.id
    assert candidate.author_agent_id == optimizer.id
    assert candidate.author_principal == Principal.agent(optimizer.id)


def test_commit_optimize_child() -> None:
    service, agents, mentor, optimizer, _, _, cluster = _stack()
    root = _import(service, cluster)
    task = _assign(agents, mentor, optimizer, TaskKind.OPTIMIZE, candidate_id=root.id)
    candidate = _commit(service, task, optimizer)

    assert candidate.parent_id == root.id


def test_commit_requires_optimize_task_and_running_state() -> None:
    service, agents, mentor, optimizer, tester, _, cluster = _stack()
    root = _import(service, cluster)
    test_task = _assign(agents, mentor, tester, TaskKind.TEST, candidate_id=root.id)

    with pytest.raises(CandidateError):
        _commit(service, test_task, tester)

    generate_task = _assign(agents, mentor, optimizer, TaskKind.GENERATE)
    agents.complete_task(
        mentor_id=mentor.id,
        task_id=generate_task.id,
        result_ref="artifact://result",
        now_ms=100,
    )
    with pytest.raises(CandidateError):
        _commit(service, generate_task, optimizer)


def test_commit_requires_optimizer_author() -> None:
    service, agents, mentor, optimizer, tester, _, _ = _stack()
    task = _assign(agents, mentor, optimizer, TaskKind.GENERATE)

    with pytest.raises(CandidateError):
        _commit(service, task, tester)


def test_commit_requires_existing_parent() -> None:
    service, agents, mentor, optimizer, _, _, cluster = _stack()
    root = _import(service, cluster)
    task = _assign(agents, mentor, optimizer, TaskKind.OPTIMIZE, candidate_id=root.id)
    task.candidate_id = CandidateId.generate()

    with pytest.raises(CandidateError):
        _commit(service, task, optimizer)
