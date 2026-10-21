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
    FakeToolBackend,
    InMemoryAgentRepository,
    InMemoryCandidateRepository,
    InMemoryClusterRepository,
    InMemoryTaskRepository,
    InMemoryTestRecordRepository,
    InMemoryToolJobRepository,
)
from justkernel.application.testing_service import TestingService as Service
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, CandidateId, DirectionId
from justkernel.task.state import TaskKind
from justkernel.task.task import Task
from justkernel.testing.errors import TestRecordError as RecordError
from justkernel.testing.job import ToolJobError, ToolJobState
from justkernel.testing.record import ArtifactRef, Environment
from justkernel.testing.state import (
    TestCoverage as Coverage,
)
from justkernel.testing.state import (
    TestOutcome as Outcome,
)
from justkernel.testing.state import (
    TestRecordKind as RecordKind,
)


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


def _artifact() -> ArtifactRef:
    return ArtifactRef(ref="artifact://record", digest=Digest.from_text("zip"))


def _environment() -> Environment:
    return Environment(values=(("soc", "Ascend910B4"),))


def _stack() -> tuple[
    Service,
    AgentService,
    FakeToolBackend,
    InMemoryTestRecordRepository,
    InMemoryToolJobRepository,
    AgentInstance,
    AgentInstance,
    AgentInstance,
    object,
    object,
]:
    clusters = InMemoryClusterRepository()
    agents = InMemoryAgentRepository()
    tasks = InMemoryTaskRepository()
    candidates = InMemoryCandidateRepository()
    records = InMemoryTestRecordRepository()
    jobs = InMemoryToolJobRepository()
    ids = FakeIds()
    backend = FakeToolBackend()
    cluster_service = ClusterService(clusters, ids)
    agent_service = AgentService(clusters, agents, tasks, ids)
    candidate_service = CandidateService(candidates, tasks, agents, ids)
    testing_service = Service(tasks, agents, records, jobs, backend, ids)
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
    tester = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.TESTER,
        model_profile="model-1",
        skills=(),
    )
    profiler = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.PROFILER,
        model_profile="model-1",
        skills=(),
    )
    candidate = candidate_service.import_candidate(
        cluster_id=cluster.id,
        direction_id=DirectionId.generate(),
        source_files={"op_kernel/kernel.cpp": "// root"},
        diff_artifact="artifact://diff",
        import_id="import-1",
        created_at=0,
    )
    return (
        testing_service,
        agent_service,
        backend,
        records,
        jobs,
        mentor,
        tester,
        profiler,
        candidate,
        cluster,
    )


def _assign(
    service: AgentService,
    mentor: AgentInstance,
    worker: AgentInstance,
    kind: TaskKind,
    candidate_id: CandidateId,
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
        objective="test flow",
        candidate_id=candidate_id,
        skill_ref=_skill(),
        created_at=0,
    )


# ---- submit jobs ------------------------------------------------------------
def test_submit_test_is_idempotent_and_detects_conflicts() -> None:
    testing, agents, backend, _, jobs, mentor, tester, _, candidate, _ = _stack()
    task = _assign(agents, mentor, tester, TaskKind.TEST, candidate.id)

    first = testing.submit_test(
        task_id=task.id,
        case_selection=("case-1",),
        timeout_s=30,
        device="npu:0",
    )
    second = testing.submit_test(
        task_id=task.id,
        case_selection=("case-1",),
        timeout_s=30,
        device="npu:0",
    )

    assert first == second
    assert first.state is ToolJobState.QUEUED
    assert jobs.get_by_task(task.id) == first
    assert len(backend.submissions) == 1

    with pytest.raises(ToolJobError):
        testing.submit_test(
            task_id=task.id,
            case_selection=("case-2",),
            timeout_s=30,
            device="npu:0",
        )


def test_submit_requires_matching_task_kind() -> None:
    testing, agents, _, _, _, mentor, tester, _, candidate, _ = _stack()
    task = _assign(agents, mentor, tester, TaskKind.TEST, candidate.id)

    with pytest.raises(ToolJobError):
        testing.submit_profile(
            task_id=task.id,
            case_selection=("case-1",),
            timeout_s=30,
        )


# ---- records ----------------------------------------------------------------
def test_seal_record_and_job_completion() -> None:
    testing, agents, _, records, jobs, mentor, tester, _, candidate, _ = _stack()
    task = _assign(agents, mentor, tester, TaskKind.TEST, candidate.id)
    job = testing.submit_test(
        task_id=task.id,
        case_selection=("case-1",),
        timeout_s=30,
    )

    record = testing.seal_record(
        task_id=task.id,
        outcome=Outcome.PASS,
        coverage=Coverage.FULL,
        artifact=_artifact(),
        environment=_environment(),
        backend="cann-simulation",
        created_at=100,
    )

    assert record.kind is RecordKind.TEST
    assert record.executed is True
    assert record.task_id == task.id
    assert record.job_id == job.id
    assert record.candidate_id == candidate.id
    assert records.get_by_task(task.id) == record

    completed = jobs.get(job.id)
    assert completed.state is ToolJobState.SUCCEEDED
    assert completed.record_id == record.id.value

    with pytest.raises(RecordError):
        testing.seal_record(
            task_id=task.id,
            outcome=Outcome.PASS,
            coverage=Coverage.FULL,
            artifact=_artifact(),
            environment=_environment(),
            backend="cann-simulation",
            created_at=200,
        )


def test_seal_audit_record() -> None:
    testing, _, _, records, _, _, _, _, candidate, _ = _stack()
    record = testing.seal_audit(
        candidate_id=candidate.id,
        kind=RecordKind.TEST,
        skill_ref=_skill(),
        outcome=Outcome.CANCELLED,
        audit_id="audit-1",
        artifact=_artifact(),
        environment=_environment(),
        created_at=100,
    )

    assert record.executed is False
    assert record.coverage is Coverage.NONE
    assert record.task_id is None
    assert record.job_id is None
    assert record.audit_id == "audit-1"
    assert records.list_by_candidate(candidate.id) == (record,)


def test_profile_job_and_record() -> None:
    testing, agents, _, _, _, mentor, _, profiler, candidate, _ = _stack()
    task = _assign(agents, mentor, profiler, TaskKind.PROFILE, candidate.id)
    job = testing.submit_profile(
        task_id=task.id,
        case_selection=("case-1",),
        timeout_s=30,
    )
    record = testing.seal_record(
        task_id=task.id,
        outcome=Outcome.PASS,
        coverage=Coverage.FULL,
        artifact=_artifact(),
        environment=_environment(),
        backend="cann-profiler",
        created_at=100,
    )

    assert job.id == "job-1"
    assert record.kind is RecordKind.PROFILE
    assert record.backend == "cann-profiler"
