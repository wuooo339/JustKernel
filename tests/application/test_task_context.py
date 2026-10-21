from __future__ import annotations

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import Role
from justkernel.application.agent_service import AgentService
from justkernel.application.candidate_service import CandidateService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import (
    FakeArtifactStore,
    FakeIds,
    InMemoryAgentRepository,
    InMemoryCandidateRepository,
    InMemoryClusterRepository,
    InMemoryTaskRepository,
)
from justkernel.application.task_context_service import TaskContextService
from justkernel.candidate.candidate import CandidateVersion
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, DirectionId, TaskId
from justkernel.shared.paths import ProjectPath
from justkernel.task.context import (
    ArtifactGrant,
    CandidateRef,
    EmptyReason,
    TaskBudget,
    TaskContext,
    TaskContextError,
)
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
        name="cann-simulation-test",
        version="1",
        source_path="/skills/tester",
        digest=Digest.from_text("skill"),
    )


def _stack() -> tuple[
    TaskContextService,
    AgentService,
    Task,
    AgentInstance,
    AgentInstance,
    AgentInstance,
    CandidateVersion,
    FakeArtifactStore,
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
    worker = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.OPTIMIZER,
        model_profile="model-1",
        skills=(),
    )
    other = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.OPTIMIZER,
        model_profile="model-1",
        skills=(),
    )
    candidate = candidate_service.import_candidate(
        cluster_id=cluster.id,
        direction_id=DirectionId.generate(),
        source_files={"kernel.cpp": "// source"},
        diff_artifact="artifact://diff",
        import_id="import-1",
        created_at=0,
    )
    task = agent_service.assign_task(
        mentor_id=mentor.id,
        worker_id=worker.id,
        kind=TaskKind.OPTIMIZE,
        direction_id=DirectionId.generate(),
        operator_spec_ref=_operator_ref(),
        context_ref="artifact://context",
        context_digest=Digest.from_text("context"),
        budget_ref="budget-1",
        objective="repair",
        candidate_id=candidate.id,
        created_at=0,
    )
    store = FakeArtifactStore()
    return (
        TaskContextService(tasks, candidates),
        agent_service,
        task,
        mentor,
        worker,
        other,
        candidate,
        store,
    )


def _grant(task: Task, digest: Digest, *, expires: int = 100) -> ArtifactGrant:
    return ArtifactGrant(
        grant_id="grant-1",
        task_id=task.id,
        artifact_digest=digest,
        readonly_scope=(ProjectPath("candidate/source"),),
        expires_at_ms=expires,
    )


def _context(
    service: TaskContextService,
    task: Task,
    mentor_id: AgentId,
    candidate: CandidateVersion,
    grant: ArtifactGrant,
    *,
    now_ms: int = 0,
) -> TaskContext:
    return service.create_context(
        task_id=task.id,
        mentor_id=mentor_id,
        base_candidate_ref=CandidateRef(candidate.id, candidate.source.digest),
        objective="repair",
        acceptance=("compile",),
        feedback=(),
        history=(),
        shared_evidence=(),
        resource_grants=(grant,),
        budget=TaskBudget(max_duration_s=100),
        empty_reasons=(
            EmptyReason("feedback", "no feedback"),
            EmptyReason("history", "no history"),
            EmptyReason("shared_evidence", "no shared evidence"),
        ),
        now_ms=now_ms,
    )


# ---- context creation -------------------------------------------------------
def test_create_context_binds_task_and_candidate() -> None:
    service, _, task, mentor, _, _, candidate, _ = _stack()
    artifact_digest = Digest.from_text("artifact")
    context = _context(service, task, mentor.id, candidate, _grant(task, artifact_digest))

    assert context.task_id == task.id
    assert context.base_candidate_ref is not None
    assert context.base_candidate_ref.source_digest == candidate.source.digest
    assert context.resource_grants[0].artifact_digest == artifact_digest


def test_create_context_rejects_foreign_mentor_and_candidate_digest() -> None:
    service, _, task, mentor, _, _, candidate, _ = _stack()
    grant = _grant(task, Digest.from_text("artifact"))

    with pytest.raises(TaskContextError):
        _context(service, task, AgentId.generate(), candidate, grant)

    with pytest.raises(TaskContextError):
        service.create_context(
            task_id=task.id,
            mentor_id=mentor.id,
            base_candidate_ref=CandidateRef(candidate.id, Digest.from_text("wrong")),
            objective="repair",
            acceptance=("compile",),
            feedback=(),
            history=(),
            shared_evidence=(),
            resource_grants=(grant,),
            budget=TaskBudget(max_duration_s=100),
            empty_reasons=(
                EmptyReason("feedback", "no feedback"),
                EmptyReason("history", "no history"),
                EmptyReason("shared_evidence", "no shared evidence"),
            ),
        )


def test_create_context_rejects_grant_for_another_task() -> None:
    service, _, task, mentor, _, _, candidate, _ = _stack()
    foreign_grant = ArtifactGrant(
        grant_id="grant-1",
        task_id=TaskId.generate(),
        artifact_digest=Digest.from_text("artifact"),
        readonly_scope=(ProjectPath("candidate/source"),),
        expires_at_ms=100,
    )

    with pytest.raises(TaskContextError):
        _context(service, task, mentor.id, candidate, foreign_grant)


# ---- context reads ----------------------------------------------------------
def test_context_reads_are_owner_only() -> None:
    service, _, task, mentor, worker, other, candidate, _ = _stack()
    context = _context(service, task, mentor.id, candidate, _grant(task, Digest.from_text("a")))

    assert service.read_context(task.id, context, worker.id) is context
    assert service.read_context(task.id, context, mentor.id) is context
    with pytest.raises(TaskContextError):
        service.read_context(task.id, context, other.id)


# ---- artifact grants --------------------------------------------------------
def test_artifact_grant_checks_digest_scope_and_expiry() -> None:
    service, _, task, mentor, worker, _, candidate, _ = _stack()
    store = FakeArtifactStore()
    digest = store.put_bytes(b"candidate source")
    context = _context(service, task, mentor.id, candidate, _grant(task, digest))
    source_path = ProjectPath("candidate/source/kernel.cpp")

    assert service.authorize_artifact(context, digest, source_path, 50).artifact_digest == digest
    assert (
        service.read_artifact(
            task.id,
            context,
            worker.id,
            digest,
            source_path,
            50,
            store,
        )
        == b"candidate source"
    )

    with pytest.raises(TaskContextError):
        service.authorize_artifact(context, Digest.from_text("other"), source_path, 50)
    with pytest.raises(TaskContextError):
        service.authorize_artifact(context, digest, ProjectPath("candidate/other.cpp"), 50)
    with pytest.raises(TaskContextError):
        service.authorize_artifact(context, digest, source_path, 100)


def test_artifact_read_requires_owner_and_valid_store_value() -> None:
    service, _, task, mentor, _, other, candidate, _ = _stack()
    store = FakeArtifactStore()
    digest = store.put_bytes(b"candidate source")
    context = _context(service, task, mentor.id, candidate, _grant(task, digest))
    source_path = ProjectPath("candidate/source/kernel.cpp")

    with pytest.raises(TaskContextError):
        service.read_artifact(task.id, context, other.id, digest, source_path, 50, store)
    with pytest.raises(TaskContextError):
        service.read_artifact(
            task.id,
            context,
            AgentId.generate(),
            digest,
            source_path,
            50,
            store,
        )


def test_expired_grant_is_rejected_at_creation() -> None:
    service, _, task, mentor, _, _, candidate, _ = _stack()
    digest = Digest.from_text("artifact")
    grant = _grant(task, digest, expires=100)

    with pytest.raises(TaskContextError):
        _context(service, task, mentor.id, candidate, grant, now_ms=100)
